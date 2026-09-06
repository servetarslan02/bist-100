"""ALPHA BIST — Veri Modelleri ve Şemalar (Domain Models & Schemas).

Sistem genelinde kullanılan temel Pydantic v2 modelleri, doğrulamalar (invariant validations),
orjson tabanlı hızlı serileştirme ve finansal veri standartları.
"""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Final, Self

import orjson
import polars as pl
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# =====================================================
# Sabitler (Constants)
# =====================================================
DEFAULT_INITIAL_CAPITAL: Final[float] = 100_000.0
DEFAULT_VIX_LEVEL: Final[float] = 20.0
DEFAULT_RSI: Final[float] = 50.0
DEFAULT_RISK_APPETITE: Final[float] = 0.5


class BaseDomainModel(BaseModel):
    """ALPHA BIST temel veri modeli.

    Tüm domain modelleri için ortak konfigürasyon, orjson serileştirme
    ve açıklayıcı string temsili sağlar.
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        populate_by_name=True,
        validate_assignment=True,
    )

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson ile ikili (bytes) JSON formatına serileştirir."""
        return orjson.dumps(self.model_dump(mode="python"), default=str)

    def to_orjson_str(self) -> str:
        """Modeli orjson ile UTF-8 JSON metnine serileştirir."""
        return self.to_orjson_bytes().decode("utf-8")

    @classmethod
    def from_orjson(cls, data: bytes | str | dict[str, Any]) -> Self:
        """orjson verisinden (bayt, string veya sözlük) model örneği üretir (GEMINI.md Kural 5)."""
        if isinstance(data, (bytes, str)):
            parsed = orjson.loads(data)
        else:
            parsed = data
        return cls.model_validate(parsed)

    @classmethod
    def to_polars(cls, models: list[Self]) -> pl.DataFrame:
        """Model listesini yüksek performanslı Polars DataFrame'e dönüştürür (GEMINI.md Kural 2)."""
        if not models:
            return pl.DataFrame()
        return pl.DataFrame([m.model_dump(mode="python") for m in models])

    def __repr__(self) -> str:
        """Sınıf adı ve birincil alanları içeren açıklayıcı temsil."""
        attrs = ", ".join(f"{k}={v!r}" for k, v in list(self.__dict__.items())[:5])
        return f"{self.__class__.__name__}({attrs})"


def models_to_polars(models: list[BaseDomainModel]) -> pl.DataFrame:
    """Temel etki alanı model listesini Polars DataFrame'e dönüştürür (GEMINI.md Kural 2)."""
    if not models:
        return pl.DataFrame()
    return pl.DataFrame([m.model_dump(mode="python") for m in models])


# =====================================================
# Enums
# =====================================================


class Direction(StrEnum):
    """Piyasa pozisyonu veya sinyal yönü (Uzun / Kısa / Nötr)."""

    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class RiskLevel(StrEnum):
    """Portföy ve emir risk seviyesi derecelendirmesi."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SignalStatus(StrEnum):
    """Üretilen bir al-sat sinyalinin yaşam döngüsü durumu."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TRIGGERED = "TRIGGERED"
    CANCELLED = "CANCELLED"


class MarketRegime(StrEnum):
    """Tespit edilen makro ve mikro piyasa rejimi."""

    RISK_ON = "RISK-ON"
    RISK_OFF = "RISK-OFF"
    TRENDING_UP = "TRENDING-UP"
    TRENDING_DOWN = "TRENDING-DOWN"
    RANGE = "RANGE"
    HIGH_VOLATILITY = "HIGH-VOLATILITY"
    LOW_VOLATILITY = "LOW-VOLATILITY"
    PANIC = "PANIC"
    RECOVERY = "RECOVERY"
    MOMENTUM_EXPANSION = "MOMENTUM-EXPANSION"
    MOMENTUM_CONTRACTION = "MOMENTUM-CONTRACTION"


class TimeHorizon(StrEnum):
    """Tahmin ve pozisyon hedef zaman ufku."""

    SHORT = "1-5D"
    MEDIUM = "1-4W"
    LONG = "1-6M"
    VERY_LONG = "6-24M"


# =====================================================
# Piyasa Veri Modelleri (Market Data Models)
# =====================================================


