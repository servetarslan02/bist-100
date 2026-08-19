"""
ALPHA BIST — Event-Driven Scanner v1.0

Haber/KAP/makro geldiğinde → affected stocks → immediate rescan

Normal mod: 5 dakika beklemez.
Event geldiğinde Tier 0'dan Tier 3'e atlayabilir.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


class EventScanner:
    """
    Event-driven scanner.
    Haber/KAP/makro geldiğinde etkilenen hisseleri anında yeniden analiz eder.
    """

    def __init__(self):
        self._pending_rescans: Dict[str, Dict] = {}  # ticker -> event data
        self._last_rescan: Dict[str, datetime] = {}

    def on_event(self, event_type: str, event_data: Dict) -> List[str]:
        """
        Event geldiğinde etkilenen hisseleri döndür.

        Returns: Etkilenen ticker listesi
        """
        affected = []

        if event_type == "kap.event":
            ticker = event_data.get("ticker", "")
            importance = event_data.get("importance", 0)
            direction = event_data.get("direction", 0)  # -1, 0, +1

            if ticker and importance > 0.5:
                affected.append(ticker)
                self._pending_rescans[ticker] = {
                    "event_type": "KAP",
                    "importance": importance,
                    "direction": direction,
                    "title": event_data.get("title", ""),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                logger.info("KAP event → rescan", ticker=ticker, importance=importance, direction=direction)

        elif event_type == "news.event":
            # Haber etkilenen hisseleri bul
            affected_tickers = event_data.get("affected_tickers", [])
            importance = event_data.get("importance", 0)
            direction = event_data.get("direction", 0)

            if importance > 0.6:
                for ticker in affected_tickers:
                    affected.append(ticker)
                    self._pending_rescans[ticker] = {
                        "event_type": "NEWS",
                        "importance": importance,
                        "direction": direction,
                        "title": event_data.get("title", ""),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                logger.info("News event → rescan", tickers=affected, importance=importance, direction=direction)

        elif event_type == "macro.event":
            # Makro olay → sektör exposure graph'a göre etkilenen hisseleri bul
            indicator = event_data.get("indicator", "")
            surprise = event_data.get("surprise_zscore", 0)

            if abs(surprise) > 1.5:
                affected = self._get_macro_affected_stocks(indicator, surprise)
                importance = min(abs(surprise) / 3, 1.0)
                direction = 1 if surprise > 0 else -1  # Pozitif sürpriz → LONG, negatif → SHORT

                for ticker in affected:
                    self._pending_rescans[ticker] = {
                        "event_type": "MACRO",
                        "importance": importance,
                        "direction": direction,
                        "indicator": indicator,
                        "surprise": surprise,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                logger.info("Macro event → rescan", indicator=indicator,
                           surprise=surprise, affected_count=len(affected))

        elif event_type == "market_state.changed":
            # Rejim değişimi → tüm hisseleri yeniden değerlendir
            old_regime = event_data.get("old_regime", "")
            new_regime = event_data.get("new_regime", "")
            logger.warning("REGIME CHANGE", old=old_regime, new=new_regime)
            # Tüm hisseler etkilenir ama bu batch scan'de ele alınır

        return affected

    def get_pending_rescans(self) -> Dict[str, Dict]:
        """Bekleyen yeniden tarama isteklerini döndür."""
        return self._pending_rescans.copy()

    def clear_rescan(self, ticker: str):
        """Yeniden tarama tamamlandı."""
        self._pending_rescans.pop(ticker, None)
        self._last_rescan[ticker] = datetime.now(timezone.utc)

    def clear_all(self):
        """Tüm bekleyen taramaları temizle."""
        self._pending_rescans.clear()

    def should_rescan(self, ticker: str) -> bool:
        """Bu hisse yeniden taranmalı mı?"""
        if ticker in self._pending_rescans:
            return True

        # Son yeniden taramadan bu yana 5 dakika geçtiyse
        last = self._last_rescan.get(ticker)
        if last and (datetime.now(timezone.utc) - last).total_seconds() > 300:
            return True

        return False

    def _get_macro_affected_stocks(self, indicator: str, surprise: float) -> List[str]:
        """
        Makro olaydan etkilenen hisseleri sektör exposure graph'a göre belirle.
        Hard-coded liste yok — sektör_relationships kullanır.
        """
        # Sektör exposure graph
        SECTOR_MACRO_EXPOSURE = {
            "CPI": ["BANK", "RETAIL", "FOOD"],
            "RATE": ["BANK", "REAL", "HOLDING"],
            "USD": ["ENERGY", "AVIATION", "METAL", "CHEM"],
            "OIL": ["ENERGY", "AVIATION", "TRANSPORT"],
            "GDP": ["INDUST", "RETAIL", "TECH"],
            "VIX": ["BANK", "HOLDING", "TECH"],
            "GOLD": ["MINING", "HOLDING"],
        }

        # Sektör → hisse eşleme
        SECTOR_STOCKS = {
            "BANK": ["AKBNK", "GARAN", "YKBNK", "HALKB", "VAKBN", "SKBNK"],
            "ENERGY": ["TUPRS", "PETKM", "AKSEN", "ODAS", "AYEN"],
            "AVIATION": ["THYAO", "PGSUS"],
            "METAL": ["EREGL", "KRDMD", "ISDMR"],
            "RETAIL": ["BIMAS", "MGROS", "SOKM"],
            "INDUST": ["ARCLK", "ASELS", "TOASO"],
            "TECH": ["ASELS", "NETAS", "LOGO"],
            "HOLDING": ["KCHOL", "SAHOL", "DOHOL"],
            "REAL": ["EKGYO", "HLGYO"],
            "FOOD": ["ULKER", "CCOLA", "AEFES"],
            "CHEM": ["SISE", "BAGFS", "SASA"],
            "TRANSPORT": ["THYAO", "PGSUS"],
            "MINING": [],
        }

        # Indicator'a göre sektörleri belirle
        indicator_upper = indicator.upper()
        exposed_sectors = []

        for key, sectors in SECTOR_MACRO_EXPOSURE.items():
            if key in indicator_upper:
                exposed_sectors.extend(sectors)

        # Eğer eşleşme yoksa genel etki
        if not exposed_sectors:
            exposed_sectors = ["BANK", "ENERGY", "HOLDING"]

        # Sektörlerden hisseleri topla
        affected = set()
        for sector in exposed_sectors:
            stocks = SECTOR_STOCKS.get(sector, [])
            affected.update(stocks)

        return list(affected)

    def get_event_score(self, ticker: str) -> float:
        """
        Event etki skoru (0-100).
        Event yönü (pozitif/negatif) ile birlikte hesaplanır.
        """
        pending = self._pending_rescans.get(ticker)
        if not pending:
            return 50.0  # Nötr

        importance = pending.get("importance", 0)
        event_type = pending.get("event_type", "")
        direction = pending.get("direction", 0)  # -1, 0, +1

        # Event tipine göre base skor
        base_score = 50
        if event_type == "KAP":
            base_score += importance * 40 * direction
        elif event_type == "NEWS":
            base_score += importance * 30 * direction
        elif event_type == "MACRO":
            base_score += importance * 25 * direction

        # Direction 0 ise (belirlenmemiş), importance'ın yarısını pozitif say
        if direction == 0 and importance > 0:
            base_score += importance * 15  # Nötr ama etkili event

        return max(0, min(100, base_score))

    def set_event_direction(self, ticker: str, direction: int):
        """Event yönünü belirle: +1 pozitif, -1 negatif, 0 nötr."""
        if ticker in self._pending_rescans:
            self._pending_rescans[ticker]["direction"] = direction


# Singleton
event_scanner = EventScanner()
