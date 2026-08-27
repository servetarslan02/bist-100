"""
ALPHA BIST — Macro Regime Detector v1.0

Makro rejim tespiti — skor bazlı:
- EXPANSION: Genişleyici (düşük faiz, düşük enflasyon, güçlü büyüme)
- CONTRACTION: Daraltıcı (yüksek faiz, yüksek enflasyon, zayıf büyüme)
- STAGFLATION: Stagflasyon (yüksek enflasyon, zayıf büyüme, yüksek faiz)
- REFLATION: Reflasyon (düşük faiz, yükselen enflasyon, toparlanma)
- RISK_ON: Risk Açıklığı (düşük VIX, yükselen S&P500, düşük CDS)
- RISK_OFF: Risk Kaçışı (yüksek VIX, düşen S&P500, yükselen CDS)

Tespit yöntemi: Her rejim için ağırlıklı skor hesapla, en yüksek skorlu rejimi seç.

KURAL: Rejim değişimi smoothing ile filtrelenmeli (chatter önleme).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from services.macro.config.macro_config import macro_config

logger = structlog.get_logger()


@dataclass
class RegimeResult:
    """Rejim tespit sonucu."""
    regime: str
    confidence: float
    all_scores: dict[str, float]
    description: str
    characteristics: list[str]
    recommended_strategy: str
    timestamp: str


@dataclass
class RegimeTransition:
    """Rejim geçiş kaydı."""
    from_regime: str
    to_regime: str
    timestamp: str
    confidence: float


class MacroRegimeDetector:
    """Makro rejim tespit motoru."""

    MACRO_REGIMES = {
        "EXPANSION": {
            "description": "Genişleyici",
            "characteristics": ["düşük faiz", "düşük enflasyon", "güçlü büyüme", "yükselen kredi"],
            "strategy": "Büyüme hisseleri, yüksek beta, teknoloji",
        },
        "CONTRACTION": {
            "description": "Daraltıcı",
            "characteristics": ["yüksek faiz", "yüksek enflasyon", "zayıf büyüme", "düşen kredi"],
            "strategy": "Defansif, düşük beta, temettü, altın",
        },
        "STAGFLATION": {
            "description": "Stagflasyon",
            "characteristics": ["yüksek enflasyon", "zayıf büyüme", "yüksek faiz", "düşen reel gelir"],
            "strategy": "Emtia, altın, kısa vadeli, nakit",
        },
        "REFLATION": {
            "description": "Reflasyon",
            "characteristics": ["düşük faiz", "yükselen enflasyon", "toparlanma", "artan kredi"],
            "strategy": "Döngüsel hisseler, emtia, banka",
        },
        "RISK_ON": {
            "description": "Risk Açıklığı",
            "characteristics": ["düşük VIX", "yükselen S&P500", "düşük CDS", "artan sermaye akışı"],
            "strategy": "Yüksek beta, büyüme, teknoloji, gelişmekte olan piyasalar",
        },
        "RISK_OFF": {
            "description": "Risk Kaçışı",
            "characteristics": ["yüksek VIX", "düşen S&P500", "yükselen CDS", "çıkan sermaye"],
            "strategy": "Defansif, altın, ABD tahvil, nakit, JPY",
        },
    }

    def __init__(self):
        self._current_regime: str | None = None
        self._regime_history: list[RegimeResult] = []
        self._transitions: list[RegimeTransition] = []
        self._regime_duration: int = 0

    def detect_regime(self, macro_features: dict[str, float]) -> RegimeResult:
        """Makro rejim tespit et.

        Args:
            macro_features: Makro feature'lar (MacroFeatureEngine çıktısı)

        Returns:
            RegimeResult
        """
        cfg = macro_config.regime

        # Her rejim için skor hesapla
        scores = {
            "EXPANSION": self._score_expansion(macro_features),
            "CONTRACTION": self._score_contraction(macro_features),
            "STAGFLATION": self._score_stagflation(macro_features),
            "REFLATION": self._score_reflation(macro_features),
            "RISK_ON": self._score_risk_on(macro_features),
            "RISK_OFF": self._score_risk_off(macro_features),
        }

        # En yüksek skorlu rejim
        best_regime = max(scores, key=scores.get)
        best_score = scores[best_regime]

        # Confidence threshold kontrolü
        if best_score < cfg.confidence_threshold:
            best_regime = self._current_regime or "EXPANSION"
            best_score = cfg.confidence_threshold

        # Smoothing — rejim geçiş filtresi
        if self._current_regime and best_regime != self._current_regime:
            self._regime_duration += 1
            if self._regime_duration < cfg.min_regime_duration_days:
                # Henüz minimum sürede değil → mevcut rejimde kal
                best_regime = self._current_regime
                best_score = scores.get(best_regime, 0)
            else:
                # Rejim değişimi
                transition = RegimeTransition(
                    from_regime=self._current_regime,
                    to_regime=best_regime,
                    timestamp=datetime.now(UTC).isoformat(),
                    confidence=best_score,
                )
                self._transitions.append(transition)
                if len(self._transitions) > 500:
                    self._transitions = self._transitions[-500:]
                self._regime_duration = 0

                logger.warning("Macro regime change",
                             from_regime=self._current_regime,
                             to_regime=best_regime,
                             confidence=round(best_score, 4))
        else:
            self._regime_duration += 1

        self._current_regime = best_regime

        regime_info = self.MACRO_REGIMES[best_regime]
        result = RegimeResult(
            regime=best_regime,
            confidence=round(best_score, 4),
            all_scores={k: round(v, 4) for k, v in scores.items()},
            description=regime_info["description"],
            characteristics=regime_info["characteristics"],
            recommended_strategy=regime_info["strategy"],
            timestamp=datetime.now(UTC).isoformat(),
        )

        self._regime_history.append(result)
        if len(self._regime_history) > 1000:
            self._regime_history = self._regime_history[-1000:]
        return result

    def compute_regime_features(self, macro_features: dict[str, float]) -> dict[str, float]:
        """Rejim feature'ları üret."""
        result = self.detect_regime(macro_features)

        features = {}

        # Her rejim skoru
        for regime, score in result.all_scores.items():
            features[f"macro_regime_{regime.lower()}_score"] = score

        # Composite skor (0-5 arası)
        regime_order = ["EXPANSION", "REFLATION", "RISK_ON", "CONTRACTION", "STAGFLATION", "RISK_OFF"]
        composite = 0.0
        for i, regime in enumerate(regime_order):
            composite += result.all_scores.get(regime, 0) * i
        features["macro_regime_composite"] = round(composite / max(sum(result.all_scores.values()), 0.01), 4)

        # Rejim dummy (en yüksek skorlu rejim = 1)
        for regime in regime_order:
            features[f"macro_regime_{regime.lower()}"] = 1.0 if result.regime == regime else 0.0

        # Rejim süresi
        features["macro_regime_duration_days"] = float(self._regime_duration)

        # Rejim değişimi (son 30 günde değişti mi?)
        recent_transitions = [
            t for t in self._transitions
            if t.timestamp > (datetime.now(UTC) - timedelta(days=30)).isoformat()
        ]
        features["macro_regime_changed_30d"] = 1.0 if recent_transitions else 0.0

        return features

    def get_current_regime(self) -> str | None:
        """Mevcut rejim."""
        return self._current_regime

    def get_regime_report(self) -> dict[str, Any]:
        """Rejim raporu."""
        return {
            "current_regime": self._current_regime,
            "duration_days": self._regime_duration,
            "total_transitions": len(self._transitions),
            "recent_transitions": [
                {"from": t.from_regime, "to": t.to_regime, "timestamp": t.timestamp}
                for t in self._transitions[-5:]
            ],
            "regime_descriptions": {
                k: v["description"] for k, v in self.MACRO_REGIMES.items()
            },
        }

    # ===================== SKOR FONKSİYONLARI =====================

    def _score_expansion(self, f: dict) -> float:
        """Genişleyici rejim skoru."""
        score = 0.0
        count = 0

        # Faiz düşüyor
        if "rate_trend" in f:
            score += 0.25 if f["rate_trend"] < 0 else 0
            count += 1

        # Enflasyon düşüyor
        if "inflation_trend" in f:
            score += 0.20 if f["inflation_trend"] < 0 else 0
            count += 1

        # S&P500 yükseliyor
        if "sp500_momentum_20d" in f:
            score += 0.20 if f["sp500_momentum_20d"] > 0 else 0
            count += 1

        # VIX düşük
        if "vix_regime" in f:
            score += 0.20 if f["vix_regime"] < 1.5 else 0
            count += 1

        # Kredi büyüyor
        if "credit_growth_yoy" in f:
            score += 0.15 if f["credit_growth_yoy"] > 0 else 0
            count += 1

        return min(score, 1.0) if count > 0 else 0.0

    def _score_contraction(self, f: dict) -> float:
        """Daraltıcı rejim skoru."""
        score = 0.0

        if "rate_trend" in f and f["rate_trend"] > 0:
            score += 0.25
        if "inflation_trend" in f and f["inflation_trend"] > 0:
            score += 0.20
        if "sp500_momentum_20d" in f and f["sp500_momentum_20d"] < -3:
            score += 0.20
        if "vix_regime" in f and f["vix_regime"] > 2.0:
            score += 0.20
        if "credit_growth_yoy" in f and f["credit_growth_yoy"] < 0:
            score += 0.15

        return min(score, 1.0)

    def _score_stagflation(self, f: dict) -> float:
        """Stagflasyon rejim skoru."""
        score = 0.0

        # Yüksek enflasyon
        if "cpi_level" in f and f["cpi_level"] > 15:
            score += 0.25
        # Zayıf büyüme (S&P500 düşüyor)
        if "sp500_momentum_20d" in f and f["sp500_momentum_20d"] < -2:
            score += 0.20
        # Yüksek faiz
        if "tcmb_policy_rate" in f and f["tcmb_policy_rate"] > 15:
            score += 0.20
        # VIX yüksek
        if "vix_regime" in f and f["vix_regime"] > 2.0:
            score += 0.15
        # USDTRY yükseliyor
        if "usdtry_momentum_20d" in f and f["usdtry_momentum_20d"] > 3:
            score += 0.20

        return min(score, 1.0)

    def _score_reflation(self, f: dict) -> float:
        """Reflasyon rejim skoru."""
        score = 0.0

        # Düşük/faiz stabil
        if "rate_trend" in f and f["rate_trend"] <= 0:
            score += 0.20
        # Enflasyon yükseliyor (ama çok yüksek değil)
        if "inflation_trend" in f and f["inflation_trend"] > 0:
            cpi = f.get("cpi_level", 0)
            if 5 < cpi < 20:  # Çok yüksek değil
                score += 0.25
        # Toparlanma (S&P500 yükseliyor)
        if "sp500_momentum_20d" in f and f["sp500_momentum_20d"] > 0:
            score += 0.20
        # Kredi büyüyor
        if "credit_growth_yoy" in f and f["credit_growth_yoy"] > 0:
            score += 0.15
        # VIX normal
        if "vix_regime" in f and f["vix_regime"] < 2.0:
            score += 0.20

        return min(score, 1.0)

    def _score_risk_on(self, f: dict) -> float:
        """Risk-on rejim skoru."""
        score = 0.0

        # VIX düşük
        if "vix_regime" in f and f["vix_regime"] < 1.0:
            score += 0.30
        # S&P500 yükseliyor
        if "sp500_momentum_20d" in f and f["sp500_momentum_20d"] > 3:
            score += 0.30
        # CDS düşük
        if "cds_5y" in f and f["cds_5y"] < 200:
            score += 0.20
        # USDTRY stabil/düşüyor
        if "usdtry_momentum_20d" in f and f["usdtry_momentum_20d"] < 2:
            score += 0.20

        return min(score, 1.0)

    def _score_risk_off(self, f: dict) -> float:
        """Risk-off rejim skoru."""
        score = 0.0

        # VIX yüksek
        if "vix_regime" in f and f["vix_regime"] > 2.5:
            score += 0.30
        # S&P500 düşüyor
        if "sp500_momentum_20d" in f and f["sp500_momentum_20d"] < -5:
            score += 0.25
        # CDS yüksek
        if "cds_5y" in f and f["cds_5y"] > 300:
            score += 0.20
        # USDTRY yükseliyor
        if "usdtry_momentum_20d" in f and f["usdtry_momentum_20d"] > 5:
            score += 0.25

        return min(score, 1.0)


# Singleton
macro_regime_detector = MacroRegimeDetector()
