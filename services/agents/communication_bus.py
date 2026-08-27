"""
ALPHA BIST — Communication Bus & Conflict Resolver v1.0

Agent'lar arası iletişim protokolü.
Confidence-weighted conflict resolution.

FAZ 4: Conflict Resolution + Communication
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from .agent_system import AgentResult, AgentRole

logger = structlog.get_logger()


@dataclass
class AgentMessage:
    """Agent mesaj formatı."""
    sender: AgentRole
    receiver: AgentRole
    task_id: str
    message_type: str  # REQUEST, RESPONSE, DEBATE, ALERT, CONTEXT
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    priority: str = "NORMAL"  # LOW, NORMAL, HIGH, CRITICAL


@dataclass
class Resolution:
    """Çözüm sonucu."""
    direction: str
    confidence: float
    method: str  # majority_vote, confidence_tiebreak, debate_consensus, risk_veto
    vote_distribution: dict[str, int] = field(default_factory=dict)
    conflict: bool = False
    agents: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "confidence": self.confidence,
            "method": self.method,
            "vote_distribution": self.vote_distribution,
            "conflict": self.conflict,
            "agents": self.agents,
        }


class AgentCommunicationBus:
    """Agent'lar arası iletişim bus'ı.

    Mesaj türleri:
    - REQUEST: Veri isteği
    - RESPONSE: Veri yanıtı
    - DEBATE: Tartışma mesajı
    - ALERT: Uyarı
    - CONTEXT: Bağlam paylaşımı
    """

    def __init__(self):
        self._message_queue: dict[AgentRole, list[AgentMessage]] = {
            role: [] for role in AgentRole
        }
        self._message_log: list[AgentMessage] = []

    def send(self, message: AgentMessage):
        """Mesaj gönder."""
        self._message_queue[message.receiver].append(message)
        self._message_log.append(message)
        if len(self._message_log) > 1000:
            self._message_log = self._message_log[-1000:]

    def receive(self, role: AgentRole) -> list[AgentMessage]:
        """Mesaj al (ve kuyruktan sil)."""
        messages = self._message_queue.get(role, [])
        self._message_queue[role] = []
        return messages

    def peek(self, role: AgentRole) -> list[AgentMessage]:
        """Mesajları görüntüle (kuyruktan silmeden)."""
        return self._message_queue.get(role, [])

    def broadcast(
        self,
        sender: AgentRole,
        message_type: str,
        payload: dict[str, Any],
        priority: str = "NORMAL",
    ):
        """Tüm agent'lara gönder."""
        for role in AgentRole:
            if role != sender:
                self.send(AgentMessage(
                    sender=sender,
                    receiver=role,
                    task_id="broadcast",
                    message_type=message_type,
                    payload=payload,
                    priority=priority,
                ))

    def get_context_enrichment(self, role: AgentRole) -> dict[str, Any]:
        """Bu agent için diğer agent'lardan gelen bağlamı topla."""
        messages = self.receive(role)
        return {
            "peer_insights": [
                {
                    "from": m.sender.value,
                    "type": m.message_type,
                    "data": m.payload,
                }
                for m in messages if m.message_type == "CONTEXT"
            ],
            "alerts": [
                {
                    "from": m.sender.value,
                    "data": m.payload,
                }
                for m in messages if m.message_type == "ALERT"
            ],
            "debate_messages": [
                {
                    "from": m.sender.value,
                    "data": m.payload,
                }
                for m in messages if m.message_type == "DEBATE"
            ],
        }

    def get_message_log(
        self,
        limit: int = 50,
        message_type: str | None = None,
    ) -> list[dict]:
        """Mesaj geçmişini getir."""
        messages = self._message_log
        if message_type:
            messages = [m for m in messages if m.message_type == message_type]
        return [
            {
                "sender": m.sender.value,
                "receiver": m.receiver.value,
                "type": m.message_type,
                "timestamp": m.timestamp.isoformat(),
                "priority": m.priority,
            }
            for m in messages[-limit:]
        ]

    def clear(self):
        """Tüm kuyrukları temizle."""
        for role in AgentRole:
            self._message_queue[role] = []


