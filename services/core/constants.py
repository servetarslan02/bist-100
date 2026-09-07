"""ALPHA BIST — Global Sistem ve Piyasa Sabitleri v3.0 (Global Constants)

F-022: Magic number'ların (sihirli sayılar) sistem genelinde kullanımını önleyen
merkezi kurumsal sabitler havuzudur. BIST mevzuatı (SPK & Borsa İstanbul),
komisyon oranları, devre kesici eşikleri, model eğitim hiperparametreleri (purge/embargo),
risk limitleri ve portföy kısıtları tek bir kaynaktan yönetilir.

Kategoriler:
1. BIST Piyasa ve Mevzuat Sabitleri (Komisyon, BSMV, EBDKS, devre kesici, tavan/taban)
2. Model Eğitim ve Doğrulama Sabitleri (Walk-forward purge/embargo, rejim ağırlıkları)
3. Risk ve Portföy Limitleri (VaR, stop-loss, take-profit, max hisse/sektör payı)
4. Teknik İndikatör ve Özellik Mühendisliği Sabitleri (RSI, Bollinger, MACD, ATR)
5. Değerleme ve Makro Sabitleri (WACC, vergi oranı, risksiz faiz oranı)
6. Veri Kalitesi ve Sağlık Denetim Sabitleri
7. Polars ve DuckDB Analitik Entegrasyonu
"""

from __future__ import annotations

import contextlib
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import orjson
import polars as pl
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.constants")

# =====================================================
# 1. BIST PİYASA VE İŞLEM SABİTLERİ
# =====================================================
BIST_COMMISSION_RATE: float = 0.0003  # %0.03 (on binde 3 aracı kurum komisyonu)
BIST_EXCHANGE_FEE_RATE: float = 0.000056  # %0.0056 (Borsa payı)
BIST_BSMV_RATE: float = 0.05  # %5 BSMV (Banka ve Sigorta Muameleleri Vergisi)
BIST_MIN_COMMISSION: float = 1.0  # Minimum komisyon tutarı (TL)
BIST_SLIPPAGE_DEFAULT: float = 0.0005  # Varsayılan kayma payı (%0.05 / 5 bps)

# BIST Devre Kesici ve Fiyat Sınırları (SPK / Borsa İstanbul Güncel)
BIST_CIRCUIT_BREAKER_PCT: float = 5.0  # Pay bazında otomatik devre kesici eşiği (%5)
BIST_EBDKS_THRESHOLD_PCT: float = 5.0  # Endekse Bağlı Devre Kesici 1. Eşik (%5 düşüş)
BIST_EBDKS_THRESHOLD_1_PCT: float = 5.0  # EBDKS 1. Eşik (%5)
BIST_EBDKS_THRESHOLD_2_PCT: float = 7.0  # EBDKS 2. Eşik (%7)
BIST_MAX_DAILY_PRICE_LIMIT_PCT: float = 10.0  # Günlük tavan / taban fiyat limiti (%10)
BIST_HALTED_PRICE_THRESHOLD: float = 10.0  # Aşırı volatilite durdurma eşiği (%)

# Likidite ve Katılım Sınırları
MIN_VOLUME_FOR_TRADING: int = 1000  # İşlem için gereken minimum günlük lot adedi
MAX_PARTICIPATION_RATE: float = 0.10  # Günlük hacmin maksimum %10'una katılım izni

# VIOP Takasbank SPAN Teminat Sabitleri
VIOP_INITIAL_MARGIN_PCT: float = 15.0  # Başlangıç teminat oranı (%15)
VIOP_MAINTENANCE_MARGIN_PCT: float = 11.25  # Sürdürme teminatı oranı (%11.25, 0.75 * Başlangıç)
VIOP_LIQUIDATION_MARGIN_PCT: float = 7.5  # Likidasyon teminatı oranı (%7.5, 0.50 * Başlangıç)

