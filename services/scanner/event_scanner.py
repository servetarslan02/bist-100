"""
ALPHA BIST — Event-Driven Scanner v1.0

Haber/KAP/makro geldiğinde → affected stocks → immediate rescan

Normal mod: 5 dakika beklemez.
Event geldiğinde Tier 0'dan Tier 3'e atlayabilir.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
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

            if ticker and importance > 0.5:
                affected.append(ticker)
                self._pending_rescans[ticker] = {
                    "event_type": "KAP",
                    "importance": importance,
                    "title": event_data.get("title", ""),
                    "timestamp": datetime.utcnow().isoformat(),
                }
                logger.info("KAP event → rescan", ticker=ticker, importance=importance)

        elif event_type == "news.event":
            # Haber etkilenen hisseleri bul
            affected_tickers = event_data.get("affected_tickers", [])
            importance = event_data.get("importance", 0)

            if importance > 0.6:
                for ticker in affected_tickers:
                    affected.append(ticker)
                    self._pending_rescans[ticker] = {
                        "event_type": "NEWS",
                        "importance": importance,
                        "title": event_data.get("title", ""),
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                logger.info("News event → rescan", tickers=affected, importance=importance)

        elif event_type == "macro.event":
            # Makro olay → tüm piyasayı etkiler ama bazı sektörleri daha fazla
            indicator = event_data.get("indicator", "")
            surprise = event_data.get("surprise_zscore", 0)

            if abs(surprise) > 1.5:
                # Sürpriz makro veri → bankacılık ve enerji hisselerini etkile
                affected = ["AKBNK", "GARAN", "YKBNK", "HALKB", "VAKBN",
                           "TUPRS", "PETKM", "THYAO"]
                for ticker in affected:
                    self._pending_rescans[ticker] = {
                        "event_type": "MACRO",
                        "importance": min(abs(surprise) / 3, 1.0),
                        "indicator": indicator,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                logger.info("Macro event → rescan", indicator=indicator, surprise=surprise)

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
        self._last_rescan[ticker] = datetime.utcnow()

    def clear_all(self):
        """Tüm bekleyen taramaları temizle."""
        self._pending_rescans.clear()

    def should_rescan(self, ticker: str) -> bool:
        """Bu hisse yeniden taranmalı mı?"""
        if ticker in self._pending_rescans:
            return True

        # Son yeniden taramadan bu yana 5 dakika geçtiyse
        last = self._last_rescan.get(ticker)
        if last and (datetime.utcnow() - last).total_seconds() > 300:
            return True

        return False

    def get_event_score(self, ticker: str) -> float:
        """
        Event etki skoru (0-100).
        Bu skor Opportunity Score'a dahil edilir.
        """
        pending = self._pending_rescans.get(ticker)
        if not pending:
            return 50.0  # Nötr

        importance = pending.get("importance", 0)
        event_type = pending.get("event_type", "")

        # Event tipine göre skor
        base_score = 50
        if event_type == "KAP":
            base_score += importance * 40
        elif event_type == "NEWS":
            base_score += importance * 30
        elif event_type == "MACRO":
            base_score += importance * 25

        return min(100, base_score)


# Singleton
event_scanner = EventScanner()
