"""
ALPHA BIST — Point-in-Time Store v1.0

Geleceğe sızıntıyı (look-ahead bias) engelleyen veri deposu.

Her veri kaydı:
- O tarihte bilinen versiyon olarak saklanır
- Sonradan düzeltmeler yeni kayıt olarak eklenir (eski kayıt silinmez)
- Backtest sadece o tarihte bilinen veriyi görür

Kaynak: Quant research — pandas index alignment ile gelecek veri sızıntısı
"""

import functools
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.pit_store")


def otel_trace(span_name: str) -> Any:
    """Decorator to wrap a method in an OTel span."""

    def decorator(func) -> Any:
        """Otomatik eklendi."""
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs) -> Any:
            """Otomatik eklendi."""
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


@dataclass
class PITRecord:
    """Point-in-Time kayıt."""

    ticker: str
    field_name: str  # price, revenue, pe_ratio, vb.
    value: Any
    valid_from: datetime  # Bu tarihten itibaren biliniyor
    valid_until: datetime | None = None  # Bu tarihte düzeltildi
    source: str = ""
    revision: int = 0  # Kaçıncı revizyon


class PointInTimeStore:
    """Point-in-Time veri deposu.

    Kritik kural: Backtest'te sadece o tarihte bilinen veri kullanılır.
    Sonradan düzeltilmiş bilanço geçmişe sızamaz.
    """

    def __init__(self):
        """Otomatik eklendi."""
        # ticker → field_name → [PITRecord] (zaman sıralı)
        self._store: dict[str, dict[str, list[PITRecord]]] = {}

    @otel_trace("pit_store.insert")
    def insert(
        self,
        ticker: str,
        field_name: str,
        value: Any,
        valid_from: datetime,
        source: str = "",
    ) -> Any:
        """Yeni veri kaydet (veya mevcut kaydı güncelle)."""
        if ticker not in self._store:
            self._store[ticker] = {}
        if field_name not in self._store[ticker]:
            self._store[ticker][field_name] = []

        records = self._store[ticker][field_name]

        # Mevcut kaydın valid_until'ünü güncelle
        if records:
            last = records[-1]
            if last.valid_until is None:
                last.valid_until = valid_from

        # Yeni kayıt ekle
        new_record = PITRecord(
            ticker=ticker,
            field_name=field_name,
            value=value,
            valid_from=valid_from,
            source=source,
            revision=len(records),
        )
        records.append(new_record)

    @otel_trace("pit_store.get_as_of")
    def get_as_of(
        self,
        ticker: str,
        field_name: str,
        as_of_date: datetime,
    ) -> Any | None:
        """Belirli bir tarihte bilinen değeri döndür.

        Kritik: Sadece as_of_date'ten ÖNCE bilinen veriyi döndürür.
        """
        records = self._store.get(ticker, {}).get(field_name, [])

        # as_of_date'ten önceki en son kayıt
        result = None
        for record in records:
            if record.valid_from <= as_of_date:
                result = record.value
            else:
                break  # Kayıtlar zaman sıralı

        return result

    @otel_trace("pit_store.get_latest")
    def get_latest(self, ticker: str, field_name: str) -> Any | None:
        """En son kaydedilen değeri döndür."""
        records = self._store.get(ticker, {}).get(field_name, [])
        return records[-1].value if records else None

    @otel_trace("pit_store.get_history")
    def get_history(
        self,
        ticker: str,
        field_name: str,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[dict]:
        """Değer geçmişini döndür."""
        records = self._store.get(ticker, {}).get(field_name, [])
        result = []

        for r in records:
            if from_date and r.valid_from < from_date:
                continue
            if to_date and r.valid_from > to_date:
                continue
            result.append(
                {
                    "value": r.value,
                    "valid_from": r.valid_from.isoformat(),
                    "valid_until": r.valid_until.isoformat() if r.valid_until else None,
                    "source": r.source,
                    "revision": r.revision,
                }
            )

        return result

    @otel_trace("pit_store.get_revisions")
    def get_revisions(self, ticker: str, field_name: str) -> int:
        """Toplam revizyon sayısı."""
        return len(self._store.get(ticker, {}).get(field_name, []))

    @otel_trace("pit_store.bulk_insert")
    def bulk_insert(
        self,
        ticker: str,
        data: dict[str, Any],
        valid_from: datetime,
        source: str = "",
    ) -> Any:
        """Toplu veri kaydetme."""
        for field_name, value in data.items():
            self.insert(ticker, field_name, value, valid_from, source)

    @otel_trace("pit_store.get_stats")
    def get_stats(self) -> dict:
        """İstatistikler."""
        total_records = sum(len(records) for fields in self._store.values() for records in fields.values())
        return {
            "tickers": len(self._store),
            "total_records": total_records,
        }


# Singleton
pit_store = PointInTimeStore()
