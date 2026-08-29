"""
ALPHA BIST — Signal Fusion & Decision Integration v1.0

Tüm sinyalleri birleştirir:
- Signal Fusion (çoklu kaynak birleştirme)
- Conflict Detection (çelişki tespiti)
- Explainability (açıklanabilirlik)
- Self-Check (sonuç sorgulama)

FAZ 9: Decision & Risk Engine Integration
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class FusedSignal:
    """Birleştirilmiş sinyal."""

    ticker: str
    timestamp: datetime

    # Bileşen sinyalleri
    technical_direction: str = "NEUTRAL"
    fundamental_direction: str = "NEUTRAL"
    momentum_direction: str = "NEUTRAL"
    sentiment_direction: str = "NEUTRAL"
    macro_direction: str = "NEUTRAL"
    valuation_direction: str = "NEUTRAL"
    ai_direction: str = "NEUTRAL"
    monte_carlo_direction: str = "NEUTRAL"

    # Bileşen skorları
    technical_score: float = 50.0
    fundamental_score: float = 50.0
    momentum_score: float = 50.0
    sentiment_score: float = 50.0
    macro_score: float = 50.0
    valuation_score: float = 50.0
    ai_score: float = 50.0
    monte_carlo_score: float = 50.0
    opportunity_score: float = 50.0

    # Birleştirilmiş sonuç
    fused_direction: str = "NEUTRAL"
    fused_confidence: float = 0.0
    fused_score: float = 50.0

    # Çelişki
    has_conflict: bool = False
    conflict_details: list[str] = field(default_factory=list)

    # Açıklama
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    invalidation: str = ""

    # Self-check
    self_check_passed: bool = True
    self_check_warnings: list[str] = field(default_factory=list)


class SignalFusionEngine:
    """Sinyal birleştirme motoru."""

    # Varsayılan temel ağırlıklar
    DEFAULT_WEIGHTS = {
        "technical": 0.13,
        "fundamental": 0.13,
        "momentum": 0.16,
        "sentiment": 0.09,
        "news": 0.04,
        "macro": 0.09,
        "valuation": 0.12,
        "ai": 0.09,
        "spec": 0.05,  # SPEC engine entegrasyonu
        "monte_carlo": 0.10,  # Monte Carlo simülasyon sinyali
    }

    REGIME_WEIGHT_OVERRIDES = {
        # Boğa: Momentum ve teknik öne çıkar, AI destekleyici rolde
        "BULL": {"momentum": 0.22, "technical": 0.18, "sentiment": 0.05, "ai": 0.12},
        "BULL_ACCELERATING": {"momentum": 0.22, "technical": 0.18, "sentiment": 0.05, "ai": 0.12},
        "BULL_NORMAL": {"momentum": 0.22, "technical": 0.18, "sentiment": 0.05, "ai": 0.12},
        "TRENDING-UP": {"momentum": 0.22, "technical": 0.18, "sentiment": 0.05, "ai": 0.12},
        # Ayı: Makro ve teknik öne çıkar, AI negatif sinyalleri ayırt eder
        "BEAR": {"momentum": 0.20, "technical": 0.18, "macro": 0.14, "ai": 0.14},
        "BEAR_NORMAL": {"momentum": 0.20, "technical": 0.18, "macro": 0.14, "ai": 0.14},
        "BEAR_CRASH": {"macro": 0.22, "valuation": 0.14, "ai": 0.18},
        "TRENDING-DOWN": {"momentum": 0.20, "technical": 0.18, "macro": 0.14, "ai": 0.14},
        # Yüksek volatilite: AI bağlamsal analizi kritik
        "HIGH_VOL": {"macro": 0.18, "valuation": 0.18, "momentum": 0.08, "ai": 0.18},
        "HIGH-VOLATILITY": {"macro": 0.18, "valuation": 0.18, "momentum": 0.08, "ai": 0.18},
        # Risk-On/Off: Makro haberler baskın, LLM haberleri yorumlar
        "RISK-ON": {"momentum": 0.22, "sentiment": 0.13, "ai": 0.15},
        "RISK-OFF": {"macro": 0.18, "valuation": 0.18, "fundamental": 0.16, "ai": 0.20},
        # Panik/Kriz: LLM en kritik rolde — teknik göstergeler gecikmeli!
        "PANIC": {"macro": 0.20, "valuation": 0.13, "ai": 0.25},
        "CRISIS": {"macro": 0.20, "valuation": 0.13, "ai": 0.25},
        "GEOPOLITICAL_CRISIS": {"macro": 0.15, "valuation": 0.10, "ai": 0.30},
        # Toparlanma: Temel analiz ve AI birlikte
        "RECOVERY": {"fundamental": 0.22, "valuation": 0.18, "sentiment": 0.12, "ai": 0.15},
    }

    def __init__(self):
        """Otomatik eklendi."""
        self._adaptive_weights: dict[str, float] = {}
        self._restore_weights()

    def _restore_weights(self) -> Any:
        """Restart sonrası ağırlıkları SQLite'dan geri yükle."""
        try:
            from services.core.state_store import state_store

            saved = state_store.load_fusion_weights()
            if saved:
                self._adaptive_weights = saved
                logger.info("Fusion weights restored from SQLite", weights=len(saved))
        except Exception as e:
            logger.debug("Fusion weights restore skipped", error=str(e))

    def _persist_weights(self) -> Any:
        """Ağırlıkları SQLite'a kaydet."""
        try:
            from services.core.state_store import state_store

            if self._adaptive_weights:
                state_store.save_fusion_weights(self._adaptive_weights)
        except Exception:
            logger.warning("Caught Exception in _persist_weights", exc_info=True)

    def set_adaptive_weights(self, weights: dict[str, float]) -> Any:
        """Model Learning sisteminden gelen dinamik güvenilirlik ağırlıklarını kaydeder."""
        if not weights:
            return
        # Sınırla ve normalize et
        valid = {}
        for k, v in weights.items():
            valid[k] = max(0.05, min(0.35, float(v)))
        tot = sum(valid.values())
        if tot > 0:
            self._adaptive_weights = {k: round(v / tot, 4) for k, v in valid.items()}
            self._persist_weights()

    def get_current_weights(self, market_regime: str = "RANGE") -> dict[str, float]:
        """Aktif ağırlıkları getirir (Adaptif + Rejim harmanı)."""
        base = dict(self._adaptive_weights) if self._adaptive_weights else dict(self.DEFAULT_WEIGHTS)
        if market_regime in self.REGIME_WEIGHT_OVERRIDES:
            for k, v in self.REGIME_WEIGHT_OVERRIDES[market_regime].items():
                base[k] = (base.get(k, 0.10) * 0.5) + (v * 0.5)
        tot = sum(base.values())
        return {k: round(v / tot, 4) for k, v in base.items()} if tot > 0 else self.DEFAULT_WEIGHTS

    def fuse_signals(
        self,
        ticker: str,
        signals: dict[str, Any],
        market_regime: str = "RANGE",
    ) -> FusedSignal:
        """Tüm sinyalleri birleştir."""
        result = FusedSignal(
            ticker=ticker,
            timestamp=datetime.now(UTC),
        )

        # Bileşen yönleri ve skorları
        for component in [
            "technical",
            "fundamental",
            "momentum",
            "sentiment",
            "news",
            "macro",
            "valuation",
            "ai",
            "spec",
            "monte_carlo",
        ]:
            comp_data = signals.get(component, {})
            setattr(result, f"{component}_direction", comp_data.get("direction", "NEUTRAL"))
            setattr(result, f"{component}_score", comp_data.get("score", 50))

        result.opportunity_score = signals.get("opportunity", {}).get("score", 50)

        # Ağırlıklı skor — dinamik adaptif öğrenilen ağırlıkları uygula
        weights = self.get_current_weights(market_regime)
        weighted_score = 0.0
        total_weight = 0.0

        for component, weight in weights.items():
            score = getattr(result, f"{component}_score", 50)
            weighted_score += score * weight
            total_weight += weight

        result.fused_score = weighted_score / total_weight if total_weight > 0 else 50

        # Yön belirleme (çoğunluk + ağırlık)
        # Düzeltme (v2.1): effective_weight = weight * (score/100) yerine
        # sadece weight kullanılıyor. Neden: score/100 çarpanı yüksek skorlu
        # sinyallerin yön kararını domine etmesine neden oluyordu.
        # Örn: momentum_score=80, direction=LONG → 0.20 * 0.80 = 0.16
        #       fundamental_score=40, direction=SHORT → 0.15 * 0.40 = 0.06
        # momentum 2.67x daha ağır basıyor, oysa ağırlıklar 0.20 vs 0.15.
        # Çözüm: Yön belirlemede sadece ağırlık kullan, skor sadece fused_score'a yansır.
        long_weight = 0.0
        short_weight = 0.0

        for component, weight in weights.items():
            direction = getattr(result, f"{component}_direction", "NEUTRAL")

            if direction == "LONG":
                long_weight += weight
            elif direction == "SHORT":
                short_weight += weight

        if long_weight > short_weight * 1.3:
            result.fused_direction = "LONG"
        elif short_weight > long_weight * 1.3:
            result.fused_direction = "SHORT"
        else:
            result.fused_direction = "NEUTRAL"

        # Confidence
        direction_agreement = abs(long_weight - short_weight) / max(long_weight + short_weight, 0.01)
        result.fused_confidence = min(direction_agreement, 0.95)

        # Çelişki tespiti
        result.has_conflict, result.conflict_details = self._detect_conflicts(signals)

        # Açıklama
        result.reasons = self._generate_reasons(result, signals)
        result.risks = self._generate_risks(result, signals)
        result.invalidation = self._generate_invalidation(result, signals)

        # Self-check
        result.self_check_passed, result.self_check_warnings = self._self_check(result, signals)

        return result

    def _detect_conflicts(self, signals: dict) -> tuple[bool, list[str]]:
        """Sinyal çakışması tespit et."""
        conflicts = []

        directions = {}
        for component in [
            "technical",
            "fundamental",
            "momentum",
            "sentiment",
            "news",
            "macro",
            "valuation",
            "ai",
            "monte_carlo",
        ]:
            comp_data = signals.get(component, {})
            direction = comp_data.get("direction", "NEUTRAL")
            if direction != "NEUTRAL":
                directions[component] = direction

        # LONG ve SHORT karışımı var mı?
        long_components = [k for k, v in directions.items() if v == "LONG"]
        short_components = [k for k, v in directions.items() if v == "SHORT"]

        if long_components and short_components:
            conflicts.append(f"Çelişki: {', '.join(long_components)} LONG vs {', '.join(short_components)} SHORT")

        # Skor çakışması (yüksek skor ama negatif yön)
        for component in ["technical", "fundamental", "momentum"]:
            comp_data = signals.get(component, {})
            score = comp_data.get("score", 50)
            direction = comp_data.get("direction", "NEUTRAL")
            if score > 70 and direction == "SHORT":
                conflicts.append(f"{component} yüksek skor ({score}) ama SHORT yön")
            elif score < 30 and direction == "LONG":
                conflicts.append(f"{component} düşük skor ({score}) ama LONG yön")

        return len(conflicts) > 0, conflicts

    def _generate_reasons(self, result: FusedSignal, signals: dict) -> list[str]:
        """Gerekçe üret."""
        reasons = []

        for component in [
            "technical",
            "fundamental",
            "momentum",
            "sentiment",
            "news",
            "macro",
            "valuation",
            "ai",
            "spec",
            "monte_carlo",
        ]:
            direction = getattr(result, f"{component}_direction", "NEUTRAL")
            score = getattr(result, f"{component}_score", 50)

            label = "AI Analizi" if component == "ai" else component.title()
            if direction == "LONG" and score > 60:
                reasons.append(f"{label} pozitif: {score:.0f}")
            elif direction == "SHORT" and score < 40:
                reasons.append(f"{label} negatif: {score:.0f}")

        if result.opportunity_score > 65:
            reasons.append(f"Fırsat skoru yüksek: {result.opportunity_score:.0f}")

        return reasons

    def _generate_risks(self, result: FusedSignal, signals: dict) -> list[str]:
        """Risk üret."""
        risks = []

        if result.has_conflict:
            risks.append("Sinyal çakışması var")

        for component in ["technical", "fundamental", "momentum", "ai", "macro"]:
            direction = getattr(result, f"{component}_direction", "NEUTRAL")
            score = getattr(result, f"{component}_score", 50)

            label = "AI Analizi" if component == "ai" else component.title()
            if direction == "LONG" and score < 40:
                risks.append(f"{label} zayıf: {score:.0f}")
            elif direction == "SHORT" and score > 60:
                risks.append(f"{label} Short pozisyonda güçlü: {score:.0f}")

        if result.fused_confidence < 0.3:
            risks.append("Düşük güven")

        return risks

    def _generate_invalidation(self, result: FusedSignal, signals: dict) -> str:
        """Geçersizlik koşulu üret."""
        if result.fused_direction == "LONG":
            return "Fiyat destek seviyesinin altına düşerse veya momentum terse dönerse"
        elif result.fused_direction == "SHORT":
            return "Fiyat direnç seviyesini yukarı kırarsa veya fundamental bozulursa"
        return "Belirgin bir yön yok"

    def _self_check(self, result: FusedSignal, signals: dict) -> tuple[bool, list[str]]:
        """Sonuç sorgulama."""
        warnings = []

        # Çok yüksek confidence şüpheli
        if result.fused_confidence > 0.9:
            warnings.append("Confidence çok yüksek (>0.9) — şüpheli")

        # Tüm bileşenler nötr ama yüksek skor
        all_neutral = all(
            getattr(result, f"{c}_direction", "NEUTRAL") == "NEUTRAL"
            for c in ["technical", "fundamental", "momentum", "sentiment", "news", "macro", "valuation"]
        )
        if all_neutral and result.fused_score > 70:
            warnings.append("Tüm bileşenler nötr ama yüksek skor")

        # Veri kalitesi kontrolü
        if result.opportunity_score > 0 and result.fused_confidence < 0.1:
            warnings.append("Yüksek fırsat skoru ama düşük güven")

        passed = len(warnings) == 0
        return passed, warnings


# Singleton
signal_fusion_engine = SignalFusionEngine()


# Singleton
signal_fusion = signal_fusion_engine  # SignalFusionEngine instance
