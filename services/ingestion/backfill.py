"""
ALPHA BIST — Backfill Manager v1.0

Kapalı kalınan süredeki eksik verileri tespit edip doldurur.

Kişisel PC senaryosu:
- PC kapalıyken kaçırılan piyasa verilerini geriye dönük çeker
- ClickHouse'da eksik bar'ları tespit eder
- Günlük, saatlik ve tick bazlı backfill desteği
- Rate limiting ile kaynak dostu çalışır
- Öncelik sırası: yakın tarih → uzak tarih

Kullanım:
    from services.ingestion.backfill import backfill_manager

    # Startup'ta çalıştır
    gaps = await backfill_manager.detect_all_gaps()
    await backfill_manager.backfill_all(gaps)
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger()

SECONDS_PER_DAY: float = 86400.0
"""Bir gündeki saniye sayısı."""


class BackfillPriority(StrEnum):
    """Backfill öncelik seviyeleri.

    Attributes:
        CRITICAL: Son 1 gün içindeki eksiklik.
        HIGH: Son 1 hafta içindeki eksiklik.
        MEDIUM: Son 1 ay içindeki eksiklik.
        LOW: 1 aydan eski eksiklik.
    """

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class DataGap:
    """Veri boşluğu bilgisi.

    Attributes:
        ticker: Hisse senedi kodu.
        gap_start: Boşluğun başladığı tarih.
        gap_end: Boşluğun bittiği tarih.
        gap_type: Boşluk türü ("daily", "hourly", "tick").
        priority: Backfill önceliği.
        estimated_bars: Tahmini bar sayısı.
    """

    ticker: str
    gap_start: datetime
    gap_end: datetime
    gap_type: str
    priority: BackfillPriority = BackfillPriority.MEDIUM
    estimated_bars: int = 0

    def __repr__(self) -> str:
        return (
            f"DataGap(ticker={self.ticker!r}, "
            f"gap_start={self.gap_start.isoformat()!r}, "
            f"gap_end={self.gap_end.isoformat()!r}, "
            f"priority={self.priority.value!r})"
        )

    @property
    def gap_days(self) -> float:
        """Boşluğun gün cinsinden süresi."""
        return (self.gap_end - self.gap_start).total_seconds() / SECONDS_PER_DAY


@dataclass
class BackfillResult:
    """Tek bir backfill işleminin sonucu.

    Attributes:
        ticker: Hisse senedi kodu.
        gap_start: Doldurulan boşluğun başlangıcı.
        gap_end: Doldurulan boşluğun bitişi.
        bars_filled: Doldurulan bar sayısı.
        success: İşlem başarılı mı.
        error: Hata mesajı (başarısızsa).
        duration_seconds: İşlem süresi (saniye).
    """

    ticker: str
    gap_start: datetime
    gap_end: datetime
    bars_filled: int = 0
    success: bool = False
    error: str | None = None
    duration_seconds: float = 0.0

    def __repr__(self) -> str:
        return (
            f"BackfillResult(ticker={self.ticker!r}, "
            f"success={self.success}, bars_filled={self.bars_filled}, "
            f"duration={self.duration_seconds:.1f}s)"
        )


@dataclass
class BackfillStats:
    """Backfill toplam istatistikleri.

    Attributes:
        total_gaps: Toplam tespit edilen boşluk sayısı.
        gaps_filled: Başarıyla doldurulan boşluk sayısı.
        gaps_failed: Başarısız olan boşluk sayısı.
        total_bars_filled: Toplam doldurulan bar sayısı.
        total_duration_seconds: Toplam işlem süresi.
        last_backfill_time: Son backfill zaman damgası (epoch).
    """

    total_gaps: int = 0
    gaps_filled: int = 0
    gaps_failed: int = 0
    total_bars_filled: int = 0
    total_duration_seconds: float = 0.0
    last_backfill_time: float | None = None

    def __repr__(self) -> str:
        return (
            f"BackfillStats(total_gaps={self.total_gaps}, "
            f"filled={self.gaps_filled}, failed={self.gaps_failed}, "
            f"bars={self.total_bars_filled})"
        )


class BackfillManager:
    """Veri boşluğu tespit ve doldurma yöneticisi.

    Özellikler:
    - ClickHouse ve PostgreSQL'de eksik bar tespiti
    - Günlük veri backfill (yfinance)
    - Rate limiting (API limit aşımı önleme)
    - Öncelik sıralama (yeni → eski)
    - Chunk'lı çalışma (bellek dostu)
    - Progress tracking

    Raises:
        ValueError: Boşluk listesi boş olduğunda.
    """

    # Backfill'in yazdığı tablo adı — gap tespiti ile aynı olmalı
    TABLE_DAILY_BARS: str = "daily_bars"

    def __init__(
        self,
        max_lookback_days: int = 30,
        chunk_size: int = 10,
        delay_between_chunks: float = 2.0,
        delay_between_tickers: float = 0.5,
    ) -> None:
        """BackfillManager örneği oluşturur.

        Args:
            max_lookback_days: Geriye dönük bakılacak maksimum gün sayısı.
            chunk_size: Aynı anda işlenecek boşluk sayısı.
            delay_between_chunks: Chunk'lar arası bekleme süresi (saniye).
            delay_between_tickers: Ticker'lar arası bekleme süresi (saniye).
        """
        self._max_lookback_days = max_lookback_days
        self._chunk_size = chunk_size
        self._delay_chunks = delay_between_chunks
        self._delay_tickers = delay_between_tickers

        self._stats = BackfillStats()
        self._running = False
        self._progress: dict[str, Any] = {}

    async def detect_all_gaps(
        self,
        tickers: list[str] | None = None,
        clickhouse_client: Any | None = None,
        pg_pool: Any | None = None,
    ) -> list[DataGap]:
        """Tüm ticker'lar için veri boşluklarını tespit eder.

        Args:
            tickers: Ticker listesi (None = tüm BIST).
            clickhouse_client: ClickHouse bağlantı nesnesi.
            pg_pool: PostgreSQL connection pool.

        Returns:
            Tespit edilen boşluklar (öncelik sırasıyla).
        """
        gaps: list[DataGap] = []

        if not tickers:
            try:
                from ..ingestion.bist_universe import bist_universe

                tickers = bist_universe.get_tickers()
            except Exception as exc:
                logger.warning("Cannot load BIST universe for gap detection", error=str(exc))
                return []

        logger.info("Detecting data gaps", tickers=len(tickers))

        for ticker in tickers:
            try:
                ticker_gaps = await self._detect_ticker_gaps(ticker, clickhouse_client, pg_pool)
                gaps.extend(ticker_gaps)
            except Exception as exc:
                logger.warning("Gap detection failed", ticker=ticker, error=str(exc))

        # Öncelik sırasına göre sırala
        priority_order = {
            BackfillPriority.CRITICAL: 0,
            BackfillPriority.HIGH: 1,
            BackfillPriority.MEDIUM: 2,
            BackfillPriority.LOW: 3,
        }
        gaps.sort(key=lambda g: (priority_order[g.priority], g.gap_start))

        self._stats.total_gaps = len(gaps)
        logger.info(
            "Data gaps detected",
            total_gaps=len(gaps),
            critical=sum(1 for g in gaps if g.priority == BackfillPriority.CRITICAL),
            high=sum(1 for g in gaps if g.priority == BackfillPriority.HIGH),
        )

        return gaps

    async def _detect_ticker_gaps(
        self,
        ticker: str,
        clickhouse_client: Any | None = None,
        pg_pool: Any | None = None,
    ) -> list[DataGap]:
        """Tek ticker için veri boşluklarını tespit eder.

        Args:
            ticker: Hisse senedi kodu.
            clickhouse_client: ClickHouse bağlantı nesnesi.
            pg_pool: PostgreSQL connection pool.

        Returns:
            Ticker'a ait boşluk listesi.
        """
        gaps: list[DataGap] = []

        last_date = await self._get_last_recorded_date(ticker, clickhouse_client, pg_pool)

        if last_date is None:
            gap_start = datetime.now(UTC) - timedelta(days=self._max_lookback_days)
            gap_end = datetime.now(UTC)
            gaps.append(
                DataGap(
                    ticker=ticker,
                    gap_start=gap_start,
                    gap_end=gap_end,
                    gap_type="daily",
                    priority=BackfillPriority.CRITICAL,
                    estimated_bars=int(self._max_lookback_days),
                )
            )
            return gaps

        now = datetime.now(UTC)
        gap_days = (now - last_date).total_seconds() / SECONDS_PER_DAY

        if gap_days < 1:
            return []

        if gap_days <= 3:
            priority = BackfillPriority.CRITICAL
        elif gap_days <= 7:
            priority = BackfillPriority.HIGH
        elif gap_days <= 30:
            priority = BackfillPriority.MEDIUM
        else:
            priority = BackfillPriority.LOW

        gap_start = last_date + timedelta(days=1)
        business_days = self._count_business_days(gap_start, now)

        gaps.append(
            DataGap(
                ticker=ticker,
                gap_start=gap_start,
                gap_end=now,
                gap_type="daily",
                priority=priority,
                estimated_bars=business_days,
            )
        )

        return gaps

    async def _get_last_recorded_date(
        self,
        ticker: str,
        clickhouse_client: Any | None = None,
        pg_pool: Any | None = None,
    ) -> datetime | None:
        """Ticker için son kayıtlı tarihi bulur.

        Args:
            ticker: Hisse senedi kodu.
            clickhouse_client: ClickHouse bağlantı nesnesi.
            pg_pool: PostgreSQL connection pool.

        Returns:
            Son kayıt tarihi veya None.
        """
        if clickhouse_client:
            try:
                result = clickhouse_client.query(
                    f"SELECT max(timestamp) as last_ts FROM {self.TABLE_DAILY_BARS} WHERE ticker = %(ticker)s",
                    {"ticker": ticker},
                )
                if result.result_rows and result.result_rows[0][0]:
                    return result.result_rows[0][0]
            except Exception as exc:
                logger.warning(
                    "ClickHouse son kayıt sorgusu başarısız",
                    ticker=ticker,
                    error=str(exc),
                )

        if pg_pool:
            try:
                async with pg_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        f"SELECT max(trade_date) as last_ts FROM {self.TABLE_DAILY_BARS} WHERE ticker = $1",
                        ticker,
                    )
                    if row and row["last_ts"]:
                        return row["last_ts"]
            except Exception as exc:
                logger.warning(
                    "PostgreSQL son kayıt sorgusu başarısız",
                    ticker=ticker,
                    error=str(exc),
                )

        return None

    async def backfill_all(
        self,
        gaps: list[DataGap],
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> list[BackfillResult]:
        """Tüm boşlukları doldurur.

        Args:
            gaps: Doldurulacak boşluk listesi.
            progress_callback: İlerleme callback'i (ticker, progress_pct).

        Returns:
            Her boşluk için BackfillResult listesi.
        """
        if not gaps:
            logger.info("Backfill: boşluk listesi boş, işlem yapılmadı")
            return []

        self._running = True
        results: list[BackfillResult] = []
        start_time = time.time()
        total_gaps = len(gaps)

        logger.info("Starting backfill", total_gaps=total_gaps)

        for i in range(0, total_gaps, self._chunk_size):
            if not self._running:
                break

            chunk = gaps[i : i + self._chunk_size]
            chunk_results = await self._backfill_chunk(chunk, progress_callback, processed=i, total=total_gaps)
            results.extend(chunk_results)

            if i + self._chunk_size < total_gaps:
                await asyncio.sleep(self._delay_chunks)

        self._stats.gaps_filled = sum(1 for r in results if r.success)
        self._stats.gaps_failed = sum(1 for r in results if not r.success)
        self._stats.total_bars_filled = sum(r.bars_filled for r in results)
        self._stats.total_duration_seconds = time.time() - start_time
        self._stats.last_backfill_time = time.time()

        logger.info(
            "Backfill completed",
            filled=self._stats.gaps_filled,
            failed=self._stats.gaps_failed,
            bars=self._stats.total_bars_filled,
            duration_seconds=round(self._stats.total_duration_seconds, 1),
        )

        return results

    async def _backfill_chunk(
        self,
        gaps: list[DataGap],
        progress_callback: Callable[[str, float], None] | None = None,
        processed: int = 0,
        total: int = 1,
    ) -> list[BackfillResult]:
        """Boşluk chunk'ını doldurur.

        Args:
            gaps: İşlenecek boşluklar.
            progress_callback: İlerleme callback'i.
            processed: Şimdiye kadar işlenen boşluk sayısı.
            total: Toplam boşluk sayısı.

        Returns:
            Sonuç listesi.
        """
        results: list[BackfillResult] = []

        for idx, gap in enumerate(gaps):
            if not self._running:
                break

            result = await self._backfill_single_gap(gap)
            results.append(result)

            if progress_callback:
                pct = ((processed + idx + 1) / total) * 100
                try:
                    progress_callback(gap.ticker, pct)
                except Exception as exc:
                    logger.warning("Progress callback hatası", error=str(exc))

            await asyncio.sleep(self._delay_tickers)

        return results

    async def _backfill_single_gap(self, gap: DataGap) -> BackfillResult:
        """Tek bir boşluğu doldurur.

        Args:
            gap: Doldurulacak boşluk.

        Returns:
            BackfillResult: İşlem sonucu.
        """
        start_time = time.time()

        try:
            import yfinance as yf

            logger.info(
                "Backfilling",
                ticker=gap.ticker,
                from_date=gap.gap_start.date().isoformat(),
                to_date=gap.gap_end.date().isoformat(),
                priority=gap.priority.value,
            )

            ticker_symbol = f"{gap.ticker}.IS"
            t = yf.Ticker(ticker_symbol)

            hist = t.history(
                start=gap.gap_start.strftime("%Y-%m-%d"),
                end=gap.gap_end.strftime("%Y-%m-%d"),
                interval="1d",
            )

            if hist.empty:
                return BackfillResult(
                    ticker=gap.ticker,
                    gap_start=gap.gap_start,
                    gap_end=gap.gap_end,
                    bars_filled=0,
                    success=True,
                    duration_seconds=time.time() - start_time,
                )

            bars_filled = len(hist)

            try:
                from ..core.database import pg_execute

                for idx, row in hist.iterrows():
                    trade_date = idx.date() if hasattr(idx, "date") else idx
                    await pg_execute(
                        f"""INSERT INTO {self.TABLE_DAILY_BARS} (ticker, trade_date, open, high, low, close, volume)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT (ticker, trade_date) DO UPDATE SET
                            open = EXCLUDED.open, high = EXCLUDED.high,
                            low = EXCLUDED.low, close = EXCLUDED.close,
                            volume = EXCLUDED.volume""",
                        gap.ticker,
                        trade_date,
                        float(row.get("Open", 0)),
                        float(row.get("High", 0)),
                        float(row.get("Low", 0)),
                        float(row.get("Close", 0)),
                        int(row.get("Volume", 0)),
                    )
            except Exception as write_err:
                logger.error(
                    "Backfill DB yazma hatası",
                    ticker=gap.ticker,
                    error=str(write_err),
                )
                return BackfillResult(
                    ticker=gap.ticker,
                    gap_start=gap.gap_start,
                    gap_end=gap.gap_end,
                    bars_filled=0,
                    success=False,
                    error=f"DB write failed: {write_err}",
                    duration_seconds=time.time() - start_time,
                )

            logger.info("Backfill data fetched", ticker=gap.ticker, bars=bars_filled)

            return BackfillResult(
                ticker=gap.ticker,
                gap_start=gap.gap_start,
                gap_end=gap.gap_end,
                bars_filled=bars_filled,
                success=True,
                duration_seconds=time.time() - start_time,
            )

        except Exception as exc:
            logger.error("Backfill failed", ticker=gap.ticker, error=str(exc))
            return BackfillResult(
                ticker=gap.ticker,
                gap_start=gap.gap_start,
                gap_end=gap.gap_end,
                bars_filled=0,
                success=False,
                error=str(exc),
                duration_seconds=time.time() - start_time,
            )

    def _count_business_days(self, start: datetime, end: datetime) -> int:
        """İki tarih arasındaki iş günü sayısını hesaplar.

        Args:
            start: Başlangıç tarihi.
            end: Bitiş tarihi.

        Returns:
            İş günü sayısı.
        """
        count = 0
        current = start.date()
        end_date = end.date()

        while current <= end_date:
            if current.weekday() < 5:
                count += 1
            current += timedelta(days=1)

        return count

    def stop(self) -> None:
        """Backfill işlemini durdurur."""
        self._running = False

    def get_stats(self) -> dict[str, Any]:
        """Backfill istatistiklerini döndürür.

        Returns:
            İstatistik sözlüğü.
        """
        return {
            "total_gaps": self._stats.total_gaps,
            "gaps_filled": self._stats.gaps_filled,
            "gaps_failed": self._stats.gaps_failed,
            "total_bars_filled": self._stats.total_bars_filled,
            "total_duration_seconds": round(self._stats.total_duration_seconds, 1),
            "last_backfill": datetime.fromtimestamp(self._stats.last_backfill_time, tz=UTC).isoformat()
            if self._stats.last_backfill_time
            else None,
            "running": self._running,
        }

    def get_progress(self) -> dict[str, Any]:
        """İlerleme durumunu döndürür.

        Returns:
            İlerleme sözlüğü.
        """
        return {
            "running": self._running,
            "progress": self._progress,
        }


# Singleton
backfill_manager = BackfillManager()