# =====================================================
# 2. MODEL EĞİTİM VE DOĞRULAMA SABİTLERİ (QUANT / ML)
# =====================================================
DEFAULT_PURGE_DAYS: int = 5  # Train/Test arası point-in-time arınma süresi (gün)
DEFAULT_EMBARGO_DAYS: int = 5  # Test sonrası otokorelasyon engelleme süresi (gün)
DEFAULT_TRAIN_DAYS: int = 252  # 1 yıllık işlem günü bazında eğitim penceresi
DEFAULT_TEST_DAYS: int = 63  # 3 aylık test penceresi
DEFAULT_STEP_DAYS: int = 21  # 1 aylık kaydırma adımı (Walk-forward roll)
MIN_TRAIN_SAMPLES: int = 100  # Minimum geçerli eğitim gözlemi

# Piyasa Rejimi (Regime Detection) Sabitleri
REGIME_WINDOW_SIZE: int = 63  # Rejim yuvarlanan pencere boyutu (3 ay)
REGIME_HMM_WEIGHT: float = 0.30  # HMM model ağırlığı
REGIME_MACRO_WEIGHT: float = 0.15  # Makroekonomik faktör ağırlığı
REGIME_SCORE_WEIGHT: float = 0.55  # Fiyat/hacim skor ağırlığı

# =====================================================
# 3. RİSK VE PORTFÖY LİMİTLERİ
# =====================================================
VAR_CONFIDENCE_LEVEL: float = 0.95  # %95 Parametrik ve Tarihsel VaR güven seviyesi
MAX_POSITION_PCT: float = 15.0  # Tek bir hisseye portföyün maksimum %15'i tahsis edilebilir
MAX_SECTOR_PCT: float = 30.0  # Tek bir sektöre maksimum %30 yoğunlaşma limiti
DEFAULT_STOP_LOSS_PCT: float = 6.0  # Varsayılan zarar kes eşiği (%6)
DEFAULT_TAKE_PROFIT_PCT: float = 10.0  # Varsayılan kar al eşiği (%10)
DEFAULT_TRAILING_STOP_PCT: float = 3.0  # İz süren stop eşiği (%3)

# Monte Carlo Simülasyon Sabitleri
DEFAULT_MC_SIMULATIONS: int = 10000  # Simülasyon patika sayısı
DEFAULT_MC_HORIZON: int = 20  # Tahmin ufku (20 işlem günü)

# Portföy Yönetim Sabitleri
DEFAULT_INITIAL_CAPITAL: float = 10_000_000.0  # Varsayılan başlangıç sermayesi (TL)
MAX_POSITIONS: int = 30  # Portföyde taşınabilecek maksimum hisse sayısı (0-30 dinamik)
REBALANCE_THRESHOLD_PCT: float = 5.0  # Yeniden dengeleme tetikleme sapması (%)
MAX_TURNOVER: float = 0.30  # Maksimum günlük portföy devir hızı (%30)

# =====================================================
# 4. TEKNİK ANALİZ VE FEATURE ENGINEERING SABİTLERİ
# =====================================================
RSI_PERIOD: int = 14  # RSI hesaplama periyodu
RSI_OVERSOLD: float = 30.0  # Aşırı satım bölgesi eşiği
RSI_OVERBOUGHT: float = 70.0  # Aşırı alım bölgesi eşiği

BB_PERIOD: int = 20  # Bollinger Bantları periyodu
BB_STD_MULTIPLIER: float = 2.0  # Bollinger standart sapma çarpanı

ATR_PERIOD: int = 14  # Ortalama Gerçek Aralık (ATR) periyodu

SMA_SHORT: int = 20  # Kısa vadeli hareketli ortalama
SMA_LONG: int = 50  # Orta vadeli hareketli ortalama
SMA_TREND: int = 200  # Uzun vadeli ana trend ortalaması

# =====================================================
# 5. DEĞERLEME VE MAKROEKONOMİK SABİTLER
# =====================================================
DEFAULT_WACC: float = 0.20  # %20 Ağırlıklı Ortalama Sermaye Maliyeti (Risk Primi Dahil)
DEFAULT_TAX_RATE: float = 0.23  # %23 Kurumlar Vergisi Oranı (Türkiye)
DEFAULT_TERMINAL_GROWTH: float = 0.03  # %3 Nihai büyüme oranı (Uzun vadeli reel büyüme)