class MarketTick(BaseDomainModel):
    """Anlık tekil işlem (tick) verisi.

    Fiyat, hacim ve kalite metriklerini doğrular.
    """

    instrument_id: int
    ticker: str
    timestamp: datetime
    price: float
    volume: int
    bid: float | None = None
    ask: float | None = None
    source: str = "yfinance"
    quality: float = 1.0

    @field_validator("price")
    @classmethod
    def _validate_price(cls, v: float) -> float:
        """Fiyatın kesinlikle pozitif olduğunu doğrular."""
        if v <= 0:
            raise ValueError(f"Fiyat pozitif olmalıdır, alınan: {v}")
        return v

    @field_validator("volume")
    @classmethod
    def _validate_volume(cls, v: int) -> int:
        """Hacmin negatif olmadığını doğrular."""
        if v < 0:
            raise ValueError(f"Hacim negatif olamaz, alınan: {v}")
        return v

    @field_validator("quality")
    @classmethod
    def _validate_quality(cls, v: float) -> float:
        """Veri kalite skorunun [0, 1] aralığında olduğunu doğrular (nümerik tolerans korumalı)."""
        if -1e-6 <= v < 0.0:
            v = 0.0
        elif 1.0 < v <= 1.0 + 1e-6:
            v = 1.0
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Kalite skoru [0,1] aralığında olmalıdır, alınan: {v}")
        return v


class OHLCV(BaseDomainModel):
    """Bar (mum) verisi.

    Açılış, yüksek, düşük, kapanış fiyatlarının tutarlılığını ve hacmi doğrular.
    """

    instrument_id: int
    ticker: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float | None = None

    @field_validator("open", "high", "low", "close")
    @classmethod
    def _validate_positive_prices(cls, v: float) -> float:
        """OHLC fiyatlarının pozitif olduğunu doğrular."""
        if v <= 0:
            raise ValueError(f"OHLC fiyatı pozitif olmalıdır, alınan: {v}")
        return v

    @field_validator("volume")
    @classmethod
    def _validate_volume(cls, v: int) -> int:
        """Hacmin sıfır veya pozitif olduğunu doğrular."""
        if v < 0:
            raise ValueError(f"Hacim negatif olamaz, alınan: {v}")
        return v

    @model_validator(mode="after")
    def _validate_bar_consistency(self) -> "OHLCV":
        """Yüksek ve düşük fiyatların açılış ve kapanışla mantıksal uyumunu denetler."""
        if self.high < self.low:
            raise ValueError(f"En yüksek fiyat ({self.high}) en düşük fiyattan ({self.low}) küçük olamaz.")
        if self.high < max(self.open, self.close):
            raise ValueError(f"En yüksek fiyat ({self.high}) açılış veya kapanıştan düşük olamaz.")
        if self.low > min(self.open, self.close):
            raise ValueError(f"En düşük fiyat ({self.low}) açılış veya kapanıştan yüksek olamaz.")
        if self.vwap is not None and (self.vwap < self.low * 0.999 or self.vwap > self.high * 1.001):
            raise ValueError(
                f"VWAP ({self.vwap}) barın düşük-yüksek aralığının dışında olamaz ({self.low} - {self.high})."
            )
        return self


class OrderBookSnapshot(BaseDomainModel):
    """Derinlik ve emir defteri (order book) anlık görüntüsü."""

    instrument_id: int
    timestamp: datetime
    bid_prices: list[float]
    bid_volumes: list[int]
    ask_prices: list[float]
    ask_volumes: list[int]
    spread: float
    mid_price: float

    @model_validator(mode="after")
    def _validate_book(self) -> "OrderBookSnapshot":
        """Alış/satış derinlik dizilerinin boyutlarını ve spread tutarlılığını doğrular."""
        if len(self.bid_prices) != len(self.bid_volumes):
            raise ValueError("Alış fiyatları ve hacimleri liste uzunluğu eşleşmelidir.")
        if len(self.ask_prices) != len(self.ask_volumes):
            raise ValueError("Satış fiyatları ve hacimleri liste uzunluğu eşleşmelidir.")
        if self.spread < 0:
            raise ValueError(f"Spread negatif olamaz, alınan: {self.spread}")
        if self.mid_price <= 0:
            raise ValueError(f"Orta fiyat (mid_price) pozitif olmalıdır, alınan: {self.mid_price}")
        if self.bid_prices and self.ask_prices and self.bid_prices[0] > self.ask_prices[0]:
            raise ValueError(
                f"En iyi alış fiyatı ({self.bid_prices[0]}) en iyi satış fiyatından ({self.ask_prices[0]}) büyük olamaz."
            )
        return self


