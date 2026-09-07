"""ALPHA BIST — Veri Doğrulama Şemaları ve Veri Kontratları v3.0 (Pydantic v2 & Polars)

F-026: Sistem genelinde veri kalitesi, tip güvenliği ve sınır doğrulaması sağlar.
Pydantic v2 tabanlı veri modelleri ile akış verilerini, Polars vektörel kontrolleri ile
toplu veri kümelerini BIST piyasa standartlarına göre doğrular.

Desteklenen Veri Kontratları:
1. OHLCVSchema: Fiyat pozitifliği, OHLC geometrisi (High >= Low, High >= Open/Close, Low <= Open/Close).
2. FeatureVectorSchema: NaN, Sonsuz (Inf) ve None değer guard'ları.
3. PredictionSchema: Model yönü (UP, DOWN, NEUTRAL), güven skoru (0.0 - 1.0) ve tahmin ufku.
4. SignalSchema: Alım/satım aksiyonu (BUY, SELL, HOLD), fiyat ve stop-loss/hedef mantığı.
5. PositionSchema: Pozisyon yönü (LONG, SHORT), adet, giriş fiyatı ve cari fiyat tutarlılığı.
6. Polars Vektörel Doğrulayıcılar: validate_ohlcv_polars, validate_features_polars.
7. DuckDB Doğrulama Denetim Günlüğü: bist_schema_validation_audit.
"""

from __future__ import annotations

import contextlib
import math
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import orjson
import polars as pl
import structlog
from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.core.duckdb_store import configure_duckdb_wal
from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# =====================================================
# SABİTLER (DEFAULT CONSTANTS)
# =====================================================
DEFAULT_SCHEMA_AUDIT_DUCKDB_PATH: str = "data/schema_audit.duckdb"
DEFAULT_SCHEMA_AUDIT_TABLE: str = "bist_schema_validation_audit"
DEFAULT_MAX_AUDIT_MEMORY_ENTRIES: int = 500

# =====================================================
# BELLEK DENETİM KAYDI VE THREAD-SAFETY
# =====================================================
_audit_lock = threading.RLock()
_audit_log_entries: list[dict[str, Any]] = []


def _record_schema_violation(schema_name: str, error_msg: str, payload: dict[str, Any]) -> None:
    """Şema doğrulama ihlalini bellek içi denetim günlüğüne kaydeder."""
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "schema_name": schema_name,
        "error_message": error_msg[:300],
        "payload_preview": str(payload)[:200],
    }
    with _audit_lock:
        if len(_audit_log_entries) >= DEFAULT_MAX_AUDIT_MEMORY_ENTRIES:
            _audit_log_entries.pop(0)
        _audit_log_entries.append(entry)


def clear_schema_audit_log() -> None:
    """Bellekte tutulan şema denetim günlüğünü sıfırlar."""
    with _audit_lock:
        _audit_log_entries.clear()
        logger.info("sema_denetim_gunlugu_temizlendi")


# =====================================================
# PYDANTIC V2 VERİ DOĞRULAMA ŞEMALARI
# =====================================================
class BaseDataSchema(BaseModel):
    """Tüm BIST veri şemaları için temel Pydantic v2 modeli."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="ignore",
        populate_by_name=True,
        validate_assignment=True,
    )

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisi üretir."""
        return orjson.dumps(self.model_dump(mode="json"), default=str)

    def __repr__(self) -> str:
        """Açıklayıcı model metin temsili."""
        fields = ", ".join(f"{k}={v!r}" for k, v in list(self.model_dump().items())[:5])
        return f"<{self.__class__.__name__} {fields}>"


