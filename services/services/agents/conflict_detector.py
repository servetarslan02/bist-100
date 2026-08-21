"""
ALPHA BIST — Conflict Detector v1.0

Agent sonuçları arasında çelişki tespit eder.
LONG/SHORT dağılımını analiz eder.
Debate gerekip gerekmediğini belirler.

FAZ 2: Conflict Detection
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field
import structlog

from .agent_system import AgentRole, AgentResult

logger = structlog.get_logger()


@dataclass
class ConflictReport:
    """Çelişki raporu."""
    has_conflict: bool
    is_unanimous: bool
    long_agents: List[AgentRole] = field(default_factory=list)
    short_agents: List[AgentRole] = field(default_factory=list)
    neutral_agents: List[AgentRole] = field(default_factory=list)
    no_trade_agents: List[AgentRole] = field(default_factory=list)
    requires_debate: bool = False
    conflict_score: float = 0.0  # 0-1 arası, 1 = tam çelişki

    @property
    def long_count(self) -> int:
        return len(self.long_agents)

    @property
    def short_count(self) -> int:
        return len(self.short_agents)

    @property
    def total_agents(self) -> int:
        return self.long_count + self.short_count + len(self.neutral_agents)

    @property
    def majority_direction(self) -> Optional[str]:
        """Çoğunluk yönü."""
        if self.long_count > self.short_count:
            return "LONG"
        elif self.short_count > self.long_count:
            return "SHORT"
        return None

    def to_dict(self) -> Dict:
        return {
            "has_conflict": self.has_conflict,
            "is_unanimous": self.is_unanimous,
            "long_count": self.long_count,
            "short_count": self.short_count,
            "neutral_count": len(self.neutral_agents),
            "requires_debate": self.requires_debate,
            "conflict_score": self.conflict_score,
            "majority_direction": self.majority_direction,
            "long_agents": [a.value for a in self.long_agents],
            "short_agents": [a.value for a in self.short_agents],
        }


class ConflictDetector:
    """Agent sonuçları arasında çelişki tespit eder.

    Kurallar:
    - LONG ve SHORT aynı anda var = çelişki
    - Çelişki varsa debate gerekli
    - Çelişki yoksa doğrudan sentez
    - NEUTRAL oy sayılır ama ağırlığı düşük
    """

    # Debate'i tetikleyen minimum çelişki skoru
    DEBATE_THRESHOLD = 0.3

    def detect(
        self,
        results: Dict[AgentRole, AgentResult],
        exclude_roles: Optional[List[AgentRole]] = None,
    ) -> ConflictReport:
        """Çelişki tespit et.

        Args:
            results: Agent sonuçları
            exclude_roles: Hariç tutulacak roller (SYNTHESIS, RISK gibi)

        Returns:
            ConflictReport
        """
        exclude = set(exclude_roles or [AgentRole.SYNTHESIS, AgentRole.RISK])

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
        long_agents = []
        short_agents = []
        neutral_agents = []
        no_trade_agents = []

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
        is_unanimous = (
            len(long_agents) == len(valid_results) or
            len(short_agents) == len(valid_results)
        )

        # Çelişki skoru (0-1)
        total = len(valid_results)
        if total == 0:
            conflict_score = 0.0
        else:
            # LONG ve SHORT oranı arasındaki fark
            long_ratio = len(long_agents) / total
            short_ratio = len(short_agents) / total
            # Her ikisi de varsa çelişki
            if long_ratio > 0 and short_ratio > 0:
                conflict_score = min(long_ratio, short_ratio) * 2  # 0-1 arası normalize
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
        results: Dict[AgentRole, AgentResult],
    ) -> List[Dict]:
        """Agent'lar arası detaylı çelişki analizi."""
        conflicts = []
        valid = {r: res for r, res in results.items() if res.success}

        roles = list(valid.keys())
        for i in range(len(roles)):
            for j in range(i + 1, len(roles)):
                role_a = roles[i]
                role_b = roles[j]
                dir_a = valid[role_a].output.get("direction", "NEUTRAL")
                dir_b = valid[role_b].output.get("direction", "NEUTRAL")

                # LONG vs SHORT veya SHORT vs LONG
                if (dir_a == "LONG" and dir_b == "SHORT") or \
                   (dir_a == "SHORT" and dir_b == "LONG"):
                    conflicts.append({
                        "agent_a": role_a.value,
                        "direction_a": dir_a,
                        "confidence_a": valid[role_a].confidence,
                        "reasoning_a": valid[role_a].reasoning[:200],
                        "agent_b": role_b.value,
                        "direction_b": dir_b,
                        "confidence_b": valid[role_b].confidence,
                        "reasoning_b": valid[role_b].reasoning[:200],
                        "type": "direction_conflict",
                    })

        return conflicts
