"""ALPHA BIST — Tarihsel Temel Analiz Sağlayıcı Motoru (Historical Fundamental Provider).

Bu modül, BIST hisseleri için çeyreklik finansal tablolar (quarterly financials) ve
bilanço verilerini Point-In-Time (PIT) uyumlu olarak temin eder.

Her finansal snapshot için:
- `period_end`: Finansal dönemin sonu (örn: 2025-06-30).
- `available_at`: Raporun kamuya açıklandığı kesin tarih (earnings_date).
- `values`: Standartlaştırılmış finansal rasyolar ve bilanço kalemleri.

PIT Kuralı:
- Yalnızca `available_at <= current_date` olan snapshot'lar karar motorlarına aktarılır.
"""

from __future__ import annotations

import contextlib
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.data.historical_contracts import FundamentalSnapshot

logger = structlog.get_logger(__name__)

# ==============================================================================
# Yapılandırma ve WAL Sabitleri
# ==============================================================================

DEFAULT_CACHE_TTL_SECONDS: Final[int] = 3600
DEFAULT_MAX_PERIODS: Final[int] = 8
DEFAULT_FALLBACK_DAYS_OFFSET: Final[int] = 60
DEFAULT_FUNDAMENTAL_AUDIT_DB_PATH: Final[str] = "data/fundamental_audit.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"


