"""
ALPHA BIST — Communication Bus & Conflict Resolver v2.0

Agent'lar arası iletişim protokolü.
Confidence-weighted conflict resolution.

FAZ 4: Conflict Resolution + Communication
"""

from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import orjson
import structlog

from .agent_system import AgentResult, AgentRole

logger = structlog.get_logger(__name__)

__all__ = [
    "AgentMessage",
    "Resolution",
    "ConflictResolver",
    "AgentCommunicationBus",
]


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

    def to_dict(self) -> dict[str, Any]:
        """Mesajı sözlük formatına dönüştürür."""
        return {
            "sender": getattr(self.sender, "value", str(self.sender)),
            "receiver": getattr(self.receiver, "value", str(self.receiver)),
            "task_id": self.task_id,
            "message_type": self.message_type,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
            "priority": self.priority,
        }

    def to_json(self) -> str:
        """orjson ile yüksek hızlı serileştirme."""
        return orjson.dumps(self.to_dict()).decode("utf-8")

    def __repr__(self) -> str:
        sender_val = getattr(self.sender, "value", str(self.sender))
        receiver_val = getattr(self.receiver, "value", str(self.receiver))
        return (
            f"AgentMessage({sender_val}->{receiver_val}, "
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

    def to_json(self) -> str:
        """orjson ile JSON serileştirme."""
        return orjson.dumps(self.to_dict()).decode("utf-8")

    def __repr__(self) -> str:
        return (
            f"Resolution(direction={self.direction!r}, confidence={self.confidence:.2f}, "
            f"method={self.method!r}, conflict={self.conflict})"
        )


class AgentCommunicationBus:
    """Agent'lar arası thread-safe ve kurumsal iletişim bus'ı.

    Mesaj kuyrukları ve broadcast desteği sağlar.
    Her agent rolünün ayrı bir mesaj kuyruğu vardır.
    """

    def __init__(self, max_queue_per_role: int = 100, max_dlq: int = 50):
        """İletişim bus'ı oluştur.

        Args:
            max_queue_per_role: Her rol için maksimum kuyruk boyutu
            max_dlq: Dead Letter Queue maksimum boyutu
        """
        self._lock = threading.RLock()
        self._message_queue: dict[AgentRole, deque[AgentMessage]] = {
            role: deque(maxlen=max_queue_per_role) for role in AgentRole
        }
        self._message_log: deque[AgentMessage] = deque(maxlen=1000)
        self._max_queue = max_queue_per_role
        self._dlq: deque[dict[str, Any]] = deque(maxlen=max_dlq)
        self._dlq_max_retries = 3

    def send(self, message: AgentMessage) -> None:
        """Mesaj gönder (Thread-safe).

        Args:
            message: Gönderilecek mesaj

        Raises:
            ValueError: Geçersiz alıcı veya boş task_id
        """
        with self._lock:
            if message.receiver not in self._message_queue:
                raise ValueError(f"Geçersiz alıcı: {message.receiver}")
            if not message.task_id:
                raise ValueError("task_id boş olamaz")
            self._message_queue[message.receiver].append(message)
            self._message_log.append(message)

    def receive(self, role: AgentRole) -> list[AgentMessage]:
        """Mesaj al (ve kuyruktan sil — Thread-safe).

        Args:
            role: Mesajı alacak agent rolü

        Returns:
            Bu role gönderilen tüm mesajlar (kuyruk temizlenir)
        """
        with self._lock:
            messages = list(self._message_queue[role])
            self._message_queue[role].clear()
            return messages

    def peek(self, role: AgentRole) -> list[AgentMessage]:
        """Mesajları görüntüle (kuyruktan silmeden — Thread-safe).

        Args:
            role: Mesajları görüntülenecek agent rolü

        Returns:
            Bu role gönderilen mesajlar (kuyruk korunur)
        """
        with self._lock:
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
                    "from": getattr(m.sender, "value", str(m.sender)),
                    "type": m.message_type,
                    "data": m.payload,
                }
                for m in messages
                if m.message_type == "CONTEXT"
            ],
            "alerts": [
                {
                    "from": getattr(m.sender, "value", str(m.sender)),
                    "data": m.payload,
                }
                for m in messages
                if m.message_type == "ALERT"
            ],
            "debate_messages": [
                {
                    "from": getattr(m.sender, "value", str(m.sender)),
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
        with self._lock:
            messages: list[AgentMessage] = list(self._message_log)
        if message_type:
            messages = [m for m in messages if m.message_type == message_type]
        return [
            {
                "sender": getattr(m.sender, "value", str(m.sender)),
                "receiver": getattr(m.receiver, "value", str(m.receiver)),
                "type": m.message_type,
                "timestamp": m.timestamp.isoformat(),
                "priority": m.priority,
            }
            for m in messages[-limit:]
        ]

    def send_with_retry(self, message: AgentMessage, max_retries: int | None = None) -> bool:
        """Mesaj gönder — başarısız olursa DLQ'ya ekle (Thread-safe).

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
            with self._lock:
                dlq_entry = {
                    "message": {
                        "sender": getattr(message.sender, "value", str(message.sender)),
                        "receiver": getattr(message.receiver, "value", str(message.receiver)),
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
                sender=getattr(message.sender, "value", str(message.sender)),
                receiver=getattr(message.receiver, "value", str(message.receiver)),
                error=str(e),
            )
            return False

    def retry_dlq(self) -> int:
        """DLQ'daki mesajları tekrar dene.

        Returns:
            Başarıyla gönderilen mesaj sayısı
        """
        with self._lock:
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
        with self._lock:
            return list(self._dlq)

    def clear(self) -> None:
        """Tüm kuyrukları temizle (DLQ dahil)."""
        with self._lock:
            for role in AgentRole:
                self._message_queue[role].clear()
            self._dlq.clear()

    def __repr__(self) -> str:
        with self._lock:
            total = sum(len(q) for q in self._message_queue.values())
            dlq_count = len(self._dlq)
            log_count = len(self._message_log)
        return f"AgentCommunicationBus(queued={total}, dlq={dlq_count}, log={log_count})"


class ConflictResolver:
    """Agent çelişki çözümü — rol ve güven ağırlıklı oylama (confidence & role-weighted voting).

    Yöntemler (öncelik sırası):
    1. Risk Veto — risk agent veto ettiyse → NO_TRADE (Fail-closed)
    2. Debate Consensus — debate sonucu varsa → onu kullan
    3. Weighted Majority Vote — en çok ağırlıklı oy alan yön
    4. Confidence Tiebreak — beraberlikte en yüksek güven
    """

    def __init__(self, role_weights: dict[str, float] | None = None) -> None:
        """ConflictResolver başlatıcı.

        Args:
            role_weights: Agent rollerine göre oylama ağırlıkları
        """
        self.role_weights: dict[str, float] = role_weights or {
            "technical": 1.2,
            "fundamental": 1.2,
            "sentiment": 0.8,
            "macro": 1.0,
            "valuation": 1.1,
            "portfolio": 1.0,
            "scenario": 0.9,
            "backtest": 1.0,
        }

    def __repr__(self) -> str:
        return f"ConflictResolver(role_weights={self.role_weights!r})"

    def resolve(
        self,
        results: dict[AgentRole, AgentResult],
        debate_consensus: str | None = None,
        risk_approved: bool = True,
        risk_veto_reason: str | None = None,
    ) -> Resolution:
        """Çelişki varsa çözer.

        Args:
            results: Agent sonuçları
            debate_consensus: Debate sonucu (varsa)
            risk_approved: Risk agent onayladı mı
            risk_veto_reason: Veto gerekçesi

        Returns:
            Resolution — nihai yön, güven, yöntem
        """
        # 1. Risk veto kontrolü — en yüksek öncelik (Fail-closed)
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
        excluded_roles = {
            getattr(AgentRole, "SYNTHESIS", None),
            getattr(AgentRole, "RISK", None),
            getattr(AgentRole, "BULL", None),
            getattr(AgentRole, "BEAR", None),
        }
        valid = {
            r: res
            for r, res in results.items()
            if res.success and r not in excluded_roles
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
            direction = str(result.output.get("direction", "NEUTRAL")).upper()
            if direction not in direction_groups:
                direction_groups[direction] = []
            direction_groups[direction].append((role, result))

        # 5. Ağırlıklı oy sayıları (sadece LONG/SHORT sayılır)
        directional_weighted_votes: dict[str, float] = {}
        for d, group in direction_groups.items():
            if d in ["LONG", "SHORT"]:
                total_w = 0.0
                for r, res in group:
                    role_key = getattr(r, "value", str(r))
                    rw = self.role_weights.get(role_key, 1.0)
                    total_w += float(res.confidence) * rw
                directional_weighted_votes[d] = total_w

        vote_counts = {d: len(v) for d, v in direction_groups.items()}

        if not directional_weighted_votes:
            return Resolution(
                direction="NO_TRADE",
                confidence=0.0,
                method="no_directional_votes",
                vote_distribution=vote_counts,
                conflict=False,
                agents={d: [getattr(r, "value", str(r)) for r, _ in g] for d, g in direction_groups.items()},
            )

        # 6. En çok oy alan yön (sadece LONG/SHORT)
        max_vote = max(directional_weighted_votes.values())
        top_directions = [d for d, v in directional_weighted_votes.items() if abs(v - max_vote) < 1e-6]

        if len(top_directions) == 1:
            final = top_directions[0]
            confidences = [float(r.confidence) for _, r in direction_groups[final]]
            confidence = sum(confidences) / len(confidences) if confidences else 0.5
            method = "majority_vote"
        else:
            # 7. Beraberlik — en yüksek ortalama confidence'a göre
            best_dir: str | None = None
            best_conf = -1.0
            for d in top_directions:
                matching_confs = [float(r.confidence) for _, r in direction_groups[d]]
                avg_conf = sum(matching_confs) / len(matching_confs) if matching_confs else 0.0
                if avg_conf > best_conf:
                    best_conf = avg_conf
                    best_dir = d
            final = best_dir or top_directions[0]
            confidence = max(0.0, best_conf * 0.8)  # Beraberlik cezası
            method = "confidence_tiebreak"

        if math.isnan(confidence) or math.isinf(confidence):
            confidence = 0.0
        else:
            confidence = max(0.0, min(1.0, confidence))

        # Agent listelerini oluştur
        agents = {d: [getattr(r, "value", str(r)) for r, _ in group] for d, group in direction_groups.items()}

        return Resolution(
            direction=final,
            confidence=round(confidence, 4),
            method=method,
            vote_distribution=vote_counts,
            conflict=len(top_directions) > 1,
            agents=agents,
        )