# =====================================================
# Varlık ve Piyasa Durum Modelleri (State Models)
# =====================================================


class AssetState(BaseDomainModel):
    """Tek bir hisse senedinin çok boyutlu anlık analitik durumu.

    Fiyat, hacim, momentum, volatilite, likidite, temel ve ML skorlarını birleştirir.
    """

    instrument_id: int
    ticker: str
    timestamp: datetime

    # Fiyat Metrikleri
    price: float = 0.0
    price_change_pct: float = 0.0
    price_change_1d: float = 0.0
    price_change_5d: float = 0.0
    price_change_20d: float = 0.0

    # Hacim Metrikleri
    volume: int = 0
    volume_avg_20d: int = 0
    volume_zscore: float = 0.0
    volume_ratio: float = 0.0
    unusual_volume: bool = False

    # Momentum Metrikleri
    momentum_5d: float = 0.0
    momentum_20d: float = 0.0
    momentum_60d: float = 0.0
    rate_of_change: float = 0.0

    # Volatilite Metrikleri
    atr_14: float = 0.0
    realized_vol_5d: float = 0.0
    realized_vol_20d: float = 0.0
    volatility_regime: str = "NORMAL"
    volatility_zscore: float = 0.0

    # Teknik İndikatörler
    rsi_14: float = DEFAULT_RSI
    macd_signal: float = 0.0
    adx: float = 0.0
    trend_strength: float = 0.0

    # Göreceli Güç ve Sıralama
    relative_strength_vs_index: float = 0.0
    relative_strength_vs_sector: float = 0.0
    sector_rank: int = 0
    cross_sectional_rank: int = 0

    # Likidite Metrikleri
    bid_ask_spread: float = 0.0
    amihud_illiquidity: float = 0.0
    turnover_rate: float = 0.0

    # Temel Veriler
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    dividend_yield: float | None = None

    # Olay ve Duyarlılık Metrikleri
    kap_sentiment: float = 0.0
    news_sentiment: float = 0.0
    social_sentiment: float = 0.0
    event_impact: float = 0.0
    days_since_last_event: int = 0

    # Makine Öğrenimi Skorları
    anomaly_score: float = 0.0
    spec_score: float = 0.0
    ml_momentum_score: float = 0.0
    ml_breakout_score: float = 0.0
    ml_return_5d: float = 0.0
    ml_return_20d: float = 0.0
    ml_return_60d: float = 0.0
    ml_risk_score: float = 0.0

    # Birleşik Karar Metrikleri
    edge_score: float = 0.0
    confidence: float = 0.0
    risk_level: str = "MEDIUM"

    # Piyasa Rejimi Uyumu
    regime: str = "NORMAL"
    regime_confidence: float = 0.0


class MarketState(BaseDomainModel):
    """Piyasanın genel genişliği ve makro rejim durumu."""

    timestamp: datetime
    regime: MarketRegime = MarketRegime.RANGE
    regime_confidence: float = 0.0
    trend_score: float = 0.0
    breadth_pct: float = 0.0
    dispersion: float = 0.0
    correlation: float = 0.0
    volatility_regime: str = "NORMAL"
    liquidity_level: str = "NORMAL"
    risk_appetite: float = DEFAULT_RISK_APPETITE
    advancing_count: int = 0
    declining_count: int = 0
    unchanged_count: int = 0


