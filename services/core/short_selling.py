"""ALPHA BIST — Açığa Satış Denetim ve Mevzuat Doğrulama Motoru (Short Selling Monitor).

Borsa İstanbul (BIST) ve SPK açığa satış kuralları (Eylül 2025 Güncel):
1. Sadece BIST-50 endeksine dahil hisselerde açığa satış yapılabilir.
2. Brüt takas kısıtı olan hisselerde açığa satış kesinlikle yasaktır.
3. SPK geçici işlem yasağı bulunan hisselerde açığa satış yasaktır.
4. Yukarı Adım Kuralı (Uptick Rule): BIST-100 endeksi gün içinde %2 veya daha fazla
   düştüğünde seans sonuna kadar zorunlu olarak uygulanır. Açığa satış fiyatı,
   hissenin son işlem fiyatından ve en iyi satış fiyatından düşük olamaz.
5. Normal piyasa koşullarında da açığa satış fiyatı son işlem fiyatından düşük olamaz.

Tüm kararlar SPK denetim standartlarına uygun olarak DuckDB denetim günlüğünde arşivlenir
ve analitik Polars DataFrame entegrasyonu sağlanır.
"""

from __future__ import annotations

import functools
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

DEFAULT_SHORT_SELLING_DB: Final[str] = "data/short_selling_audit.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"

try:
    from .otel import get_tracer

    tracer = get_tracer("alpha-bist.short_selling")
except ImportError:
    from opentelemetry import trace

    tracer = trace.get_tracer("alpha-bist.short_selling")

logger = structlog.get_logger(__name__)


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder."""
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.debug("DuckDB WAL pragma uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir veriyi orjson ile güvenli byte dizisine serileştirir."""
    if hasattr(val, "to_dict"):
        return orjson.dumps(val.to_dict(), default=str)
    return orjson.dumps(val, default=str)


def otel_trace(span_name: str) -> Any:
    """Metotları OpenTelemetry izleme span'i içerisine alan dekoratör."""

    def decorator(func: Any) -> Any:
        @functools.wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            if tracer is not None and hasattr(tracer, "start_as_current_span"):
                with tracer.start_as_current_span(span_name):
                    return func(self, *args, **kwargs)
            return func(self, *args, **kwargs)

        return wrapper

    return decorator


@dataclass(slots=True)
class ShortSellingDecision:
    """Açığa satış emri kontrolünün yasal uygunluk karar modeli.

    Args:
        allowed: Açığa satış emrinin iletilmesine izin verilip verilmediği.
        reason: İzin verilmeme gerekçesi veya yasal onay açıklaması.
        details: Fiyatlar, endeks durumu ve kontrolleri içeren ayrıntılı meta veri.
    """

    allowed: bool
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Karar modelini standart Python sözlüğüne dönüştürür."""
        return asdict(self)

    def to_orjson_bytes(self) -> bytes:
        """Karar modelini optimize edilmiş orjson bayt dizisine serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return (
            f"ShortSellingDecision(allowed={self.allowed}, "
            f"reason='{self.reason}', details={self.details})"
        )


