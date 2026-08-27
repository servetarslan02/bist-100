"""
ALPHA BIST — Alpha Engine v2.0

3 katmanlı tarama:
Layer 1: Live Scanner    → her tick, çok ucuz
Layer 2: Batch Scanner   → belirli aralıklarla tam tarama
Layer 3: Event Scanner   → haber/KAP geldiğinde immediate

Tüm pipeline tek motor:
800 hisse → data → bars → features → regime → scanner → signals
"""

import time
from datetime import datetime
from typing import Any

import numpy as np
import polars as pl
import structlog
import yfinance as yf

logger = structlog.get_logger()


class AlphaEngine:
    """ALPHA'nın ana motoru — v2.0"""

    def __init__(self):
        self._universe: list[str] = []
        self._features_map: dict[str, dict[str, float]] = {}
        self._ml_scores: dict[str, float] = {}
        self._event_scores: dict[str, float] = {}
        self._market_regime: str = "RANGE"
        self._regime_confidence: float = 0.5
        self._last_scan_results: list = []
        self._last_scan_summary: dict = {}
        self._scan_count: int = 0
        self._running: bool = False

        # Katmanlar
        from ml.model_loader import ml_model_loader

        from .event_queue import event_queue
        from .event_scanner import event_scanner
        from .live_scanner import live_scanner

        self._live = live_scanner
        self._events = event_scanner
        self._queue = event_queue
        self._ml_loader = ml_model_loader

        # Yeni modüller (SCANNER-NIHAI-SPEC entegrasyonu)
        from .custom_filters import custom_filter_engine
        from .deduplicator import scan_deduplicator
        from .performance_tracker import performance_tracker
        from .scan_alerts import scan_alert_manager
        from .scan_persistence import scan_persistence

        self._dedup = scan_deduplicator
        self._persistence = scan_persistence
        self._perf_tracker = performance_tracker
        self._alert_manager = scan_alert_manager
        self._filter_engine = custom_filter_engine

    def load_universe(self, tickers: list[str]):
        """BIST evrenini yükle."""
        try:
            self._universe = tickers
            logger.info("Universe loaded", count=len(tickers))
        except Exception as e:
            logger.error("Failed to load universe", error=str(e))
            self._universe = []

    # =====================================================
    # Layer 1: Live Scanner (her tick'te)
    # =====================================================

    def process_tick(self, ticker: str, price: float, volume: int, timestamp: datetime | None = None) -> dict | None:
        """
        Her tick'te çalışır. Çok düşük maliyetli.
        State update → candidate check → event score güncelle.
        """
        result = self._live.process_tick(ticker, price, volume, timestamp)

        if result:
            # Event score güncelle
            event_score = self._events.get_event_score(ticker)
            result["event_score"] = event_score

            # Live candidate alert kontrolü
            if result["score"] > 80:
                self._alert_manager.check_scan_results(
                    [
                        {
                            "ticker": ticker,
                            "score": result["score"],
                            "signal": result["reason"],
                            "volume_zscore": result.get("vol_z", 0),
                            "breakout_score": 0,
                            "price": price,
                        }
                    ],
                    regime=self._market_regime,
                )

            logger.info("LIVE CANDIDATE", ticker=ticker, reason=result["reason"], score=result["score"])

        return result

    # =====================================================
    # Layer 2: Batch Scanner (belirli aralıklarla)
    # =====================================================

    async def run_batch_scan(self) -> dict[str, Any]:
        """
        Tam batch tarama. 800 hisse → data → features → scanner → signals.
        Günde 5-6 kez çalışır (09:50, 12:00, 15:00, 17:50).
        """
        start = time.time()
        self._scan_count += 1

        logger.info("=== BATCH SCAN START ===", scan_count=self._scan_count, universe=len(self._universe))

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
        self._event_scores = {ticker: self._events.get_event_score(ticker) for ticker in self._universe}

        # 6. Deduplication kontrolü — sadece tarama gereken hisseler
        universe_to_scan = []
        for ticker in self._features_map:
            if self._dedup.should_scan(ticker):
                universe_to_scan.append(ticker)

        if not universe_to_scan:
            logger.info("All tickers in cooldown, skipping batch scan")
            return {"skipped": True, "reason": "all_in_cooldown"}

        # 7. Scanner çalıştır
        from .alpha_scanner import alpha_scanner

        results = alpha_scanner.scan(
            universe=universe_to_scan,
            features_map=self._features_map,
            market_regime=self._market_regime,
            regime_confidence=self._regime_confidence,
            ml_scores=self._ml_scores,
            event_scores=self._event_scores,
        )
        self._last_scan_results = results

        # 8. Custom filters uygula
        result_dicts = [
            r.to_dict()
            if hasattr(r, "to_dict")
            else {
                "ticker": r.ticker,
                "score": r.opportunity_score,
                "signal": r.signal_type,
                "direction": r.signal_direction,
                "confidence": r.signal_confidence,
                "price": r.price,
                "volume": r.volume,
                "volume_zscore": r.volume_zscore,
                "breakout_score": r.breakout_score,
            }
            for r in results
        ]
        filtered_results, filter_log = self._filter_engine.apply_filters(result_dicts)

        # 9. Alert kontrolü
        new_alerts = self._alert_manager.check_scan_results(filtered_results, regime=self._market_regime)

        # 10. Persistence — sonuçları kaydet
        self._persistence.save_batch_results(
            scan_type="batch",
            results=filtered_results[:50],
            regime=self._market_regime,
        )

        # 11. Deduplication — tarama kaydet
        for r in results:
            self._dedup.record_scan(
                ticker=r.ticker,
                score=r.opportunity_score,
                signal=r.signal_type,
            )

        # 12. Performance tracking
        elapsed_ms = (time.time() - start) * 1000
        self._perf_tracker.record_scan(
            scan_type="batch",
            tickers_scanned=len(universe_to_scan),
            opportunities_found=len([r for r in results if r.opportunity_score > 60]),
            signals_generated=len([r for r in results if r.signal_type]),
            duration_ms=elapsed_ms,
            regime=self._market_regime,
        )

        # 13. Özet
        summary = alpha_scanner.get_summary(results)
        summary["scan_count"] = self._scan_count
        summary["elapsed_seconds"] = round(time.time() - start, 1)
        summary["regime"] = self._market_regime
        summary["regime_confidence"] = self._regime_confidence
        summary["ml_scores_used"] = len([v for v in self._ml_scores.values() if v != 50])
        summary["event_scores_used"] = len([v for v in self._event_scores.values() if v != 50])
        summary["dedup_stats"] = self._dedup.get_stats()
        summary["alerts_generated"] = len(new_alerts)
        summary["filtered_out"] = len(results) - len(filtered_results)
        self._last_scan_summary = summary

        logger.info(
            "=== BATCH SCAN COMPLETE ===",
            scanned=summary["total_scanned"],
            signals=summary["signals_generated"],
            elapsed=summary["elapsed_seconds"],
            alerts=len(new_alerts),
            filtered_out=summary["filtered_out"],
        )

        return summary

    # =====================================================
    # Layer 3: Event Scanner (haber/KAP geldiğinde)
    # =====================================================

    def on_event(self, event_type: str, event_data: dict) -> list[dict]:
        """
        Event geldiğinde çalışır.
        1. Etkilenen hisseleri bul
        2. Dedup force scan — cooldown bypass
        3. Event score güncelle
        4. Etkilenen hisseleri derin analiz yap
        5. Opportunity Score yeniden hesapla
        6. Sinyal üret
        7. Alert kontrolü
        """
        from .alpha_scanner import alpha_scanner

        affected = self._events.on_event(event_type, event_data)

        if not affected:
            return []

        logger.info("EVENT TRIGGERED", type=event_type, affected=affected)

        # Dedup force scan — event-driven cooldown bypass
        self._dedup.force_scan_batch(affected)

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
                    result_dict = {
                        "ticker": ticker,
                        "opportunity_score": result.opportunity_score,
                        "signal_type": result.signal_type,
                        "signal_score": result.signal_score,
                        "signal_direction": result.signal_direction,
                        "event_type": event_type,
                        "event_importance": event_data.get("importance", 0),
                        "price": result.price,
                        "volume": result.volume,
                        "volume_zscore": result.volume_zscore,
                        "breakout_score": result.breakout_score,
                    }
                    results.append(result_dict)

                    # 5. Dedup kaydet
                    self._dedup.record_scan(
                        ticker=ticker,
                        score=result.opportunity_score,
                        signal=result.signal_type,
                        forced=True,
                    )

                    logger.info(
                        "EVENT RESCAN", ticker=ticker, score=result.opportunity_score, signal=result.signal_type
                    )

        # 6. Alert kontrolü
        if results:
            self._alert_manager.check_scan_results(results, regime=self._market_regime)

            # Persistence
            self._persistence.save_batch_results(
                scan_type="event",
                results=results,
                regime=self._market_regime,
            )

            # Performance tracking
            self._perf_tracker.record_scan(
                scan_type="event",
                tickers_scanned=len(affected),
                opportunities_found=len(results),
                signals_generated=len([r for r in results if r.get("signal_type")]),
                duration_ms=0,  # Event anlık
                regime=self._market_regime,
            )

        # 7. Event scanner'dan temizle
        for ticker in affected:
            self._events.clear_rescan(ticker)

        return results

    # =====================================================
    # Yardımcı Fonksiyonlar
    # =====================================================

    async def _fetch_all_data(self):
        try:
            tickers = [f"{t}.IS" for t in self._universe]
            return yf.download(tickers, period="60d", group_by="ticker", threads=True, progress=False)
        except Exception as e:
            logger.error("Data fetch error", error=str(e))
            return None

    def _compute_all_features(self, data) -> dict[str, dict[str, float]]:
        import polars as pl

        from ..features.calculator import feature_calculator

        features_map = {}

        for ticker in self._universe:
            try:
                td = data[f"{ticker}.IS"].dropna()
                if len(td) < 20:
                    continue
                td = td.reset_index()
                df = pl.from_pandas(td[["Date", "Open", "High", "Low", "Close", "Volume"]])
                df = df.rename(
                    {
                        "Date": "timestamp",
                        "Open": "open",
                        "High": "high",
                        "Low": "low",
                        "Close": "close",
                        "Volume": "volume",
                    }
                )
                df = df.drop_nulls(subset=["close"])
                features = feature_calculator.compute_all_features(df)
                if features:
                    close_list = [x for x in df["close"].to_list() if x is not None]
                    features["price"] = close_list[-1] if close_list else 0
                    features_map[ticker] = features
            except Exception:
                logger.warning("Caught Exception in _compute_all_features", exc_info=True)
        return features_map

    def _detect_regime(self) -> tuple:
        if not self._features_map:
            return "RANGE", 0.5

        advancing = declining = 0
        volatilities, momentums = [], []

        for _ticker, features in self._features_map.items():
            ret = features.get("return_1d", 0)
            if ret > 0:
                advancing += 1
            elif ret < 0:
                declining += 1
            vol = features.get("realized_vol_20d", 20)
            if vol:
                volatilities.append(vol)
            mom = features.get("momentum_20d", 0)
            if mom:
                momentums.append(mom)

        total = advancing + declining
        breadth = (advancing / total * 100) if total > 0 else 50
        avg_vol = np.mean(volatilities) if volatilities else 20
        avg_mom = np.mean(momentums) if momentums else 0

        if breadth < 20 and avg_vol > 40:
            return "PANIC", 0.9
        elif breadth < 35:
            return "RISK-OFF", 0.8
        elif avg_vol > 35:
            return "HIGH-VOLATILITY", 0.7
        elif breadth > 70 and avg_mom > 5:
            return "MOMENTUM-EXPANSION", 0.8
        elif breadth > 65 and avg_mom > 0:
            return "TRENDING-UP", 0.7
        elif breadth < 40 and avg_mom < -5:
            return "TRENDING-DOWN", 0.7
        elif 45 < breadth < 55 and avg_mom > 0:
            return "RECOVERY", 0.6
        elif avg_vol < 12:
            return "LOW-VOLATILITY", 0.6
        else:
            return "RANGE", 0.5

    def _compute_single_feature(self, ticker: str) -> dict[str, float] | None:
        """Tek hisse için hızlı feature hesaplama (event fallback)."""
        from ..features.calculator import feature_calculator

        try:
            t = yf.Ticker(f"{ticker}.IS")
            hist = t.history(period="60d").reset_index()
            if len(hist) < 20:
                return None

            df = pl.from_pandas(hist[["Date", "Open", "High", "Low", "Close", "Volume"]])
            df = df.rename(
                {
                    "Date": "timestamp",
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
            )
            df = df.drop_nulls(subset=["close"])

            features = feature_calculator.compute_all_features(df)
            if features:
                close_list = [x for x in df["close"].to_list() if x is not None]
                features["price"] = close_list[-1] if close_list else 0
                self._features_map[ticker] = features
                return features
        except Exception as e:
            logger.warning("Single feature computation failed", ticker=ticker, error=str(e))

        return None

    def _compute_ml_scores(self) -> dict[str, float]:
        """
        ML skorları — gerçek model varsa kullanır, yoksa quant proxy.

        ml/model_loader.py'daki MLModelLoader:
        - Eğitilmiş model varsa → ML ensemble inference
        - Yoksa → Quant Probability Proxy (feature-based heuristic)
        """
        # Modelleri yükle (bir kez)
        if not self._ml_loader._loaded:
            self._ml_loader.load_models()

        scores = {}
        for ticker, features in self._features_map.items():
            result = self._ml_loader.predict_ensemble(features)
            # 0-100 skoruna çevir
            prediction = result.get("prediction", 0)
            result.get("confidence", 0.3)

            # Prediction'ı 0-100 skoruna normalize et
            score = 50 + prediction * 10  # -5..+5 → 45..55
            score = max(0, min(100, score))

            # Confidence ile ayarla
            source = result.get("source", "quant_proxy")
            if source == "quant_proxy":
                # Proxy düşük güven
                scores[ticker] = score
            else:
                # Gerçek ML modeli
                scores[ticker] = score

        return scores

    def get_last_summary(self) -> dict:
        """Son tarama ozetini dondur."""
        return self._last_scan_summary

    def get_last_results(self) -> list:
        """Son tarama sonuclarini dondur."""
        return self._last_scan_results

    def get_regime(self) -> str:
        """Mevcut piyasa rejimini dondur."""
        return self._market_regime

    def get_live_candidates(self) -> dict:
        """Canlı adaylari dondur."""
        return self._live.get_candidates()

    def get_event_candidates(self) -> dict:
        """Event adaylarini dondur."""
        return self._events.get_pending_rescans()


# Singleton
alpha_engine = AlphaEngine()