class OHLCVSchema(BaseDataSchema):
    """OHLCV çubuk fiyat ve hacim doğrulama şeması.

    BIST piyasa kurallarına göre fiyatlar pozitif olmalı,
    High en yüksek, Low en düşük olmalıdır.
    """

    date: datetime
    open: float = Field(gt=0, description="Açılış fiyatı (TL)")
    high: float = Field(gt=0, description="En yüksek fiyat (TL)")
    low: float = Field(gt=0, description="En düşük fiyat (TL)")
    close: float = Field(gt=0, description="Kapanış fiyatı (TL)")
    volume: float = Field(ge=0, description="İşlem hacmi (Lot)")

    @model_validator(mode="after")
    def validate_geometry(self) -> OHLCVSchema:
        """OHLC çubuk geometrisini doğrular."""
        if not (
            math.isfinite(self.open)
            and math.isfinite(self.high)
            and math.isfinite(self.low)
            and math.isfinite(self.close)
            and math.isfinite(self.volume)
        ):
            raise ValueError("OHLCV değerleri NaN veya Sonsuz (Inf) içeremez")

        if self.high < self.low:
            raise ValueError(f"High ({self.high}) değeri Low ({self.low}) değerinden küçük olamaz")

        if self.open > self.high or self.open < self.low:
            raise ValueError(f"Open ({self.open}) değeri Low ({self.low}) ve High ({self.high}) aralığında olmalıdır")

        if self.close > self.high or self.close < self.low:
            raise ValueError(
                f"Close ({self.close}) değeri Low ({self.low}) ve High ({self.high}) aralığında olmalıdır"
            )

        return self


class FeatureVectorSchema(BaseDataSchema):
    """Makine öğrenimi özellik vektörü (feature vector) doğrulama şeması."""

    ticker: str = Field(min_length=1, max_length=20, description="Hisse kodu")
    date: datetime = Field(description="Özellik hesaplama tarihi")
    features: dict[str, float] = Field(description="Özellik adı ve sayısal değeri")

    @model_validator(mode="after")
    def validate_features_finite(self) -> FeatureVectorSchema:
        """Özelliklerin NaN veya Sonsuz olmadığını doğrular."""
        for feat_name, feat_val in self.features.items():
            if feat_val is None or not math.isfinite(feat_val):
                raise ValueError(f"Feature '{feat_name}' geçersiz veya NaN/Inf içeriyor: {feat_val}")
        return self


class PredictionSchema(BaseDataSchema):
    """Model tahmin çıktısı doğrulama şeması."""

    model_id: str = Field(min_length=1, description="Tahmini üreten model kimliği")
    ticker: str = Field(min_length=1, max_length=20, description="Hisse kodu")
    timestamp: datetime = Field(description="Tahmin zamanı")
    predicted_direction: str = Field(pattern="^(UP|DOWN|NEUTRAL)$", description="Tahmin edilen yön")
    confidence: float = Field(ge=0.0, le=1.0, description="Model güven skoru (0.0 - 1.0)")
    prediction_horizon: str = Field(min_length=1, description="Tahmin vadesi (örn. '1d', '5d')")


class SignalSchema(BaseDataSchema):
    """Ticari karar motoru sinyal doğrulama şeması."""

    ticker: str = Field(min_length=1, max_length=20, description="Hisse kodu")
    action: str = Field(pattern="^(BUY|SELL|HOLD)$", description="İşlem aksiyonu")
    price: float = Field(gt=0, description="Sinyal tetiklenme fiyatı")
    confidence: float = Field(ge=0.0, le=1.0, description="Sinyal güven katsayısı")
    stop_loss: float | None = Field(default=None, gt=0, description="Zarar kes fiyatı")
    target: float | None = Field(default=None, gt=0, description="Hedef kar fiyatı")

    @model_validator(mode="after")
    def validate_signal_logic(self) -> SignalSchema:
        """Alım veya satım sinyallerinde stop-loss ve hedef mantığını doğrular."""
        if self.action == "BUY":
            if self.stop_loss and self.stop_loss >= self.price:
                raise ValueError(f"BUY sinyalinde stop_loss ({self.stop_loss}) fiyattan ({self.price}) küçük olmalıdır")
            if self.target and self.target <= self.price:
                raise ValueError(f"BUY sinyalinde target ({self.target}) fiyattan ({self.price}) büyük olmalıdır")
        elif self.action == "SELL":
            if self.stop_loss and self.stop_loss <= self.price:
                raise ValueError(f"SELL sinyalinde stop_loss ({self.stop_loss}) fiyattan ({self.price}) büyük olmalıdır")
            if self.target and self.target >= self.price:
                raise ValueError(f"SELL sinyalinde target ({self.target}) fiyattan ({self.price}) küçük olmalıdır")
        return self


