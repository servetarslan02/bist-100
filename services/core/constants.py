"""
ALPHA BIST — Global Constants v1.0

F-022: Magic numbers yerine merkezi sabit tanımları.
Tüm servisler bu sabitleri kullanmalıdır.

Kullanım:
    from services.core.constants import *
    veya
    from services.core.constants import BIST_COMMISSION_RATE, DEFAULT_PURGE_DAYS
"""

# =====================================================
# BIST PİYASA SABİTLERİ
# =====================================================

# Komisyon oranları
BIST_COMMISSION_RATE = 0.0003  # %0.03 (tek yön)
BIST_EXCHANGE_FEE_RATE = 0.000056  # %0.0056
BIST_BSMV_RATE = 0.05  # %5 BSMV
BIST_MIN_COMMISSION = 1.0  # Minimum komisyon (TL)
BIST_SLIPPAGE_DEFAULT = 0.05  # Varsayılan slippage (%)

# Devre kesici eşikleri (Eylül 2025 güncel)
BIST_CIRCUIT_BREAKER_PCT = 5.0  # Pay bazında devre kesici eşiği (Yıldız/Ana Pazar)
BIST_EBDKS_THRESHOLD_PCT = 6.0  # Endekse bağlı devre kesici (BIST-100 %6 düşüş)
BIST_HALTED_PRICE_THRESHOLD = 10.0  # Aşırı volatilite (%)

# Likidite
MIN_VOLUME_FOR_TRADING = 1000  # Minimum lot (likidite)
MAX_PARTICIPATION_RATE = 0.10  # Max %10 günlük hacimden

# =====================================================
# MODEL EĞİTİM SABİTLERİ
# =====================================================

# Walk-forward
DEFAULT_PURGE_DAYS = 5  # Train/test arası gap
DEFAULT_EMBARGO_DAYS = 5  # Test sonrası gap
DEFAULT_TRAIN_DAYS = 252  # 1 yıl günlük
DEFAULT_TEST_DAYS = 63  # 3 ay günlük
DEFAULT_STEP_DAYS = 21  # 1 ay günlük
MIN_TRAIN_SAMPLES = 100  # Minimum eğitim örneği

# Regime detection
REGIME_WINDOW_SIZE = 63  # Rolling window (3 ay)
REGIME_HMM_WEIGHT = 0.30  # HMM ağırlığı
REGIME_MACRO_WEIGHT = 0.15  # Macro ağırlığı

# =====================================================
# RİSK SABİTLERİ
# =====================================================

# VaR/CVaR
VAR_CONFIDENCE_LEVEL = 0.95  # %95 güven
MAX_POSITION_PCT = 15.0  # Tek pozisyon max %
MAX_SECTOR_PCT = 30.0  # Sektör max % (risk parity limiti)
DEFAULT_STOP_LOSS_PCT = 6.0  # Varsayılan stop-loss %
DEFAULT_TAKE_PROFIT_PCT = 10.0  # Varsayılan take-profit %

# Monte Carlo
DEFAULT_MC_SIMULATIONS = 10000  # Simülasyon sayısı
DEFAULT_MC_HORIZON = 20  # Tahmin ufku (gün)

# =====================================================
# FEATURE ENGINEERING SABİTLERİ
# =====================================================

# RSI
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

# Bollinger Bands
BB_PERIOD = 20
BB_STD_MULTIPLIER = 2.0

# ATR
ATR_PERIOD = 14

# Hareketli ortalamalar
SMA_SHORT = 20
SMA_LONG = 50
SMA_TREND = 200

# =====================================================
# DEĞERLEME SABİTLERİ
# =====================================================

DEFAULT_WACC = 0.20  # %20 (Türkiye risk primi)
DEFAULT_TAX_RATE = 0.23  # %23 kurumlar vergisi
DEFAULT_TERMINAL_GROWTH = 0.03  # %3 (enflasyon + reel)


import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.constants")

def _load_risk_free_rate() -> float:
    """TCMB politika faizini config dosyasından oku."""
    with tracer.start_as_current_span("constants._load_risk_free_rate") as span:
        try:
            from pathlib import Path
            import orjson

            config_path = Path(__file__).parent.parent.parent / "config" / "risk_free_rate.json"
            if config_path.exists():
                data = orjson.loads(config_path.read_bytes())
                rate = float(data.get("risk_free_rate", 0.45))
                span.set_attribute("risk_free_rate", rate)
                return rate
            else:
                logger.debug("risk_free_rate.json not found, using default 0.45")
        except Exception as e:
            logger.warning("Failed to load risk_free_rate.json, using default 0.45", error=str(e))
            span.record_exception(e)
            
        span.set_attribute("risk_free_rate", 0.45)
        return 0.45  # fallback


DEFAULT_RISK_FREE_RATE = _load_risk_free_rate()  # config/risk_free_rate.json'dan okunur

# =====================================================
# VERİ KALİTESİ SABİTLERİ
# =====================================================

MAX_TIMESTAMP_GAP_DAYS = 5  # Max zaman aralığı (gün)
MIN_DATA_ROWS = 60  # Minimum veri satırı
STALE_DATA_THRESHOLD_HOURS = 24  # Eski veri eşiği (saat)

# =====================================================
# PORTFÖY SABİTLERİ
# =====================================================

DEFAULT_INITIAL_CAPITAL = 10_000_000.0  # Varsayılan başlangıç sermayesi (TL)
MAX_POSITIONS = 20  # Max pozisyon sayısı
REBALANCE_THRESHOLD_PCT = 5.0  # Rebalance eşik (%)
MAX_TURNOVER = 0.30  # Max turnover (0-1)

# =====================================================
# LOGGING & MONITORING
# =====================================================

MAX_TRADES_HISTORY = 10000  # Trade geçmişi limiti
MAX_CASH_LEDGER = 50000  # Cash ledger limiti
MAX_EQUITY_CURVE = 5000  # Equity curve limiti
MAX_DAILY_PNL = 1000  # Günlük PnL limiti
