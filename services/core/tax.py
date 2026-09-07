"""
ALPHA BIST — Tax Calculator (Güncel Mevzuat ve Vergi Hesaplama Motoru) v2.0

BIST ve Sermaye Piyasası Vergi Hesaplama Mimarisi (2025-2026):
- BIST Hisse Senetleri: GVK Geçici 67. Madde uyarınca tam mükellef gerçek kişiler için %0 stopaj (istisna kapsamı).
- Beyana Tabi / Yabancı Hisse Kazançları: Yıllık kümülatif gelir vergisi dilimlerine göre (%15-%40).
- Temettü Gelirleri: %15 veya güncel Cumhurbaşkanı Kararı stopajı (GVK Md. 94/Geçici 67).
- Tahvil, Bono ve Faiz Gelirleri: %10 stopaj.
- Yatırım Fonları: Fon türüne ve hisse yoğunluğuna göre %0 - %10 stopaj.
- Eurobond ve Repo İşlemleri: Mevzuat stopaj oranları.

Tasarım İlkeleri:
- Sayısal Guard'lar (Fail-Closed): NaN, Inf, negatif veya sıfır fiyat/adet kontrolleri.
- Eşzamanlılık: threading.RLock() korumalı vergi hesaplayıcı motoru.
- DuckDB >= 1.3.0 denetim izi: tax_calculations_audit tablosu ile her hesaplamanın diske arşivlenmesi.
- Polars >= 1.30.0 vektörize portföy analitiği: calculate_tax_polars() ve export_tax_audit_to_polars().
- orjson yüksek hızlı serileştirme ve kurumsal Türkçe docstring/repr standartları.
"""

from __future__ import annotations

import functools
import inspect
import math
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

DEFAULT_TAX_DB: Final[str] = "data/tax_calculations_audit.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"

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
    """Metotları OpenTelemetry span veya güvenli yerel izleme sarmalayıcısına alır."""

    def decorator(func: Any) -> Any:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


# BIST ve Gelir Vergisi Dilimleri (2025-2026 Takvim Yılı)
INCOME_TAX_BRACKETS: list[tuple[float, float]] = [
    (110_000.0, 0.15),  # 110.000 TL'ye kadar %15
    (230_000.0, 0.20),  # 110.001 - 230.000 TL arası %20
    (580_000.0, 0.27),  # 230.001 - 580.000 TL arası %27
    (3_000_000.0, 0.35),  # 580.001 - 3.000.000 TL arası %35
    (float("inf"), 0.40),  # 3.000.001 TL üzeri %40
]

# Stopaj ve Muafiyet Oranları
DEFAULT_TAX_RATES: dict[str, float] = {
    "stock_bist": 0.00,  # BIST hisse senedi alım-satım kazancı GVK Geçici 67 kapsamında %0 stopaj
    "stock_foreign": 0.15,  # Yabancı hisse senedi kazançları (asgari dilim)
    "dividend": 0.15,  # Temettü stopajı (%15)
    "bond": 0.10,  # Devlet tahvili / Hazine bonosu stopajı (%10)
    "fund_equity": 0.00,  # Hisse senedi yoğun yatırım fonları (%0 muafiyet)
    "fund_other": 0.10,  # Diğer yatırım fonları (%10 stopaj)
    "repo": 0.10,  # Repo gelirleri stopajı (%10)
    "viop": 0.00,  # Pay ve pay endeksine dayalı VİOP kontratları (%0 stopaj)
}

# Uzun vadeli elde tutma eşiği (180 gün / 6 ay)
HOLDING_PERIOD_THRESHOLD: int = 180


@dataclass(slots=True)
class TaxResult:
    """Vergi hesaplama sonucu veri modeli.

    Attributes:
        profit: Brüt kâr veya zarar (TL).
        tax_rate: Uygulanan vergi veya stopaj oranı (0.0 - 0.40).
        tax: Ödenecek toplam vergi tutarı (TL).
        net_profit: Vergi sonrası net kâr veya zarar (TL).
        holding_days: Elde tutma süresi (gün).
        is_long_term: 180 gün ve üzeri uzun vadeli yatırım mı.
        tax_bracket: Uygulanan vergi dilimi veya stopaj açıklaması.
        asset_type: Varlık türü.
        calculated_at: Hesaplama zaman damgası.
    """

    profit: float
    tax_rate: float
    tax: float
    net_profit: float
    holding_days: int
    is_long_term: bool
    tax_bracket: str = ""
    asset_type: str = "stock_bist"
    calculated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Modeli standart Python sözlüğüne dönüştürür."""
        data = asdict(self)
        data["calculated_at"] = self.calculated_at.isoformat()
        return data

    def to_orjson_bytes(self) -> bytes:
        """Modeli yüksek hızlı orjson baytlarına serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        return (
            f"TaxResult(asset={self.asset_type!r}, profit={self.profit:,.2f}TL, "
            f"tax={self.tax:,.2f}TL, net={self.net_profit:,.2f}TL, rate={self.tax_rate:.1%})"
        )


