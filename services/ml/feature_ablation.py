import structlog

logger = structlog.get_logger(__name__)
from typing import Any

import polars as pl

from services.backtest.execution_engine import BacktestEngine
from services.backtest.walk_forward import WalkForwardEngine
from services.core.alpha_engine import AlphaEngine
from services.core.risk_manager import RiskManager


class FeatureAblator:
    """Feature ablation and redundancy analysis engine."""

    def __init__(self, base_features: list[str]):
        """Initialize FeatureAblator."""
        self.base_features = base_features
        self.engine = AlphaEngine()
        self.rm = RiskManager()
        self.wf = WalkForwardEngine(train_days=252, test_days=63, step_days=63, purge_days=5, embargo_days=5)

    def _run_ablation_test(self, active_features: list[str], market_data, bm_df, sector_map, common_dates) -> dict:
        """Belirtilen feature seti ile hizli bir OOS testi dondurur (Sadece 5 fold - temsil kabiliyeti yuksek son yillar)."""
        all_signals = []
        folds = self.wf.create_folds(common_dates)

        # Son 5 fold uzerinde hizli ablasyon (ortalama 1.5 yil)
        target_folds = folds[-5:]

        for fold in target_folds:
            # AlphaEngine'e sadece aktif feature'lari kullanmasi icin kanca atiyoruz
            if isinstance(self.engine.params, dict):
                self.engine.params["feature_fraction"] = 1.0  # Ablasyonda fraction kullanilmaz

            success = self.engine.train(market_data, bm_df, sector_map, fold["train_start"], fold["train_end"])
            if not success:
                continue

            preds = self.engine.predict(market_data, bm_df, sector_map, fold["test_start"])
            top_picks = preds[:10]
            if not top_picks:
                continue

            # Eşit ağırlık (%10)
            for pick in top_picks:
                ticker = pick["ticker"]
                adj_weight = 0.10  # Equal weight

                df_t = market_data.get(ticker)
                if df_t is None or len(df_t) == 0:
                    continue

                if "Date" in df_t.columns:
                    df_test = df_t.filter((pl.col("Date") >= fold["test_start"]) & (pl.col("Date") <= fold["test_end"]))
                else:
                    continue

                if len(df_test) == 0:
                    continue

                start_date_str = str(df_test["Date"][0])[:10]
                end_date_str = str(df_test["Date"][-1])[:10]

                all_signals.append(
                    {
                        "date": start_date_str,
                        "ticker": ticker,
                        "action": "BUY",
                        "score": pick["score"],
                        "weight": adj_weight,
                    }
                )
                all_signals.append(
                    {
                        "date": end_date_str,
                        "ticker": ticker,
                        "action": "SELL",
                        "score": pick["score"],
                        "weight": adj_weight,
                    }
                )

        if not all_signals:
            return {"cagr_pct": 0.0, "max_drawdown_pct": 0.0, "sharpe_ratio": 0.0}

        # Fiyat verilerini formatla
        price_data_formatted = {}
        for ticker, df_t in market_data.items():
            if df_t is None or len(df_t) == 0:
                continue
            rows = []
            for row in df_t.iter_rows(named=True):
                d_val = row.get("Date")
                date_str = str(d_val)[:10] if d_val is not None else ""
                rows.append(
                    {
                        "date": date_str,
                        "close": float(row.get("Close", 0.0)),
                        "volume": float(row.get("Volume", 0.0)),
                    }
                )
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
            stop_loss_pct=1.0,  # Stop yok
            trailing_stop_pct=1.0,  # Stop yok
            market_regime=1.0,
        )
        return report.metrics

    def run_full_ablation(self) -> Any:
        """Run full ablation study across all base features."""
        logger.info("📥 Ablasyon icin 3 yillik hizli veri seti indiriliyor (2021-2024)...")
        market_data, bm_df, sector_map = self.engine.fetch_data("2021-01-01", "2024-11-03")
        common_dates = list(sorted([str(d)[:10] for d in bm_df["Date"]])) if "Date" in bm_df.columns else []

        logger.info("▶ Baseline (Tum featurelar) OOS hesaplaniyor...")
        base_metrics = self._run_ablation_test(self.base_features, market_data, bm_df, sector_map, common_dates)
        cagr = getattr(base_metrics, "cagr_pct", 0.0)
        maxdd = getattr(base_metrics, "max_drawdown_pct", 0.0)
        sharpe = getattr(base_metrics, "sharpe_ratio", 0.0)
        logger.info(
            f"🌟 Baseline -> CAGR: %{cagr:.2f}, MaxDD: -%{maxdd:.2f}, Sharpe: {sharpe:.2f}"
        )

        ablation_results = []

        for i, feature in enumerate(self.base_features, 1):
            logger.info(f"[{i}/{len(self.base_features)}] Ablasyon Testi: '{feature}' kaldiriliyor...")
            self.engine.exclude_features = [feature]

            test_features = [f for f in self.base_features if f != feature]
            m = self._run_ablation_test(test_features, market_data, bm_df, sector_map, common_dates)

            m_sharpe = getattr(m, "sharpe_ratio", 0.0)
            diff = m_sharpe - sharpe
            if diff > 0.05:
                logger.info(
                    f"  🔴 KESIN ZARARLI! '{feature}' cikarildiginda Sharpe {sharpe:.2f} -> {m_sharpe:.2f} ({(diff):.2f} artis)"
                )
            elif diff > 0.0:
                logger.info(
                    f"  🟠 MUHTEMEL GURULTU. '{feature}' cikarildiginda Sharpe {sharpe:.2f} -> {m_sharpe:.2f} ({(diff):.2f} artis)"
                )
            else:
                logger.info(
                    f"  🟢 FAYDALI. '{feature}' cikarildiginda Sharpe {sharpe:.2f} -> {m_sharpe:.2f}"
                )

            ablation_results.append(
                {
                    "dropped_feature": feature,
                    "cagr": getattr(m, "cagr_pct", 0.0),
                    "maxdd": getattr(m, "max_drawdown_pct", 0.0),
                    "sharpe": m_sharpe,
                    "diff": diff,
                }
            )

        logger.info("\n=== ABLASYON OZETI (EN ZARARLI FEATURELAR) ===")
        ablation_results.sort(key=lambda x: x["diff"], reverse=True)
        for res in ablation_results:
            if res["diff"] > 0:
                logger.info(f"DROP: {res['dropped_feature']} -> Yeni Sharpe: {res['sharpe']:.2f} (Artis: +{res['diff']:.2f})")