CONFIG_DIR: Path = Path(__file__).parent.parent.parent / "config"
DEFAULT_DUCKDB_PATH: Path = Path("data/constants.duckdb")
DEFAULT_CONSTANTS_DUCKDB_PATH: str = str(DEFAULT_DUCKDB_PATH)

_rf_lock: threading.RLock = threading.RLock()
_cached_rf_rate: float | None = None


def get_risk_free_rate(config_path: Path | None = None) -> float:
    """TCMB politika veya risksiz faiz oranını dosyadan okur (varsayılan: %45).

    Args:
        config_path: İsteğe bağlı risk_free_rate.json dosya yolu.

    Returns:
        Yıllık risksiz getiri oranı (ondalık, örn. 0.45).
    """
    global _cached_rf_rate
    with _rf_lock:
        if _cached_rf_rate is not None:
            return _cached_rf_rate

        target_path = config_path or (CONFIG_DIR / "risk_free_rate.json")
        with tracer.start_as_current_span("constants.get_risk_free_rate") as span:
            if target_path.exists() and target_path.stat().st_size > 0:
                try:
                    data = orjson.loads(target_path.read_bytes())
                    rate = float(data.get("risk_free_rate", 0.45))
                    span.set_attribute("risk_free_rate", rate)
                    _cached_rf_rate = rate
                    return rate
                except Exception as e:
                    logger.warning("risk_free_rate_okunamadi_varsayilan_kullaniliyor", error=str(e))

            span.set_attribute("risk_free_rate", 0.45)
            _cached_rf_rate = 0.45
            return 0.45


def set_risk_free_rate(rate: float) -> None:
    """Çalışma zamanında risksiz faiz oranını günceller.

    Args:
        rate: Yeni risksiz faiz oranı (örn. 0.45).
    """
    global _cached_rf_rate
    with _rf_lock:
        _cached_rf_rate = max(0.0, float(rate))


DEFAULT_RISK_FREE_RATE: float = get_risk_free_rate()

# =====================================================
# 6. VERİ KALİTESİ VE GÜNLÜK TAKİP LİMİTLERİ
# =====================================================
MAX_TIMESTAMP_GAP_DAYS: int = 5  # İzin verilen maksimum zaman serisi boşluğu (gün)
MIN_DATA_ROWS: int = 60  # Güvenilir istatistik için gereken minimum veri satırı
STALE_DATA_THRESHOLD_HOURS: int = 24  # Eski (bayat) veri kabul sınırı (saat)

MAX_TRADES_HISTORY: int = 10000  # Hafızada tutulan maksimum işlem geçmişi
MAX_CASH_LEDGER: int = 50000  # Kasa defteri işlem kayıt limiti
MAX_EQUITY_CURVE: int = 5000  # Portföy getiri eğrisi kayıt sayısı
MAX_DAILY_PNL: int = 1000  # Günlük PnL kayıt hafıza limiti

# =====================================================
# 7. POLARS VE DUCKDB ANALİTİK DIŞA AKTARIMI
# =====================================================


