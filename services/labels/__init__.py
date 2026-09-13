"""
ALPHA BIST — Labels Service

Modüller:
- generator: Temel forward return etiketleme (y_1d, y_5d, y_10d, y_20d, binary, vs_sector)
- triple_barrier: Triple Barrier etiketleme (López de Prado) + Meta-labeling
- regime_labels: Piyasa rejimi etiketleme (bull/bear/sideways/crisis/high_vol)
- adaptive_labels: Volatilite bazlı adaptif ve çok dönemli etiketleme
- label_quality: Etiket kalite analizi (IC, sınıf dengesi, sinyal-gürültü)
"""

from .adaptive_labels import (
    AdaptiveLabeler,
    AdaptiveLabelResult,
    MultiPeriodLabelResult,
    adaptive_labeler,
)
from .generator import LabelGenerator, LabelResult, label_generator
from .label_quality import (
    LabelQualityAnalyzer,
    LabelQualityReport,
    PortfolioLabelStats,
    label_quality_analyzer,
)
from .regime_labels import (
    RegimeLabel,
    RegimeLabeler,
    RegimeLabelResult,
    VolatilityRegimeLabeler,
    VolatilityRegimeResult,
    regime_labeler,
    volatility_regime_labeler,
)
from .triple_barrier import (
    BarrierHit,
    MetaLabeler,
    MetaLabelResult,
    TripleBarrierLabeler,
    TripleBarrierLabels,
    TripleBarrierResult,
    meta_labeler,
    triple_barrier_labeler,
)

__all__ = [
    # generator
    "LabelGenerator",
    "LabelResult",
    "label_generator",
    # triple_barrier
    "BarrierHit",
    "MetaLabelResult",
    "MetaLabeler",
    "TripleBarrierLabeler",
    "TripleBarrierLabels",
    "TripleBarrierResult",
    "meta_labeler",
    "triple_barrier_labeler",
    # regime_labels
    "RegimeLabel",
    "RegimeLabelResult",
    "RegimeLabeler",
    "VolatilityRegimeLabeler",
    "VolatilityRegimeResult",
    "regime_labeler",
    "volatility_regime_labeler",
    # adaptive_labels
    "AdaptiveLabelResult",
    "AdaptiveLabeler",
    "MultiPeriodLabelResult",
    "adaptive_labeler",
    # label_quality
    "LabelQualityAnalyzer",
    "LabelQualityReport",
    "PortfolioLabelStats",
    "label_quality_analyzer",
]
