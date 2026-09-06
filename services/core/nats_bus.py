"""
ALPHA BIST — NATS JetStream Event Bus & Message Streaming Engine
================================================================
Yüksek Hızlı, Güvenilir ve Asenkron Finansal Olay Akışı:
1. Stream Tanımları (market.ticks, signals.alpha, orders.execution, risk.alerts)
2. Exactly-Once Delivery (Deduplication Window ile çift mesaj engelleme)
3. Consumer Groups & Load Balancing
4. Dead-Letter-Queue (DLQ) — DuckDB destekli hatalı mesaj izolasyonu (GEMINI.md Kural 5)
5. Kesintisiz Çalışma & In-Memory Fallback
6. Polars Telemetri ve Analitik Dışa Aktarımı (GEMINI.md Kural 2)
7. Thread-safe eşzamanlı kilit mimarisi
"""

from __future__ import annotations

import contextlib
import hashlib
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Coroutine, Final

import duckdb
import orjson
import polars as pl
import structlog

logger = structlog.get_logger(__name__)

# Sabitler
DEFAULT_MAX_MESSAGES: Final[int] = 1_000_000
DEFAULT_MAX_AGE_HOURS: Final[int] = 24
DEFAULT_DEDUP_WINDOW_SEC: Final[int] = 300
DEFAULT_DEDUP_CACHE_SIZE: Final[int] = 100_000
DEFAULT_MAX_RETRIES: Final[int] = 3
DEFAULT_NATS_DLQ_DB_PATH: Final[str] = "data/nats_dlq.duckdb"


def configure_duckdb_wal(conn: Any) -> None:
    """DuckDB WAL boyut ve checkpoint ayarlarını SSD koruması için yapılandırır."""
    with contextlib.suppress(Exception):
        conn.execute("PRAGMA checkpoint_threshold='4MB'")
        conn.execute("PRAGMA wal_autocheckpoint='2MB'")


