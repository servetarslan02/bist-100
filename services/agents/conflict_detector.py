"""ALPHA BIST — Conflict Detector (Çatışma Tespit) Modülü v3.0.

Bu modül, Alpha BIST multi-agent mimarisinde paralel araştırma yürüten uzman agent'ların
(Teknik, Temel, Haber, Makro, Portföy vb.) kararları arasındaki yön (LONG/SHORT) ve
güven (confidence) çelişkilerini tespit eder. Ağırlıklı çelişki skoru ve şiddet seviyesine
göre (NONE/LOW/MEDIUM/HIGH/CRITICAL) Boğa/Ayı münazara motorunun (Debate Engine) tetiklenip
tetiklenmeyeceğini belirler.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

import orjson
import structlog

from .agent_system import AgentResult, AgentRole

logger = structlog.get_logger(__name__)

__all__: Final[list[str]] = [
    "ConflictSeverity",
    "ConflictReport",
    "ConflictDetector",
]


class ConflictSeverity(StrEnum):
    """Ajan kararları arasındaki çelişkinin şiddet seviyeleri.

    NONE:     Çelişki yok (tüm ajanlar tek yönde veya yönsüz).
    LOW:      Hafif çelişki (0.0 < skor < 0.3) — münazara gerekmeyebilir.
    MEDIUM:   Orta çelişki (0.3 <= skor < 0.5) — münazara önerilir.
    HIGH:     Yüksek çelişki (0.5 <= skor < 0.8) — münazara zorunlu.
    CRITICAL: Kritik kutuplaşma (0.8 <= skor <= 1.0) — derinlemesine münazara zorunlu.
    """

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @classmethod
    def from_score(cls, score: float) -> ConflictSeverity:
        """Sayısal çelişki skorundan uygun şiddet seviyesini üretir.

        Args:
            score: 0.0 ile 1.0 aralığındaki sayısal skor.

        Returns:
            ConflictSeverity: Belirlenen şiddet enum değeri.
        """
        if score <= 0.0 or math.isnan(score):
            return cls.NONE
        elif score < 0.3:
            return cls.LOW
        elif score < 0.5:
            return cls.MEDIUM
        elif score < 0.8:
            return cls.HIGH
        else:
            return cls.CRITICAL


@dataclass
class ConflictReport:
    """Ajan sonuçlarının yön dağılımı ve çelişki analizi özeti."""

    has_conflict: bool
    is_unanimous: bool
    long_agents: list[AgentRole] = field(default_factory=list)
    short_agents: list[AgentRole] = field(default_factory=list)
    neutral_agents: list[AgentRole] = field(default_factory=list)
    no_trade_agents: list[AgentRole] = field(default_factory=list)
    requires_debate: bool = False
    conflict_score: float = 0.0  # 0.0 - 1.0 arası, 1.0 = tam eşit kutuplaşma
    severity: ConflictSeverity = ConflictSeverity.NONE
    majority_confidence: float = 0.0

    @property
    def long_count(self) -> int:
        """LONG yönünde oy veren ajan sayısı."""
        return len(self.long_agents)

    @property
    def short_count(self) -> int:
        """SHORT yönünde oy veren ajan sayısı."""
        return len(self.short_agents)

    @property
    def total_agents(self) -> int:
        """Toplam geçerli değerlendirme yapan ajan sayısı."""
        return self.long_count + self.short_count + len(self.neutral_agents) + len(self.no_trade_agents)

    @property
    def majority_direction(self) -> str | None:
        """Çoğunluk yönü ('LONG' veya 'SHORT'). Beraberlikte veya yönsüzlükte None döner."""
        if self.long_count > self.short_count:
            return "LONG"
        elif self.short_count > self.long_count:
            return "SHORT"
        return None

    def to_dict(self) -> dict[str, Any]:
        """Raporu serileştirilebilir Python sözlüğüne çevirir.

        Returns:
            dict[str, Any]: Yapılandırılmış rapor sözlüğü.
        """
        return {
            "has_conflict": self.has_conflict,
            "is_unanimous": self.is_unanimous,
            "long_count": self.long_count,
            "short_count": self.short_count,
            "neutral_count": len(self.neutral_agents),
            "no_trade_count": len(self.no_trade_agents),
            "requires_debate": self.requires_debate,
            "conflict_score": round(self.conflict_score, 4),
            "severity": self.severity.value,
            "majority_direction": self.majority_direction,
            "majority_confidence": round(self.majority_confidence, 4),
            "long_agents": [a.value for a in self.long_agents],
            "short_agents": [a.value for a in self.short_agents],
            "neutral_agents": [a.value for a in self.neutral_agents],
            "no_trade_agents": [a.value for a in self.no_trade_agents],
        }

    def to_json(self) -> str:
        """Raporu orjson kullanarak JSON dizgisine dönüştürür.

        Returns:
            str: JSON formatında çatışma raporu.
        """
        return orjson.dumps(self.to_dict()).decode("utf-8")

    def __repr__(self) -> str:
        return (
            f"ConflictReport(conflict={self.has_conflict}, "
            f"LONG={self.long_count}, SHORT={self.short_count}, "
            f"score={self.conflict_score:.2f}, severity={self.severity.value!r}, "
            f"debate={self.requires_debate})"
        )


class ConflictDetector:
    """Uzman ajan sonuçları arasındaki yön ve tez çatışmalarını tespit eden analiz motoru."""

    # Münazara motorunu tetikleyen taban çelişki skoru eşiği
    DEBATE_THRESHOLD: float = 0.3

    # Analize doğrudan oy olarak katılmayan üst seviye/denetim rolleri
    _EXCLUDE_ROLES: set[AgentRole] = {
        AgentRole.SYNTHESIS,
        AgentRole.RISK,
        AgentRole.BULL,
        AgentRole.BEAR,
    }

    def __init__(
        self,
        debate_threshold: float = DEBATE_THRESHOLD,
        role_weights: dict[AgentRole, float] | None = None,
    ) -> None:
        """ConflictDetector başlatıcı.

        Args:
            debate_threshold: Münazara tetikleme skor eşiği (varsayılan: 0.3).
            role_weights: Ajan rollerine göre isteğe bağlı oy ağırlıkları sözlüğü.
        """
        self.debate_threshold: float = debate_threshold
        self.role_weights: dict[AgentRole, float] = dict(role_weights or {})

    def detect(
        self,
        results: dict[AgentRole, AgentResult],
        exclude_roles: set[AgentRole] | None = None,
    ) -> ConflictReport:
        """Ajan sonuçlarını analiz ederek çelişki raporu üretir.

        Args:
            results: Ajan rolü anahtarlı AgentResult sonuç sözlüğü.
            exclude_roles: Çelişki hesabına katılmayacak özel rol kümesi.

        Returns:
            ConflictReport: Ayrıntılı çelişki ve oy dağılım raporu.
        """
        exclude = exclude_roles if exclude_roles is not None else self._EXCLUDE_ROLES

        # Yalnızca başarılı ve hariç tutulmamış ajanları al
        valid_results = {
            role: result
            for role, result in results.items()
            if result.success and role not in exclude
        }

        if not valid_results:
            return ConflictReport(
                has_conflict=False,
                is_unanimous=False,
                requires_debate=False,
                severity=ConflictSeverity.NONE,
            )

        long_agents: list[AgentRole] = []
        short_agents: list[AgentRole] = []
        neutral_agents: list[AgentRole] = []
        no_trade_agents: list[AgentRole] = []

        for role, result in valid_results.items():
            direction = str(result.output.get("direction", "NEUTRAL")).upper()
            if direction == "LONG":
                long_agents.append(role)
            elif direction == "SHORT":
                short_agents.append(role)
            elif direction == "NO_TRADE":
                no_trade_agents.append(role)
            else:
                neutral_agents.append(role)

        # Çelişki: Aynı anda en az 1 LONG ve en az 1 SHORT varsa
        has_conflict = len(long_agents) > 0 and len(short_agents) > 0

        # Oy birliği: Yönlü oyların (LONG+SHORT) tamamı tek bir yöndeyse
        directional_count = len(long_agents) + len(short_agents)
        is_unanimous = (
            directional_count > 0
            and (len(long_agents) == directional_count or len(short_agents) == directional_count)
        )

        total_valid = len(valid_results)
        conflict_score = 0.0
        majority_conf = 0.0

        if total_valid > 0 and has_conflict:
            # Ağırlıklı oy oranı hesabı
            long_weight = sum(self.role_weights.get(r, 1.0) for r in long_agents)
            short_weight = sum(self.role_weights.get(r, 1.0) for r in short_agents)
            total_weight = sum(self.role_weights.get(r, 1.0) for r in valid_results)

            if total_weight > 0.0:
                long_ratio = long_weight / total_weight
                short_ratio = short_weight / total_weight
                base_score = min(long_ratio, short_ratio) * 2.0

                # Güven skoru ağırlığı
                long_confs = [
                    max(0.0, min(1.0, float(valid_results[a].confidence)))
                    for a in long_agents
                    if not math.isnan(float(valid_results[a].confidence))
                ]
                short_confs = [
                    max(0.0, min(1.0, float(valid_results[a].confidence)))
                    for a in short_agents
                    if not math.isnan(float(valid_results[a].confidence))
                ]

                avg_long_conf = sum(long_confs) / len(long_confs) if long_confs else 0.5
                avg_short_conf = sum(short_confs) / len(short_confs) if short_confs else 0.5

                # İki taraf da ne kadar eminse (fark azsa) çelişki o kadar ciddidir
                conf_diff = abs(avg_long_conf - avg_short_conf)
                confidence_multiplier = max(0.2, 1.0 - conf_diff)

                conflict_score = min(1.0, max(0.0, base_score * confidence_multiplier))

        # Çoğunluk güven ortalaması
        if len(long_agents) > len(short_agents):
            confs = [valid_results[a].confidence for a in long_agents]
            majority_conf = sum(confs) / len(confs) if confs else 0.0
        elif len(short_agents) > len(long_agents):
            confs = [valid_results[a].confidence for a in short_agents]
            majority_conf = sum(confs) / len(confs) if confs else 0.0

        severity = ConflictSeverity.from_score(conflict_score)
        requires_debate = has_conflict and conflict_score >= self.debate_threshold

        report = ConflictReport(
            has_conflict=has_conflict,
            is_unanimous=is_unanimous,
            long_agents=long_agents,
            short_agents=short_agents,
            neutral_agents=neutral_agents,
            no_trade_agents=no_trade_agents,
            requires_debate=requires_debate,
            conflict_score=round(conflict_score, 4),
            severity=severity,
            majority_confidence=round(majority_conf, 4),
        )

        if has_conflict:
            logger.info(
                "Ajanlar arası karar çatışması tespit edildi",
                long_sayisi=len(long_agents),
                short_sayisi=len(short_agents),
                catisma_skoru=report.conflict_score,
                siddet=severity.value,
                munazara_gerekli=requires_debate,
            )

        return report

    def detect_cross_agent_conflicts(
        self,
        results: dict[AgentRole, AgentResult],
        exclude_roles: set[AgentRole] | None = None,
    ) -> list[dict[str, Any]]:
        """Ajan çiftleri arasındaki birebir tez ve yön çatışmalarını detaylandırır.

        Args:
            results: Ajan sonuçları sözlüğü.
            exclude_roles: Hariç tutulacak roller.

        Returns:
            list[dict[str, Any]]: Çatışan ajan ikilileri ayrıntı listesi.
        """
        exclude = exclude_roles if exclude_roles is not None else self._EXCLUDE_ROLES
        conflicts: list[dict[str, Any]] = []

        valid = {
            r: res
            for r, res in results.items()
            if res.success and r not in exclude
        }

        roles = list(valid.keys())
        for i in range(len(roles)):
            for j in range(i + 1, len(roles)):
                role_a = roles[i]
                role_b = roles[j]
                dir_a = str(valid[role_a].output.get("direction", "NEUTRAL")).upper()
                dir_b = str(valid[role_b].output.get("direction", "NEUTRAL")).upper()

                if (dir_a == "LONG" and dir_b == "SHORT") or (dir_a == "SHORT" and dir_b == "LONG"):
                    conf_a = float(valid[role_a].confidence)
                    conf_b = float(valid[role_b].confidence)
                    conflicts.append(
                        {
                            "agent_a": role_a.value,
                            "direction_a": dir_a,
                            "confidence_a": round(conf_a, 4),
                            "reasoning_a": str(valid[role_a].reasoning)[:200],
                            "agent_b": role_b.value,
                            "direction_b": dir_b,
                            "confidence_b": round(conf_b, 4),
                            "reasoning_b": str(valid[role_b].reasoning)[:200],
                            "confidence_diff": round(abs(conf_a - conf_b), 4),
                            "type": "direction_conflict",
                        }
                    )

        return conflicts

    def __repr__(self) -> str:
        return f"ConflictDetector(threshold={self.debate_threshold}, weighted_roles={len(self.role_weights)})"
