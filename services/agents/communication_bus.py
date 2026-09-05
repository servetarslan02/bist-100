"""
ALPHA BIST — Communication Bus & Conflict Resolver v2.0

Agent'lar arası iletişim protokolü.
Confidence-weighted conflict resolution.

FAZ 4: Conflict Resolution + Communication
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .agent_system import AgentResult, AgentRole

logger = logging.getLogger(__name__)


@dataclass
class AgentMessage:
    """Agent mesaj formatı.

    Agent'lar arası iletişim için standart mesaj yapısı.
    Mesaj türleri: REQUEST, RESPONSE, DEBATE, ALERT, CONTEXT
    """

    sender: AgentRole
    receiver: AgentRole
    task_id: str
    message_type: str  # REQUEST, RESPONSE, DEBATE, ALERT, CONTEXT
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    priority: str = "NORMAL"  # LOW, NORMAL, HIGH, CRITICAL

    def __repr__(self) -> str:
        return (
            f"AgentMessage({self.sender.value}->{self.receiver.value}, "
            f"type={self.message_type!r}, priority={self.priority!r})"
        )


@dataclass
class Resolution:
    """Çözüm sonucu — conflict resolution'ın çıktısı.

    Yöntemler:
    - majority_vote: En çok oy alan yön
    - confidence_tiebreak: Beraberlikte en yüksek güven
    - debate_consensus: Debate sonucu
    - risk_veto: Risk agent veto ettiyse
    """

    direction: str
    confidence: float
    method: str
    vote_distribution: dict[str, int] = field(default_factory=dict)
    conflict: bool = False
    agents: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialization için dict'e çevir."""
        return {
            "direction": self.direction,
            "confidence": self.confidence,
            "method": self.method,
            "vote_distribution": self.vote_distribution,
            "conflict": self.conflict,
            "agents": self.agents,
        }

    def __repr__(self) -> str:
        return (
            f"Resolution(direction={self.direction!r}, confidence={self.confidence:.2f}, "
            f"method={self.method!r}, conflict={self.conflict})"
        )