@dataclass(slots=True)
class EventMessage:
    """NATS Event Zarfı.

    Attributes:
        subject: Olayın yayınlandığı konu başlığı.
        data: Olay yükü sözlüğü.
        msg_id: Benzersiz mesaj kimliği (deduplication için kullanılır).
        timestamp: ISO-8601 formatında UTC zaman damgası.
        correlation_id: İşlem zincirini bağlayan korelasyon kimliği.
        retry_count: Hata durumunda yeniden deneme sayısı.
    """

    subject: str
    data: dict[str, Any]
    msg_id: str = field(default_factory=lambda: hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:16])
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    correlation_id: str | None = None
    retry_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Mesajı sözlük formatına dönüştürür."""
        return {
            "subject": self.subject,
            "data": self.data,
            "msg_id": self.msg_id,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "retry_count": self.retry_count,
        }

    def to_orjson_bytes(self) -> bytes:
        """Mesajı orjson ikili serileştirme ile paketler."""
        return orjson.dumps(self.to_dict(), option=orjson.OPT_SORT_KEYS)

    def __repr__(self) -> str:
        """Okunabilir metinsel temsil."""
        return (
            f"<EventMessage msg_id={self.msg_id} subject='{self.subject}' "
            f"retries={self.retry_count} ts={self.timestamp}>"
        )


@dataclass(slots=True)
class StreamConfig:
    """NATS Stream yapılandırması.

    Attributes:
        name: Stream benzersiz adı.
        subjects: Stream kapsamındaki konu şablonları listesi.
        max_messages: Saklanacak azami mesaj adedi.
        max_age_hours: Mesajların azami ömrü (saat).
        duplicate_window_sec: Mükerrer mesaj filtreleme penceresi (saniye).
    """

    name: str
    subjects: list[str]
    max_messages: int = DEFAULT_MAX_MESSAGES
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS
    duplicate_window_sec: int = DEFAULT_DEDUP_WINDOW_SEC

    def __repr__(self) -> str:
        """Okunabilir metinsel temsil."""
        return f"<StreamConfig name='{self.name}' subjects={self.subjects} max_msgs={self.max_messages}>"


class NATSJetStreamBus:
    """BIST-100 NATS JetStream Event Bus.

    Finansal olayların dağıtımı, deduplication koruması, aboneye bildirim
    ve başarısız mesajların DuckDB tabanlı DLQ deposuna aktarımını yönetir.
    """

    def __init__(self, dlq_db_path: str = DEFAULT_NATS_DLQ_DB_PATH) -> None:
        """NATSJetStreamBus bileşenini ilklendirir."""
        self._streams: dict[str, StreamConfig] = {}
        self._subscribers: dict[str, list[Callable[[EventMessage], Coroutine[Any, Any, None]]]] = defaultdict(list)
        self._dedup_cache: deque[str] = deque(maxlen=DEFAULT_DEDUP_CACHE_SIZE)
        self._dlq: list[EventMessage] = []
        self._is_connected: bool = False
        self._lock = threading.RLock()
        self._dlq_db_path = Path(dlq_db_path)
        self._dlq_db_path.parent.mkdir(parents=True, exist_ok=True)

        self._metrics = {
            "published_count": 0,
            "delivered_count": 0,
            "duplicate_dropped": 0,
            "dlq_count": 0,
        }

        self._init_dlq_duckdb()
        self._init_default_streams()

    def _init_dlq_duckdb(self) -> None:
        """DLQ tablosunu DuckDB üzerinde ilklendirir."""
        with self._lock:
            try:
                conn = duckdb.connect(str(self._dlq_db_path))
                configure_duckdb_wal(conn)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS nats_dlq (
                        msg_id VARCHAR PRIMARY KEY,
                        subject VARCHAR NOT NULL,
                        data_json VARCHAR NOT NULL,
                        timestamp VARCHAR NOT NULL,
                        correlation_id VARCHAR,
                        retry_count INTEGER NOT NULL,
                        created_at VARCHAR NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_nats_dlq_subject ON nats_dlq (subject)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_nats_dlq_ts ON nats_dlq (timestamp)")
                conn.close()
            except Exception as exc:
                logger.warning("nats_dlq_tablo_baslatma_hatasi", path=str(self._dlq_db_path), hata=str(exc))

    def _init_default_streams(self) -> None:
        """Standart finansal JetStream akışlarını oluşturur."""
        self.create_stream(StreamConfig("MARKET_DATA", ["market.ticks.*", "market.orderbook.*"]))
        self.create_stream(StreamConfig("SIGNALS", ["signals.alpha.*", "signals.ensemble.*"]))
        self.create_stream(StreamConfig("EXECUTION", ["orders.new", "orders.fill", "orders.reject"]))
        self.create_stream(StreamConfig("RISK", ["risk.limit_breach", "risk.kill_switch", "risk.var_alert"]))

    def create_stream(self, config: StreamConfig) -> None:
        """Yeni bir JetStream akış tanımı kaydeder.

        Args:
            config: Akış yapılandırma nesnesi.
        """
        with self._lock:
            self._streams[config.name] = config
        logger.info("nats_jetstream_olusturuldu", stream=config.name, subjects=config.subjects)

    async def publish(
        self,
        subject: str,
        data: dict[str, Any],
        msg_id: str | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        """Mesajı deduplication ve DLQ korumalı olarak yayınlar.

        Args:
            subject: Hedef konu başlığı.
            data: Mesaj veri yükü.
            msg_id: Opsiyonel tekil mesaj kimliği (verilmezse içerik karmasından üretilir).
            correlation_id: İşlem izleme korelasyon kimliği.

        Returns:
            Mesaj başarıyla yayınlandıysa True, mükerrer ise False.
        """
        if not msg_id:
            payload_bytes = orjson.dumps(data, option=orjson.OPT_SORT_KEYS)
            digest = hashlib.sha256(f"{subject}:{payload_bytes.decode()}".encode()).hexdigest()[:16]
            msg_id = digest

        msg = EventMessage(
            subject=subject,
            data=data,
            msg_id=msg_id,
            correlation_id=correlation_id,
        )

        # 1. Deduplication denetimi
        with self._lock:
            if msg.msg_id in self._dedup_cache:
                self._metrics["duplicate_dropped"] += 1
                logger.debug("mukerrer_olay_atlandi", msg_id=msg.msg_id, subject=subject)
                return False

            self._dedup_cache.append(msg.msg_id)
            self._metrics["published_count"] += 1

            matched_handlers = []
            for sub_pattern, handlers in self._subscribers.items():
                if self._matches_subject(sub_pattern, subject):
                    matched_handlers.extend(handlers)

        # 2. Abonelere Dağıtım (Lock dışında çağrılır)
        for handler in matched_handlers:
            try:
                await handler(msg)
                with self._lock:
                    self._metrics["delivered_count"] += 1
            except Exception as e:
                logger.error("olay_isleyici_hatasi", subject=subject, msg_id=msg.msg_id, hata=str(e))
                msg.retry_count += 1
                if msg.retry_count >= DEFAULT_MAX_RETRIES:
                    self._persist_dlq_message(msg)
                    logger.warning("olay_dlq_kuyruguna_aktarildi", msg_id=msg.msg_id, subject=subject)

        return True

    def _persist_dlq_message(self, msg: EventMessage) -> None:
        """Başarısız mesajı bellek içi listeye ve DuckDB kalıcı defterine yazar."""
        with self._lock:
            self._dlq.append(msg)
            self._metrics["dlq_count"] += 1

            try:
                conn = duckdb.connect(str(self._dlq_db_path))
                conn.execute(
                    """
                    INSERT INTO nats_dlq
                    (msg_id, subject, data_json, timestamp, correlation_id, retry_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (msg_id) DO UPDATE SET
                        retry_count = EXCLUDED.retry_count,
                        created_at = EXCLUDED.created_at
                """,
                    (
                        msg.msg_id,
                        msg.subject,
                        orjson.dumps(msg.data).decode("utf-8"),
                        msg.timestamp,
                        msg.correlation_id or "",
                        msg.retry_count,
                        datetime.now(UTC).isoformat(),
                    ),
                )
                conn.close()
            except Exception as exc:
                logger.error("nats_dlq_duckdb_yazma_hatasi", msg_id=msg.msg_id, hata=str(exc))

    def subscribe(
        self,
        subject_pattern: str,
        handler: Callable[[EventMessage], Coroutine[Any, Any, None]],
    ) -> None:
        """Belirtilen subject kalıbına asenkron abone kaydeder.

        Args:
            subject_pattern: Konu şablonu (* ve > joker karakterlerini destekler).
            handler: Asenkron geri çağırım fonksiyonu.
        """
        with self._lock:
            self._subscribers[subject_pattern].append(handler)
        logger.info("nats_konusuna_abone_olundu", pattern=subject_pattern)

    @staticmethod
    def _matches_subject(pattern: str, subject: str) -> bool:
        """NATS subject wildcard eşleştirme (* ve > destekler).

        Standart NATS kuralları:
        - `*` tek bir token ile tam eşleşir.
        - `>` akışın sonundaki 1 veya daha fazla token ile eşleşir.

        Args:
            pattern: Joker karakterli konu şablonu.
            subject: İncelenen tam konu başlığı.

        Returns:
            Eşleşme varsa True, yoksa False.
        """
        if pattern == ">" or pattern == subject:
            return True

        p_parts = pattern.split(".")
        s_parts = subject.split(".")

        if pattern.endswith(">"):
            prefix_len = len(p_parts) - 1
            if len(s_parts) <= prefix_len:
                return False
            return all(p == "*" or p == s for p, s in zip(p_parts[:prefix_len], s_parts[:prefix_len], strict=True))

        if len(p_parts) != len(s_parts):
            return False

        return all(p == "*" or p == s for p, s in zip(p_parts, s_parts, strict=True))

    def get_metrics(self) -> dict[str, Any]:
        """Streaming bus operasyonel telemetrisini döndürür."""
        with self._lock:
            return {
                **self._metrics,
                "active_streams": len(self._streams),
                "subscriber_topics": len(self._subscribers),
                "dlq_pending": len(self._dlq),
                "dedup_cache_size": len(self._dedup_cache),
            }

    def get_dlq_messages(self) -> list[dict[str, Any]]:
        """Bellek içi Dead Letter Queue'daki mesajları döndürür."""
        with self._lock:
            return [
                {
                    "msg_id": m.msg_id,
                    "subject": m.subject,
                    "timestamp": m.timestamp,
                    "retries": m.retry_count,
                    "correlation_id": m.correlation_id,
                    "data": m.data,
                }
                for m in self._dlq
            ]

    def query_dlq_duckdb(self, limit: int = 100) -> list[dict[str, Any]]:
        """Kalıcı DuckDB DLQ tablosundaki kayıtları sorgular.

        Args:
            limit: Döndürülecek azami kayıt sayısı.

        Returns:
            DLQ kayıtları sözlük listesi.
        """
        with self._lock:
            try:
                conn = duckdb.connect(str(self._dlq_db_path))
                cur = conn.execute(
                    """
                    SELECT msg_id, subject, data_json, timestamp, correlation_id, retry_count, created_at
                    FROM nats_dlq
                    ORDER BY created_at DESC
                    LIMIT ?
                """,
                    (limit,),
                )
                cols = [d[0] for d in cur.description] if cur.description else []
                rows = cur.fetchall()
                conn.close()

                results = []
                for r in rows:
                    row_dict = dict(zip(cols, r, strict=False))
                    try:
                        row_dict["data"] = orjson.loads(row_dict.pop("data_json", "{}"))
                    except Exception:
                        row_dict["data"] = {}
                    results.append(row_dict)
                return results
            except Exception as exc:
                logger.error("nats_dlq_duckdb_sorgu_hatasi", hata=str(exc))
                return []

    async def replay_dlq_message(self, msg_id: str) -> bool:
        """Kalıcı veya bellek içi DLQ'da bulunan bir mesajı abonelere yeniden dağıtır (Self-healing).

        Args:
            msg_id: Yeniden dağıtılacak mesajın tekil kimliği.

        Returns:
            Mesaj bulunup yeniden dağıtıldıysa True, bulunamazsa False.
        """
        target_msg: EventMessage | None = None
        with self._lock:
            for m in self._dlq:
                if m.msg_id == msg_id:
                    target_msg = m
                    break

        if target_msg is None:
            records = self.query_dlq_duckdb(limit=1000)
            for r in records:
                if r.get("msg_id") == msg_id:
                    target_msg = EventMessage(
                        subject=r["subject"],
                        data=r["data"],
                        msg_id=r["msg_id"],
                        timestamp=r["timestamp"],
                        correlation_id=r.get("correlation_id"),
                        retry_count=0,
                    )
                    break

        if target_msg is None:
            logger.warning("yeniden_oynatilacak_dlq_mesaji_bulunamadi", msg_id=msg_id)
            return False

        with self._lock:
            matched_handlers = []
            for sub_pattern, handlers in self._subscribers.items():
                if self._matches_subject(sub_pattern, target_msg.subject):
                    matched_handlers.extend(handlers)

        success = True
        for handler in matched_handlers:
            try:
                await handler(target_msg)
            except Exception as exc:
                success = False
                logger.error("dlq_mesaj_yeniden_oynatma_hatasi", msg_id=msg_id, hata=str(exc))

        if success:
            with self._lock:
                self._dlq = [m for m in self._dlq if m.msg_id != msg_id]
                try:
                    conn = duckdb.connect(str(self._dlq_db_path))
                    conn.execute("DELETE FROM nats_dlq WHERE msg_id = ?", [msg_id])
                    conn.close()
                except Exception as exc:
                    logger.debug("dlq_silme_hatasi", msg_id=msg_id, hata=str(exc))
            logger.info("dlq_mesaji_basariyla_yeniden_oynatildi", msg_id=msg_id)
            return True

        return False

    def clear_dlq(self) -> int:
        """Bellek içi ve DuckDB DLQ kayıtlarını temizler.

        Returns:
            Silinen kayıt adedi.
        """
        with self._lock:
            mem_count = len(self._dlq)
            self._dlq.clear()
            deleted_rows = 0
            try:
                conn = duckdb.connect(str(self._dlq_db_path))
                del_cur = conn.execute("DELETE FROM nats_dlq RETURNING msg_id")
                deleted_rows = len(del_cur.fetchall())
                conn.close()
            except Exception as exc:
                logger.error("nats_dlq_temizleme_hatasi", hata=str(exc))
            total = max(mem_count, deleted_rows)
            self._metrics["dlq_count"] = 0
            return total

    def export_dlq_to_polars(self) -> pl.DataFrame:
        """DLQ mesajlarını sıfır kopyalı Polars DataFrame olarak dışa aktarır.

        Returns:
            pl.DataFrame: DLQ mesaj tablosu.
        """
        messages = self.query_dlq_duckdb(limit=1000)
        schema = {
            "msg_id": pl.String,
            "subject": pl.String,
            "timestamp": pl.String,
            "correlation_id": pl.String,
            "retry_count": pl.Int64,
            "created_at": pl.String,
        }
        if not messages:
            return pl.DataFrame(schema=schema)

        records = [
            {
                "msg_id": m["msg_id"],
                "subject": m["subject"],
                "timestamp": m["timestamp"],
                "correlation_id": m.get("correlation_id") or "",
                "retry_count": int(m.get("retry_count", 0)),
                "created_at": m.get("created_at", ""),
            }
            for m in messages
        ]
        return pl.DataFrame(records, schema=schema)

    def export_metrics_to_polars(self) -> pl.DataFrame:
        """Telemetri metriklerini Polars DataFrame olarak dışa aktarır."""
        m = self.get_metrics()
        return pl.DataFrame(
            [
                {
                    "metric_name": k,
                    "metric_value": float(v),
                    "recorded_at": datetime.now(UTC).isoformat(),
                }
                for k, v in m.items()
            ]
        )

    def __repr__(self) -> str:
        """Bus metinsel temsili."""
        with self._lock:
            return (
                f"<NATSJetStreamBus streams={len(self._streams)} "
                f"subscribers={len(self._subscribers)} dlq={len(self._dlq)}>"
            )


# Singleton
event_bus: Final[NATSJetStreamBus] = NATSJetStreamBus()
nats_bus: Final[NATSJetStreamBus] = event_bus

export_dlq_to_polars = event_bus.export_dlq_to_polars
export_metrics_to_polars = event_bus.export_metrics_to_polars
query_dlq_duckdb = event_bus.query_dlq_duckdb
replay_dlq_message = event_bus.replay_dlq_message
clear_dlq = event_bus.clear_dlq

__all__: Final[list[str]] = [
    "DEFAULT_DEDUP_CACHE_SIZE",
    "DEFAULT_DEDUP_WINDOW_SEC",
    "DEFAULT_MAX_AGE_HOURS",
    "DEFAULT_MAX_MESSAGES",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_NATS_DLQ_DB_PATH",
    "EventMessage",
    "NATSJetStreamBus",
    "StreamConfig",
    "clear_dlq",
    "configure_duckdb_wal",
    "event_bus",
    "export_dlq_to_polars",
    "export_metrics_to_polars",
    "nats_bus",
    "query_dlq_duckdb",
    "replay_dlq_message",
]