class WorldState(BaseDomainModel):
    """Küresel makroekonomik risk ve emtia göstergeleri."""

    timestamp: datetime
    geopolitical_risk: float = 0.0
    global_risk_appetite: float = DEFAULT_RISK_APPETITE
    usd_strength: float = 0.5
    us_rate_pressure: float = 0.5
    commodity_pressure: float = 0.5
    oil_pressure: float = 0.5
    turkey_macro_risk: float = 0.5
    vix_level: float = DEFAULT_VIX_LEVEL
    vix_normalized: float = 0.5
    news_shock: float = 0.0
    emerging_market_risk: float = 0.5

    @field_validator(
        "geopolitical_risk",
        "global_risk_appetite",
        "usd_strength",
        "us_rate_pressure",
        "commodity_pressure",
        "oil_pressure",
        "turkey_macro_risk",
        "vix_normalized",
        "emerging_market_risk",
    )
    @classmethod
    def _validate_01_range(cls, v: float) -> float:
        """[0, 1] sınırları dışındaki değerleri güvenli aralığa sabitler."""
        if not 0.0 <= v <= 1.0:
            return max(0.0, min(1.0, v))
        return v


# =====================================================
# Sinyal Modelleri (Signal Models)
# =====================================================


class EdgeDecomposition(BaseDomainModel):
    """Üretilen sinyalin alfa bileşenlerinin ayrıntılı dökümü."""

    flow_anomaly: float = 0.0
    relative_strength: float = 0.0
    regime_compatibility: float = 0.0
    historical_similarity: float = 0.0
    fundamental_state: float = 0.0
    event_state: float = 0.0
    volatility_risk: float = 0.0
    correlation_risk: float = 0.0
    total: float = 0.0


class Signal(BaseDomainModel):
    """Strateji ve modeller tarafından üretilen al-sat işlem sinyali."""

    id: int | None = None
    instrument_id: int
    ticker: str
    signal_type: str
    direction: Direction
    score: float
    confidence: float
    risk_level: RiskLevel
    horizon: TimeHorizon
    expected_return_pct: float = 0.0
    expected_volatility_pct: float = 0.0
    edge_decomposition: EdgeDecomposition = Field(default_factory=EdgeDecomposition)
    reasoning: str = ""
    model_version: str = ""
    strategy_id: int = 0
    status: SignalStatus = SignalStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, v: float) -> float:
        """Güven skorunun [0, 1] aralığında olduğunu doğrular (nümerik tolerans korumalı)."""
        if -1e-6 <= v < 0.0:
            v = 0.0
        elif 1.0 < v <= 1.0 + 1e-6:
            v = 1.0
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Güven skoru [0,1] aralığında olmalıdır, alınan: {v}")
        return v

    @field_validator("score")
    @classmethod
    def _validate_score(cls, v: float) -> float:
        """Sinyal puanının [0, 100] aralığında olduğunu doğrular (nümerik tolerans korumalı)."""
        if -1e-5 <= v < 0.0:
            v = 0.0
        elif 100.0 < v <= 100.0 + 1e-5:
            v = 100.0
        if not 0.0 <= v <= 100.0:
            raise ValueError(f"Sinyal puanı [0,100] aralığında olmalıdır, alınan: {v}")
        return v

    @field_validator("expected_volatility_pct")
    @classmethod
    def _validate_volatility(cls, v: float) -> float:
        """Beklenen volatilitenin negatif olamayacağını doğrular."""
        if v < 0:
            raise ValueError(f"Beklenen volatilite negatif olamaz, alınan: {v}")
        return v


# =====================================================
# Portföy Modelleri (Portfolio Models)
# =====================================================


class Position(BaseDomainModel):
    """Portföydeki tekil bir hisse senedi pozisyonu."""

    instrument_id: int
    ticker: str
    quantity: int
    avg_cost: float
    current_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    weight_pct: float = 0.0
    entry_date: datetime | None = None

    @field_validator("avg_cost")
    @classmethod
    def _validate_avg_cost(cls, v: float) -> float:
        """Ortalama maliyetin negatif olmadığını doğrular."""
        if v < 0:
            raise ValueError(f"Ortalama maliyet negatif olamaz, alınan: {v}")
        return v

    @field_validator("quantity")
    @classmethod
    def _validate_quantity(cls, v: int) -> int:
        """Pozisyon adedinin negatif olmadığını doğrular."""
        if v < 0:
            raise ValueError(f"Pozisyon adedi negatif olamaz, alınan: {v}")
        return v

    @field_validator("current_price", "market_value")
    @classmethod
    def _validate_non_negative_price(cls, v: float) -> float:
        """Güncel fiyat veya piyasa değerinin negatif olmadığını doğrular."""
        if v < 0:
            raise ValueError(f"Fiyat veya piyasa değeri negatif olamaz, alınan: {v}")
        return v