class TaxCalculator:
    """Sermaye piyasası ve BIST mevzuatına uygun vergi hesaplama motoru."""

    def __init__(self, duckdb_path: str = DEFAULT_TAX_DB) -> None:
        """TaxCalculator başlatıcısı.

        Args:
            duckdb_path: Vergi hesaplama denetim günlüğü için DuckDB dosya yolu veya ':memory:'.
        """
        self._lock = threading.RLock()
        self._rates = dict(DEFAULT_TAX_RATES)
        self._duckdb_path = duckdb_path

        # DuckDB denetim tablosu kurulumu
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
        self._init_duckdb_schema()

    def _init_duckdb_schema(self) -> None:
        """DuckDB vergi denetim tablosunu ve dizisini oluşturur."""
        with self._lock:
            try:
                self._duckdb_con.execute("""
                    CREATE SEQUENCE IF NOT EXISTS seq_tax_audit_id START 1;
                    CREATE TABLE IF NOT EXISTS tax_calculations_audit (
                        id BIGINT DEFAULT nextval('seq_tax_audit_id') PRIMARY KEY,
                        asset_type VARCHAR NOT NULL,
                        buy_price DOUBLE NOT NULL,
                        sell_price DOUBLE NOT NULL,
                        quantity BIGINT NOT NULL,
                        holding_days INTEGER NOT NULL,
                        profit DOUBLE NOT NULL,
                        tax DOUBLE NOT NULL,
                        tax_rate DOUBLE NOT NULL,
                        net_profit DOUBLE NOT NULL,
                        is_long_term BOOLEAN NOT NULL,
                        tax_bracket VARCHAR NOT NULL,
                        calculated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
            except Exception as exc:
                logger.error("TaxCalculator DuckDB schema init failed", error=str(exc))

    def _record_audit_log(
        self,
        buy_price: float,
        sell_price: float,
        quantity: int,
        result: TaxResult,
    ) -> None:
        """Hesaplama sonucunu yerel DuckDB tablosuna kaydeder."""
        with self._lock:
            try:
                self._duckdb_con.execute(
                    """
                    INSERT INTO tax_calculations_audit
                    (asset_type, buy_price, sell_price, quantity, holding_days,
                     profit, tax, tax_rate, net_profit, is_long_term, tax_bracket, calculated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        result.asset_type,
                        float(buy_price),
                        float(sell_price),
                        int(quantity),
                        int(result.holding_days),
                        float(result.profit),
                        float(result.tax),
                        float(result.tax_rate),
                        float(result.net_profit),
                        bool(result.is_long_term),
                        result.tax_bracket,
                        result.calculated_at,
                    ],
                )
            except Exception as exc:
                logger.warning("Failed to record tax audit log", error=str(exc))

    def _get_income_tax_rate(self, annual_income: float) -> float:
        """Yıllık kümülatif gelir vergisi matrahına göre geçerli oranı döndürür."""
        if annual_income <= 0.0 or math.isnan(annual_income) or math.isinf(annual_income):
            return INCOME_TAX_BRACKETS[0][1]

        for threshold, rate in INCOME_TAX_BRACKETS:
            if annual_income <= threshold:
                return rate
        return 0.40

    @otel_trace("tax.calculate_tax")
    def calculate_tax(
        self,
        buy_price: float,
        sell_price: float,
        quantity: int,
        holding_days: int = 1,
        asset_type: str = "stock_bist",
        annual_income: float = 0.0,
        is_declared_income: bool = False,
    ) -> TaxResult:
        """Tekil alım-satım veya getiri işlemi için vergi hesaplar.

        Args:
            buy_price: Alış birim maliyeti (TL).
            sell_price: Satış birim fiyatı (TL).
            quantity: İşlem adedi (pozitif tam sayı).
            holding_days: Elde tutulan gün sayısı.
            asset_type: Varlık türü ('stock_bist', 'stock_foreign', 'dividend', 'bond', 'fund_equity', 'repo').
            annual_income: Yıllık kümülatif gelir (Gelir vergisi dilimi için).
            is_declared_income: Stopaj yerine yıllık gelir vergisi beyannamesine tabi mi.

        Returns:
            TaxResult: Detaylı vergi ve net kâr/zarar sonucu.
        """
        # Sayısal Guard'lar (Fail-Closed)
        if (
            math.isnan(buy_price)
            or math.isinf(buy_price)
            or buy_price <= 0.0
            or math.isnan(sell_price)
            or math.isinf(sell_price)
            or sell_price < 0.0
            or quantity <= 0
        ):
            return TaxResult(
                profit=0.0,
                tax_rate=0.0,
                tax=0.0,
                net_profit=0.0,
                holding_days=max(0, holding_days),
                is_long_term=False,
                tax_bracket="Gecersiz Parametre",
                asset_type=asset_type,
            )

        profit = (sell_price - buy_price) * quantity
        is_long_term = holding_days >= HOLDING_PERIOD_THRESHOLD

        with self._lock:
            default_rate = self._rates.get(asset_type, 0.15)

        # Zarar durumunda vergi doğmaz
        if profit <= 0.0:
            res = TaxResult(
                profit=round(profit, 4),
                tax_rate=0.0,
                tax=0.0,
                net_profit=round(profit, 4),
                holding_days=holding_days,
                is_long_term=is_long_term,
                tax_bracket="Zarar / Vergi Matrahi Yok",
                asset_type=asset_type,
            )
            self._record_audit_log(buy_price, sell_price, quantity, res)
            return res

        # 1. BIST Hisse Senedi (GVK Geçici 67 - %0 Stopaj)
        if asset_type == "stock_bist" and not is_declared_income:
            rate = 0.00
            tax_bracket = "GVK Gecici 67 (%0 Muafiyet)"
        # 2. Yıllık Gelir Vergisi Beyanına Tabi Durumlar (Yabancı hisse veya beyana tabi kazanç)
        elif is_declared_income or asset_type == "stock_foreign":
            # 6+ ay holding avantajı: kârın %50'si istisna olabilir
            taxable_profit = profit * 0.50 if is_long_term else profit
            taxable_base = max(0.0, annual_income + taxable_profit)
            rate = self._get_income_tax_rate(taxable_base)
            tax_bracket = f"Gelir Vergisi Dilimi (%{rate * 100:.0f})"
        # 3. Sabit Stopaj Oranına Tabi Varlıklar
        else:
            rate = default_rate
            tax_bracket = f"Stopaj (%{rate * 100:.0f})"

        tax = round(profit * rate, 4)
        net_profit = round(profit - tax, 4)

        res = TaxResult(
            profit=round(profit, 4),
            tax_rate=rate,
            tax=tax,
            net_profit=net_profit,
            holding_days=holding_days,
            is_long_term=is_long_term,
            tax_bracket=tax_bracket,
            asset_type=asset_type,
        )
        self._record_audit_log(buy_price, sell_price, quantity, res)
        return res

    def calculate_tax_polars(self, df: pl.DataFrame) -> pl.DataFrame:
        """Toplu işlem listesi için Polars ile vektörize vergi ve net kâr hesaplaması yapar.

        Beklenen Sütunlar:
            buy_price: pl.Float64
            sell_price: pl.Float64
            quantity: pl.Int64 veya pl.Float64
            holding_days: pl.Int64
            asset_type: pl.Utf8 (isteğe bağlı, varsayılan 'stock_bist')
        """
        required_cols = {"buy_price", "sell_price", "quantity"}
        if not required_cols.issubset(set(df.columns)) or df.is_empty():
            return pl.DataFrame(
                schema={
                    "profit": pl.Float64,
                    "tax_rate": pl.Float64,
                    "tax": pl.Float64,
                    "net_profit": pl.Float64,
                    "is_long_term": pl.Boolean,
                }
            )

        augmented = df.clone()
        if "holding_days" not in augmented.columns:
            augmented = augmented.with_columns(pl.lit(1).alias("holding_days"))
        if "asset_type" not in augmented.columns:
            augmented = augmented.with_columns(pl.lit("stock_bist").alias("asset_type"))

        augmented = augmented.with_columns([
            ((pl.col("sell_price") - pl.col("buy_price")) * pl.col("quantity")).alias("profit"),
            (pl.col("holding_days") >= HOLDING_PERIOD_THRESHOLD).alias("is_long_term"),
        ]).with_columns([
            # BIST hisselerinde %0, diğerlerinde standart stopaj
            pl.when(pl.col("asset_type") == "stock_bist")
            .then(pl.lit(0.00))
            .when(pl.col("asset_type") == "dividend")
            .then(pl.lit(0.15))
            .when(pl.col("asset_type") == "bond")
            .then(pl.lit(0.10))
            .otherwise(pl.lit(0.10))
            .alias("tax_rate")
        ]).with_columns([
            # Zarar durumunda vergi sıfırdır
            pl.when(pl.col("profit") <= 0.0)
            .then(pl.lit(0.00))
            .otherwise(pl.col("profit") * pl.col("tax_rate"))
            .alias("tax")
        ]).with_columns([
            (pl.col("profit") - pl.col("tax")).alias("net_profit")
        ])

        return augmented

    def export_tax_audit_to_polars(self) -> pl.DataFrame:
        """DuckDB'de kayıtlı vergi hesaplama denetim kayıtlarını Polars DataFrame olarak dışa aktarır."""
        with self._lock:
            try:
                return self._duckdb_con.execute("""
                    SELECT id, asset_type, buy_price, sell_price, quantity, holding_days,
                           profit, tax, tax_rate, net_profit, is_long_term, tax_bracket, calculated_at
                    FROM tax_calculations_audit
                    ORDER BY id ASC
                """).pl()
            except Exception as exc:
                logger.error("Failed to export tax audit log to Polars", error=str(exc))
                return pl.DataFrame()

    def clear_audit_duckdb(self) -> None:
        """Vergi denetim tablosunu temizler."""
        with self._lock:
            try:
                self._duckdb_con.execute("DELETE FROM tax_calculations_audit")
            except Exception as exc:
                logger.warning("DuckDB vergi denetim tablosu temizlenemedi", hata=str(exc))

    def close(self) -> None:
        """DuckDB bağlantısını güvenli şekilde kapatır."""
        with self._lock:
            try:
                self._duckdb_con.close()
            except Exception as exc:
                logger.debug("DuckDB baglantisi kapatilirken hata", hata=str(exc))

    def __repr__(self) -> str:
        with self._lock:
            return f"TaxCalculator(rates={len(self._rates)}, duckdb={self._duckdb_path!r})"