def export_constants_to_dict() -> dict[str, dict[str, Any]]:
    """Tüm sistem sabitlerini kategori bazında hiyerarşik sözlük olarak döner."""
    return {
        "BIST_MARKET": {
            "BIST_COMMISSION_RATE": BIST_COMMISSION_RATE,
            "BIST_EXCHANGE_FEE_RATE": BIST_EXCHANGE_FEE_RATE,
            "BIST_BSMV_RATE": BIST_BSMV_RATE,
            "BIST_MIN_COMMISSION": BIST_MIN_COMMISSION,
            "BIST_SLIPPAGE_DEFAULT": BIST_SLIPPAGE_DEFAULT,
            "BIST_CIRCUIT_BREAKER_PCT": BIST_CIRCUIT_BREAKER_PCT,
            "BIST_EBDKS_THRESHOLD_PCT": BIST_EBDKS_THRESHOLD_PCT,
            "BIST_EBDKS_THRESHOLD_1_PCT": BIST_EBDKS_THRESHOLD_1_PCT,
            "BIST_EBDKS_THRESHOLD_2_PCT": BIST_EBDKS_THRESHOLD_2_PCT,
            "BIST_MAX_DAILY_PRICE_LIMIT_PCT": BIST_MAX_DAILY_PRICE_LIMIT_PCT,
            "BIST_HALTED_PRICE_THRESHOLD": BIST_HALTED_PRICE_THRESHOLD,
            "MIN_VOLUME_FOR_TRADING": MIN_VOLUME_FOR_TRADING,
            "MAX_PARTICIPATION_RATE": MAX_PARTICIPATION_RATE,
        },
        "VIOP_DERIVATIVES": {
            "VIOP_INITIAL_MARGIN_PCT": VIOP_INITIAL_MARGIN_PCT,
            "VIOP_MAINTENANCE_MARGIN_PCT": VIOP_MAINTENANCE_MARGIN_PCT,
            "VIOP_LIQUIDATION_MARGIN_PCT": VIOP_LIQUIDATION_MARGIN_PCT,
        },
        "MODEL_TRAINING": {
            "DEFAULT_PURGE_DAYS": DEFAULT_PURGE_DAYS,
            "DEFAULT_EMBARGO_DAYS": DEFAULT_EMBARGO_DAYS,
            "DEFAULT_TRAIN_DAYS": DEFAULT_TRAIN_DAYS,
            "DEFAULT_TEST_DAYS": DEFAULT_TEST_DAYS,
            "DEFAULT_STEP_DAYS": DEFAULT_STEP_DAYS,
            "MIN_TRAIN_SAMPLES": MIN_TRAIN_SAMPLES,
            "REGIME_WINDOW_SIZE": REGIME_WINDOW_SIZE,
            "REGIME_HMM_WEIGHT": REGIME_HMM_WEIGHT,
            "REGIME_MACRO_WEIGHT": REGIME_MACRO_WEIGHT,
            "REGIME_SCORE_WEIGHT": REGIME_SCORE_WEIGHT,
        },
        "RISK_PORTFOLIO": {
            "VAR_CONFIDENCE_LEVEL": VAR_CONFIDENCE_LEVEL,
            "MAX_POSITION_PCT": MAX_POSITION_PCT,
            "MAX_SECTOR_PCT": MAX_SECTOR_PCT,
            "DEFAULT_STOP_LOSS_PCT": DEFAULT_STOP_LOSS_PCT,
            "DEFAULT_TAKE_PROFIT_PCT": DEFAULT_TAKE_PROFIT_PCT,
            "DEFAULT_TRAILING_STOP_PCT": DEFAULT_TRAILING_STOP_PCT,
            "DEFAULT_MC_SIMULATIONS": DEFAULT_MC_SIMULATIONS,
            "DEFAULT_MC_HORIZON": DEFAULT_MC_HORIZON,
            "DEFAULT_INITIAL_CAPITAL": DEFAULT_INITIAL_CAPITAL,
            "MAX_POSITIONS": MAX_POSITIONS,
            "REBALANCE_THRESHOLD_PCT": REBALANCE_THRESHOLD_PCT,
            "MAX_TURNOVER": MAX_TURNOVER,
        },
        "TECHNICAL_FEATURES": {
            "RSI_PERIOD": RSI_PERIOD,
            "RSI_OVERSOLD": RSI_OVERSOLD,
            "RSI_OVERBOUGHT": RSI_OVERBOUGHT,
            "BB_PERIOD": BB_PERIOD,
            "BB_STD_MULTIPLIER": BB_STD_MULTIPLIER,
            "ATR_PERIOD": ATR_PERIOD,
            "SMA_SHORT": SMA_SHORT,
            "SMA_LONG": SMA_LONG,
            "SMA_TREND": SMA_TREND,
        },
        "VALUATION_MACRO": {
            "DEFAULT_WACC": DEFAULT_WACC,
            "DEFAULT_TAX_RATE": DEFAULT_TAX_RATE,
            "DEFAULT_TERMINAL_GROWTH": DEFAULT_TERMINAL_GROWTH,
            "DEFAULT_RISK_FREE_RATE": get_risk_free_rate(),
        },
        "DATA_QUALITY_LOGGING": {
            "MAX_TIMESTAMP_GAP_DAYS": MAX_TIMESTAMP_GAP_DAYS,
            "MIN_DATA_ROWS": MIN_DATA_ROWS,
            "STALE_DATA_THRESHOLD_HOURS": STALE_DATA_THRESHOLD_HOURS,
            "MAX_TRADES_HISTORY": MAX_TRADES_HISTORY,
            "MAX_CASH_LEDGER": MAX_CASH_LEDGER,
            "MAX_EQUITY_CURVE": MAX_EQUITY_CURVE,
            "MAX_DAILY_PNL": MAX_DAILY_PNL,
        },
    }