class AgentCommunicationBus:
    """Agent'lar arası iletişim bus'ı.

    Mesaj kuyrukları ve broadcast desteği sağlar.
    Her agent rolünün ayrı bir mesaj kuyruğu vardır.

    Mesaj türleri:
    - REQUEST: Veri isteği
    - RESPONSE: Veri yanıtı
    - DEBATE: Tartışma mesajı
    - ALERT: Uyarı
    - CONTEXT: Bağlam paylaşımı

    Kullanım:
        bus = AgentCommunicationBus()
        bus.send(AgentMessage(...))
        messages = bus.receive(AgentRole.TECHNICAL)
    """

    def __init__(self, max_queue_per_role: int = 100, max_dlq: int = 50):
        """İletişim bus'ı oluştur.

        Args:
            max_queue_per_role: Her rol için maksimum kuyruk boyutu
            max_dlq: Dead Letter Queue maksimum boyutu
        """
        self._message_queue: dict[AgentRole, deque[AgentMessage]] = {
            role: deque(maxlen=max_queue_per_role) for role in AgentRole
        }
        self._message_log: deque[AgentMessage] = deque(maxlen=1000)
        self._max_queue = max_queue_per_role
        # Dead Letter Queue — teslim edilemeyen mesajlar
        self._dlq: deque[dict[str, Any]] = deque(maxlen=max_dlq)
        self._dlq_max_retries = 3

    def send(self, message: AgentMessage) -> None:
        """Mesaj gönder.

        Args:
            message: Gönderilecek mesaj

        Raises:
            ValueError: Geçersiz alıcı veya boş task_id
        """
        if message.receiver not in self._message_queue:
            raise ValueError(f"Geçersiz alıcı: {message.receiver}")
        if not message.task_id:
            raise ValueError("task_id boş olamaz")
        self._message_queue[message.receiver].append(message)
        self._message_log.append(message)

    def receive(self, role: AgentRole) -> list[AgentMessage]:
        """Mesaj al (ve kuyruktan sil).

        Args:
            role: Mesajı alacak agent rolü

        Returns:
            Bu role gönderilen tüm mesajlar (kuyruk temizlenir)
        """
        messages = list(self._message_queue[role])
        self._message_queue[role].clear()
        return messages

    def peek(self, role: AgentRole) -> list[AgentMessage]:
        """Mesajları görüntüle (kuyruktan silmeden).

        Args:
            role: Mesajları görüntülenecek agent rolü

        Returns:
            Bu role gönderilen mesajlar (kuyruk korunur)
        """
        return list(self._message_queue[role])

    def broadcast(
        self,
        sender: AgentRole,
        message_type: str,
        payload: dict[str, Any],
        priority: str = "NORMAL",
    ) -> None:
        """Tüm agent'lara gönder (gönderici hariç).

        Args:
            sender: Gönderen agent rolü
            message_type: Mesaj türü
            payload: Mesaj içeriği
            priority: Öncelik seviyesi
        """
        for role in AgentRole:
            if role != sender:
                self.send(
                    AgentMessage(
                        sender=sender,
                        receiver=role,
                        task_id="broadcast",
                        message_type=message_type,
                        payload=payload,
                        priority=priority,
                    )
                )

    def get_context_enrichment(self, role: AgentRole) -> dict[str, Any]:
        """Bu agent için diğer agent'lardan gelen bağlamı topla.

        Not: Bu fonksiyon mesajları kuyruktan siler (receive kullanır).
        Eğer mesajları korumak istiyorsanız peek() kullanın.

        Args:
            role: Bağlam toplanacak agent rolü

        Returns:
            peer_insights, alerts, debate_messages listeleri
        """
        messages = self.receive(role)
        return {
            "peer_insights": [
                {
                    "from": m.sender.value,
                    "type": m.message_type,
                    "data": m.payload,
                }
                for m in messages
                if m.message_type == "CONTEXT"
            ],
            "alerts": [
                {
                    "from": m.sender.value,
                    "data": m.payload,
                }
                for m in messages
                if m.message_type == "ALERT"
            ],
            "debate_messages": [
                {
                    "from": m.sender.value,
                    "data": m.payload,
                }
                for m in messages
                if m.message_type == "DEBATE"
            ],
        }

    def get_message_log(
        self,
        limit: int = 50,
        message_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Mesaj geçmişini getir.

        Args:
            limit: Maksimum mesaj sayısı
            message_type: Filtrelenecek mesaj türü (opsiyonel)

        Returns:
            Mesaj meta-bilgileri listesi
        """
        messages: list[AgentMessage] = list(self._message_log)
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

    def send_with_retry(self, message: AgentMessage, max_retries: int | None = None) -> bool:
        """Mesaj gönder — başarısız olursa DLQ'ya ekle.

        Args:
            message: Gönderilecek mesaj
            max_retries: Maksimum deneme sayısı (varsayılan: 3)

        Returns:
            True: başarılı, False: DLQ'ya eklendi
        """
        retries = max_retries if max_retries is not None else self._dlq_max_retries
        try:
            self.send(message)
            return True
        except Exception as e:
            # DLQ'ya ekle
            dlq_entry = {
                "message": {
                    "sender": message.sender.value,
                    "receiver": message.receiver.value,
                    "type": message.message_type,
                    "task_id": message.task_id,
                    "payload": message.payload,
                },
                "error": str(e),
                "retries": retries,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            self._dlq.append(dlq_entry)
            logger.warning(
                "Message sent to DLQ",
                sender=message.sender.value,
                receiver=message.receiver.value,
                error=str(e),
            )
            return False

    def retry_dlq(self) -> int:
        """DLQ'daki mesajları tekrar dene.

        Returns:
            Başarıyla gönderilen mesaj sayısı
        """
        retried = 0
        remaining: deque[dict[str, Any]] = deque(maxlen=self._dlq.maxlen)

        while self._dlq:
            entry = self._dlq.popleft()
            if entry["retries"] <= 0:
                remaining.append(entry)
                continue

            try:
                msg = AgentMessage(
                    sender=AgentRole(entry["message"]["sender"]),
                    receiver=AgentRole(entry["message"]["receiver"]),
                    task_id=entry["message"]["task_id"],
                    message_type=entry["message"]["type"],
                    payload=entry["message"]["payload"],
                )
                self.send(msg)
                retried += 1
            except Exception:
                entry["retries"] -= 1
                remaining.append(entry)

        self._dlq = remaining
        if retried > 0:
            logger.info("DLQ retry completed", retried=retried, remaining=len(self._dlq))
        return retried

    def get_dlq(self) -> list[dict[str, Any]]:
        """Dead Letter Queue içeriğini getir."""
        return list(self._dlq)

    def clear(self) -> None:
        """Tüm kuyrukları temizle (DLQ dahil)."""
        for role in AgentRole:
            self._message_queue[role].clear()
        self._dlq.clear()

    def __repr__(self) -> str:
        total = sum(len(q) for q in self._message_queue.values())
        return f"AgentCommunicationBus(queued={total}, dlq={len(self._dlq)}, log={len(self._message_log)})"


class ConflictResolver:
    """Agent çelişki çözümü — confidence-weighted voting.

    Yöntemler (öncelik sırası):
    1. Risk Veto — risk agent veto ettiyse → NO_TRADE
    2. Debate Consensus — debate sonucu varsa → onu kullan
    3. Majority Vote — en çok oy alan yön
    4. Confidence Tiebreak — beraberlikte en yüksek güven

    Kullanım:
        resolver = ConflictResolver()
        resolution = resolver.resolve(results, risk_approved=True)
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
            risk_veto_reason: Veto gerekçesi (bilgi amaçlı, log'da kullanılır)

        Returns:
            Resolution — nihai yön, güven, yöntem
        """
        # 1. Risk veto kontrolü — en yüksek öncelik
        if not risk_approved:
            logger.info(
                "Risk veto applied",
                reason=risk_veto_reason or "Risk agent rejected",
            )
            return Resolution(
                direction="NO_TRADE",
                confidence=0.0,
                method="risk_veto",
                conflict=False,
            )

        # 2. Debate consensus varsa onu kullan (NO_TRADE dahil)
        if debate_consensus:
            return Resolution(
                direction=debate_consensus,
                confidence=0.7 if debate_consensus != "NO_TRADE" else 0.0,
                method="debate_consensus",
                conflict=False,
            )

        # 3. Geçerli sonuçları filtrele (SYNTHESIS, RISK, BULL, BEAR hariç)
        valid = {
            r: res
            for r, res in results.items()
            if res.success and r not in [AgentRole.SYNTHESIS, AgentRole.RISK, AgentRole.BULL, AgentRole.BEAR]
        }

        if not valid:
            return Resolution(
                direction="NO_TRADE",
                confidence=0.0,
                method="no_valid_results",
                conflict=False,
            )

        # 4. Yön bazlı gruplama
        direction_groups: dict[str, list[tuple[AgentRole, AgentResult]]] = {}
        for role, result in valid.items():
            direction = result.output.get("direction", "NEUTRAL")
            if direction not in direction_groups:
                direction_groups[direction] = []
            direction_groups[direction].append((role, result))

        # 5. Oy sayıları (NEUTRAL hariç — sadece LONG/SHORT sayılır)
        directional_votes = {d: len(v) for d, v in direction_groups.items() if d in ["LONG", "SHORT"]}
        vote_counts = {d: len(v) for d, v in direction_groups.items()}

        if not directional_votes:
            return Resolution(
                direction="NO_TRADE",
                confidence=0.0,
                method="no_directional_votes",
                vote_distribution=vote_counts,
                conflict=False,
                agents={d: [r.value for r, _ in g] for d, g in direction_groups.items()},
            )

        # 6. En çok oy alan yön (sadece LONG/SHORT)
        max_votes = max(directional_votes.values())
        top_directions = [d for d, v in directional_votes.items() if v == max_votes]

        if len(top_directions) == 1:
            # Net çoğunluk
            final = top_directions[0]
            confidences = [r.confidence for _, r in direction_groups[final]]
            confidence = sum(confidences) / len(confidences)
            method = "majority_vote"
        else:
            # 7. Beraberlik — confidence'a göre
            best_dir: str | None = None
            best_conf = 0.0
            for d in top_directions:
                avg_conf = sum(r.confidence for _, r in direction_groups[d]) / len(direction_groups[d])
                if avg_conf > best_conf:
                    best_conf = avg_conf
                    best_dir = d
            # Edge case: best_dir None kalabilir (tüm conf=0)
            final = best_dir or top_directions[0]
            confidence = best_conf * 0.8  # Beraberlik cezası
            method = "confidence_tiebreak"

        # Agent listelerini oluştur
        agents = {d: [r.value for r, _ in group] for d, group in direction_groups.items()}

        return Resolution(
            direction=final,
            confidence=round(confidence, 4),
            method=method,
            vote_distribution=vote_counts,
            conflict=len(top_directions) > 1,
            agents=agents,
        )