class PositionSchema(BaseDataSchema):
    """Portföy açık pozisyon doğrulama şeması."""

    ticker: str = Field(min_length=1, max_length=20, description="Hisse kodu")
    direction: str = Field(pattern="^(LONG|SHORT)$", description="Pozisyon yönü")
    quantity: int = Field(gt=0, description="Lot adedi")
    entry_price: float = Field(gt=0, description="Pozisyon giriş maliyeti")
    current_price: float = Field(ge=0, description="Cari piyasa fiyatı")


# =====================================================
# DOĞRULAMA YARDIMCI FONKSİYONLARI (SINGLE ROW)
# =====================================================
@otel_trace("data_schemas.validate_ohlcv")
def validate_ohlcv(data: dict[str, Any], raise_on_error: bool = False) -> dict[str, Any] | None:
    """OHLCV sözlük verisini doğrular ve temizlenmiş sözlük döner.

    Args:
        data: Ham OHLCV verisi.
        raise_on_error: Hata durumunda istisna fırlatılsın mı?

    Returns:
        dict[str, Any] | None: Doğrulanmış sözlük veya hata durumunda None.

    Raises:
        ValueError: raise_on_error True olduğunda ve veri geçersizse fırlatılır.
    """
    try:
        validated = OHLCVSchema(**data)
        return validated.model_dump(mode="json")
    except Exception as e:
        _record_schema_violation("OHLCVSchema", str(e), data)
        logger.warning("ohlcv_dogrulama_hatasi", error=str(e), ticker=data.get("ticker", "UNKNOWN"))
        if raise_on_error:
            raise ValueError(f"OHLCV doğrulama başarısız: {e}") from e
        return None


@otel_trace("data_schemas.validate_features")
def validate_features(data: dict[str, Any], raise_on_error: bool = False) -> dict[str, Any] | None:
    """Özellik vektörünü doğrular.

    Args:
        data: Ham özellik verisi.
        raise_on_error: Hata durumunda istisna fırlatılsın mı?

    Returns:
        dict[str, Any] | None: Doğrulanmış sözlük veya None.
    """
    try:
        validated = FeatureVectorSchema(**data)
        return validated.model_dump(mode="json")
    except Exception as e:
        _record_schema_violation("FeatureVectorSchema", str(e), data)
        logger.warning("feature_dogrulama_hatasi", error=str(e), ticker=data.get("ticker", "UNKNOWN"))
        if raise_on_error:
            raise ValueError(f"Feature vektörü doğrulama başarısız: {e}") from e
        return None


@otel_trace("data_schemas.validate_prediction")
def validate_prediction(data: dict[str, Any], raise_on_error: bool = False) -> dict[str, Any] | None:
    """Model tahmin çıktısını doğrular.

    Args:
        data: Ham tahmin verisi.
        raise_on_error: Hata durumunda istisna fırlatılsın mı?

    Returns:
        dict[str, Any] | None: Doğrulanmış sözlük veya None.
    """
    try:
        validated = PredictionSchema(**data)
        return validated.model_dump(mode="json")
    except Exception as e:
        _record_schema_violation("PredictionSchema", str(e), data)
        logger.warning("tahmin_dogrulama_hatasi", error=str(e), ticker=data.get("ticker", "UNKNOWN"))
        if raise_on_error:
            raise ValueError(f"Tahmin doğrulama başarısız: {e}") from e
        return None


@otel_trace("data_schemas.validate_signal")
def validate_signal(data: dict[str, Any], raise_on_error: bool = False) -> dict[str, Any] | None:
    """Karar motoru sinyalini doğrular.

    Args:
        data: Ham sinyal verisi.
        raise_on_error: Hata durumunda istisna fırlatılsın mı?

    Returns:
        dict[str, Any] | None: Doğrulanmış sözlük veya None.
    """
    try:
        validated = SignalSchema(**data)
        return validated.model_dump(mode="json")
    except Exception as e:
        _record_schema_violation("SignalSchema", str(e), data)
        logger.warning("sinyal_dogrulama_hatasi", error=str(e), ticker=data.get("ticker", "UNKNOWN"))
        if raise_on_error:
            raise ValueError(f"Sinyal doğrulama başarısız: {e}") from e
        return None


