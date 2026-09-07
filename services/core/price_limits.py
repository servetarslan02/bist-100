"""ALPHA BIST — Price Limits (Eylül 2025 Güncel)

BIST fiyat limitleri (Eylül 2025 sonrası — tüm pazarlarda standart):
- Yıldız Pazar: ±%10
- Ana Pazar: ±%10
- Alt Pazar: ±%10
- Devre kesici sonrası: Marj daraltılır (±%5)
- Halka arz günü: Limit serbest

Kaynak: Borsa İstanbul resmi mevzuat ve seans kuralları.
"""

from __future__ import annotations

import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.core.bist_tick_size import round_to_valid_tick
from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# Modül Sabitleri
DEFAULT_LIMIT_PCT: Final[float] = 10.0
DEFAULT_POST_CB_LIMIT_PCT: Final[float] = 5.0
DEFAULT_POST_CORP_ACTION_LIMIT_PCT: Final[float] = 10.0
DEFAULT_TOLERANCE_RATIO: Final[float] = 0.0001  # %0.01 floating-point toleransı
DEFAULT_PRICE_LIMIT_DUCKDB_PATH: Final[str] = "data/price_limits.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"

# Pazar bazlı limit haritası
MARKET_LIMITS: Final[dict[str, float]] = {
    "yildiz": 10.0,
    "ana": 10.0,
    "alt": 10.0,
    "fiyat": 10.0,  # Fiyat Pazarı
    "kesin": 10.0,  # Kesin Alım Satım Pazarı
    "gözaltı": 10.0,  # Gözaltı Pazarı
    "yakın": 10.0,  # Yakın İzleme Pazarı
    "kolektif": 10.0,  # Kolektif Yatırım Ürünleri
    "serbest": 0.0,  # Serbest İşlem (limit yok)
}


def configure_duckdb_wal(
    conn: duckdb.DuckDBPyConnection,
    checkpoint_threshold: str = DEFAULT_CHECKPOINT_SIZE,
    wal_autocheckpoint: str = DEFAULT_WAL_SIZE,
) -> None:
    """DuckDB WAL boyutunu optimize eder."""
    try:
        conn.execute(f"SET checkpoint_threshold = '{checkpoint_threshold}';")
        conn.execute(f"SET wal_autocheckpoint = '{wal_autocheckpoint}';")
    except Exception as e:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(e))


@dataclass(slots=True)
class PriceLimitResult:
    """Fiyat limiti denetim sonucu veri modeli.

    Attributes:
        limit_hit: Tavan veya taban limitine ulaşılıp ulaşılmadığı.
        direction: Limit aşım yönü ("UP", "DOWN" veya "").
        change_pct: Referans fiyata göre yüzdesel değişim.
        limit: Uygulanan efektif yüzde sınırı.
        reference_price: Baz alınan referans fiyat (önceki gün kapanışı).
        current_price: Güncel işlem fiyatı.
        upper_limit: İzin verilen azami tavan fiyatı.
        lower_limit: İzin verilen asgari taban fiyatı.
        ticker: Hisse/enstrüman sembolü.
    """

    limit_hit: bool
    direction: str = ""  # "UP" veya "DOWN"
    change_pct: float = 0.0
    limit: float = DEFAULT_LIMIT_PCT
    reference_price: float = 0.0
    current_price: float = 0.0
    upper_limit: float = 0.0
    lower_limit: float = 0.0
    ticker: str = ""

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        return (
            f"PriceLimitResult(ticker={self.ticker!r}, hit={self.limit_hit}, dir={self.direction!r}, "
            f"chg={self.change_pct:.2f}%, cur={self.current_price}, range=[{self.lower_limit:.2f}, {self.upper_limit:.2f}])"
        )

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return {
            "ticker": self.ticker,
            "limit_hit": self.limit_hit,
            "direction": self.direction,
            "change_pct": round(self.change_pct, 2),
            "limit": self.limit,
            "reference_price": self.reference_price,
            "current_price": self.current_price,
            "upper_limit": round(self.upper_limit, 2),
            "lower_limit": round(self.lower_limit, 2),
        }

    def to_orjson_bytes(self) -> bytes:
        """Sonuç verilerini yüksek hızlı orjson bayt dizisine dönüştürür."""
        return orjson.dumps(self.to_dict(), default=str)


