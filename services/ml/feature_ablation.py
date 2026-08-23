import json
import numpy as np
import pandas as pd
from typing import List, Dict
import os

from services.core.alpha_engine import AlphaEngine
from services.backtest.walk_forward import WalkForwardEngine
from services.backtest.engine import BacktestEngine
from services.core.risk_manager import RiskManager

class FeatureAblator:
    def __init__(self, base_features: List[str]):
        self.base_features = base_features
        self.engine = AlphaEngine()
        self.rm = RiskManager()
        self.wf = WalkForwardEngine(
            train_days=252, test_days=63, step_days=63, purge_days=5, embargo_days=5
        )
        
    def _run_ablation_test(self, active_features: List[str], market_data, bm_df, sector_map, common_dates) -> dict:
        """Belirtilen feature seti ile hizli bir OOS testi dondurur (Sadece 5 fold - temsil kabiliyeti yuksek son yillar)"""
        all_signals = []
        folds = self.wf.create_folds(common_dates)
        
        # Son 5 fold uzerinde hizli ablasyon (ortalama 1.5 yil)
        target_folds = folds[-5:]
        
        for fold in target_folds:
            # AlphaEngine'e sadece aktif feature'lari kullanmasi icin kanca atiyoruz
            self.engine.params["feature_fraction"] = 1.0 # Ablasyonda fraction kullanilmaz
            
            success = self.engine.train(
                market_data, bm_df, sector_map,
                fold['train_start'], fold['train_end']
            )
            if not success: continue
            
            preds = self.engine.predict(market_data, bm_df, sector_map, fold['test_start'])
            top_picks = preds[:10]
            if not top_picks: continue
            
            # Eşit ağırlık (%10) ve rejim (Market Regime'i 1.0 sabitliyoruz ki ablation sadece feature'lari test etsin)
            regime = 1.0
            
            for pick in top_picks:
                ticker = pick["ticker"]
                adj_weight = 0.10 # Equal weight
                
                df_t = market_data.get(ticker)
                t_start = pd.Timestamp(fold['test_start'])
                t_end = pd.Timestamp(fold['test_end'])
                df_test = df_t[(df_t.index >= t_start) & (df_t.index <= t_end)]
                if df_test.empty: continue
                
                all_signals.append({
                    "date": str(df_test.index[0].date()), "ticker": ticker, 
                    "action": "BUY", "score": pick["score"], "weight": adj_weight
                })
                all_signals.append({
                    "date": str(df_test.index[-1].date()), "ticker": ticker, 
                    "action": "SELL", "score": pick["score"], "weight": adj_weight
                })
                
        if not all_signals:
            return {"cagr_pct": 0, "max_drawdown_pct": 0, "sharpe_ratio": 0}
            
        # Fiyat verilerini formatla
        price_data_formatted = {}
        for ticker, df_t in market_data.items():
            if df_t.empty: continue
            rows = []
            for d, row in df_t.iterrows():
                rows.append({
                    "date": str(d.date()) if hasattr(d, 'date') else str(d)[:10],
                    "close": float(row.get("Close", 0.0)),
                    "volume": float(row.get("Volume", 0.0))
                })
            price_data_formatted[ticker] = rows
            
        backtest = BacktestEngine()
        report = backtest.run_backtest(
            strategy_name="Ablation",
            price_data=price_data_formatted,
            signals=all_signals,
            initial_capital=100000.0,
            commission_rate=0.001,
            slippage_pct=0.002,
            dump_ledger=False,
            stop_loss_pct=1.0, # Stop yok
            trailing_stop_pct=1.0, # Stop yok
            market_regime=1.0
        )
        return report.metrics

    def run_full_ablation(self):
        print("📥 Ablasyon icin 3 yillik hizli veri seti indiriliyor (2021-2024)...")
        market_data, bm_df, sector_map = self.engine.fetch_data("2021-01-01", "2024-11-03")
        common_dates = list(sorted([d.strftime('%Y-%m-%d') for d in bm_df.index]))
        
        print("▶ Baseline (Tum featurelar) OOS hesaplaniyor...")
        base_metrics = self._run_ablation_test(self.base_features, market_data, bm_df, sector_map, common_dates)
        print(f"🌟 Baseline -> CAGR: %{base_metrics.cagr_pct:.2f}, MaxDD: -%{base_metrics.max_drawdown_pct:.2f}, Sharpe: {base_metrics.sharpe_ratio:.2f}")
        
        ablation_results = []
        
        for i, feature in enumerate(self.base_features, 1):
            print(f"[{i}/{len(self.base_features)}] Ablasyon Testi: '{feature}' kaldiriliyor...")
            self.engine.exclude_features = [feature]
            
            test_features = [f for f in self.base_features if f != feature]
            m = self._run_ablation_test(test_features, market_data, bm_df, sector_map, common_dates)
            
            diff = m.sharpe_ratio - base_metrics.sharpe_ratio
            if diff > 0.05:
                print(f"  🔴 KESIN ZARARLI! '{feature}' cikarildiginda Sharpe {base_metrics.sharpe_ratio:.2f} -> {m.sharpe_ratio:.2f} ({(diff):.2f} artis)")
            elif diff > 0.0:
                print(f"  🟠 MUHTEMEL GURULTU. '{feature}' cikarildiginda Sharpe {base_metrics.sharpe_ratio:.2f} -> {m.sharpe_ratio:.2f} ({(diff):.2f} artis)")
            else:
                print(f"  🟢 FAYDALI. '{feature}' cikarildiginda Sharpe {base_metrics.sharpe_ratio:.2f} -> {m.sharpe_ratio:.2f}")
                
            ablation_results.append({
                "dropped_feature": feature,
                "cagr": m.cagr_pct,
                "maxdd": m.max_drawdown_pct,
                "sharpe": m.sharpe_ratio,
                "diff": diff
            })
            
        print("\n=== ABLASYON OZETI (EN ZARARLI FEATURELAR) ===")
        ablation_results.sort(key=lambda x: x["diff"], reverse=True)
        for res in ablation_results:
            if res["diff"] > 0:
                print(f"DROP: {res['dropped_feature']} -> Yeni Sharpe: {res['sharpe']:.2f} (Artis: +{res['diff']:.2f})")
