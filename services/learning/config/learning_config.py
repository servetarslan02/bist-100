"""
ALPHA BIST — Learning System Configuration

Tüm eşikler, parametreler ve konfigürasyonlar tek merkezden yönetilir.
Hardcoded değerler YASAKTIR — hepsi buradan okunur.
"""

from pydantic import BaseModel, Field
import os


class CalibrationConfig(BaseModel):
    """Calibration ayarları."""
    check_interval_days: int = Field(default=7, description="Calibration kontrol sıklığı (gün)")
    brier_threshold: float = Field(default=0.25, description="Brier score eşik — üstü kötü")
    ece_threshold: float = Field(default=0.10, description="Expected Calibration Error eşik")
    overconfidence_threshold: float = Field(default=0.15, description="Overconfidence miscalibration eşik")
    min_samples: int = Field(default=30, description="Minimum calibration sample sayısı")
    n_bins: int = Field(default=10, description="Calibration bin sayısı")
    platt_scaling_enabled: bool = Field(default=True, description="Platt scaling aktif mi")


class DriftConfig(BaseModel):
    """Drift detection ayarları."""
    check_interval_days: int = Field(default=1, description="Drift kontrol sıklığı (gün)")

    # PSI
    psi_warning: float = Field(default=0.1, description="PSI uyarı eşiği")
    psi_alert: float = Field(default=0.2, description="PSI alarm eşiği")
    psi_critical: float = Field(default=0.5, description="PSI kritik eşiği")

    # KS Test
    ks_p_threshold: float = Field(default=0.05, description="KS test p-value eşiği")

    # Z-score
    zscore_warning: float = Field(default=2.5, description="Z-score uyarı eşiği")
    zscore_critical: float = Field(default=3.5, description="Z-score kritik eşiği")

    # Page-Hinkley
    ph_threshold: float = Field(default=0.5, description="Page-Hinkley eşik katsayısı")
    ph_delta: float = Field(default=0.005, description="Page-Hinkley delta")

    # ADWIN
    adwin_delta: float = Field(default=0.002, description="ADWIN delta")

    # Concept drift
    concept_drift_accuracy_drop: float = Field(default=0.10, description="Accuracy drop oranı — concept drift")
    concept_drift_window: int = Field(default=50, description="Concept drift pencere boyutu")

    # Minimum veri
    min_samples: int = Field(default=100, description="Minimum sample sayısı")


class RetrainConfig(BaseModel):
    """Retrain ayarları."""
    sharpe_threshold: float = Field(default=0.3, description="Sharpe retrain eşiği")
    winrate_threshold: float = Field(default=0.45, description="Win rate retrain eşiği")
    ic_threshold: float = Field(default=0.02, description="IC retrain eşiği")
    max_interval_days: int = Field(default=14, description="Maksimum retrain aralığı (gün)")
    min_interval_days: int = Field(default=3, description="Minimum retrain aralığı (gün)")
    min_samples: int = Field(default=500, description="Minimum training sample sayısı")
    performance_window: int = Field(default=21, description="Performans penceresi (gün)")

    # Walk-forward
    wf_train_size: int = Field(default=252, description="Walk-forward train boyutu (gün)")
    wf_test_size: int = Field(default=21, description="Walk-forward test boyutu (gün)")
    wf_purge_size: int = Field(default=5, description="Purge gap (gün)")
    wf_embargo_size: int = Field(default=5, description="Embargo gap (gün)")
    wf_step_size: int = Field(default=21, description="Step boyutu (gün)")
    wf_min_correlation: float = Field(default=0.05, description="Minimum WF korelasyon")
    wf_min_direction_accuracy: float = Field(default=52.0, description="Minimum WF yön doğruluğu (%)")


class ShadowConfig(BaseModel):
    """Shadow mode ayarları."""
    duration_days: int = Field(default=21, description="Shadow mode süresi (gün)")
    min_predictions: int = Field(default=50, description="Minimum prediction sayısı")
    promote_threshold_pct: float = Field(default=10.0, description="Promote için min iyileşme (%)")
    significance_p: float = Field(default=0.05, description="İstatistiksel anlamlılık p-value")
    canary_allocation_pct: float = Field(default=0.10, description="Canary deployment pozisyon oranı (%)")


class FeatureImportanceConfig(BaseModel):
    """Feature importance ayarları."""
    track_interval_days: int = Field(default=1, description="Tracking sıklığı (gün)")
    trend_window_days: int = Field(default=30, description="Trend analizi penceresi (gün)")
    min_importance_threshold: float = Field(default=0.001, description="Min importance eşiği")
    shap_sample_size: int = Field(default=1000, description="SHAP hesaplama sample boyutu")


class ModelRegistryConfig(BaseModel):
    """Model registry ayarları."""
    max_versions: int = Field(default=20, description="Maksimum model versiyon sayısı")
    auto_cleanup: bool = Field(default=True, description="Eski versiyonları otomatik temizle")
    archive_retired: bool = Field(default=True, description="Retired modelleri arşivle")


class MetaLearningConfig(BaseModel):
    """Meta-learning ayarları."""
    regime_performance_window: int = Field(default=10, description="Rejim performans penceresi")
    decay_trend_threshold: float = Field(default=-0.001, description="Decay trend eşiği")
    ensemble_min_models: int = Field(default=2, description="Minimum ensemble model sayısı")


class HealthConfig(BaseModel):
    """Health monitoring ayarları."""
    check_interval_minutes: int = Field(default=60, description="Health check sıklığı (dakika)")
    max_healing_attempts: int = Field(default=3, description="Maksimum healing deneme sayısı")
    healing_backoff_seconds: int = Field(default=60, description="Healing backoff süresi (saniye)")


class LearningSettings(BaseModel):
    """Ana Learning System konfigürasyonu."""

    # Alt modül konfigürasyonları
    calibration: CalibrationConfig = Field(default_factory=CalibrationConfig)
    drift: DriftConfig = Field(default_factory=DriftConfig)
    retrain: RetrainConfig = Field(default_factory=RetrainConfig)
    shadow: ShadowConfig = Field(default_factory=ShadowConfig)
    feature_importance: FeatureImportanceConfig = Field(default_factory=FeatureImportanceConfig)
    model_registry: ModelRegistryConfig = Field(default_factory=ModelRegistryConfig)
    meta_learning: MetaLearningConfig = Field(default_factory=MetaLearningConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)

    # Genel ayarlar
    log_level: str = Field(default="INFO", description="Log seviyesi")
    state_persistence_path: str = Field(
        default="data/learning_state.json",
        description="Learning state dosya yolu"
    )
    enable_event_bus: bool = Field(default=True, description="Event bus aktif mi")
    enable_self_healing: bool = Field(default=True, description="Self-healing aktif mi")

    @classmethod
    def from_env(cls) -> "LearningSettings":
        """Ortam değişkenlerinden override."""
        overrides = {}
        # Örnek: LEARNING_DRIFT_PSI_CRITICAL=0.6
        prefix = "LEARNING_"
        for key, value in os.environ.items():
            if key.startswith(prefix):
                # Nested config path oluştur
                parts = key[len(prefix):].lower().split("_")
                if len(parts) >= 2:
                    section = parts[0]
                    field = "_".join(parts[1:])
                    if section in cls.model_fields:
                        overrides.setdefault(section, {})[field] = value
        return cls(**overrides)


# Singleton
learning_settings = LearningSettings()