def export_constants_to_orjson_bytes() -> bytes:
    """Tüm sistem sabitlerini orjson formatında bayt dizisine serileştirir."""
    return orjson.dumps(export_constants_to_dict(), default=str)


def export_constants_to_polars() -> pl.DataFrame:
    """Tüm sistem sabitlerini kategori, isim, tip ve değerleri ile Polars DataFrame olarak döner.

    Returns:
        'category', 'constant_name', 'value', 'data_type' sütunlu DataFrame.
    """
    categories = export_constants_to_dict()

    rows: list[dict[str, str]] = []
    for cat, item_dict in categories.items():
        for name, val in item_dict.items():
            rows.append({
                "category": cat,
                "constant_name": name,
                "value": str(val),
                "data_type": type(val).__name__,
            })

    schema = {
        "category": pl.Utf8,
        "constant_name": pl.Utf8,
        "value": pl.Utf8,
        "data_type": pl.Utf8,
    }
    return pl.DataFrame(rows, schema=schema)


def export_constants_to_duckdb(
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    table_name: str = "bist_system_constants",
) -> int:
    """Sistem sabitlerini DuckDB tablosuna kaydeder.

    Args:
        db_path: DuckDB dosya yolu.
        table_name: Hedef tablo adı.

    Returns:
        Yazılan kayıt sayısı.
    """
    df = export_constants_to_polars()
    if df.is_empty():
        return 0

    now_ts = datetime.now(UTC).isoformat()
    df_snapshot = df.with_columns(pl.lit(now_ts).alias("snapshot_timestamp"))

    path_obj = Path(db_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    if path_obj.exists() and path_obj.stat().st_size == 0:
        with contextlib.suppress(OSError):
            path_obj.unlink()

    try:
        with duckdb.connect(str(path_obj)) as conn:
            try:
                from services.core.debounce import configure_duckdb_wal

                configure_duckdb_wal(conn)
            except Exception:
                with contextlib.suppress(Exception):
                    conn.execute("PRAGMA wal_autocheckpoint='10MB';")

            conn.register("df_consts", df_snapshot.to_arrow())
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM df_consts WHERE 1=0"
            )
            conn.execute(f"INSERT INTO {table_name} SELECT * FROM df_consts")
            with contextlib.suppress(Exception):
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_cat ON {table_name} (category)")
        return len(df_snapshot)
    except Exception as e:
        logger.error("export_constants_to_duckdb_failed", error=str(e))
        return 0


