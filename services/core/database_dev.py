"""ALPHA BIST — Geliştirme ve Eski Sürümler İçin Veritabanı Uyumluluk Katmanı (Compatibility Shim)

DEPRECATED: Bu modül yalnızca eski testler ve geriye dönük uyumluluk için korunmaktadır.
Tüm üretim ve servis kodu doğrudan `services.core.database` modülünü kullanmalıdır.

Bu uyumluluk modülü, eski kodların kırılmaması amacıyla temel veritabanı fonksiyonlarını
ve `dev_db` nesnesini merkezi `services.core.database` üzerine yönlendirerek dışa aktarır.
"""

from __future__ import annotations

import warnings
from typing import Any

from services.core.otel import otel_trace

from .database import (
    close_databases,
    get_db_pool,
    get_pg_pool,
    init_databases,
    pg_execute,
    pg_fetch,
    pg_fetchrow,
    pg_fetchval,
)

warnings.warn(
    "services.core.database_dev modülü kullanımdan kaldırılmıştır (DEPRECATED). "
    "Lütfen doğrudan services.core.database modülünü kullanınız.",
    DeprecationWarning,
    stacklevel=2,
)


class _DevDBCompat:
    """Eski `dev_db` arabirimini taklit eden geriye dönük uyumluluk sarmalayıcısı."""

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        return "<_DevDBCompat shim -> services.core.database>"

    @otel_trace("database_dev.pg_fetch")
    async def pg_fetch(self, query: str, *args: Any) -> list[Any]:
        """PostgreSQL havuzundan satır listesi çeker.

        Args:
            query: SQL sorgu metni.
            *args: Sorgu parametreleri.

        Returns:
            list[Any]: Kayıt listesi.
        """
        return await pg_fetch(query, *args)

    @otel_trace("database_dev.pg_fetchrow")
    async def pg_fetchrow(self, query: str, *args: Any) -> Any | None:
        """PostgreSQL havuzundan tek bir satır çeker.

        Args:
            query: SQL sorgu metni.
            *args: Sorgu parametreleri.

        Returns:
            Any | None: Bulunan tek kayıt veya None.
        """
        return await pg_fetchrow(query, *args)

    @otel_trace("database_dev.pg_fetchval")
    async def pg_fetchval(self, query: str, *args: Any) -> Any:
        """PostgreSQL havuzundan tek bir skalar değer çeker.

        Args:
            query: SQL sorgu metni.
            *args: Sorgu parametreleri.

        Returns:
            Any: Skalar değer.
        """
        return await pg_fetchval(query, *args)

    @otel_trace("database_dev.pg_execute")
    async def pg_execute(self, query: str, *args: Any) -> str:
        """PostgreSQL üzerinde yazma veya güncelleme sorgusu çalıştırır.

        Args:
            query: SQL sorgu metni.
            *args: Sorgu parametreleri.

        Returns:
            str: İşlem sonuç durumu.
        """
        return await pg_execute(query, *args)

    @otel_trace("database_dev.init")
    async def init(self) -> None:
        """Tüm veritabanı altyapı havuzlarını başlatır."""
        await init_databases()

    @otel_trace("database_dev.close")
    async def close(self) -> None:
        """Tüm veritabanı altyapı havuzlarını kapatır."""
        await close_databases()


dev_db = _DevDBCompat()

__all__ = [
    "_DevDBCompat",
    "close_databases",
    "dev_db",
    "get_db_pool",
    "get_pg_pool",
    "init_databases",
    "pg_execute",
    "pg_fetch",
    "pg_fetchrow",
    "pg_fetchval",
]