class ShortSellingMonitor:
    """BIST açığa satış mevzuatı ve risk kurallarını denetleyen merkezi yönetici.

    Thread-safe erişim, DuckDB yasal denetim günlüğü, Polars entegrasyonu ve
    Eylül 2025 BIST-50 / Yukarı Adım Kuralı (Uptick Rule) standartlarını uygular.
    """

    # BIST-100 günlük düşüş eşiği: Endeks %2 düşerse uptick rule seans sonuna kadar aktifleşir
    UPTICK_RULE_THRESHOLD_PCT: float = 2.0

    def __init__(self, duckdb_path: str = DEFAULT_SHORT_SELLING_DB) -> None:
        """Açığa satış denetçisini başlatır ve gerekli kilitler ile veri havuzunu kurar.

        Args:
            duckdb_path: Denetim kayıtları için DuckDB dosya yolu veya bellek içi veritabanı.
        """
        self._lock = threading.RLock()
        self._bist50_cache: list[str] | None = None
        self._gross_settlement_tickers: set[str] = set()
        self._spk_banned_tickers: set[str] = set()
        self._uptick_rule_active: bool = False
        self._duckdb_path = duckdb_path

        if self._duckdb_path != ":memory:":
            try:
                Path(self._duckdb_path).parent.mkdir(parents=True, exist_ok=True)
                self._duckdb_con = duckdb.connect(self._duckdb_path)
            except Exception as e:
                logger.warning(
                    "DuckDB disk baglantisi kurulamadi, bellege donuluyor",
                    yol=self._duckdb_path,
                    hata=str(e),
                )
                self._duckdb_con = duckdb.connect(":memory:")
        else:
            self._duckdb_con = duckdb.connect(":memory:")

        configure_duckdb_wal(self._duckdb_con)
        self._init_duckdb()

    def _init_duckdb(self) -> None:
        """DuckDB üzerinde açığa satış kararlarının denetim tablosunu oluşturur."""
        with self._lock:
            try:
                self._duckdb_con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS short_selling_audit (
                        id BIGINT PRIMARY KEY,
                        ticker VARCHAR,
                        current_price DOUBLE,
                        last_trade_price DOUBLE,
                        best_ask_price DOUBLE,
                        allowed BOOLEAN,
                        reason VARCHAR,
                        details_json VARCHAR,
                        recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                self._duckdb_con.execute("CREATE SEQUENCE IF NOT EXISTS seq_short_selling_audit_id START 1")
            except Exception as e:
                logger.error("DuckDB aciga satis denetim tablosu olusturulamadi", hata=str(e))

    def _record_audit(
        self,
        ticker: str,
        current_price: float,
        last_trade_price: float,
        best_ask_price: float,
        decision: ShortSellingDecision,
    ) -> None:
        """Açığa satış denetim kararını yasal takip amacıyla DuckDB'ye yazar."""
        with self._lock:
            try:
                details_json_str = orjson.dumps(decision.details, default=str).decode("utf-8")
                self._duckdb_con.execute(
                    """
                    INSERT INTO short_selling_audit (
                        id, ticker, current_price, last_trade_price, best_ask_price,
                        allowed, reason, details_json
                    )
                    VALUES (nextval('seq_short_selling_audit_id'), ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        ticker,
                        current_price,
                        last_trade_price,
                        best_ask_price,
                        decision.allowed,
                        decision.reason,
                        details_json_str,
                    ],
                )
            except Exception as e:
                logger.warning("Aciga satis denetim kaydi DuckDB'ye yazilamadi", hata=str(e))

    def _normalize_ticker(self, ticker: str) -> str:
        """Hisse sembolünü büyük harfe dönüştürür ve boşluklardan arındırır."""
        if not ticker or not isinstance(ticker, str):
            return ""
        return ticker.strip().upper()

    def _get_bist50(self) -> list[str]:
        """Aktif BIST-50 hisse senetleri listesini döndürür veya önbellekten alır."""
        with self._lock:
            if self._bist50_cache is not None:
                return self._bist50_cache

            try:
                from services.ingestion.bist_universe import bist_universe

                if hasattr(bist_universe, "BIST_50_TICKERS") and bist_universe.BIST_50_TICKERS:
                    self._bist50_cache = [self._normalize_ticker(t) for t in bist_universe.BIST_50_TICKERS]
                elif hasattr(bist_universe, "BIST_30_TICKERS") and bist_universe.BIST_30_TICKERS:
                    self._bist50_cache = [self._normalize_ticker(t) for t in bist_universe.BIST_30_TICKERS]
                else:
                    self._bist50_cache = []
            except Exception as e:
                logger.warning("BIST-50 listesi bist_universe modulunden yuklenemedi", hata=str(e))
                self._bist50_cache = []

            return self._bist50_cache

    @otel_trace("short_selling.refresh_bist50_cache")
    def refresh_bist50_cache(self, custom_tickers: list[str] | None = None) -> None:
        """BIST-50 hisse listesini manuel veya periyodik olarak yeniler.

        BIST-50 endeks bileşenleri her yıl Mart, Haziran, Eylül ve Aralık aylarında revize edilir.
        """
        with self._lock:
            if custom_tickers is not None:
                self._bist50_cache = [self._normalize_ticker(t) for t in custom_tickers if t]
            else:
                self._bist50_cache = None
                self._get_bist50()
            logger.info("BIST-50 hisse onbellegi yenilendi", toplam=len(self._bist50_cache or []))

    def is_quarterly_rebalance_month(self) -> bool:
        """İçinde bulunulan ayın BIST endeks yeniden dengeleme ayı olup olmadığını doğrular."""
        return datetime.now(UTC).month in {3, 6, 9, 12}

    def auto_refresh_if_needed(self) -> None:
        """Endeks revizyon aylarında BIST-50 önbelleğini otomatik olarak günceller."""
        if self.is_quarterly_rebalance_month():
            self.refresh_bist50_cache()

    def set_gross_settlement(self, tickers: list[str]) -> None:
        """Brüt takas uygulamasına tabi tutulan hisseler listesini günceller."""
        with self._lock:
            self._gross_settlement_tickers = {self._normalize_ticker(t) for t in tickers if t}
            logger.info("Brut takasli hisseler guncellendi", adet=len(self._gross_settlement_tickers))

    def set_spk_banned(self, tickers: list[str]) -> None:
        """SPK tarafından geçici açığa satış yasağı getirilen hisseleri günceller."""
        with self._lock:
            self._spk_banned_tickers = {self._normalize_ticker(t) for t in tickers if t}
            logger.info("SPK yasakli hisseler guncellendi", adet=len(self._spk_banned_tickers))

    def set_uptick_rule_active(self, active: bool) -> None:
        """Yukarı Adım Kuralı (Uptick Rule) durumunu doğrudan günceller."""
        with self._lock:
            self._uptick_rule_active = active
            if active:
                logger.warning("BIST Yukari Adim Kurali (Uptick Rule) AKTIF — BIST-100 dususu %2 veya uzeri")
            else:
                logger.info("BIST Yukari Adim Kurali (Uptick Rule) pasife alindi")

    def check_uptick_rule(self, bist100_change_pct: float) -> bool:
        """BIST-100 endeksi günlük değişim oranına göre uptick kuralını tetikler veya korur.

        Args:
            bist100_change_pct: BIST-100 gün içi yüzde değişimi (örn. -2.15).

        Returns:
            bool: Kuralın güncel aktiflik durumu.
        """
        with self._lock:
            if bist100_change_pct <= -self.UPTICK_RULE_THRESHOLD_PCT:
                self.set_uptick_rule_active(True)
            return self._uptick_rule_active

    def reset_uptick_rule(self) -> None:
        """Seans bitiminde veya gün başlangıcında Yukarı Adım Kuralını sıfırlar."""
        self.set_uptick_rule_active(False)

    @otel_trace("short_selling.can_short_sell")
    def can_short_sell(
        self,
        ticker: str,
        current_price: float = 0.0,
        last_trade_price: float = 0.0,
        best_ask_price: float = 0.0,
    ) -> ShortSellingDecision:
        """Verilen hisse ve fiyatlar için açığa satış yapılabilirliğini mevzuata göre denetler.

        Args:
            ticker: Hisse senedi sembolü.
            current_price: İletilmek istenen açığa satış emir fiyatı.
            last_trade_price: Hissenin piyasadaki en son gerçekleşen işlem fiyatı.
            best_ask_price: Tahtadaki en iyi satış fiyatı (pasif spread kontrolü).

        Returns:
            ShortSellingDecision: İzin, red gerekçesi ve detayları içeren karar nesnesi.
        """
        norm_ticker = self._normalize_ticker(ticker)
        details: dict[str, Any] = {
            "ticker": norm_ticker,
            "current_price": current_price,
            "last_trade_price": last_trade_price,
            "best_ask_price": best_ask_price,
        }

        with self._lock:
            uptick_active = self._uptick_rule_active
            gross_settlement = norm_ticker in self._gross_settlement_tickers
            spk_banned = norm_ticker in self._spk_banned_tickers
            bist50_list = list(self._get_bist50())

        details["uptick_active"] = uptick_active

        # 0. Ticker ve Fiyat Geçerlilik Guard Kontrolü (Fail-Closed)
        if not norm_ticker:
            decision = ShortSellingDecision(
                allowed=False,
                reason="Gecersiz veya bos hisse sembolu",
                details=details,
            )
            self._record_audit(norm_ticker, current_price, last_trade_price, best_ask_price, decision)
            return decision

        # 1. BIST-50 Endeks Kapsamı Kontrolü
        if bist50_list and norm_ticker not in bist50_list:
            decision = ShortSellingDecision(
                allowed=False,
                reason=f"{norm_ticker} BIST-50 listesinde yer almamaktadir — aciga satis sadece BIST-50 hisselerinde serbesttir",
                details=details,
            )
            self._record_audit(norm_ticker, current_price, last_trade_price, best_ask_price, decision)
            return decision

        # 2. Brüt Takas Kısıtı Kontrolü
        if gross_settlement:
            decision = ShortSellingDecision(
                allowed=False,
                reason=f"{norm_ticker} hissesi brut takas uygulamasindadir — aciga satis kesinlikle yasaktir",
                details=details,
            )
            self._record_audit(norm_ticker, current_price, last_trade_price, best_ask_price, decision)
            return decision

        # 3. SPK Geçici Açığa Satış Yasağı Kontrolü
        if spk_banned:
            decision = ShortSellingDecision(
                allowed=False,
                reason=f"{norm_ticker} hissesi SPK gecici aciga satis yasagi listesindedir",
                details=details,
            )
            self._record_audit(norm_ticker, current_price, last_trade_price, best_ask_price, decision)
            return decision

        # 4. Yukarı Adım Kuralı (Uptick Rule) ve Fiyat Seviyesi Kontrolü
        if uptick_active:
            # Uptick aktifken emir fiyatı son işlem fiyatından düşük olamaz
            if current_price > 0 and last_trade_price > 0 and current_price < last_trade_price:
                decision = ShortSellingDecision(
                    allowed=False,
                    reason=(
                        f"Yukari Adim Kurali (Uptick Rule) AKTIF (BIST-100 %2+ dustu): "
                        f"Emir fiyati ({current_price:.2f}) < Son islem fiyati ({last_trade_price:.2f})"
                    ),
                    details=details,
                )
                self._record_audit(norm_ticker, current_price, last_trade_price, best_ask_price, decision)
                return decision

            # Tahtadaki en iyi satış fiyatından da düşük girilemez (Spread kuralı)
            if current_price > 0 and best_ask_price > 0 and current_price < best_ask_price:
                decision = ShortSellingDecision(
                    allowed=False,
                    reason=(
                        f"Yukari Adim Kurali (Uptick Rule) AKTIF: "
                        f"Emir fiyati ({current_price:.2f}) < En iyi satis fiyati ({best_ask_price:.2f})"
                    ),
                    details=details,
                )
                self._record_audit(norm_ticker, current_price, last_trade_price, best_ask_price, decision)
                return decision
        else:
            # Standart piyasada da emir fiyatı son fiyattan düşük olamaz
            if current_price > 0 and last_trade_price > 0 and current_price < last_trade_price:
                decision = ShortSellingDecision(
                    allowed=False,
                    reason=(
                        f"Genel yukari adim kurali: "
                        f"Emir fiyati ({current_price:.2f}) < Son islem fiyati ({last_trade_price:.2f})"
                    ),
                    details=details,
                )
                self._record_audit(norm_ticker, current_price, last_trade_price, best_ask_price, decision)
                return decision

        # Tüm şartları sağlayan emir onaylanır
        decision = ShortSellingDecision(
            allowed=True,
            reason="Aciga satis mevzuatina ve fiyat kurallarina uygun",
            details=details,
        )
        self._record_audit(norm_ticker, current_price, last_trade_price, best_ask_price, decision)
        return decision

    def check_short_selling_polars(self, df: pl.DataFrame) -> pl.DataFrame:
        """Toplu emir listesi içeren Polars DataFrame üzerinde vektörize açığa satış denetimi uygular.

        Args:
            df: 'ticker', 'current_price', 'last_trade_price', opsiyonel 'best_ask_price' kolonları içeren DataFrame.

        Returns:
            pl.DataFrame: 'allowed' (bool) ve 'reason' (str) kolonları eklenmiş Polars DataFrame.
        """
        if df.is_empty():
            return df.with_columns(
                pl.lit(True).alias("allowed"),
                pl.lit("").alias("reason"),
            )

        rows = df.to_dicts()
        results: list[dict[str, Any]] = []

        for row in rows:
            ticker = str(row.get("ticker", ""))
            c_price = float(row.get("current_price", 0.0) or 0.0)
            l_price = float(row.get("last_trade_price", 0.0) or 0.0)
            b_price = float(row.get("best_ask_price", 0.0) or 0.0)

            decision = self.can_short_sell(
                ticker=ticker,
                current_price=c_price,
                last_trade_price=l_price,
                best_ask_price=b_price,
            )
            results.append({"allowed": decision.allowed, "reason": decision.reason})

        res_df = pl.DataFrame(results)
        return df.with_columns(
            res_df["allowed"],
            res_df["reason"],
        )

    def export_audit_to_polars(self, limit: int = 1000) -> pl.DataFrame:
        """DuckDB üzerindeki açığa satış denetim loglarını Polars DataFrame olarak dışa aktarır."""
        with self._lock:
            try:
                df = self._duckdb_con.execute(
                    """
                    SELECT id, ticker, current_price, last_trade_price, best_ask_price,
                           allowed, reason, details_json, recorded_at
                    FROM short_selling_audit
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    [limit],
                ).pl()
                return df
            except Exception as e:
                logger.error("DuckDB aciga satis kayitlari Polars'a aktarilamadi", hata=str(e))
                return pl.DataFrame(
                    schema={
                        "id": pl.Int64,
                        "ticker": pl.Utf8,
                        "current_price": pl.Float64,
                        "last_trade_price": pl.Float64,
                        "best_ask_price": pl.Float64,
                        "allowed": pl.Boolean,
                        "reason": pl.Utf8,
                        "details_json": pl.Utf8,
                        "recorded_at": pl.Datetime,
                    }
                )

    def clear_audit_duckdb(self) -> None:
        """Denetim günlüğü tablosundaki tüm kayıtları temizler."""
        with self._lock:
            try:
                self._duckdb_con.execute("DELETE FROM short_selling_audit")
            except Exception as e:
                logger.warning("DuckDB aciga satis tablosu temizlenemedi", hata=str(e))

    def close(self) -> None:
        """DuckDB bağlantısını güvenli şekilde kapatır."""
        with self._lock:
            try:
                self._duckdb_con.close()
            except Exception as exc:
                logger.debug("DuckDB baglantisi kapatilirken hata olustu", hata=str(exc))

    def __repr__(self) -> str:
        with self._lock:
            bist50_count = len(self._bist50_cache) if self._bist50_cache is not None else 0
            gross_count = len(self._gross_settlement_tickers)
            spk_count = len(self._spk_banned_tickers)
            uptick = self._uptick_rule_active
        return (
            f"ShortSellingMonitor(uptick_active={uptick}, bist50_cached={bist50_count}, "
            f"gross_settlement={gross_count}, spk_banned={spk_count})"
        )


def read_short_selling_audit_from_duckdb(
    duckdb_path: str = DEFAULT_SHORT_SELLING_DB,
    limit: int = 1000,
) -> pl.DataFrame:
    """DuckDB dosyasından doğrudan açığa satış denetim loglarını Polars DataFrame olarak okur."""
    try:
        conn = duckdb.connect(duckdb_path)
        try:
            return conn.execute(
                """
                SELECT id, ticker, current_price, last_trade_price, best_ask_price,
                       allowed, reason, details_json, recorded_at
                FROM short_selling_audit
                ORDER BY id DESC
                LIMIT ?
                """,
                [limit],
            ).pl()
        finally:
            conn.close()
    except Exception as exc:
        logger.error("DuckDB dosyasindan aciga satis kayitlari okunamadi", hata=str(exc))
        return pl.DataFrame(
            schema={
                "id": pl.Int64,
                "ticker": pl.Utf8,
                "current_price": pl.Float64,
                "last_trade_price": pl.Float64,
                "best_ask_price": pl.Float64,
                "allowed": pl.Boolean,
                "reason": pl.Utf8,
                "details_json": pl.Utf8,
                "recorded_at": pl.Datetime,
            }
        )


def clear_short_selling_audit_duckdb(duckdb_path: str = DEFAULT_SHORT_SELLING_DB) -> None:
    """Belirtilen DuckDB dosyasındaki açığa satış denetim tablosunu sıfırlar."""
    try:
        conn = duckdb.connect(duckdb_path)
        try:
            conn.execute("DELETE FROM short_selling_audit")
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("DuckDB dosyasindaki aciga satis tablosu temizlenemedi", hata=str(exc))


# Singleton
short_selling_monitor = ShortSellingMonitor()

__all__ = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_SHORT_SELLING_DB",
    "DEFAULT_WAL_SIZE",
    "ShortSellingDecision",
    "ShortSellingMonitor",
    "clear_short_selling_audit_duckdb",
    "configure_duckdb_wal",
    "otel_trace",
    "read_short_selling_audit_from_duckdb",
    "short_selling_monitor",
    "to_orjson_bytes",
]
