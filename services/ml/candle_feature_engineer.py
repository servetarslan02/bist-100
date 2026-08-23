"""
ALPHA BIST — Mum Formasyonları Ampirik Başarı Karnesi & ML Özellik Mühendisliği
=============================================================================
12 Japon Mum Formasyonunun BIST tarihindeki gerçek kazanç/kayıp istatistiklerini
(Kazanma Oranı, Kâr Çarpanı, Beklenen Değer) hesaplar ve Yapay Zeka (ML)
modeline beslenecek yüksek değerli özellik matrislerini (Feature Vectors) üretir.
"""

from typing import Dict, List, Any, Tuple, Optional
import numpy as np
import pandas as pd
import structlog

from services.intelligence.candle_patterns import candle_engine

logger = structlog.get_logger()


class CandleFeatureEngineer:
    """BIST hisselerinde mum formasyonlarının ampirik başarı analizini ve ML özelliklerini üretir."""

    def __init__(self):
        self.pattern_stats: Dict[str, Dict[str, float]] = {}

    def compute_empirical_edge_table(self, stock_dict: Dict[str, pd.DataFrame], forward_days: int = 10) -> pd.DataFrame:
        """
        Tüm BIST hisselerinin tarihsel verilerini tarayarak her bir formasyonun
        gerçek hayattaki kazanma oranını, ortalama getirisini ve kâr çarpanını hesaplar.
        """
        records = []

        for ticker, df in stock_dict.items():
            if df is None or len(df) < 50:
                continue

            closes = df["Close"].values
            n = len(df)

            for i in range(30, n - forward_days):
                sub_df = df.iloc[:i+1]
                c_res = candle_engine.analyze_dataframe(sub_df.iloc[-30:], ticker)

                p_entry = float(closes[i])
                p_exit = float(closes[i + forward_days])
                fwd_ret = (p_exit - p_entry) / p_entry * 100

                for pat in c_res.patterns_detected:
                    records.append({
                        "ticker": ticker,
                        "pattern": pat,
                        "fwd_ret": fwd_ret,
                        "is_win": fwd_ret > 0,
                        "buyer_pressure": c_res.buyer_pressure_pct
                    })

        if not records:
            return pd.DataFrame()

        df_rec = pd.DataFrame(records)
        summary = []

        for pat, grp in df_rec.groupby("pattern"):
            count = len(grp)
            win_rate = (grp["is_win"].sum() / count) * 100
            avg_ret = grp["fwd_ret"].mean()
            
            wins = grp[grp["fwd_ret"] > 0]["fwd_ret"]
            losses = abs(grp[grp["fwd_ret"] < 0]["fwd_ret"])
            
            avg_win = wins.mean() if len(wins) > 0 else 0.0
            avg_loss = losses.mean() if len(losses) > 0 else 1e-9
            
            payoff_ratio = round(avg_win / avg_loss, 2)
            profit_factor = round(wins.sum() / max(losses.sum(), 1e-9), 2)
            
            # Beklenen Değer (Expectancy = (Win% * AvgWin) - (Loss% * AvgLoss))
            expectancy = ((win_rate / 100) * avg_win) - (((100 - win_rate) / 100) * avg_loss)

            summary.append({
                "Formasyon": pat,
                "BIST Örneklem Sayısı": count,
                "Kazanma Oranı (Win Rate)": round(win_rate, 1),
                "Ort. 10G Getiri %": round(avg_ret, 2),
                "Kâr / Zarar Çarpanı (PF)": profit_factor,
                "Kazanç/Kayıp Oranı (Payoff)": payoff_ratio,
                "Beklenen Değer (Expectancy %)": round(expectancy, 2),
                "Model Öneri Derecesi": "⭐⭐⭐⭐⭐ (Güçlü Al)" if expectancy > 1.0 and win_rate >= 50 else ("⭐⭐⭐ (Nötr/Teyitli)" if expectancy > 0 else "⚠️ (Filtrelenmeli)")
            })

        df_summary = pd.DataFrame(summary).sort_values(by="Beklenen Değer (Expectancy %)", ascending=False)
        return df_summary

    def extract_features_for_dataframe(self, df: pd.DataFrame, ticker: str = "ASSET") -> pd.DataFrame:
        """
        OHLCV DataFrame'ine ML modelinin doğrudan öğrenebileceği sayısal mum özellikleri ekler.
        """
        df_feat = df.copy()
        n = len(df)
        
        # Özellik sütunları
        col_buyer_pressure = np.zeros(n)
        col_candle_score = np.zeros(n)
        col_has_engulfing = np.zeros(n)
        col_has_hammer = np.zeros(n)
        col_has_morning_star = np.zeros(n)
        col_has_soldiers = np.zeros(n)
        col_has_fvg = np.zeros(n)
        col_has_shooting_star = np.zeros(n)
        col_has_crows = np.zeros(n)

        for i in range(3, n):
            sub_df = df.iloc[max(0, i-30):i+1]
            c_res = candle_engine.analyze_dataframe(sub_df, ticker)
            
            col_buyer_pressure[i] = c_res.buyer_pressure_pct
            col_candle_score[i] = c_res.candle_score
            
            pats = set(c_res.patterns_detected)
            if "BULLISH_ENGULFING" in pats: col_has_engulfing[i] = 1.0
            if "HAMMER_PINBAR" in pats: col_has_hammer[i] = 1.0
            if "MORNING_STAR" in pats: col_has_morning_star[i] = 1.0
            if "THREE_WHITE_SOLDIERS" in pats: col_has_soldiers[i] = 1.0
            if "BULLISH_FVG" in pats: col_has_fvg[i] = 1.0
            if "SHOOTING_STAR" in pats or "BEARISH_ENGULFING" in pats: col_has_shooting_star[i] = 1.0
            if "THREE_BLACK_CROWS" in pats: col_has_crows[i] = 1.0

        df_feat["feat_buyer_pressure"] = col_buyer_pressure
        df_feat["feat_candle_score"] = col_candle_score
        df_feat["feat_has_bull_engulfing"] = col_has_engulfing
        df_feat["feat_has_hammer"] = col_has_hammer
        df_feat["feat_has_morning_star"] = col_has_morning_star
        df_feat["feat_has_soldiers"] = col_has_soldiers
        df_feat["feat_has_fvg"] = col_has_fvg
        df_feat["feat_has_shooting_star"] = col_has_shooting_star
        df_feat["feat_has_crows"] = col_has_crows

        return df_feat


# Singleton
candle_feature_engineer = CandleFeatureEngineer()
