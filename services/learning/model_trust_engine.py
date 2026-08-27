"""ALPHA BIST — Model Trust & Reliability Engine v2.0

Modellerin geçmiş performansından dinamik güvenilirlik puanı (Reliability / Trust Score) üretir:
- Rolling accuracy & hit rate
- Risk-adjusted return (Sharpe)
- Kalibrasyon (1 - Brier)
- Örneklem güveni (Shrinkage to prior)
- Piyasa rejimi uyumu (Regime-specific competence)
- İstatistiksel anlamlılık (t-stat)
"""

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog

from .model_performance_engine import PerformanceMetrics

logger = structlog.get_logger()


@dataclass
class ModelTrustScore:
    """Model güvenilirlik ve adaptif ağırlıklandırma puanı."""
    model_id: str
    model_version: str
    sample_size: int
    reliability_score: float  # [0.0, 1.0]
    confidence_shrinkage: float  # [0.0, 1.0] örneklem büyüklüğü güveni
    accuracy_score: float
    sharpe_score: float
    calibration_score: float
    regime_score: float
    statistical_significance_p: float
    recommended_fusion_weight: float
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class ModelTrustEngine:
    """Modeller için dinamik güvenilirlik skoru ve adaptif ağırlık hesaplayıcı."""

    def __init__(
        self,
        min_samples_threshold: int = 30,
        prior_trust: float = 0.50,
        weight_min: float = 0.05,
        weight_max: float = 0.35,
    ):
        self.min_samples_threshold = min_samples_threshold
        self.prior_trust = prior_trust
        self.weight_min = weight_min
        self.weight_max = weight_max

    def compute_trust_score(
        self,
        metrics: PerformanceMetrics,
        current_regime: str = "BULL_MOMENTUM",
    ) -> ModelTrustScore:
        """Metriklerden dinamik güvenilirlik skoru hesaplar."""
        n = metrics.evaluated_samples

        # 1. Örneklem Güven Çarpanı (Shrinkage Factor)
        # N=0 ise 0.0, N=30 ise ~0.63, N=100 ise ~0.96
        k_samples = float(self.min_samples_threshold)
        shrinkage = float(1.0 - math.exp(-max(0, n) / k_samples)) if n > 0 else 0.0

        # 2. Doğruluk Bileşeni (Accuracy / Hit Rate Score)
        # 0.50 doğruluk -> 0.0 puan, 0.70 doğruluk -> 1.0 puan
        acc = metrics.direction_accuracy
        acc_score = max(0.0, min(1.0, (acc - 0.40) / 0.30))

        # 3. Sharpe Bileşeni (Risk-Adjusted Return)
        # Sharpe <= 0 -> 0.0, Sharpe >= 2.5 -> 1.0
        sharpe = metrics.annualized_sharpe
        sharpe_score = max(0.0, min(1.0, (sharpe + 0.5) / 3.0))

        # 4. Kalibrasyon Bileşeni (Brier Score: 0 en iyi, 0.25 rastgele)
        # Brier 0.10 -> 0.90 puan, Brier 0.25 -> 0.50 puan
        brier = metrics.brier_score
        calibration_score = max(0.0, min(1.0, 1.0 - (brier * 2.0)))

        # 5. Rejim Uyumu Bileşeni
        regime_stats = metrics.regime_breakdown.get(current_regime, {})
        if regime_stats and regime_stats.get("samples", 0) >= 5:
            regime_acc = regime_stats.get("accuracy", acc)
            regime_score = max(0.0, min(1.0, (regime_acc - 0.40) / 0.30))
        else:
            regime_score = acc_score

        # 6. Ham Güvenilirlik Formülü
        raw_trust = (
            0.35 * acc_score +
            0.25 * sharpe_score +
            0.20 * calibration_score +
            0.20 * regime_score
        )

        # 7. Shrinkage Uygulama (Yetersiz örneklem durumunda Prior'a çeker)
        # S_rel = (1 - shrinkage) * prior + shrinkage * raw_trust
        final_trust = (1.0 - shrinkage) * self.prior_trust + shrinkage * raw_trust
        final_trust = max(0.05, min(0.95, final_trust))

        # 8. İstatistiksel Anlamlılık (Basit t-test p-değeri yaklaşımı)
        # H0: p = 0.5 (yazı tura)
        if n >= 10:
            z = (acc - 0.50) / math.sqrt(0.25 / n)
            p_val = max(0.001, min(1.0, 1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2)))))
        else:
            p_val = 0.50

        return ModelTrustScore(
            model_id=metrics.model_id,
            model_version=metrics.model_version,
            sample_size=n,
            reliability_score=round(final_trust, 4),
            confidence_shrinkage=round(shrinkage, 4),
            accuracy_score=round(acc_score, 4),
            sharpe_score=round(sharpe_score, 4),
            calibration_score=round(calibration_score, 4),
            regime_score=round(regime_score, 4),
            statistical_significance_p=round(p_val, 4),
            recommended_fusion_weight=0.0,  # Batch normalization sırasında doldurulur
        )

    def calculate_ensemble_weights(
        self,
        trust_scores: list[ModelTrustScore],
    ) -> dict[str, float]:
        """Tüm modellerin trust skorlarını normalize ederek nihai Signal Fusion ağırlıklarını üretir."""
        if not trust_scores:
            return {}

        n = len(trust_scores)
        # Eğer model sayısı az ise (n < 1/weight_max), max ağırlık sınırı doğal olarak 1.0 / n olur
        eff_max = max(self.weight_max, 1.0 / n)
        eff_min = min(self.weight_min, 1.0 / (2 * n))

        total_trust = sum(ts.reliability_score for ts in trust_scores)
        if total_trust <= 1e-6:
            equal_w = 1.0 / n
            return {ts.model_id: round(equal_w, 4) for ts in trust_scores}

        # Başlangıç ağırlıkları
        weights = {ts.model_id: (ts.reliability_score / total_trust) for ts in trust_scores}

        # İteratif Sıkıştırma ve Yeniden Dağıtım (Iterative Clip & Redistribute)
        for _ in range(10):
            clipped = False
            excess = 0.0
            free_keys = []

            for k, w in weights.items():
                if w > eff_max:
                    excess += (w - eff_max)
                    weights[k] = eff_max
                    clipped = True
                elif w < eff_min:
                    excess -= (eff_min - w)
                    weights[k] = eff_min
                    clipped = True
                else:
                    free_keys.append(k)

            if not clipped or not free_keys:
                break

            # Kalan fazlalığı/eksiği serbest modellere dağıt
            share = excess / len(free_keys)
            for k in free_keys:
                weights[k] += share

        # Son normalizasyon
        tot = sum(weights.values())
        final_weights = {k: round(v / tot, 4) for k, v in weights.items()}

        # ModelTrustScore nesnelerine de yaz
        for ts in trust_scores:
            ts.recommended_fusion_weight = final_weights.get(ts.model_id, 0.0)

        return final_weights