class PriceLimitMonitor:
    """BIST fiyat limitleri denetleyici ve yöneticisi.

    Tüm işlemler reentrant kilit (RLock) ile thread-safe güvence altındadır.
    Devre kesici, halka arz ve kurumsal işlem durumlarında marjları dinamik ayarlar.
    """

    DEFAULT_LIMIT = DEFAULT_LIMIT_PCT
    POST_CB_LIMIT = DEFAULT_POST_CB_LIMIT_PCT
    POST_CORP_ACTION_LIMIT = DEFAULT_POST_CORP_ACTION_LIMIT_PCT

    def __init__(self, duckdb_path: str = DEFAULT_PRICE_LIMIT_DUCKDB_PATH) -> None:
        self._lock = threading.RLock()
        self._duckdb_path = duckdb_path
        self._custom_limits: dict[str, float] = {}
        self._post_cb_tickers: dict[str, float] = {}  # Devre kesici sonrası daraltılmış marj
        self._ipo_tickers: set[str] = set()  # Halka arz günü (limit yok)
        self._corp_action_tickers: set[str] = set()  # Kurumsal işlem sonrası
        self._market_type: dict[str, str] = {}  # Hisse → pazar tipi

    @otel_trace("price_limits.set_custom_limit")
    def set_custom_limit(self, ticker: str, limit_pct: float) -> None:
        """Volatil veya özel tedbirli hisseler için özel limit belirler."""
        with self._lock:
            self._custom_limits[ticker] = limit_pct

    @otel_trace("price_limits.set_market_type")
    def set_market_type(self, ticker: str, market_type: str) -> None:
        """Hisse için pazar tipi atar (yildiz, ana, alt vb.)."""
        with self._lock:
            self._market_type[ticker] = market_type.lower().strip()

    @otel_trace("price_limits.add_ipo_ticker")
    def add_ipo_ticker(self, ticker: str) -> None:
        """Halka arz günü işlem gören hisseyi serbest marja alır."""
        with self._lock:
            self._ipo_tickers.add(ticker)

    @otel_trace("price_limits.remove_ipo_ticker")
    def remove_ipo_ticker(self, ticker: str) -> None:
        """Halka arz günü serbest marj durumunu sonlandırır."""
        with self._lock:
            self._ipo_tickers.discard(ticker)

    @otel_trace("price_limits.add_corporate_action_ticker")
    def add_corporate_action_ticker(self, ticker: str) -> None:
        """Kurumsal işlem sonrası (bedelsiz/temettü vb.) takibe alır."""
        with self._lock:
            self._corp_action_tickers.add(ticker)

    @otel_trace("price_limits.remove_corporate_action_ticker")
    def remove_corporate_action_ticker(self, ticker: str) -> None:
        """Kurumsal işlem takibini kaldırır."""
        with self._lock:
            self._corp_action_tickers.discard(ticker)

    @otel_trace("price_limits.set_post_circuit_breaker_limit")
    def set_post_circuit_breaker_limit(self, ticker: str) -> None:
        """Devre kesici sonrası marjı daraltır (±%5)."""
        with self._lock:
            self._post_cb_tickers[ticker] = self.POST_CB_LIMIT
            logger.info("devre_kesici_sonrasi_marj_daraltildi", hisse=ticker, yeni_limit=self.POST_CB_LIMIT)

    @otel_trace("price_limits.clear_post_circuit_breaker_limit")
    def clear_post_circuit_breaker_limit(self, ticker: str) -> None:
        """Devre kesici sonrası marj daraltmasını kaldırır."""
        with self._lock:
            self._post_cb_tickers.pop(ticker, None)

    @otel_trace("price_limits.get_effective_limit")
    def get_effective_limit(self, ticker: str) -> float:
        """Hisseye uygulanan efektif fiyat limit oranını döndürür."""
        with self._lock:
            # Halka arz günü → limit yok
            if ticker in self._ipo_tickers:
                return 0.0

            # Devre kesici sonrası daraltma kontrolü
            if ticker in self._post_cb_tickers:
                return self._post_cb_tickers[ticker]

            # Özel limit kontrolü
            if ticker in self._custom_limits:
                return self._custom_limits[ticker]

            # Pazar tipine göre limit
            market = self._market_type.get(ticker, "")
            if market in MARKET_LIMITS:
                return MARKET_LIMITS[market]

            return self.DEFAULT_LIMIT

    @otel_trace("price_limits.check_price_limit")
    def check_price_limit(
        self,
        ticker: str,
        current_price: float,
        reference_price: float,
    ) -> PriceLimitResult:
        """Fiyat limiti aşım kontrolünü gerçekleştirir.

        Args:
            ticker: Hisse/enstrüman sembolü.
            current_price: Anlık işlem fiyatı.
            reference_price: Referans baz fiyat (önceki kapanış).

        Returns:
            PriceLimitResult nesnesi.
        """
        if reference_price <= 0 or current_price <= 0:
            return PriceLimitResult(limit_hit=False, ticker=ticker)

        limit = self.get_effective_limit(ticker)

        # Halka arz günü limit yok
        if limit == 0.0:
            return PriceLimitResult(
                limit_hit=False,
                direction="",
                change_pct=((current_price / reference_price) - 1.0) * 100.0,
                limit=0.0,
                reference_price=reference_price,
                current_price=current_price,
                upper_limit=float("inf"),
                lower_limit=0.0,
                ticker=ticker,
            )

        # Değişim yüzdesi
        change_pct = ((current_price / reference_price) - 1.0) * 100.0

        # BIST Fiyat Adımı (Tick Size) uyumlu tavan ve taban hesaplama
        raw_upper = reference_price * (1.0 + limit / 100.0)
        raw_lower = reference_price * (1.0 - limit / 100.0)

        # Üst limit bir alt adıma yuvarlanır, alt limit bir üst adıma yuvarlanır (BIST kuralı)
        upper_limit = round_to_valid_tick(raw_upper, round_up=False)
        lower_limit = round_to_valid_tick(max(0.01, raw_lower), round_up=True)

        limit_hit = False
        direction = ""

        tol = reference_price * DEFAULT_TOLERANCE_RATIO
        if current_price >= upper_limit - tol:
            limit_hit = True
            direction = "UP"
        elif current_price <= lower_limit + tol:
            limit_hit = True
            direction = "DOWN"

        if limit_hit:
            logger.warning(
                "fiyat_limiti_asildi",
                hisse=ticker,
                yon=direction,
                anlik_fiyat=current_price,
                referans=reference_price,
                tavan=upper_limit,
                taban=lower_limit,
            )

        return PriceLimitResult(
            limit_hit=limit_hit,
            direction=direction,
            change_pct=change_pct,
            limit=limit,
            reference_price=reference_price,
            current_price=current_price,
            upper_limit=upper_limit,
            lower_limit=lower_limit,
            ticker=ticker,
        )

    # =====================================================
    # POLARS VEKTÖREL KONTROL & DUCKDB DENETİMİ
    # =====================================================

    def check_price_limits_polars(
        self,
        df: pl.DataFrame,
        current_price_col: str = "close",
        ref_price_col: str = "prev_close",
        ticker_col: str = "ticker",
    ) -> pl.DataFrame:
        """Tüm hisse evrenini Polars vektörel ifadeleriyle tavan/taban limitleri açısından denetler.

        Args:
            df: Piyasa verisi içeren Polars DataFrame.
            current_price_col: Güncel fiyat sütunu adı.
            ref_price_col: Referans baz fiyat sütunu adı.
            ticker_col: Hisse sembolü sütunu adı.

        Returns:
            Limit durumu eklenmiş Polars DataFrame.
        """
        if df.is_empty():
            return df

        # Vektörel % değişim ve tavan/taban sınırları
        return df.with_columns(
            [
                (((pl.col(current_price_col) / pl.col(ref_price_col)) - 1.0) * 100.0).alias("change_pct"),
                (pl.col(ref_price_col) * (1.0 + DEFAULT_LIMIT_PCT / 100.0)).alias("upper_limit"),
                (pl.col(ref_price_col) * (1.0 - DEFAULT_LIMIT_PCT / 100.0)).alias("lower_limit"),
            ]
        ).with_columns(
            [
                (
                    pl.when(pl.col(current_price_col) >= pl.col("upper_limit") - (pl.col(ref_price_col) * DEFAULT_TOLERANCE_RATIO))
                    .then(pl.lit("UP"))
                    .when(pl.col(current_price_col) <= pl.col("lower_limit") + (pl.col(ref_price_col) * DEFAULT_TOLERANCE_RATIO))
                    .then(pl.lit("DOWN"))
                    .otherwise(pl.lit(""))
                ).alias("limit_direction"),
                (
                    (pl.col(current_price_col) >= pl.col("upper_limit") - (pl.col(ref_price_col) * DEFAULT_TOLERANCE_RATIO))
                    | (pl.col(current_price_col) <= pl.col("lower_limit") + (pl.col(ref_price_col) * DEFAULT_TOLERANCE_RATIO))
                ).alias("limit_hit"),
            ]
        )

    def save_breach_to_duckdb(
        self,
        result: PriceLimitResult,
        db_path: str | None = None,
    ) -> None:
        """Fiyat limiti ihlalini DuckDB kalıcı denetim tablosuna kaydeder.

        Args:
            result: Fiyat limiti sonucu.
            db_path: İsteğe bağlı hedef DuckDB dosya yolu.
        """
        if not result.limit_hit:
            return

        target_path = db_path or self._duckdb_path
        path_obj = Path(target_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)

        conn = duckdb.connect(str(path_obj))
        try:
            configure_duckdb_wal(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS price_limit_breaches (
                    ticker VARCHAR,
                    direction VARCHAR,
                    change_pct DOUBLE,
                    current_price DOUBLE,
                    reference_price DOUBLE,
                    upper_limit DOUBLE,
                    lower_limit DOUBLE,
                    breach_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                INSERT INTO price_limit_breaches (ticker, direction, change_pct, current_price, reference_price, upper_limit, lower_limit)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    result.ticker,
                    result.direction,
                    result.change_pct,
                    result.current_price,
                    result.reference_price,
                    result.upper_limit,
                    result.lower_limit,
                ],
            )
            logger.info("fiyat_limiti_ihlali_duckdb_kaydedildi", hisse=result.ticker, yon=result.direction)
        finally:
            conn.close()

    def save_breaches_to_duckdb(
        self,
        results: list[PriceLimitResult],
        db_path: str | None = None,
    ) -> int:
        """Birden çok fiyat limiti ihlalini DuckDB tablosuna toplu olarak kaydeder.

        Args:
            results: PriceLimitResult listesi.
            db_path: İsteğe bağlı DuckDB dosya yolu.

        Returns:
            Kaydedilen ihlal sayısı.
        """
        breaches = [r for r in results if r.limit_hit]
        if not breaches:
            return 0

        target_path = db_path or self._duckdb_path
        path_obj = Path(target_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)

        df = export_price_limits_to_polars(breaches)
        conn = duckdb.connect(str(path_obj))
        try:
            configure_duckdb_wal(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS price_limit_breaches (
                    ticker VARCHAR,
                    direction VARCHAR,
                    change_pct DOUBLE,
                    current_price DOUBLE,
                    reference_price DOUBLE,
                    upper_limit DOUBLE,
                    lower_limit DOUBLE,
                    breach_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.register("tmp_breaches_df", df.to_arrow())
            try:
                conn.execute(
                    """
                    INSERT INTO price_limit_breaches (ticker, direction, change_pct, current_price, reference_price, upper_limit, lower_limit)
                    SELECT ticker, direction, change_pct, current_price, reference_price, upper_limit, lower_limit
                    FROM tmp_breaches_df
                    """
                )
            finally:
                with suppress(Exception):
                    conn.unregister("tmp_breaches_df")
            logger.info("toplu_fiyat_limiti_ihlalleri_kaydedildi", adet=len(breaches), db_path=str(path_obj))
            return len(breaches)
        finally:
            conn.close()

    def read_breaches_from_duckdb(
        self,
        db_path: str | None = None,
        ticker: str | None = None,
    ) -> pl.DataFrame:
        """DuckDB'de kayıtlı fiyat limiti ihlallerini Polars DataFrame olarak okur."""
        target_path = db_path or self._duckdb_path
        path_obj = Path(target_path)
        empty_schema = {
            "ticker": pl.String,
            "direction": pl.String,
            "change_pct": pl.Float64,
            "current_price": pl.Float64,
            "reference_price": pl.Float64,
            "upper_limit": pl.Float64,
            "lower_limit": pl.Float64,
        }
        if not path_obj.exists():
            return pl.DataFrame(schema=empty_schema)

        conn = duckdb.connect(str(path_obj), read_only=True)
        try:
            tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
            if "price_limit_breaches" not in tables:
                return pl.DataFrame(schema=empty_schema)

            query = (
                "SELECT ticker, direction, change_pct, current_price, reference_price, upper_limit, lower_limit "
                "FROM price_limit_breaches "
            )
            params: list[Any] = []
            if ticker:
                query += "WHERE ticker = ? "
                params.append(ticker.upper().strip())
            query += "ORDER BY breach_time DESC"

            return conn.execute(query, params).pl()
        except Exception as e:
            logger.error("fiyat_limiti_duckdb_okuma_hatasi", hata=str(e))
            return pl.DataFrame(schema=empty_schema)
        finally:
            conn.close()

    def clear_breaches_duckdb(self, db_path: str | None = None) -> bool:
        """DuckDB tablosundaki tüm fiyat limiti ihlallerini temizler."""
        target_path = db_path or self._duckdb_path
        path_obj = Path(target_path)
        if not path_obj.exists():
            return True

        conn = duckdb.connect(str(path_obj))
        try:
            tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
            if "price_limit_breaches" in tables:
                conn.execute("DELETE FROM price_limit_breaches")
            logger.info("fiyat_limiti_ihlalleri_temizlendi", db_path=str(path_obj))
            return True
        except Exception as e:
            logger.error("fiyat_limiti_duckdb_temizleme_hatasi", hata=str(e))
            return False
        finally:
            conn.close()

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        with self._lock:
            return (
                f"PriceLimitMonitor(custom={len(self._custom_limits)}, "
                f"post_cb={len(self._post_cb_tickers)}, ipo={len(self._ipo_tickers)})"
            )


# Singleton
price_limit_monitor = PriceLimitMonitor()


def check_price_limit(
    ticker: str,
    current_price: float,
    reference_price: float,
    monitor: PriceLimitMonitor = price_limit_monitor,
) -> PriceLimitResult:
    """Fiyat limiti denetimi yapar."""
    return monitor.check_price_limit(ticker, current_price, reference_price)


def save_price_limit_breach_to_duckdb(
    result: PriceLimitResult,
    db_path: str = DEFAULT_PRICE_LIMIT_DUCKDB_PATH,
    monitor: PriceLimitMonitor = price_limit_monitor,
) -> None:
    """Fiyat limiti ihlalini DuckDB'ye kaydeder."""
    monitor.save_breach_to_duckdb(result, db_path=db_path)


def save_price_limit_breaches_to_duckdb(
    results: list[PriceLimitResult],
    db_path: str = DEFAULT_PRICE_LIMIT_DUCKDB_PATH,
    monitor: PriceLimitMonitor = price_limit_monitor,
) -> int:
    """Birden çok fiyat limiti ihlalini DuckDB'ye toplu kaydeder."""
    return monitor.save_breaches_to_duckdb(results, db_path=db_path)


def read_price_limit_breaches_from_duckdb(
    db_path: str = DEFAULT_PRICE_LIMIT_DUCKDB_PATH,
    ticker: str | None = None,
    monitor: PriceLimitMonitor = price_limit_monitor,
) -> pl.DataFrame:
    """DuckDB'de kayıtlı fiyat limiti ihlallerini Polars DataFrame olarak okur."""
    return monitor.read_breaches_from_duckdb(db_path=db_path, ticker=ticker)


def clear_price_limit_breaches_duckdb(
    db_path: str = DEFAULT_PRICE_LIMIT_DUCKDB_PATH,
    monitor: PriceLimitMonitor = price_limit_monitor,
) -> bool:
    """DuckDB tablosundaki ihlalleri temizler."""
    return monitor.clear_breaches_duckdb(db_path=db_path)


def to_orjson_bytes(data: Any) -> bytes:
    """Verilen veriyi orjson bayt dizisine dönüştürür."""
    return orjson.dumps(data, default=str)


def export_price_limits_to_polars(results: list[PriceLimitResult]) -> pl.DataFrame:
    """Fiyat limiti denetim sonuçları listesini Polars DataFrame formatına çevirir."""
    if not results:
        return pl.DataFrame(
            schema={
                "ticker": pl.String,
                "limit_hit": pl.Boolean,
                "direction": pl.String,
                "change_pct": pl.Float64,
                "limit": pl.Float64,
                "reference_price": pl.Float64,
                "current_price": pl.Float64,
                "upper_limit": pl.Float64,
                "lower_limit": pl.Float64,
            }
        )
    return pl.from_dicts([r.to_dict() for r in results])


__all__: Final[list[str]] = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_LIMIT_PCT",
    "DEFAULT_POST_CB_LIMIT_PCT",
    "DEFAULT_POST_CORP_ACTION_LIMIT_PCT",
    "DEFAULT_PRICE_LIMIT_DUCKDB_PATH",
    "DEFAULT_TOLERANCE_RATIO",
    "DEFAULT_WAL_SIZE",
    "MARKET_LIMITS",
    "PriceLimitMonitor",
    "PriceLimitResult",
    "check_price_limit",
    "clear_price_limit_breaches_duckdb",
    "configure_duckdb_wal",
    "export_price_limits_to_polars",
    "price_limit_monitor",
    "read_price_limit_breaches_from_duckdb",
    "save_price_limit_breach_to_duckdb",
    "save_price_limit_breaches_to_duckdb",
    "to_orjson_bytes",
]


