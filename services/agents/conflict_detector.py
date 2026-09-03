"""
ALPHA BIST — Conflict Detector v2.0

Agent sonuçları arasında çelişki tespit eder.
LONG/SHORT dağılımını analiz eder.
Debate gerekip gerekmediğini belirler.

FAZ 2: Conflict Detection
"""

from dataclasses import dataclass, field
from typing import Any

import structlog

from .agent_system import AgentResult, AgentRole

logger = structlog.get_logger()


@dataclass
class ConflictReport:
    """Çelişki raporu — agent sonuçlarının yön dağılımını ve çelişki durumunu özetler."""

    has_conflict: bool
    is_unanimous: bool
    long_agents: list[AgentRole] = field(default_factory=list)
    short_agents: list[AgentRole] = field(default_factory=list)
    neutral_agents: list[AgentRole] = field(default_factory=list)
    no_trade_agents: list[AgentRole] = field(default_factory=list)
    requires_debate: bool = False
    conflict_score: float = 0.0  # 0-1 arası, 1 = tam çelişki

    @property
    def long_count(self) -> int:
        """LONG yönünde oy veren agent sayısı."""
        return len(self.long_agents)

    @property
    def short_count(self) -> int:
        """SHORT yönünde oy veren agent sayısı."""
        return len(self.short_agents)

    @property
    def total_agents(self) -> int:
        """Toplam geçerli agent sayısı (LONG + SHORT + NEUTRAL)."""
        return self.long_count + self.short_count + len(self.neutral_agents)

    @property
    def majority_direction(self) -> str | None:
        """Çoğunluk yönü (LONG veya SHORT). Beraberlikte None."""
        if self.long_count > self.short_count:
            return "LONG"
        elif self.short_count > self.long_count:
            return "SHORT"
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialization için dict'e çevir."""
        return {
            "has_conflict": self.has_conflict,
            "is_unanimous": self.is_unanimous,
            "long_count": self.long_count,
            "short_count": self.short_count,
            "neutral_count": len(self.neutral_agents),
            "no_trade_count": len(self.no_trade_agents),
            "requires_debate": self.requires_debate,
            "conflict_score": self.conflict_score,
            "majority_direction": self.majority_direction,
            "long_agents": [a.value for a in self.long_agents],
            "short_agents": [a.value for a in self.short_agents],
        }

    def __repr__(self) -> str:
        return (
            f"ConflictReport(conflict={self.has_conflict}, "
            f"LONG={self.long_count}, SHORT={self.short_count}, "
            f"score={self.conflict_score:.2f}, debate={self.requires_debate})"
        )