@otel_trace("data_schemas.validate_position")
def validate_position(data: dict[str, Any], raise_on_error: bool = False) -> dict[str, Any] | None:
    """Portföy pozisyonunu doğrular.

    Args:
        data: Ham pozisyon verisi.
        raise_on_error: Hata durumunda istisna fırlatılsın mı?

    Returns:
        dict[str, Any] | None: Doğrulanmış sözlük veya None.
    """
    try:
        validated = PositionSchema(**data)
        return validated.model_dump(mode="json")
    except Exception as e:
        _record_schema_violation("PositionSchema", str(e), data)
        logger.warning("pozisyon_dogrulama_hatasi", error=str(e), ticker=data.get("ticker", "UNKNOWN"))
        if raise_on_error:
            raise ValueError(f"Pozisyon doğrulama başarısız: {e}") from e
        return None


# =====================================================
# POLARS VEKTÖREL DOĞRULAYICILAR (DATAFRAME LEVEL)
# =====================================================
def validate_ohlcv_polars(df: pl.DataFrame) -> tuple[bool, int, list[str]]:
    """Polars DataFrame üzerinde toplu OHLCV geometrisi ve pozitiflik doğrulaması yapar.

    Args:
        df: Denetlenecek Polars DataFrame.

    Returns:
        tuple[bool, int, list[str]]: (Geçti mi?, Hatalı satır sayısı, Hata detayları listesi).
    """
    if not isinstance(df, pl.DataFrame) or df.is_empty():
        return True, 0, []

    errors: list[str] = []
    total_violations = 0

    h_col = next((c for c in ("high", "High") if c in df.columns), None)
    l_col = next((c for c in ("low", "Low") if c in df.columns), None)
    o_col = next((c for c in ("open", "Open") if c in df.columns), None)
    c_col = next((c for c in ("close", "Close") if c in df.columns), None)

    if not all((h_col, l_col, o_col, c_col)):
        return False, len(df), ["OHLC sütunları eksik"]

    # Pozitiflik kontrolü
    for col in (h_col, l_col, o_col, c_col):
        series = df[col]
        if series.dtype.is_float():
            cond = (series <= 0.0) | series.is_null() | series.is_nan()
        else:
            cond = (series <= 0) | series.is_null()
        non_pos = int(cond.fill_null(False).sum() or 0)
        if non_pos > 0:
            errors.append(f"'{col}' sütununda {non_pos} adet <= 0 veya null/nan değer")
            total_violations += non_pos

    # Geometri kontrolü
    geom_cond = (
        (pl.col(h_col) < pl.col(l_col))
        | (pl.col(o_col) > pl.col(h_col))
        | (pl.col(o_col) < pl.col(l_col))
        | (pl.col(c_col) > pl.col(h_col))
        | (pl.col(c_col) < pl.col(l_col))
    )
    geom_violations = int(df.select(geom_cond.sum()).item() or 0)
    if geom_violations > 0:
        errors.append(f"{geom_violations} satırda OHLC geometrisi bozuk (High < Low veya Open/Close aralık dışı)")
        total_violations += geom_violations

    return total_violations == 0, total_violations, errors


def validate_features_polars(df: pl.DataFrame, feature_cols: list[str]) -> tuple[bool, int, list[str]]:
    """Polars DataFrame üzerinde özellik sütunlarının NaN veya sonsuz olmadığını doğrular.

    Args:
        df: Özellik DataFrame'i.
        feature_cols: İncelenecek özellik sütun adları.

    Returns:
        tuple[bool, int, list[str]]: (Geçti mi?, Hatalı hücre sayısı, Hata açıklamaları).
    """
    if not isinstance(df, pl.DataFrame) or df.is_empty():
        return True, 0, []

    errors: list[str] = []
    total_invalid = 0

    for col in feature_cols:
        if col in df.columns:
            series = df[col]
            if series.dtype.is_numeric():
                if series.dtype.is_float():
                    cond = series.is_null() | series.is_nan() | series.is_infinite()
                else:
                    cond = series.is_null()
                null_nan_cnt = int(cond.fill_null(False).sum() or 0)
                if null_nan_cnt > 0:
                    errors.append(f"'{col}' sütununda {null_nan_cnt} adet null/nan/inf tespit edildi")
                    total_invalid += null_nan_cnt
        else:
            errors.append(f"'{col}' sütunu DataFrame içinde bulunamadı")
            total_invalid += 1

    return total_invalid == 0, total_invalid, errors


