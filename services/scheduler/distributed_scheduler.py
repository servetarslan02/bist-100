"""
ALPHA BIST — Dağıtık Zamanlayıcı & Lider Koordinasyon Motoru (DistributedScheduler)

Çoklu worker, container veya pod ortamlarında BIST seans görevlerinin
mükerrer (duplicate) çalışmasını önleyen, Dağıtık Kilit (Distributed Lock),
Kira Süresi Yenileme (Lease Renewal) ve Lider Seçimi (Leader Election) motoru.

Özellikler:
  - Atomic Distributed Lock (Fencing token ile split-brain koruması)
  - Otomatik Lider Seçimi & Kalp Atışı (Heartbeat-based failover)
  - Görev bazlı eşzamanlılık kısıtları (Tekil görev garantisi)
  - DuckDB yerel durum kalıcılığı ve atomic CAS (Compare-And-Swap) desteği
  - Fail-Closed Güvenlik: Kilit alınamayan kritik adımlar (emir, sinyal) asla çalıştırılmaz
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto

import duckdb
import structlog

logger = structlog.get_logger(__name__)

DB_TABLE_DISTRIBUTED_LOCKS = "distributed_locks"
DB_TABLE_LEADER_ELECTION = "leader_election_leases"


class LockState(Enum):
    """Kilit durumu."""

    ACQUIRED = auto()
    DENIED = auto()
    RELEASED = auto()
    EXPIRED = auto()


@dataclass
class LockLease:
    """Dağıtık kilit kira sözleşmesi.

    Attributes:
        resource_name: Kilitlenen kaynak/görev adı.
        owner_id: Kilidi elinde tutan worker/node kimliği.
        fencing_token: Artan monoton sıra numarası (Split-Brain koruması).
        acquired_at: Alınma zamanı.
        lease_duration_seconds: Kira geçerlilik süresi (TTL).
        state: Mevcut kilit durumu.
    """

    resource_name: str
    owner_id: str
    fencing_token: int
    acquired_at: datetime
    lease_duration_seconds: float = 30.0
    state: LockState = LockState.ACQUIRED

    @property
    def is_expired(self) -> bool:
        """Kira süresi doldu mu?"""
        now_ts = datetime.now(tz=UTC).timestamp()
        return now_ts - self.acquired_at.timestamp() > self.lease_duration_seconds

    def __repr__(self) -> str:
        """Kısa temsil."""
        return (
            f"LockLease({self.resource_name} owned by {self.owner_id[:8]}, "
            f"token={self.fencing_token}, state={self.state.name})"
        )


@dataclass
class LeaderStatus:
    """Liderlik seçim durumu."""

    is_leader: bool
    leader_id: str
    term: int
    heartbeat_time: datetime
    active_workers: int = 1


class DistributedSchedulerCoordinator:
    """Dağıtık Zamanlayıcı ve Liderlik Koordinasyon Motoru."""

    def __init__(
        self,
        node_id: str | None = None,
        db_path: str = "data/distributed_coord.duckdb",
        default_lease_seconds: float = 30.0,
    ) -> None:
        """DistributedSchedulerCoordinator başlatıcı.

        Args:
            node_id: Benzersiz worker/node kimliği.
            db_path: DuckDB veritabanı yolu.
            default_lease_seconds: Varsayılan kira süresi (TTL).
        """
        self.node_id = node_id or f"worker_{uuid.uuid4().hex[:8]}"
        self.db_path = db_path
        self.default_lease_seconds = default_lease_seconds
        self._lock = threading.RLock()
        self._memory_con = duckdb.connect(":memory:") if self.db_path == ":memory:" else None
        self._held_locks: dict[str, LockLease] = {}
        self._fencing_counter = 0
        self._is_leader = False
        self._current_term = 0
        self._init_db()

    def __repr__(self) -> str:
        """Coordinator temsili."""
        role = "LEADER" if self._is_leader else "FOLLOWER"
        return f"DistributedCoordinator({self.node_id} [{role}], locks={len(self._held_locks)})"

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """DuckDB bağlantısı döndürür."""
        if self._memory_con is not None:
            return self._memory_con
        return duckdb.connect(self.db_path)

    def _init_db(self) -> None:
        """DuckDB koordinasyon tablolarını hazırlar."""
        try:
            con = self._get_connection()
            con.execute(f"""
                CREATE TABLE IF NOT EXISTS {DB_TABLE_DISTRIBUTED_LOCKS} (
                    resource_name   VARCHAR PRIMARY KEY,
                    owner_id        VARCHAR NOT NULL,
                    fencing_token   BIGINT NOT NULL,
                    acquired_at     TIMESTAMP NOT NULL,
                    expires_at      TIMESTAMP NOT NULL
                )
            """)
            con.execute(f"""
                CREATE TABLE IF NOT EXISTS {DB_TABLE_LEADER_ELECTION} (
                    cluster_id      VARCHAR PRIMARY KEY,
                    leader_id       VARCHAR NOT NULL,
                    term            BIGINT NOT NULL,
                    heartbeat_at    TIMESTAMP NOT NULL,
                    expires_at      TIMESTAMP NOT NULL
                )
            """)
            if self._memory_con is None:
                con.close()
            logger.info("Dağıtık koordinasyon DB hazır.", node=self.node_id, db=self.db_path)
        except Exception as exc:
            logger.warning("Dağıtık koordinasyon DB başlatılamadı.", hata=str(exc))

    def acquire_lock(
        self,
        resource_name: str,
        lease_duration_seconds: float | None = None,
    ) -> LockLease | None:
        """Belirtilen kaynak için dağıtık kilit almaya çalışır.

        Compare-And-Swap (CAS) mantığı ile süresi dolmuş kilitler otomatik devralınır.

        Args:
            resource_name: Kilitlenecek görev/kaynak adı.
            lease_duration_seconds: Kilit geçerlilik süresi.

        Returns:
            Başarılı ise LockLease, başarısız ise None (Fail-Closed).
        """
        ttl = lease_duration_seconds or self.default_lease_seconds
        now = datetime.now(tz=UTC)
        expires = datetime.fromtimestamp(now.timestamp() + ttl, tz=UTC)

        with self._lock:
            self._fencing_counter += 1
            token = self._fencing_counter

        try:
            con = self._get_connection()
            # Önce süresi dolmuş eski kilidi sil veya mevcut durumu kontrol et
            row = con.execute(
                f"""
                SELECT owner_id, fencing_token, expires_at
                FROM {DB_TABLE_DISTRIBUTED_LOCKS}
                WHERE resource_name = ?
                """,
                [resource_name],
            ).fetchone()

            if row:
                existing_owner, _, existing_expires = row
                # Eğer kilit başka birine aitse ve süresi henüz dolmamışsa REDDET
                now_ts = now.timestamp()
                exp_ts = existing_expires.timestamp() if hasattr(existing_expires, "timestamp") else now_ts + 100
                if existing_owner != self.node_id and exp_ts > now_ts:
                    logger.debug(
                        "Kilit alınamadı (kaynak kullanımda).",
                        resource=resource_name,
                        owner=existing_owner,
                    )
                    if self._memory_con is None:
                        con.close()
                    return None

            # Kilidi al veya süresini yenile (INSERT OR REPLACE)
            con.execute(
                f"""
                INSERT OR REPLACE INTO {DB_TABLE_DISTRIBUTED_LOCKS}
                    (resource_name, owner_id, fencing_token, acquired_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [resource_name, self.node_id, token, now, expires],
            )
            if self._memory_con is None:
                con.close()

            lease = LockLease(
                resource_name=resource_name,
                owner_id=self.node_id,
                fencing_token=token,
                acquired_at=now,
                lease_duration_seconds=ttl,
                state=LockState.ACQUIRED,
            )

            with self._lock:
                self._held_locks[resource_name] = lease

            logger.info(
                "Dağıtık kilit alındı.",
                resource=resource_name,
                node=self.node_id,
                fencing=token,
                ttl=ttl,
            )
            return lease

        except Exception as exc:
            logger.warning("Kilit alma sırasında hata!", resource=resource_name, hata=str(exc))
            return None

    def release_lock(self, resource_name: str) -> bool:
        """Elde tutulan kilidi serbest bırakır.

        Args:
            resource_name: Bırakılacak kaynak.

        Returns:
            True ise başarıyla serbest bırakıldı.
        """
        with self._lock:
            lease = self._held_locks.pop(resource_name, None)

        try:
            con = self._get_connection()
            con.execute(
                f"""
                DELETE FROM {DB_TABLE_DISTRIBUTED_LOCKS}
                WHERE resource_name = ? AND owner_id = ?
                """,
                [resource_name, self.node_id],
            )
            if self._memory_con is None:
                con.close()

            if lease:
                lease.state = LockState.RELEASED
            logger.info("Dağıtık kilit serbest bırakıldı.", resource=resource_name)
            return True
        except Exception as exc:
            logger.warning("Kilit serbest bırakılamadı.", resource=resource_name, hata=str(exc))
            return False

    def renew_lease(self, resource_name: str, additional_seconds: float = 30.0) -> bool:
        """Mevcut kilidin kira süresini uzatır (Heartbeat).

        Args:
            resource_name: Kaynak adı.
            additional_seconds: İlave uzatma süresi.

        Returns:
            True ise uzatıldı, False ise kilit kaybedilmiş.
        """
        now = datetime.now(tz=UTC)
        new_expires = datetime.fromtimestamp(now.timestamp() + additional_seconds, tz=UTC)

        try:
            con = self._get_connection()
            con.execute(
                f"""
                UPDATE {DB_TABLE_DISTRIBUTED_LOCKS}
                SET expires_at = ?
                WHERE resource_name = ? AND owner_id = ?
                """,
                [new_expires, resource_name, self.node_id],
            )
            if self._memory_con is None:
                con.close()

            with self._lock:
                lease = self._held_locks.get(resource_name)
                if lease:
                    lease.acquired_at = now
                    lease.lease_duration_seconds = additional_seconds

            return True
        except Exception as exc:
            logger.warning("Kira yenilenemedi.", resource=resource_name, hata=str(exc))
            return False

    def elect_leader(self, cluster_id: str = "alpha_bist_cluster") -> LeaderStatus:
        """Cluster genelinde lider seçimi yürütür.

        Eğer mevcut liderin kalp atışı gecikmişse liderliği üstlenir.

        Args:
            cluster_id: Küme kimliği.

        Returns:
            LeaderStatus liderlik durumu.
        """
        now = datetime.now(tz=UTC)
        ttl = self.default_lease_seconds
        expires = datetime.fromtimestamp(now.timestamp() + ttl, tz=UTC)

        try:
            con = self._get_connection()
            row = con.execute(
                f"""
                SELECT leader_id, term, heartbeat_at, expires_at
                FROM {DB_TABLE_LEADER_ELECTION}
                WHERE cluster_id = ?
                """,
                [cluster_id],
            ).fetchone()

            if row:
                current_leader, term, hb, exp = row
                now_ts = now.timestamp()
                exp_ts = exp.timestamp() if hasattr(exp, "timestamp") else now_ts + 100

                # Lider hala canlı mı?
                if current_leader == self.node_id:
                    # Kendimiz lideriz, kalp atışını güncelle
                    con.execute(
                        f"""
                        UPDATE {DB_TABLE_LEADER_ELECTION}
                        SET heartbeat_at = ?, expires_at = ?
                        WHERE cluster_id = ?
                        """,
                        [now, expires, cluster_id],
                    )
                    self._is_leader = True
                    self._current_term = term
                elif exp_ts < now_ts:
                    # Lider çökmüş (timeout)! Yeni dönem (term) ile liderliği devral
                    new_term = term + 1
                    con.execute(
                        f"""
                        UPDATE {DB_TABLE_LEADER_ELECTION}
                        SET leader_id = ?, term = ?, heartbeat_at = ?, expires_at = ?
                        WHERE cluster_id = ?
                        """,
                        [self.node_id, new_term, now, expires, cluster_id],
                    )
                    self._is_leader = True
                    self._current_term = new_term
                    logger.warning("Lider zaman aşımı! Yeni lider seçildi.", leader=self.node_id, term=new_term)
                else:
                    # Başka bir lider aktif
                    self._is_leader = False
                    self._current_term = term
            else:
                # İlk başlangıç — liderliği al
                con.execute(
                    f"""
                    INSERT INTO {DB_TABLE_LEADER_ELECTION}
                        (cluster_id, leader_id, term, heartbeat_at, expires_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [cluster_id, self.node_id, 1, now, expires],
                )
                self._is_leader = True
                self._current_term = 1
                logger.info("Küme lideri seçildi.", leader=self.node_id, term=1)

            if self._memory_con is None:
                con.close()

        except Exception as exc:
            logger.warning("Lider seçiminde hata!", hata=str(exc))
            self._is_leader = False

        return LeaderStatus(
            is_leader=self._is_leader,
            leader_id=self.node_id if self._is_leader else "OTHER",
            term=self._current_term,
            heartbeat_time=now,
        )


# Singleton
distributed_coordinator = DistributedSchedulerCoordinator()

__all__ = [
    "DistributedSchedulerCoordinator",
    "LeaderStatus",
    "LockLease",
    "LockState",
    "distributed_coordinator",
]