def query_constants_duckdb(
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    table_name: str = "bist_system_constants",
    category: str | None = None,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB üzerinden geçmiş sistem sabitlerini sorgular.

    Args:
        db_path: DuckDB dosya yolu.
        table_name: Tablo adı.
        category: İsteğe bağlı kategori filtresi (örn. 'BIST_MARKET').
        limit: Maksimum satır sayısı.

    Returns:
        Polars DataFrame.
    """
    schema = {
        "category": pl.Utf8,
        "constant_name": pl.Utf8,
        "value": pl.Utf8,
        "data_type": pl.Utf8,
        "snapshot_timestamp": pl.Utf8,
    }
    empty_df = pl.DataFrame(schema=schema)
    path_obj = Path(db_path)
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

            if category:
                query = f"SELECT * FROM {table_name} WHERE category = ? ORDER BY snapshot_timestamp DESC LIMIT ?"
                arrow_res = conn.execute(query, [category, limit]).arrow()
            else:
                query = f"SELECT * FROM {table_name} ORDER BY snapshot_timestamp DESC LIMIT ?"
                arrow_res = conn.execute(query, [limit]).arrow()

            return pl.from_arrow(arrow_res)
    except Exception as e:
        logger.error("query_constants_duckdb_failed", error=str(e))
        return empty_df


__all__ = [
    # BIST Piyasa & VIOP
    "BIST_COMMISSION_RATE",
    "BIST_EXCHANGE_FEE_RATE",
    "BIST_BSMV_RATE",
    "BIST_MIN_COMMISSION",
    "BIST_SLIPPAGE_DEFAULT",
    "BIST_CIRCUIT_BREAKER_PCT",
    "BIST_EBDKS_THRESHOLD_PCT",
    "BIST_EBDKS_THRESHOLD_1_PCT",
    "BIST_EBDKS_THRESHOLD_2_PCT",
    "BIST_MAX_DAILY_PRICE_LIMIT_PCT",
    "BIST_HALTED_PRICE_THRESHOLD",
    "MIN_VOLUME_FOR_TRADING",
    "MAX_PARTICIPATION_RATE",
    "VIOP_INITIAL_MARGIN_PCT",
    "VIOP_MAINTENANCE_MARGIN_PCT",
    "VIOP_LIQUIDATION_MARGIN_PCT",
    # Model Eğitim
    "DEFAULT_PURGE_DAYS",
    "DEFAULT_EMBARGO_DAYS",
    "DEFAULT_TRAIN_DAYS",
    "DEFAULT_TEST_DAYS",
    "DEFAULT_STEP_DAYS",
    "MIN_TRAIN_SAMPLES",
    "REGIME_WINDOW_SIZE",
    "REGIME_HMM_WEIGHT",
    "REGIME_MACRO_WEIGHT",
    "REGIME_SCORE_WEIGHT",
    # Risk ve Portföy
    "VAR_CONFIDENCE_LEVEL",
    "MAX_POSITION_PCT",
    "MAX_SECTOR_PCT",
    "DEFAULT_STOP_LOSS_PCT",
    "DEFAULT_TAKE_PROFIT_PCT",
    "DEFAULT_TRAILING_STOP_PCT",
    "DEFAULT_MC_SIMULATIONS",
    "DEFAULT_MC_HORIZON",
    "DEFAULT_INITIAL_CAPITAL",
    "MAX_POSITIONS",
    "REBALANCE_THRESHOLD_PCT",
    "MAX_TURNOVER",
    # Teknik Analiz
    "RSI_PERIOD",
    "RSI_OVERSOLD",
    "RSI_OVERBOUGHT",
    "BB_PERIOD",
    "BB_STD_MULTIPLIER",
    "ATR_PERIOD",
    "SMA_SHORT",
    "SMA_LONG",
    "SMA_TREND",
    # Değerleme ve Makro
    "DEFAULT_WACC",
    "DEFAULT_TAX_RATE",
    "DEFAULT_TERMINAL_GROWTH",
    "DEFAULT_RISK_FREE_RATE",
    "get_risk_free_rate",
    "set_risk_free_rate",
    # Veri Kalitesi & Logging
    "MAX_TIMESTAMP_GAP_DAYS",
    "MIN_DATA_ROWS",
    "STALE_DATA_THRESHOLD_HOURS",
    "MAX_TRADES_HISTORY",
    "MAX_CASH_LEDGER",
    "MAX_EQUITY_CURVE",
    "MAX_DAILY_PNL",
    # Polars & DuckDB Fonksiyonları
    "DEFAULT_CONSTANTS_DUCKDB_PATH",
    "DEFAULT_DUCKDB_PATH",
    "export_constants_to_dict",
    "export_constants_to_orjson_bytes",
    "export_constants_to_polars",
    "export_constants_to_duckdb",
    "query_constants_duckdb",
]