class ConflictResolver:
    """Agent çelişki çözümü — confidence-weighted voting.

    Yöntemler:
    1. Majority Vote — en çok oy alan yön
    2. Confidence Tiebreak — beraberlikte en yüksek güven
    3. Debate Consensus — debate sonucu
    4. Risk Veto — risk agent veto ettiyse
    """

    def resolve(
        self,
        results: dict[AgentRole, AgentResult],
        debate_consensus: str | None = None,
        risk_approved: bool = True,
        risk_veto_reason: str | None = None,
    ) -> Resolution:
        """Çelişki varsa çöz.

        Args:
            results: Agent sonuçları
            debate_consensus: Debate sonucu (varsa)
            risk_approved: Risk agent onayladı mı
            risk_veto_reason: Veto gerekçesi

        Returns:
            Resolution
        """
        # Risk veto kontrolü
        if not risk_approved:
            return Resolution(
                direction="NO_TRADE",
                confidence=0.0,
                method="risk_veto",
                conflict=False,
            )

        # Debate consensus varsa onu kullan
        if debate_consensus and debate_consensus != "NO_TRADE":
            return Resolution(
                direction=debate_consensus,
                confidence=0.7,  # Debate'ten gelen consensus güvenilir
                method="debate_consensus",
                conflict=False,
            )

        # Geçerli sonuçları filtrele
        valid = {
            r: res for r, res in results.items()
            if res.success and r not in [AgentRole.SYNTHESIS, AgentRole.RISK, AgentRole.BULL, AgentRole.BEAR]
        }

        if not valid:
            return Resolution(
                direction="NO_TRADE",
                confidence=0.0,
                method="no_valid_results",
                conflict=False,
            )

        # Yön bazlı gruplama
        direction_groups: dict[str, list[tuple]] = {}
        for role, result in valid.items():
            direction = result.output.get("direction", "NEUTRAL")
            if direction not in direction_groups:
                direction_groups[direction] = []
            direction_groups[direction].append((role, result))

        # Oy sayıları (NEUTRAL hariç — sadece LONG/SHORT sayılır)
        directional_votes = {d: len(v) for d, v in direction_groups.items() if d in ["LONG", "SHORT"]}
        vote_counts = {d: len(v) for d, v in direction_groups.items()}

        if not directional_votes:
            # Hiç LONG/SHORT yoksa NO_TRADE
            return Resolution(
                direction="NO_TRADE",
                confidence=0.0,
                method="no_directional_votes",
                vote_distribution=vote_counts,
                conflict=False,
                agents={d: [r.value for r, _ in g] for d, g in direction_groups.items()},
            )

        # En çok oy alan yön (sadece LONG/SHORT)
        max_votes = max(directional_votes.values())
        top_directions = [d for d, v in directional_votes.items() if v == max_votes]

        if len(top_directions) == 1:
            # Net çoğunluk
            final = top_directions[0]
            confidences = [r.confidence for _, r in direction_groups[final]]
            confidence = sum(confidences) / len(confidences)
            method = "majority_vote"
        else:
            # Beraberlik — confidence'a göre
            best_dir = None
            best_conf = 0
            for d in top_directions:
                avg_conf = sum(r.confidence for _, r in direction_groups[d]) / len(direction_groups[d])
                if avg_conf > best_conf:
                    best_conf = avg_conf
                    best_dir = d
            final = best_dir
            confidence = best_conf * 0.8  # Beraberlik cezası
            method = "confidence_tiebreak"

        # Agent listelerini oluştur
        agents = {
            d: [r.value for r, _ in group]
            for d, group in direction_groups.items()
        }

        return Resolution(
            direction=final,
            confidence=round(confidence, 4),
            method=method,
            vote_distribution=vote_counts,
            conflict=len(top_directions) > 1,
            agents=agents,
        )