class ConflictDetector:
    """Agent sonuçları arasında çelişki tespit eder.

    Kurallar:
    - LONG ve SHORT aynı anda var = çelişki
    - Çelişki skoru >= 0.3 ise debate gerekli
    - Çelişki yoksa doğrudan sentez
    - NEUTRAL oy sayılır ama ağırlığı düşük

    Kullanım:
        detector = ConflictDetector()
        report = detector.detect(results)
        if report.requires_debate:
            # Debate başlat
    """

    # Debate'i tetikleyen minimum çelişki skoru
    DEBATE_THRESHOLD = 0.3

    # Debate'e dahil edilmeyecek roller
    _EXCLUDE_ROLES = {AgentRole.SYNTHESIS, AgentRole.RISK, AgentRole.BULL, AgentRole.BEAR}

    def detect(
        self,
        results: dict[AgentRole, AgentResult],
        exclude_roles: set[AgentRole] | None = None,
    ) -> ConflictReport:
        """Çelişki tespit et.

        Args:
            results: Agent sonuçları
            exclude_roles: Hariç tutulacak roller (varsayılan: SYNTHESIS, RISK, BULL, BEAR)

        Returns:
            ConflictReport — çelişki durumu, oy dağılımı, debate gereksinimi
        """
        exclude = exclude_roles if exclude_roles is not None else self._EXCLUDE_ROLES

        # Geçerli sonuçları filtrele
        valid_results = {
            role: result for role, result in results.items()
            if result.success and role not in exclude
        }

        if not valid_results:
            return ConflictReport(
                has_conflict=False,
                is_unanimous=False,
                requires_debate=False,
            )

        # Yön bazlı gruplama
        long_agents: list[AgentRole] = []
        short_agents: list[AgentRole] = []
        neutral_agents: list[AgentRole] = []
        no_trade_agents: list[AgentRole] = []

        for role, result in valid_results.items():
            direction = result.output.get("direction", "NEUTRAL")
            if direction == "LONG":
                long_agents.append(role)
            elif direction == "SHORT":
                short_agents.append(role)
            elif direction == "NO_TRADE":
                no_trade_agents.append(role)
            else:
                neutral_agents.append(role)

        # Çelişki analizi
        has_conflict = len(long_agents) > 0 and len(short_agents) > 0

        # Unanimous = tüm aktif agent'lar aynı yönde (NEUTRAL/NO_TRADE hariç)
        directional_count = len(long_agents) + len(short_agents)
        is_unanimous = (
            directional_count > 0
            and (len(long_agents) == directional_count or len(short_agents) == directional_count)
        )

        # Çelişki skoru (0-1)
        # Formül: min(LONG%, SHORT%) * 2 — 0.5/0.5 dağılımda 1.0, 0.3/0.7'de 0.6
        total = len(valid_results)
        if total == 0:
            conflict_score = 0.0
        else:
            long_ratio = len(long_agents) / total
            short_ratio = len(short_agents) / total
            if long_ratio > 0 and short_ratio > 0:
                conflict_score = min(long_ratio, short_ratio) * 2
            else:
                conflict_score = 0.0

        # Debate gerekli mi?
        requires_debate = has_conflict and conflict_score >= self.DEBATE_THRESHOLD

        report = ConflictReport(
            has_conflict=has_conflict,
            is_unanimous=is_unanimous,
            long_agents=long_agents,
            short_agents=short_agents,
            neutral_agents=neutral_agents,
            no_trade_agents=no_trade_agents,
            requires_debate=requires_debate,
            conflict_score=round(conflict_score, 4),
        )

        if has_conflict:
            logger.info(
                "Conflict detected",
                long_count=len(long_agents),
                short_count=len(short_agents),
                conflict_score=conflict_score,
                requires_debate=requires_debate,
            )

        return report

    def detect_cross_agent_conflicts(
        self,
        results: dict[AgentRole, AgentResult],
    ) -> list[dict[str, Any]]:
        """Agent'lar arası detaylı çelişki analizi.

        Her LONG-SHORT çiftini ayrı ayrı raporlar.
        Debate engine tarafından kullanılabilir.

        Args:
            results: Agent sonuçları

        Returns:
            Çelişki çiftlerinin detaylı listesi
        """
        conflicts: list[dict[str, Any]] = []
        valid = {r: res for r, res in results.items() if res.success}

        roles = list(valid.keys())
        for i in range(len(roles)):
            for j in range(i + 1, len(roles)):
                role_a = roles[i]
                role_b = roles[j]
                dir_a = valid[role_a].output.get("direction", "NEUTRAL")
                dir_b = valid[role_b].output.get("direction", "NEUTRAL")

                # LONG vs SHORT veya SHORT vs LONG
                if (dir_a == "LONG" and dir_b == "SHORT") or (dir_a == "SHORT" and dir_b == "LONG"):
                    conflicts.append(
                        {
                            "agent_a": role_a.value,
                            "direction_a": dir_a,
                            "confidence_a": valid[role_a].confidence,
                            "reasoning_a": valid[role_a].reasoning[:200],
                            "agent_b": role_b.value,
                            "direction_b": dir_b,
                            "confidence_b": valid[role_b].confidence,
                            "reasoning_b": valid[role_b].reasoning[:200],
                            "type": "direction_conflict",
                        }
                    )

        return conflicts
