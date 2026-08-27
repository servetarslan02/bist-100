"""
ALPHA BIST — Macro Historical Data Store v1.0

Tarihsel makro veri deposu — point-in-time:
- Tarihsel veri kaydetme/okuma
- Point-in-time erişim (look-ahead bias yok)
- Backfill desteği
- JSON-based storage

KURAL: Backtest'te sadece o tarihte bilinen veriyi kullan.
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import orjson
import structlog

logger = structlog.get_logger()


@dataclass
class MacroDataPoint:
    """Tek veri noktası."""

    date: str
    indicator: str
    value: float
    source: str
    timestamp: str


class MacroHistoricalStore:
    """Tarihsel makro veri deposu."""

    def __init__(self, storage_path: str = "data/macro_historical.json"):
        self._storage_path = storage_path
        self._data: dict[str, dict[str, list[dict]]] = {}  # indicator → {date → [values]}
        self._load()

    def save(
        self,
        date: str,
        indicator: str,
        value: float,
        source: str = "unknown",
    ):
        """Makro veri kaydet.

        Args:
            date: Tarih (YYYY-MM-DD)
            indicator: Gösterge adı (USDTRY, CPI, POLICY_RATE, vb.)
            value: Değer
            source: Veri kaynağı
        """
        if indicator not in self._data:
            self._data[indicator] = {}

        if date not in self._data[indicator]:
            self._data[indicator][date] = []

        entry = {
            "value": value,
            "source": source,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        self._data[indicator][date].append(entry)
        self._save()

        logger.debug("Macro data saved", indicator=indicator, date=date, value=value)

    def get(
        self,
        date: str,
        indicator: str,
    ) -> float | None:
        """Belirli tarihteki veriyi getir (point-in-time).

        Args:
            date: Tarih (YYYY-MM-DD)
            indicator: Gösterge adı

        Returns:
            Değer veya None
        """
        indicator_data = self._data.get(indicator, {})
        date_data = indicator_data.get(date)

        if date_data:
            # Son kaydedilen değeri döndür
            return date_data[-1]["value"]

        return None

    def get_latest_before(
        self,
        date: str,
        indicator: str,
    ) -> dict[str, Any] | None:
        """Belirli tarihten önceki en son veriyi getir (PIT)."""
        indicator_data = self._data.get(indicator, {})

        # Tarihten önceki tüm tarihleri bul
        earlier_dates = [d for d in indicator_data if d <= date]

        if not earlier_dates:
            return None

        latest_date = max(earlier_dates)
        latest_entry = indicator_data[latest_date][-1]

        return {
            "date": latest_date,
            "indicator": indicator,
            "value": latest_entry["value"],
            "source": latest_entry["source"],
        }

    def get_range(
        self,
        indicator: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Tarih aralığındaki veriyi getir."""
        indicator_data = self._data.get(indicator, {})

        result = []
        for date, entries in sorted(indicator_data.items()):
            if start_date <= date <= end_date:
                latest = entries[-1]
                result.append(
                    {
                        "date": date,
                        "indicator": indicator,
                        "value": latest["value"],
                        "source": latest["source"],
                    }
                )

        return result

    def get_latest(self, indicator: str) -> dict[str, Any] | None:
        """Son veriyi getir."""
        indicator_data = self._data.get(indicator, {})

        if not indicator_data:
            return None

        latest_date = max(indicator_data.keys())
        latest_entry = indicator_data[latest_date][-1]

        return {
            "date": latest_date,
            "indicator": indicator,
            "value": latest_entry["value"],
            "source": latest_entry["source"],
        }

    def backfill(
        self,
        indicator: str,
        data: list[dict[str, Any]],
    ):
        """Toplu veri yükleme (backfill).

        Args:
            indicator: Gösterge adı
            data: [{"date": "YYYY-MM-DD", "value": float, "source": str}]
        """
        count = 0
        for entry in data:
            self.save(
                date=entry["date"],
                indicator=indicator,
                value=entry["value"],
                source=entry.get("source", "backfill"),
            )
            count += 1

        logger.info("Backfill completed", indicator=indicator, count=count)

    def get_available_indicators(self) -> list[str]:
        """Mevcut göstergeleri listele."""
        return list(self._data.keys())

    def get_date_range(self, indicator: str) -> dict[str, str] | None:
        """Göstergenin tarih aralığını döndür."""
        indicator_data = self._data.get(indicator, {})

        if not indicator_data:
            return None

        dates = sorted(indicator_data.keys())
        return {
            "indicator": indicator,
            "start_date": dates[0],
            "end_date": dates[-1],
            "total_points": len(dates),
        }

    def get_report(self) -> dict[str, Any]:
        """Rapor."""
        indicators = self.get_available_indicators()
        total_points = sum(sum(len(entries) for entries in ind_data.values()) for ind_data in self._data.values())

        return {
            "indicators": len(indicators),
            "total_data_points": total_points,
            "indicator_list": indicators,
            "storage_path": self._storage_path,
        }

    # ===================== PERSISTENCE =====================

    def _load(self):
        """Veriyi dosyadan yükle."""
        if os.path.exists(self._storage_path):
            try:
                with open(self._storage_path) as f:
                    self._data = orjson.loads(f.read())
                logger.info("Historical store loaded", indicators=len(self._data), path=self._storage_path)
            except Exception as e:
                logger.error("Failed to load historical store", error=str(e))
                self._data = {}

    def _save(self):
        """Veriyi dosyaya kaydet."""
        try:
            os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)
            with open(self._storage_path, "w") as f:
                f.write(orjson.dumps(self._data, option=orjson.OPT_INDENT_2).decode())
        except Exception as e:
            logger.error("Failed to save historical store", error=str(e))


# Singleton
macro_historical_store = MacroHistoricalStore()