class Portfolio(BaseDomainModel):
    """Portföyün genel varlık, nakit ve getiri durumu."""

    id: int | None = None
    name: str
    initial_capital: float = DEFAULT_INITIAL_CAPITAL
    current_capital: float = DEFAULT_INITIAL_CAPITAL
    cash_balance: float = DEFAULT_INITIAL_CAPITAL
    invested_value: float = 0.0
    total_pnl: float = 0.0
    total_return_pct: float = 0.0
    positions: list[Position] = Field(default_factory=list)
    is_paper: bool = True

    @field_validator("initial_capital", "current_capital")
    @classmethod
    def _validate_capital(cls, v: float) -> float:
        """Başlangıç ve güncel sermayenin negatif olamayacağını doğrular."""
        if v < 0:
            raise ValueError(f"Sermaye tutarı negatif olamaz, alınan: {v}")
        return v


# =====================================================
# Tahmin ve Sonuç Modelleri (Prediction & Outcome)
# =====================================================


class Prediction(BaseDomainModel):
    """ML modelleri tarafından üretilen ileriye dönük tahmin kaydı."""

    id: int | None = None
    model_version_id: int
    instrument_id: int
    ticker: str
    prediction_date: date
    horizon_days: int
    predicted_direction: Direction
    predicted_return_pct: float
    probability_positive: float
    predicted_volatility_pct: float
    confidence: float
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("confidence", "probability_positive")
    @classmethod
    def _validate_probabilities(cls, v: float) -> float:
        """Olasılık ve güven değerlerinin [0, 1] aralığında olduğunu doğrular (nümerik tolerans korumalı)."""
        if -1e-6 <= v < 0.0:
            v = 0.0
        elif 1.0 < v <= 1.0 + 1e-6:
            v = 1.0
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Olasılık/güven değeri [0,1] aralığında olmalıdır, alınan: {v}")
        return v


class Outcome(BaseDomainModel):
    """Gerçekleşen getiri ve tahmin başarımı karşılaştırması."""

    prediction_id: int
    actual_return_pct: float
    actual_direction: Direction
    actual_volatility_pct: float
    prediction_error: float
    is_correct: bool
    outcome_date: date


# =====================================================
# Simülasyon ve Stres Testi Modelleri
# =====================================================


class ScenarioResult(BaseDomainModel):
    """Belirli bir makro/mikro stres senaryosunun simülasyon sonucu."""

    scenario_name: str
    market_change_pct: float
    portfolio_impact: dict[str, Any]
    probability: float


class SimulationResult(BaseDomainModel):
    """Monte Carlo veya tarihsel senaryo simülasyonu genel raporu."""

    id: int | None = None
    name: str
    simulation_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    scenarios: list[ScenarioResult] = Field(default_factory=list)
    expected_return: float = 0.0
    expected_drawdown: float = 0.0
    var_95: float = 0.0
    cvar_95: float = 0.0
    status: str = "PENDING"


# =====================================================
# Uyarı Modelleri (Alert Models)
# =====================================================


class Alert(BaseDomainModel):
    """Sistem, risk veya anomali uyarı bildirimi."""

    id: int | None = None
    alert_type: str
    severity: RiskLevel
    title: str
    message: str
    instrument_id: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    acknowledged: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


__all__: Final[list[str]] = [
    "DEFAULT_INITIAL_CAPITAL",
    "DEFAULT_RISK_APPETITE",
    "DEFAULT_RSI",
    "DEFAULT_VIX_LEVEL",
    "Alert",
    "AssetState",
    "BaseDomainModel",
    "Direction",
    "EdgeDecomposition",
    "MarketRegime",
    "MarketState",
    "MarketTick",
    "OHLCV",
    "OrderBookSnapshot",
    "Outcome",
    "Portfolio",
    "Position",
    "Prediction",
    "RiskLevel",
    "ScenarioResult",
    "Signal",
    "SignalStatus",
    "SimulationResult",
    "TimeHorizon",
    "WorldState",
    "models_to_polars",
]
