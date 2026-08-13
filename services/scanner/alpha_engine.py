"""
ALPHA BIST — Alpha Engine v2.0

3 katmanlı tarama:
Layer 1: Live Scanner    → her tick, çok ucuz
Layer 2: Batch Scanner   → belirli aralıklarla tam tarama
Layer 3: Event Scanner   → haber/KAP geldiğinde immediate

Tüm pipeline tek motor:
800 hisse → data → bars → features → regime → scanner → signals
"""

import asyncio
import time
import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime
import structlog

logger = structlog.get_logger()


class AlphaEngine:
    """ALPHA'nın ana motoru — v2.0"""

    def __init__(self):
        self._universe: List[str] = []
        self._features_map: Dict[str, Dict[str, float]] = {}
        self._ml_scores: Dict[str, float] = {}
        self._event_scores: Dict[str, float] = {}
        self._market_regime: str = "RANGE"
        self._regime_confidence: float = 0.5
        self._last_scan_results: List = []
        self._last_scan_summary: Dict = {}
        self._scan_count: int = 0
        self._running: bool = False

        # Katmanlar
        from .live_scanner import live_scanner
        from .event_scanner import event_scanner
        self._live = live_scanner
        self._events = event_scanner

    def load_universe(self, tickers: List[str]):
        self._universe = tickers
        logger.info("Universe loaded", count=len(tickers))

    # =====================================================
    # Layer 1: Live Scanner (her tick'te)
    # =====================================================

    def process_tick(self, ticker: str, price: float, volume: int,
                     timestamp: Optional[datetime] = None) -> Optional[Dict]:
        """
        Her tick'te çalışır. Çok düşük maliyetli.
        State update → candidate check → event score güncelle.
        """
        result = self._live.process_tick(ticker, price, volume, timestamp)

        if result:
            # Event score güncelle
            event_score = self._events.get_event_score(ticker)
            result["event_score"] = event_score

            logger.info("LIVE CANDIDATE",
                       ticker=ticker, reason=result["reason"],
                       score=result["score"])

        return result

    # =====================================================
    # Layer 2: Batch Scanner (belirli aralıklarla)
    # =====================================================

    async def run_batch_scan(self) -> Dict[str, Any]:
        """
        Tam batch tarama. 800 hisse → data → features → scanner → signals.
        Günde 5-6 kez çalışır (09:50, 12:00, 15:00, 17:50).
        """
        start = time.time()
        self._scan_count += 1

        logger.info("=== BATCH SCAN START ===",
                    scan_count=self._scan_count, universe=len(self._universe))

        # 1. Veri çek
        data = await self._fetch_all_data()
        if data is None:
            return {"error": "Data fetch failed"}

        # 2. Feature hesapla
        self._features_map = self._compute_all_features(data)

        # 3. Market regime
        self._market_regime, self._regime_confidence = self._detect_regime()

        # 4. ML scores (şimdilik basit, sonra gerçek model)
        self._ml_scores = self._compute_ml_scores()

        # 5. Event scores
        self._event_scores = {
            ticker: self._events.get_event_score(ticker)
            for ticker in self._universe
        }

        # 6. Scanner çalıştır
        from .alpha_scanner import alpha_scanner
        results = alpha_scanner.scan(
            universe=list(self._features_map.keys()),
            features_map=self._features_map,
            market_regime=self._market_regime,
            regime_confidence=self._regime_confidence,
            ml_scores=self._ml_scores,
            event_scores=self._event_scores,
        )
        self._last_scan_results = results

        # 7. Özet
        summary = alpha_scanner.get_summary(results)
        summary["scan_count"] = self._scan_count
        summary["elapsed_seconds"] = round(time.time() - start, 1)
        summary["regime"] = self._market_regime
        summary["regime_confidence"] = self._regime_confidence
        summary["ml_scores_used"] = len([v for v in self._ml_scores.values() if v != 50])
        summary["event_scores_used"] = len([v for v in self._event_scores.values() if v != 50])
        self._last_scan_summary = summary

        logger.info("=== BATCH SCAN COMPLETE ===",
                    scanned=summary["total_scanned"],
                    signals=summary["signals_generated"],
                    elapsed=summary["elapsed_seconds"])

        return summary

    # =====================================================
    # Layer 3: Event Scanner (haber/KAP geldiğinde)
    # =====================================================

    def on_event(self, event_type: str, event_data: Dict) -> List[Dict]:
        """
        Event geldiğinde çalışır.
        1. Etkilenen hisseleri bul
        2. Event score güncelle
        3. Etkilenen hisseleri derin analiz yap
        4. Opportunity Score yeniden hesapla
        5. Sinyal üret
        """
        from .alpha_scanner import alpha_scanner

        affected = self._events.on_event(event_type, event_data)

        if not affected:
            return []

        logger.info("EVENT TRIGGERED", type=event_type, affected=affected)

        results = []
        for ticker in affected:
            # 1. Event score güncelle
            self._event_scores[ticker] = self._events.get_event_score(ticker)

            # 2. Feature varsa derin analiz yap, yoksa hızlı feature hesapla
            features = self._features_map.get(ticker)
            if not features:
                # Fallback: hızlı feature hesaplama
                features = self._compute_single_feature(ticker)

            if features:
                ml_score = self._ml_scores.get(ticker, 50.0)
                event_score = self._event_scores.get(ticker, 50.0)

                # 3. Scanner ile yeniden tara
                result = alpha_scanner._scan_single(ticker, features, ml_score, event_score)

                # 4. Sinyal üret
                if result.opportunity_score > 50:
                    alpha_scanner._generate_signal(result)
                    results.append({
                        "ticker": ticker,
                        "opportunity_score": result.opportunity_score,
                        "signal_type": result.signal_type,
                        "signal_score": result.signal_score,
                        "signal_direction": result.signal_direction,
                        "event_type": event_type,
                        "event_importance": event_data.get("importance", 0),
                    })

                    logger.info("EVENT RESCAN", ticker=ticker,
                               score=result.opportunity_score,
                               signal=result.signal_type)

        # 6. Event scanner'dan temizle
        for ticker in affected:
            self._events.clear_rescan(ticker)

        return results

    # =====================================================
    # Yardımcı Fonksiyonlar
    # =====================================================

    async def _fetch_all_data(self):
        import yfinance as yf
        try:
            tickers = [f"{t}.IS" for t in self._universe]
            return yf.download(tickers, period="60d", group_by="ticker", threads=True, progress=False)
        except Exception as e:
            logger.error("Data fetch error", error=str(e))
            return None

    def _compute_all_features(self, data) -> Dict[str, Dict[str, float]]:
        import polars as pl
        from ..features.calculator import FeatureCalculator
        fc = FeatureCalculator()
        features_map = {}

        for ticker in self._universe:
            try:
                td = data[f"{ticker}.IS"].dropna()
                if len(td) < 20:
                    continue
                td = td.reset_index()
                df = pl.from_pandas(td[["Date", "Open", "High", "Low", "Close", "Volume"]])
                df = df.rename({"Date": "timestamp", "Open": "open", "High": "high",
                               "Low": "low", "Close": "close", "Volume": "volume"})
                df = df.drop_nulls(subset=["close"])
                features = fc.compute_all_features(df)
                if features:
                    close_list = [x for x in df["close"].to_list() if x is not None]
                    features["price"] = close_list[-1] if close_list else 0
                    features_map[ticker] = features
            except:
                pass
        return features_map

    def _detect_regime(self) -> tuple:
        if not self._features_map:
            return "RANGE", 0.5

        advancing = declining = 0
        volatilities, momentums = [], []

        for ticker, features in self._features_map.items():
            ret = features.get("return_1d", 0)
            if ret > 0: advancing += 1
            elif ret < 0: declining += 1
            vol = features.get("realized_vol_20d", 20)
            if vol: volatilities.append(vol)
            mom = features.get("momentum_20d", 0)
            if mom: momentums.append(mom)

        total = advancing + declining
        breadth = (advancing / total * 100) if total > 0 else 50
        avg_vol = np.mean(volatilities) if volatilities else 20
        avg_mom = np.mean(momentums) if momentums else 0

        if breadth < 20 and avg_vol > 40: return "PANIC", 0.9
        elif breadth < 35: return "RISK-OFF", 0.8
        elif avg_vol > 35: return "HIGH-VOLATILITY", 0.7
        elif breadth > 70 and avg_mom > 5: return "MOMENTUM-EXPANSION", 0.8
        elif breadth > 65 and avg_mom > 0: return "TRENDING-UP", 0.7
        elif breadth < 40 and avg_mom < -5: return "TRENDING-DOWN", 0.7
        elif 45 < breadth < 55 and avg_mom > 0: return "RECOVERY", 0.6
        elif avg_vol < 12: return "LOW-VOLATILITY", 0.6
        else: return "RANGE", 0.5

    def _compute_single_feature(self, ticker: str) -> Optional[Dict[str, float]]:
        """Tek hisse için hızlı feature hesaplama (event fallback)."""
        import yfinance as yf
        import polars as pl
        from ..features.calculator import FeatureCalculator

        try:
            t = yf.Ticker(f"{ticker}.IS")
            hist = t.history(period="60d").reset_index()
            if len(hist) < 20:
                return None

            df = pl.from_pandas(hist[["Date", "Open", "High", "Low", "Close", "Volume"]])
            df = df.rename({"Date": "timestamp", "Open": "open", "High": "high",
                           "Low": "low", "Close": "close", "Volume": "volume"})
            df = df.drop_nulls(subset=["close"])

            fc = FeatureCalculator()
            features = fc.compute_all_features(df)
            if features:
                close_list = [x for x in df["close"].to_list() if x is not None]
                features["price"] = close_list[-1] if close_list else 0
                self._features_map[ticker] = features
                return features
        except Exception as e:
            logger.warning("Single feature computation failed", ticker=ticker, error=str(e))

        return None

    def _compute_ml_scores(self) -> Dict[str, float]:
        """Quant Probability Proxy — feature-based heuristic score.
        
        NOT: Bu gerçek ML modeli değil. Feature kombinasyonlarından
        üretilen bir heuristic. Gerçek ML modeli bağlandığında
        bu fonksiyon güncellenecek.
        """
        scores = {}
        for ticker, features in self._features_map.items():
            # Basit ML proxy: momentum + volume + volatility kombinasyonu
            mom = features.get("momentum_20d", 0)
            vol_z = features.get("volume_zscore", 0)
            rsi = features.get("rsi_14", 50)

            score = 50
            if mom > 5: score += min(mom * 2, 20)
            elif mom < -5: score += max(mom * 2, -20)
            if vol_z > 2: score += min(vol_z * 5, 15)
            if 30 < rsi < 70: score += 5
            elif rsi < 25: score += 10  # oversold
            elif rsi > 75: score -= 10  # overbought

            scores[ticker] = max(0, min(100, score))
        return scores

    def get_last_summary(self) -> Dict:
        return self._last_scan_summary

    def get_last_results(self) -> List:
        return self._last_scan_results

    def get_regime(self) -> str:
        return self._market_regime

    def get_live_candidates(self) -> Dict:
        return self._live.get_candidates()

    def get_event_candidates(self) -> Dict:
        return self._events.get_pending_rescans()


# Singleton
alpha_engine = AlphaEngine()