# ==============================================================================
# DuckDB WAL ve orjson Yardımcıları
# ==============================================================================


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir nesneyi orjson ile ikili bayt dizisine dönüştürür.

    Args:
        val: Serileştirilecek veri veya nesne.

    Returns:
        bytes: orjson kodlanmış baytlar.
    """
    if hasattr(val, "to_dict"):
        val = val.to_dict()
    return orjson.dumps(val, default=str)


# ==============================================================================
# Sağlayıcı Sınıfı (Provider)
# ==============================================================================


class HistoricalFundamentalProvider:
    """yfinance ve harici kaynaklardan Point-In-Time uyumlu temel analiz verisi sağlayan motor."""

    def __init__(self, cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> None:
        """HistoricalFundamentalProvider başlatıcı.

        Args:
            cache_ttl_seconds: Önbellek geçerlilik süresi (saniye).
        """
        self._lock = threading.RLock()
        self._cache: dict[str, list[FundamentalSnapshot]] = {}
        self._cache_ts: dict[str, float] = {}
        self._cache_ttl = cache_ttl_seconds

        logger.info("tarihsel_temel_saglayici_baslatildi", ttl_sec=cache_ttl_seconds)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            return f"HistoricalFundamentalProvider(onbellek_hisse_sayisi={len(self._cache)}, ttl={self._cache_ttl}s)"

    def to_dict(self) -> dict[str, Any]:
        """Sağlayıcı durumunu sözlük formatında döner."""
        with self._lock:
            return {
                "cache_ttl_seconds": self._cache_ttl,
                "cached_tickers": list(self._cache.keys()),
                "cached_count": len(self._cache),
            }

    def to_orjson_bytes(self) -> bytes:
        """Sağlayıcı durumunu ikili orjson baytlarına dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def fetch_historical_fundamentals(
        self,
        ticker: str,
        max_periods: int = DEFAULT_MAX_PERIODS,
    ) -> list[FundamentalSnapshot]:
        """Hisseye ait çeyreklik finansal snapshot'ları çeker.

        Args:
            ticker: Hisse kodu (örn: THYAO).
            max_periods: Maksimum geçmiş dönem sayısı.

        Returns:
            list[FundamentalSnapshot]: En yeniden eskiye sıralı snapshot listesi.
        """
        clean_ticker = ticker.upper().replace(".IS", "").strip()
        now = datetime.now(UTC).timestamp()

        with self._lock:
            if clean_ticker in self._cache and (now - self._cache_ts.get(clean_ticker, 0.0)) < self._cache_ttl:
                return self._cache[clean_ticker]

        snapshots: list[FundamentalSnapshot] = []

        try:
            import yfinance as yf

            yf_ticker = f"{clean_ticker}.IS"
            t = yf.Ticker(yf_ticker)

            qf = t.quarterly_financials
            if qf is None or qf.empty:
                logger.warning("ceyrek_finansal_tablo_bulunamadi", hisse=clean_ticker)
                return []

            earnings_dates: dict[str, str] = {}
            try:
                ed = t.earnings_dates
                if ed is not None and not ed.empty:
                    for idx in ed.index:
                        if hasattr(idx, "date"):
                            earnings_dates[str(idx.date())] = str(idx.date())
            except Exception as e:
                logger.debug("earnings_date_tarama_hatasi", hisse=clean_ticker, hata=str(e))

            bs = t.quarterly_balance_sheet
            balance_sheet_data: dict[str, dict[str, float]] = {}
            if bs is not None and not bs.empty:
                for col in bs.columns[:max_periods]:
                    period_end = str(col.date()) if hasattr(col, "date") else str(col)[:10]
                    balance_sheet_data[period_end] = {}
                    for metric in bs.index:
                        val = bs.loc[metric, col]
                        if val is not None and str(val) != "nan":
                            with contextlib.suppress(ValueError, TypeError):
                                balance_sheet_data[period_end][str(metric)] = float(val)

            for col in qf.columns[:max_periods]:
                period_end = str(col.date()) if hasattr(col, "date") else str(col)[:10]
                available_at = self._find_publication_date(period_end, earnings_dates)

                values: dict[str, float] = {}
                for metric in qf.index:
                    val = qf.loc[metric, col]
                    if val is not None and str(val) != "nan":
                        with contextlib.suppress(ValueError, TypeError):
                            values[str(metric)] = float(val)

                if period_end in balance_sheet_data:
                    values.update(balance_sheet_data[period_end])

                mapped = self._map_metrics(values, clean_ticker)
                if mapped:
                    snapshot = FundamentalSnapshot(
                        ticker=clean_ticker,
                        period_end=period_end,
                        available_at=available_at,
                        values=mapped,
                        source="yfinance",
                        status="FRESH" if available_at else "UNKNOWN",
                    )
                    snapshots.append(snapshot)

            snapshots.sort(key=lambda s: s.period_end, reverse=True)

            with self._lock:
                self._cache[clean_ticker] = snapshots
                self._cache_ts[clean_ticker] = now

            logger.info("tarihsel_temel_veriler_alindi", hisse=clean_ticker, snapshot_sayisi=len(snapshots))

        except Exception as e:
            logger.error("tarihsel_temel_veri_cekme_hatasi", hisse=clean_ticker, hata=str(e))

        return snapshots

    def _find_publication_date(
        self,
        period_end: str,
        earnings_dates: dict[str, str],
    ) -> str:
        """Dönem sonuna en yakın kamuya açıklanma (earnings) tarihini eşleştirir."""
        candidates = [ed for ed in sorted(earnings_dates.keys()) if ed >= period_end]
        if candidates:
            return candidates[0]

        # Bulunamazsa period_end + 60 gün güvenli öteleme tahmin edilir
        try:
            d = datetime.strptime(period_end[:10], "%Y-%m-%d").replace(tzinfo=UTC)
            estimated = d + timedelta(days=DEFAULT_FALLBACK_DAYS_OFFSET)
            return estimated.strftime("%Y-%m-%d")
        except ValueError:
            return period_end[:10]

    def _map_metrics(
        self,
        raw_values: dict[str, float],
        ticker: str,
    ) -> dict[str, float]:
        """yfinance ham bilanço metriklerini sistem standart alanlarına dönüştürür."""
        mapped: dict[str, float] = {}

        # 1. Gelir (Revenue)
        for key in ["Total Revenue", "Operating Revenue", "Revenue"]:
            if key in raw_values and raw_values[key] > 0:
                mapped["revenue"] = float(raw_values[key])
                break

        # 2. Net Kar (Net Income)
        for key in ["Net Income", "Net Income Common Stockholders"]:
            if key in raw_values:
                mapped["net_income"] = float(raw_values[key])
                break

        # 3. Faaliyet Karı (Operating Income / EBIT)
        for key in ["Operating Income", "EBIT"]:
            if key in raw_values:
                mapped["operating_income"] = float(raw_values[key])
                break

        # 4. Brüt Kar
        if "Gross Profit" in raw_values:
            mapped["gross_profit"] = float(raw_values["Gross Profit"])

        # 5. FAVÖK (EBITDA)
        if "EBITDA" in raw_values:
            mapped["ebitda"] = float(raw_values["EBITDA"])

        # 6. Serbest Nakit Akışı (Free Cash Flow)
        if "Free Cash Flow" in raw_values:
            mapped["free_cash_flow"] = float(raw_values["Free Cash Flow"])

        # 7. İşletme Nakit Akışı
        if "Operating Cash Flow" in raw_values:
            mapped["operating_cash_flow"] = float(raw_values["Operating Cash Flow"])

        # 8. Sermaye Harcaması (CapEx)
        if "Capital Expenditure" in raw_values:
            mapped["capital_expenditure"] = float(raw_values["Capital Expenditure"])

        # 9. Dolaşımdaki Hisse Sayısı
        if "Basic Average Shares" in raw_values:
            mapped["shares_outstanding"] = float(raw_values["Basic Average Shares"])

        # 10. Hisse Başı Kar (EPS)
        if "Diluted EPS" in raw_values:
            mapped["eps"] = float(raw_values["Diluted EPS"])

        # Türetilmiş Kar Marjları
        revenue = mapped.get("revenue", 0.0)
        net_income = mapped.get("net_income", 0.0)
        gross_profit = mapped.get("gross_profit", 0.0)
        operating_income = mapped.get("operating_income", 0.0)
        free_cash_flow = mapped.get("free_cash_flow", 0.0)

        if revenue and revenue > 0:
            if net_income:
                mapped["profit_margin"] = float(net_income / revenue)
            if gross_profit:
                mapped["gross_margin"] = float(gross_profit / revenue)
            if operating_income:
                mapped["operating_margin"] = float(operating_income / revenue)
            if free_cash_flow:
                mapped["fcf_margin"] = float(free_cash_flow / revenue)

        return mapped

    def clear_cache(self) -> None:
        """Önbellekteki tüm temel analiz verilerini sıfırlar."""
        with self._lock:
            self._cache.clear()
            self._cache_ts.clear()
        logger.info("temel_analiz_onbellegi_temizlendi")