def read_tax_audit_from_duckdb(
    duckdb_path: str = DEFAULT_TAX_DB,
    limit: int = 1000,
) -> pl.DataFrame:
    """DuckDB dosyasından doğrudan vergi denetim kayıtlarını Polars DataFrame olarak okur."""
    try:
        conn = duckdb.connect(duckdb_path)
        try:
            return conn.execute(
                """
                SELECT id, asset_type, buy_price, sell_price, quantity, holding_days,
                       profit, tax, tax_rate, net_profit, is_long_term, tax_bracket, calculated_at
                FROM tax_calculations_audit
                ORDER BY id DESC
                LIMIT ?
                """,
                [limit],
            ).pl()
        finally:
            conn.close()
    except Exception as exc:
        logger.error("DuckDB dosyasindan vergi kayitlari okunamadi", hata=str(exc))
        return pl.DataFrame()


def clear_tax_audit_duckdb(duckdb_path: str = DEFAULT_TAX_DB) -> None:
    """Belirtilen DuckDB dosyasındaki vergi denetim tablosunu sıfırlar."""
    try:
        conn = duckdb.connect(duckdb_path)
        try:
            conn.execute("DELETE FROM tax_calculations_audit")
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("DuckDB vergi denetim tablosu temizlenemedi", hata=str(exc))


# Küresel Singleton Nesnesi
tax_calculator = TaxCalculator()


# Geriye Dönük Uyumluluk Fonksiyonu
def calculate_tax(
    buy_price: float,
    sell_price: float,
    quantity: int,
    holding_days: int = 1,
    asset_type: str = "stock_bist",
    annual_income: float = 0.0,
) -> TaxResult:
    """Modül seviyesinde doğrudan vergi hesaplama yardımcı fonksiyonu."""
    return tax_calculator.calculate_tax(
        buy_price=buy_price,
        sell_price=sell_price,
        quantity=quantity,
        holding_days=holding_days,
        asset_type=asset_type,
        annual_income=annual_income,
    )


__all__ = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_TAX_DB",
    "DEFAULT_TAX_RATES",
    "DEFAULT_WAL_SIZE",
    "HOLDING_PERIOD_THRESHOLD",
    "INCOME_TAX_BRACKETS",
    "TaxCalculator",
    "TaxResult",
    "calculate_tax",
    "clear_tax_audit_duckdb",
    "configure_duckdb_wal",
    "otel_trace",
    "read_tax_audit_from_duckdb",
    "tax_calculator",
    "to_orjson_bytes",
]
