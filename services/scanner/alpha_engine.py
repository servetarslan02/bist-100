"""
ALPHA BIST — Alpha Engine v1.0

Tüm pipeline'ı tek bir motor haline getirir.
800 hisse → data → bars → features → regime → scanner → signals

Bu, ALPHA'nın kalbidir. Tek seferde çalışır, her şey otomatik.
"""

import asyncio
import time
import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime
import structlog

logger = structlog.get_logger()


class AlphaEngine:
    """
    ALPHA'nın ana motoru.

    Tüm pipeline tek bir yerde:
    1. 800 hisseyi yükle
    2. Veri çek (yfinance batch)
    3. Feature hesapla
    4. Market regime belirle
    5. Scanner çalıştır
    6. Sinyal üret
    7. Trade planları oluştur
    8. Bildirim üret
    """

    def __init__(self):
        self._universe: List[str] = []
        self._features_map: Dict[str, Dict[str, float]] = {}
        self._market_regime: str = "RANGE"
        self._regime_confidence: float = 0.5
        self._last_scan_results: List = []
        self._last_scan_summary: Dict = {}
        self._scan_count: int = 0
        self._running: bool = False

    def load_universe(self, tickers: List[str]):
        """800 hisseyi yükle."""
        self._universe = tickers
        logger.info("Universe loaded", count=len(tickers))

    async def run_full_cycle(self) -> Dict[str, Any]:
        """
        Tam döngü çalıştır.

        Returns: Scan summary
        """
        start = time.time()
        self._scan_count += 1

        logger.info("=== ALPHA ENGINE CYCLE START ===",
                    scan_count=self._scan_count,
                    universe=len(self._universe))

        # 1. Veri çek
        data = await self._fetch_all_data()
        if data is None or data.empty:
            logger.error("Data fetch failed")
            return {"error": "Data fetch failed"}

        # 2. Feature hesapla
        self._features_map = self._compute_all_features(data)
        logger.info("Features computed", count=len(self._features_map))

        # 3. Market regime belirle
        self._market_regime, self._regime_confidence = self._detect_regime()
        logger.info("Regime detected", regime=self._market_regime,
                    confidence=self._regime_confidence)

        # 4. Scanner çalıştır
        from .alpha_scanner import alpha_scanner
        results = alpha_scanner.scan(
            universe=list(self._features_map.keys()),
            features_map=self._features_map,
            market_regime=self._market_regime,
            regime_confidence=self._regime_confidence,
        )
        self._last_scan_results = results

        # 5. Özet oluştur
        summary = alpha_scanner.get_summary(results)
        summary["scan_count"] = self._scan_count
        summary["elapsed_seconds"] = round(time.time() - start, 1)
        summary["regime"] = self._market_regime
        summary["regime_confidence"] = self._regime_confidence
        self._last_scan_summary = summary

        logger.info("=== ALPHA ENGINE CYCLE COMPLETE ===",
                    scanned=summary["total_scanned"],
                    signals=summary["signals_generated"],
                    anomalies=summary["anomalies"],
                    elapsed=summary["elapsed_seconds"])

        return summary

    async def _fetch_all_data(self) -> Optional[Any]:
        """Tüm BIST verisini çek."""
        import yfinance as yf

        try:
            tickers = [f"{t}.IS" for t in self._universe]
            data = yf.download(
                tickers, period="60d", group_by="ticker",
                threads=True, progress=False,
            )
            return data
        except Exception as e:
            logger.error("Data fetch error", error=str(e))
            return None

    def _compute_all_features(self, data) -> Dict[str, Dict[str, float]]:
        """Tüm hisseler için feature hesapla."""
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
                df = df.rename({
                    "Date": "timestamp", "Open": "open", "High": "high",
                    "Low": "low", "Close": "close", "Volume": "volume",
                })
                df = df.drop_nulls(subset=["close"])

                features = fc.compute_all_features(df)
                if features:
                    close_list = [x for x in df["close"].to_list() if x is not None]
                    features["price"] = close_list[-1] if close_list else 0
                    features_map[ticker] = features

            except Exception:
                pass

        return features_map

    def _detect_regime(self) -> tuple:
        """Market regime tespit et."""
        if not self._features_map:
            return "RANGE", 0.5

        # Breadth hesapla
        advancing = 0
        declining = 0
        total = 0
        volatilities = []
        momentums = []

        for ticker, features in self._features_map.items():
            ret = features.get("return_1d", 0)
            if ret > 0:
                advancing += 1
            elif ret < 0:
                declining += 1
            total += 1

            vol = features.get("realized_vol_20d", 20)
            if vol:
                volatilities.append(vol)

            mom = features.get("momentum_20d", 0)
            if mom:
                momentums.append(mom)

        breadth = (advancing / total * 100) if total > 0 else 50
        avg_vol = np.mean(volatilities) if volatilities else 20
        avg_mom = np.mean(momentums) if momentums else 0

        # Regime belirle
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

    def get_last_summary(self) -> Dict:
        """Son tarama özeti."""
        return self._last_scan_summary

    def get_last_results(self) -> List:
        """Son tarama sonuçları."""
        return self._last_scan_results

    def get_regime(self) -> str:
        """Mevcut rejim."""
        return self._market_regime


# Singleton
alpha_engine = AlphaEngine()
