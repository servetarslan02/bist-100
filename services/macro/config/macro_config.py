"""
ALPHA BIST — Macro System Configuration

Tüm eşikler, parametreler ve konfigürasyonlar tek merkezden yönetilir.
Hardcoded değerler YASAKTIR — hepsi buradan okunur.
"""

from pydantic import BaseModel, Field
from typing import Dict
import os


class SurpriseConfig(BaseModel):
    """Macro surprise ayarları."""
    small_threshold: float = Field(default=0.05, description="Surprise küçük eşik (< %5)")
    medium_threshold: float = Field(default=0.10, description="Surprise orta eşik (%5-10)")
    large_threshold: float = Field(default=0.15, description="Surprise büyük eşik (> %10)")
    decay_half_life_days: int = Field(default=5, description="Surprise decay half-life (gün)")
    max_history_days: int = Field(default=365, description="Maksimum surprise geçmişi (gün)")
    expectation_cache_ttl_hours: int = Field(default=24, description="Beklenti cache TTL (saat)")


class RegimeConfig(BaseModel):
    """Macro regime detection ayarları."""
    scoring_window_days: int = Field(default=20, description="Rejim skor penceresi (gün)")
    transition_smoothing: int = Field(default=3, description="Rejim geçiş smoothing (gün)")
    min_regime_duration_days: int = Field(default=5, description="Minimum rejim süresi (gün)")
    confidence_threshold: float = Field(default=0.3, description="Rejim confidence eşiği")

    # Rejim skor ağırlıkları
    expansion_weight: float = Field(default=1.0)
    contraction_weight: float = Field(default=1.0)
    stagflation_weight: float = Field(default=1.0)
    reflation_weight: float = Field(default=1.0)
    risk_on_weight: float = Field(default=1.0)
    risk_off_weight: float = Field(default=1.0)


class SensitivityConfig(BaseModel):
    """Dynamic sensitivity ayarları."""
    rolling_window_days: int = Field(default=60, description="Rolling korelasyon penceresi (gün)")
    min_samples: int = Field(default=20, description="Minimum sample sayısı")
    significance_p_value: float = Field(default=0.05, description="Korelasyon anlamlılık p-value")
    sensitivity_update_interval_hours: int = Field(default=24, description="Sensitivity güncelleme aralığı (saat)")


class StressTestConfig(BaseModel):
    """Stres testi ayarları."""
    max_scenario_shock_pct: float = Field(default=0.50, description="Maksimum senaryo şoku (%)")
    breaking_point_threshold_pct: float = Field(default=-0.10, description="Breaking point eşik (%)")
    custom_scenario_max_shocks: int = Field(default=10, description="Maksimum özel senaryo şoku sayısı")

    # Önceden tanımlı senaryolar
    predefined_scenarios: Dict[str, Dict[str, float]] = Field(default={
        "USDTRY_10_PCT": {"usdtry_change": 0.10},
        "TCMB_RATE_HIKE_500BP": {"interest_rate_change": 0.05},
        "VIX_SPIKE_50_PCT": {"vix_change": 0.50},
        "OIL_SHOCK_20_PCT": {"oil_change": 0.20},
        "GLOBAL_RISK_OFF": {"global_change": -0.10, "usdtry_change": 0.05},
        "INFLATION_HIGH": {"inflation_change": 0.05},
        "BIST_CRASH_10_PCT": {"bist_change": -0.10},
    })


class CorrelationConfig(BaseModel):
    """Correlation tracking ayarları."""
    window_days: int = Field(default=60, description="Korelasyon penceresi (gün)")
    min_samples: int = Field(default=20, description="Minimum sample sayısı")
    breakdown_threshold: float = Field(default=0.3, description="Korelasyon bozulma eşiği")
    update_interval_hours: int = Field(default=24, description="Güncelleme aralığı (saat)")

    # Takip edilen korelasyon çiftleri
    tracked_pairs: list = Field(default=[
        ("usdtry", "gold"),
        ("interest_rate", "inflation"),
        ("vix", "bist100"),
        ("oil", "energy_sector"),
        ("sp500", "bist100"),
        ("cds", "usdtry"),
    ])


class CalendarConfig(BaseModel):
    """Calendar integration ayarları."""
    pre_event_alert_days: int = Field(default=3, description="Olay öncesi uyarı (gün)")
    post_event_analysis_hours: int = Field(default=24, description="Olay sonrası analiz (saat)")
    auto_trigger_enabled: bool = Field(default=True, description="Otomatik tetikleme aktif")


class DecayConfig(BaseModel):
    """Decay model ayarları."""
    default_half_life_days: int = Field(default=5, description="Varsayılan half-life (gün)")

    # Şok türüne göre half-life
    half_life_by_shock_type: Dict[str, int] = Field(default={
        "monetary_policy": 10,      # Para politikası sürprizi
        "inflation_surprise": 7,    # Enflasyon sürprizi
        "fx_shock": 5,             # Kur şoku
        "global_risk_off": 3,       # Global risk-off
        "commodity_shock": 5,       # Emtia şoku
        "geopolitical": 14,         # Jeopolitik şok
    })


class HistoricalStoreConfig(BaseModel):
    """Historical data store ayarları."""
    storage_backend: str = Field(default="json", description="Depolama backend (json/sqlite)")
    max_history_days: int = Field(default=1825, description="Maksimum geçmiş (5 yıl)")
    backfill_enabled: bool = Field(default=True, description="Backfill aktif")
    pit_enabled: bool = Field(default=True, description="Point-in-time aktif")


class MacroConfig(BaseModel):
    """Ana Macro System konfigürasyonu."""

    # Alt modül konfigürasyonları
    surprise: SurpriseConfig = Field(default_factory=SurpriseConfig)
    regime: RegimeConfig = Field(default_factory=RegimeConfig)
    sensitivity: SensitivityConfig = Field(default_factory=SensitivityConfig)
    stress_test: StressTestConfig = Field(default_factory=StressTestConfig)
    correlation: CorrelationConfig = Field(default_factory=CorrelationConfig)
    calendar: CalendarConfig = Field(default_factory=CalendarConfig)
    decay: DecayConfig = Field(default_factory=DecayConfig)
    historical_store: HistoricalStoreConfig = Field(default_factory=HistoricalStoreConfig)

    # Genel ayarlar
    log_level: str = Field(default="INFO", description="Log seviyesi")
    state_persistence_path: str = Field(
        default="data/macro_state.json",
        description="Macro state dosya yolu"
    )
    enable_event_bus: bool = Field(default=True, description="Event bus aktif mi")
    enable_dynamic_sensitivity: bool = Field(default=True, description="Dynamic sensitivity aktif mi")

    @classmethod
    def from_env(cls) -> "MacroConfig":
        """Ortam değişkenlerinden override."""
        overrides = {}
        prefix = "MACRO_"
        for key, value in os.environ.items():
            if key.startswith(prefix):
                parts = key[len(prefix):].lower().split("_")
                if len(parts) >= 2:
                    section = parts[0]
                    field = "_".join(parts[1:])
                    if section in cls.model_fields:
                        overrides.setdefault(section, {})[field] = value
        return cls(**overrides)


# Singleton
macro_config = MacroConfig()
