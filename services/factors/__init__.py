"""ALPHA BIST — Factor Investing Package (Nihai).

Fama-French, Piotroski, Beneish, Altman + BIST-specific faktörler.
14 modül, çok faktörlü sıralama, rejime göre rotasyon.

Modüller:
    - piotroski: Piotroski F-Score (9 kriter, ağırlıklı)
    - beneish: Beneish M-Score (manipülasyon tespiti)
    - altman: Altman Z-Score (iflas tahmini, Türkiye düzeltmeli)
    - fama_french: Fama-French factor scores (8 faktör)
    - bist_anomalies: BIST'e özgü 8 anomaly/faktör
    - ranking: Çok faktörlü risk-adjusted sıralama
    - performance: Faktör performans takibi (10+ metrik)
    - factor_correlation: Faktörler arası korelasyon
    - factor_rotation: Rejime göre faktör rotasyonu
    - factor_time_series: Zaman serisi analizi
"""

from .piotroski import calculate_f_score, calculate_f_score_simple
from .beneish import calculate_m_score, calculate_m_score_simple
from .altman import calculate_z_score, calculate_z_score_simple
from .fama_french import (
    calculate_factor_scores,
    calculate_factor_scores_batch,
    get_factor_weights,
    FACTOR_DEFINITIONS,
)
from .bist_anomalies import (
    calculate_bist_anomalies,
    calculate_anomaly_score,
    calculate_bist_anomalies_batch,
    ANOMALY_DEFINITIONS,
)
from .ranking import rank_stocks, get_top_n, get_bottom_n, DEFAULT_WEIGHTS, REGIME_WEIGHTS
from .performance import track_factor_performance, track_factor_performance_batch
from .factor_correlation import calculate_factor_correlation, calculate_rolling_correlation
from .factor_rotation import detect_regime, get_rotation_weights, calculate_rotation_signal, REGIME_FACTOR_MAP
from .factor_time_series import (
    calculate_factor_returns,
    analyze_factor_trend,
    calculate_factor_momentum,
    detect_seasonality,
)

__all__ = [
    # Piotroski
    "calculate_f_score",
    "calculate_f_score_simple",
    # Beneish
    "calculate_m_score",
    "calculate_m_score_simple",
    # Altman
    "calculate_z_score",
    "calculate_z_score_simple",
    # Fama-French
    "calculate_factor_scores",
    "calculate_factor_scores_batch",
    "get_factor_weights",
    "FACTOR_DEFINITIONS",
    # BIST Anomalies
    "calculate_bist_anomalies",
    "calculate_anomaly_score",
    "calculate_bist_anomalies_batch",
    "ANOMALY_DEFINITIONS",
    # Ranking
    "rank_stocks",
    "get_top_n",
    "get_bottom_n",
    "DEFAULT_WEIGHTS",
    "REGIME_WEIGHTS",
    # Performance
    "track_factor_performance",
    "track_factor_performance_batch",
    # Correlation
    "calculate_factor_correlation",
    "calculate_rolling_correlation",
    # Rotation
    "detect_regime",
    "get_rotation_weights",
    "calculate_rotation_signal",
    "REGIME_FACTOR_MAP",
    # Time Series
    "calculate_factor_returns",
    "analyze_factor_trend",
    "calculate_factor_momentum",
    "detect_seasonality",
]