# Global Singleton Örneği
historical_fundamental_provider: HistoricalFundamentalProvider = HistoricalFundamentalProvider()


# ==============================================================================
# DuckDB ve Polars Yardımcı Fonksiyonları
# ==============================================================================


def export_snapshots_to_polars(snapshots: list[FundamentalSnapshot]) -> pl.DataFrame:
    """Temel analiz snapshot listesini Polars DataFrame formatına dönüştürür."""
    if not snapshots:
        return pl.DataFrame()

    rows: list[dict[str, Any]] = []
    for s in snapshots:
        row: dict[str, Any] = {
            "ticker": s.ticker,
            "period_end": s.period_end,
            "available_at": s.available_at,
            "source": s.source,
            "status": s.status,
        }
        for k, v in s.values.items():
            row[f"val_{k}"] = v
        rows.append(row)

    return pl.DataFrame(rows)


def export_fundamental_to_duckdb(
    snapshot: FundamentalSnapshot,
    db_path: str = DEFAULT_FUNDAMENTAL_AUDIT_DB_PATH,
) -> int:
    """Temel analiz snapshot'ını DuckDB denetim tablosuna kaydeder.

    Args:
        snapshot: Kaydedilecek snapshot nesnesi.
        db_path: DuckDB dosya yolu.

    Returns:
        int: Eklenen kayıt sayısı (1).
    """
    target_file = Path(db_path)
    target_file.parent.mkdir(parents=True, exist_ok=True)

    row_id = uuid.uuid4().hex
    row = (
        row_id,
        datetime.now(UTC),
        snapshot.ticker,
        snapshot.period_end,
        snapshot.available_at,
        snapshot.source,
        snapshot.status,
        orjson.dumps(snapshot.values, default=str).decode("utf-8"),
    )

    try:
        with duckdb.connect(str(target_file)) as conn:
            configure_duckdb_wal(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fundamental_snapshot_audit (
                    id VARCHAR PRIMARY KEY,
                    created_at TIMESTAMP,
                    ticker VARCHAR,
                    period_end VARCHAR,
                    available_at VARCHAR,
                    source VARCHAR,
                    status VARCHAR,
                    values_json VARCHAR
                )
                """
            )
            conn.execute(
                """
                INSERT INTO fundamental_snapshot_audit (
                    id, created_at, ticker, period_end, available_at,
                    source, status, values_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
        logger.info("temel_snapshot_duckdb_kaydedildi", id=row_id, hisse=snapshot.ticker)
        return 1
    except Exception as exc:
        logger.error("temel_snapshot_kayit_hatasi", hisse=snapshot.ticker, hata=str(exc))
        return 0


def read_fundamental_audit_from_duckdb(
    db_path: str = DEFAULT_FUNDAMENTAL_AUDIT_DB_PATH,
    ticker: str | None = None,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB denetim tablosundan temel snapshot kayıtlarını Polars DataFrame olarak okur.

    Args:
        db_path: DuckDB dosya yolu.
        ticker: Opsiyonel hisse filtresi.
        limit: Maksimum satır sayısı.

    Returns:
        pl.DataFrame: Snapshot denetim geçmişi tablosu.
    """
    path_obj = Path(db_path)
    schema: dict[str, pl.DataType] = {
        "id": pl.Utf8,
        "created_at": pl.Datetime,
        "ticker": pl.Utf8,
        "period_end": pl.Utf8,
        "available_at": pl.Utf8,
        "source": pl.Utf8,
        "status": pl.Utf8,
        "values_json": pl.Utf8,
    }
    if not path_obj.exists():
        return pl.DataFrame(schema=schema)

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            tbl_check = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'fundamental_snapshot_audit'"
            ).fetchone()
            if not tbl_check or tbl_check[0] == 0:
                return pl.DataFrame(schema=schema)

            query = (
                "SELECT id, created_at, ticker, period_end, available_at, source, status, values_json "
                "FROM fundamental_snapshot_audit WHERE 1=1"
            )
            params: list[Any] = []
            if ticker:
                query += " AND ticker = ?"
                params.append(ticker.upper().replace(".IS", "").strip())
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(max(1, int(limit)))

            return conn.execute(query, params).pl()
    except Exception as exc:
        logger.warning("duckdb_fundamental_audit_okuma_hatasi", db_path=db_path, hata=str(exc))
        return pl.DataFrame(schema=schema)


def clear_fundamental_audit_duckdb(db_path: str = DEFAULT_FUNDAMENTAL_AUDIT_DB_PATH) -> None:
    """DuckDB denetim tablosunu temizler.

    Args:
        db_path: DuckDB dosya yolu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return
    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.execute("DROP TABLE IF EXISTS fundamental_snapshot_audit;")
    except Exception as exc:
        logger.error("duckdb_fundamental_audit_temizleme_hatasi", db_path=db_path, hata=str(exc))


__all__: Final[list[str]] = [
    # Sabitler
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_FALLBACK_DAYS_OFFSET",
    "DEFAULT_FUNDAMENTAL_AUDIT_DB_PATH",
    "DEFAULT_MAX_PERIODS",
    "DEFAULT_WAL_SIZE",
    # Sağlayıcı ve Singleton
    "HistoricalFundamentalProvider",
    "historical_fundamental_provider",
    # Yardımcı Fonksiyonlar
    "clear_fundamental_audit_duckdb",
    "configure_duckdb_wal",
    "export_fundamental_to_duckdb",
    "export_snapshots_to_polars",
    "read_fundamental_audit_from_duckdb",
    "to_orjson_bytes",
]