# =====================================================
# DUCKDB DENETİM GÜNLÜĞÜ ENTEGRASYONU
# =====================================================
def export_schema_audit_to_polars() -> pl.DataFrame:
    """Şema ihlal denetim günlüğünü Polars DataFrame olarak döner."""
    with _audit_lock:
        entries = list(_audit_log_entries)

    schema = {
        "timestamp": pl.Utf8,
        "schema_name": pl.Utf8,
        "error_message": pl.Utf8,
        "payload_preview": pl.Utf8,
    }
    if not entries:
        return pl.DataFrame(schema=schema)

    return pl.DataFrame(entries, schema=schema)


def export_schema_audit_to_duckdb(
    db_path: str | Path | None = None,
    table_name: str = DEFAULT_SCHEMA_AUDIT_TABLE,
) -> int:
    """Şema doğrulama ihlallerini yerel DuckDB tablosuna yazar.

    Args:
        db_path: DuckDB veritabanı yolu.
        table_name: Hedef tablo adı.

    Returns:
        int: Eklenen ihlal kayıt adedi.
    """
    df = export_schema_audit_to_polars()
    if df.is_empty():
        return 0

    path_obj = Path(db_path or DEFAULT_SCHEMA_AUDIT_DUCKDB_PATH)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    if path_obj.exists() and path_obj.stat().st_size == 0:
        with contextlib.suppress(OSError):
            path_obj.unlink()

    try:
        with duckdb.connect(str(path_obj)) as conn:
            with contextlib.suppress(Exception):
                configure_duckdb_wal(conn)
            conn.register("df_schema_audit", df.to_arrow())
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM df_schema_audit WHERE 1=0"
            )
            conn.execute(f"INSERT INTO {table_name} SELECT * FROM df_schema_audit")
            with contextlib.suppress(Exception):
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table_name}_schema_ts ON {table_name}(schema_name, timestamp)"
                )
        return len(df)
    except Exception as e:
        logger.error("export_schema_audit_to_duckdb_failed", error=str(e))
        return 0


def query_schema_audit_duckdb(
    db_path: str | Path | None = None,
    table_name: str = DEFAULT_SCHEMA_AUDIT_TABLE,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB üzerinden geçmiş şema ihlallerini sorgular.

    Args:
        db_path: DuckDB veritabanı yolu.
        table_name: Tablo adı.
        limit: Maksimum satır sayısı.

    Returns:
        pl.DataFrame: Sorgu neticesi.
    """
    schema = {
        "timestamp": pl.Utf8,
        "schema_name": pl.Utf8,
        "error_message": pl.Utf8,
        "payload_preview": pl.Utf8,
    }
    empty_df = pl.DataFrame(schema=schema)
    path_obj = Path(db_path or DEFAULT_SCHEMA_AUDIT_DUCKDB_PATH)
    if not path_obj.exists() or path_obj.stat().st_size == 0:
        return empty_df

    try:
        with duckdb.connect(str(path_obj), read_only=True) as conn:
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name = ?",
                [table_name],
            ).fetchall()
            if not tables:
                return empty_df

            query = f"SELECT * FROM {table_name} ORDER BY timestamp DESC LIMIT ?"
            arrow_res = conn.execute(query, [limit]).arrow()
            return pl.from_arrow(arrow_res)
    except Exception as e:
        logger.error("query_schema_audit_duckdb_failed", error=str(e))
        return empty_df


__all__ = [
    "DEFAULT_MAX_AUDIT_MEMORY_ENTRIES",
    "DEFAULT_SCHEMA_AUDIT_DUCKDB_PATH",
    "DEFAULT_SCHEMA_AUDIT_TABLE",
    "BaseDataSchema",
    "FeatureVectorSchema",
    "OHLCVSchema",
    "PositionSchema",
    "PredictionSchema",
    "SignalSchema",
    "clear_schema_audit_log",
    "export_schema_audit_to_duckdb",
    "export_schema_audit_to_polars",
    "query_schema_audit_duckdb",
    "validate_features",
    "validate_features_polars",
    "validate_ohlcv",
    "validate_ohlcv_polars",
    "validate_position",
    "validate_prediction",
    "validate_signal",
]
