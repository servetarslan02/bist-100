"""
ALPHA BIST — Değiştirilemez ve Doğrulanabilir Denetim Günlüğü (Audit Log Immutability Enforcement)

Sistem genelindeki tüm kritik işlemleri (CREATE, UPDATE, DELETE, EXECUTE vb.)
kriptografik hash zinciri (hash chain) ile güvenceye alır ve kurcalamaya (tamper) karşı korur.

Özellikler:
1. Kriptografik SHA-256 Hash Zinciri (Her kayıt önceki kaydın özetine zincirlenir)
2. Bütünlük ve Kurcalama Doğrulama (Hash Chain Tamper Detection)
3. SSD Dostu Yığınlı / Debounced Kalıcı Saklama (Batched Append-Only)
4. PostgreSQL / DuckDB Düzeyinde Değiştirilemezlik (Immutability) Tetikleyici Şablonları
5. Polars DataFrame ve DuckDB Tablosu (`bist_immutable_audit`) Entegrasyonu
6. Thread-Safe (threading.RLock) Eşzamanlı Erişim Koruması
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from types import TracebackType

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# =====================================================
# SABİTLER (CONSTANTS)
# =====================================================

DEFAULT_MAX_IN_MEMORY_ENTRIES: Final[int] = 1000
DEFAULT_IMMUTABLE_MAX_IN_MEMORY_ENTRIES: Final[int] = DEFAULT_MAX_IN_MEMORY_ENTRIES
DEFAULT_FLUSH_INTERVAL_SECONDS: Final[float] = 60.0
DEFAULT_BATCH_FLUSH_SIZE: Final[int] = 10
DEFAULT_AUDIT_DB_PATH: Final[Path] = Path("data/duckdb/alpha_bist_audit.duckdb")
DEFAULT_IMMUTABLE_AUDIT_DB_PATH: Final[Path] = DEFAULT_AUDIT_DB_PATH
DEFAULT_AUDIT_TABLE_NAME: Final[str] = "bist_immutable_audit"
DEFAULT_QUERY_LIMIT: Final[int] = 100
DEFAULT_IMMUTABLE_QUERY_LIMIT: Final[int] = DEFAULT_QUERY_LIMIT
GENESIS_HASH: Final[str] = "genesis_block_hash_alpha_bist_v1"


class AuditAction(StrEnum):
    """Denetim günlüğü işlem tipleri."""

    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    EXECUTE = "EXECUTE"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"


# =====================================================
# VERİ MODELLERİ (DATA MODELS)
# =====================================================


@dataclass(slots=True)
class AuditEntry:
    """Kriptografik olarak mühürlenebilir denetim günlüğü kaydı.

    Attributes:
        entry_id: Benzersiz işlem kayıt kimliği (UUID/Hash).
        timestamp: Kaydın oluşturulduğu UTC zaman damgası.
        user_id: İşlemi gerçekleştiren kullanıcı veya servis hesabı kimliği.
        action: Gerçekleştirilen işlem türü (CREATE, UPDATE vb.).
        resource_type: Etkilenen kaynak tipi (portfolio, order, config, model vb.).
        resource_id: Etkilenen kaynağın tekil kimliği.
        details: İşleme ait yapılandırılmış ayrıntı sözlüğü.
        ip_address: İstek yapan istemcinin IP adresi.
        user_agent: İstemci tarayıcı veya servis tanımlayıcısı.
        previous_hash: Zincirdeki bir önceki kaydın SHA-256 özeti.
        entry_hash: Bu kaydın hesaplanan ve mühürlenen SHA-256 özeti.
    """

    entry_id: str
    timestamp: datetime
    user_id: str
    action: str
    resource_type: str
    resource_id: str
    details: dict[str, Any]
    ip_address: str | None = None
    user_agent: str | None = None
    previous_hash: str = ""
    entry_hash: str = ""

    def compute_hash(self, previous_hash: str = "") -> str:
        """Kayıt içeriği ve önceki özetten SHA-256 hash üretir.

        Args:
            previous_hash: Bir önceki kaydın hash değeri (boş ise nesnedeki değer kullanılır).

        Returns:
            str: 32 karakterlik SHA-256 heksadesimal özeti.
        """
        prev = previous_hash if previous_hash else self.previous_hash
        content_dict = {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": self.details,
            "ip_address": self.ip_address or "",
            "user_agent": self.user_agent or "",
        }
        content_bytes = orjson.dumps(content_dict, option=orjson.OPT_SORT_KEYS, default=str)
        payload = f"{prev}:".encode() + content_bytes
        return hashlib.sha256(payload).hexdigest()[:32]

    def seal(self, previous_hash: str = "") -> str:
        """Kaydı önceki kayıt özetine zincirleyerek mühürler (immutable seal).

        Args:
            previous_hash: Önceki kaydın özet değeri.

        Returns:
            str: Üretilen mühür özeti (entry_hash).
        """
        self.previous_hash = previous_hash
        self.entry_hash = self.compute_hash(previous_hash)
        return self.entry_hash

    def to_dict(self) -> dict[str, Any]:
        """Modeli serileştirilebilir Python sözlüğüne dönüştürür.

        Returns:
            dict[str, Any]: Model alanlarının sözlük karşılığı.
        """
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": self.details,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "previous_hash": self.previous_hash,
            "entry_hash": self.entry_hash,
        }

    def to_orjson_bytes(self) -> bytes:
        """Modeli yüksek performanslı JSON bayt dizisine dönüştürür.

        Returns:
            bytes: orjson kodlu bayt dizisi.
        """
        return orjson.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditEntry:
        """Sözlükten AuditEntry nesnesi oluşturur.

        Args:
            data: Model verilerini içeren sözlük.

        Returns:
            AuditEntry: Oluşturulan denetim kaydı örneği.
        """
        ts = data.get("timestamp")
        if isinstance(ts, str):
            try:
                ts_parsed = datetime.fromisoformat(ts)
            except Exception:
                ts_parsed = datetime.now(UTC)
        elif isinstance(ts, datetime):
            ts_parsed = ts
        else:
            ts_parsed = datetime.now(UTC)

        return cls(
            entry_id=str(data.get("entry_id", "")),
            timestamp=ts_parsed,
            user_id=str(data.get("user_id", "system")),
            action=str(data.get("action", AuditAction.EXECUTE.value)),
            resource_type=str(data.get("resource_type", "unknown")),
            resource_id=str(data.get("resource_id", "unknown")),
            details=dict(data.get("details", {})),
            ip_address=data.get("ip_address"),
            user_agent=data.get("user_agent"),
            previous_hash=str(data.get("previous_hash", "")),
            entry_hash=str(data.get("entry_hash", "")),
        )

    @classmethod
    def from_json(cls, json_data: str | bytes) -> AuditEntry:
        """JSON metni veya bayt dizisinden AuditEntry nesnesi oluşturur.

        Args:
            json_data: JSON string veya bayt verisi.

        Returns:
            AuditEntry: Oluşturulan denetim kaydı nesnesi.
        """
        parsed = orjson.loads(json_data)
        return cls.from_dict(parsed)

    def __repr__(self) -> str:
        """Açıklayıcı Türkçe metin gösterimi.

        Returns:
            str: Kayıt özeti.
        """
        return (
            f"AuditEntry(id='{self.entry_id}', kullanici='{self.user_id}', "
            f"islem='{self.action}', kaynak='{self.resource_type}:{self.resource_id}', "
            f"muhur='{self.entry_hash[:8]}...')"
        )


@dataclass(slots=True)
class ComplianceReport:
    """Yasal ve kurumsal denetim uyumluluk raporu modeli.

    Attributes:
        report_time: Raporun oluşturulduğu UTC zaman damgası.
        period_since: Analiz edilen dönemin başlangıç zamanı.
        entries_count: İncelenen kayıt adedi.
        is_valid: Hash zincirinin kırılmamış ve geçerli olup olmadığı.
        error: Varsa bütünlük bozulma hata detayı.
        total_verified: Bugüne kadar yapılan toplam doğrulama sayısı.
        actions: İşlem tiplerine göre frekans dağılımı.
        user_activity: Kullanıcı bazlı işlem adetleri ve son hareketleri.
        latest_hash: Zincirin en son halkasının özet değeri.
    """

    report_time: str
    period_since: str
    entries_count: int
    is_valid: bool
    error: str | None
    total_verified: int
    actions: dict[str, int]
    user_activity: dict[str, dict[str, Any]]
    latest_hash: str | None

    def to_dict(self) -> dict[str, Any]:
        """Raporu sözlük yapısına dönüştürür.

        Returns:
            dict[str, Any]: Sözlük formatında rapor.
        """
        return {
            "report_time": self.report_time,
            "period": {
                "since": self.period_since,
                "entries_count": self.entries_count,
            },
            "integrity": {
                "is_valid": self.is_valid,
                "error": self.error,
                "total_verified": self.total_verified,
            },
            "actions": self.actions,
            "user_activity": self.user_activity,
            "hash_chain": {
                "genesis": GENESIS_HASH,
                "latest": self.latest_hash,
                "chain_length": self.entries_count,
            },
        }

    def to_orjson_bytes(self) -> bytes:
        """Raporu JSON bayt dizisine dönüştürür.

        Returns:
            bytes: orjson kodlu baytlar.
        """
        return orjson.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComplianceReport:
        """Sözlükten ComplianceReport nesnesi oluşturur.

        Args:
            data: Model verilerini içeren sözlük.

        Returns:
            ComplianceReport: Oluşturulan uyumluluk raporu.
        """
        period = data.get("period", {}) if isinstance(data.get("period"), dict) else {}
        integrity = data.get("integrity", {}) if isinstance(data.get("integrity"), dict) else {}
        hash_chain = data.get("hash_chain", {}) if isinstance(data.get("hash_chain"), dict) else {}

        return cls(
            report_time=str(data.get("report_time", datetime.now(UTC).isoformat())),
            period_since=str(period.get("since", data.get("period_since", "all_time"))),
            entries_count=int(period.get("entries_count", data.get("entries_count", 0))),
            is_valid=bool(integrity.get("is_valid", data.get("is_valid", False))),
            error=integrity.get("error", data.get("error")),
            total_verified=int(integrity.get("total_verified", data.get("total_verified", 0))),
            actions=dict(data.get("actions", {})),
            user_activity=dict(data.get("user_activity", {})),
            latest_hash=hash_chain.get("latest", data.get("latest_hash")),
        )

    @classmethod
    def from_json(cls, json_data: str | bytes) -> ComplianceReport:
        """JSON metni veya bayt dizisinden ComplianceReport nesnesi oluşturur.

        Args:
            json_data: JSON string veya bayt verisi.

        Returns:
            ComplianceReport: Oluşturulan uyumluluk raporu örneği.
        """
        parsed = orjson.loads(json_data)
        return cls.from_dict(parsed)

    def __repr__(self) -> str:
        """Rapor metin gösterimi.

        Returns:
            str: Rapor özeti.
        """
        durum = "GEÇERLİ" if self.is_valid else "BOZUK"
        return f"ComplianceReport(zaman={self.report_time}, kayit={self.entries_count}, durum='{durum}')"


# =====================================================
# DEĞİŞTİRİLEMEZ DENETİM GÜNLÜĞÜ (IMMUTABLE AUDIT LOG)
# =====================================================


class ImmutableAuditLog:
    """Kriptografik hash zinciri ile güvence altına alınmış değiştirilemez denetim motoru.

    Her kayıt bir önceki kaydın SHA-256 özetine bağlanır. Zincirdeki herhangi bir
    kaydın veya alanın değiştirilmesi sonraki tüm özetleri geçersiz kılarak derhal
    kurcalama alarmı üretir.
    """

    def __init__(self, storage_path: str | Path | None = None) -> None:
        """Denetim günlüğü servisini başlatır.

        Args:
            storage_path: Disk üzerinde append-only yazılacak dosya yolu (None ise hafıza içi çalışır).
        """
        self._lock = threading.RLock()
        self._entries: list[AuditEntry] = []
        self._last_hash: str = GENESIS_HASH
        self._storage_path: Path | None = Path(storage_path) if storage_path is not None else None
        self._total_entries: int = 0
        self._total_verified: int = 0
        self._pending_entries: list[bytes] = []
        self._last_flush: float = time.time()

        if self._storage_path:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)

    def __enter__(self) -> ImmutableAuditLog:
        """Context manager giriş protokolü."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager çıkış protokolü; bekleyen tüm kayıtları diske boşaltır."""
        self.flush()

    def shutdown(self) -> None:
        """Denetim günlüğü servisini güvenli şekilde kapatır ve tamponları boşaltır."""
        self.flush()
        logger.info("immutable_audit_kapatildi", toplam_islenen=self._total_entries)

    @otel_trace("immutable_audit.log")
    def log(
        self,
        user_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditEntry:
        """Yeni bir denetim kaydı oluşturur, hash zincirine bağlar ve mühürler.

        Args:
            user_id: İşlemi tetikleyen aktör veya sistem servisi kimliği.
            action: İşlem türü (ör: CREATE, UPDATE, EXECUTE).
            resource_type: Hedef kaynak türü (ör: position, order, config).
            resource_id: Hedef kaynak kimliği.
            details: İlave yapılandırılmış operasyon parametreleri.
            ip_address: İstemci IP adresi.
            user_agent: İstemci istemci imzası.

        Returns:
            AuditEntry: Kriptografik olarak mühürlenmiş değiştirilemez kayıt.
        """
        norm_user_id = user_id.strip() if user_id and user_id.strip() else "system"
        norm_action = action.strip().upper() if action and action.strip() else AuditAction.EXECUTE.value
        norm_res_type = resource_type.strip() if resource_type and resource_type.strip() else "unknown"
        norm_res_id = resource_id.strip() if resource_id and resource_id.strip() else "unknown"
        safe_details = details if details is not None else {}

        with self._lock:
            now = datetime.now(UTC)
            unique_seed = f"audit_{norm_user_id}_{norm_action}_{norm_res_type}_{norm_res_id}_{time.time_ns()}".encode()
            entry_id = hashlib.sha256(unique_seed).hexdigest()[:16]

            entry = AuditEntry(
                entry_id=entry_id,
                timestamp=now,
                user_id=norm_user_id,
                action=norm_action,
                resource_type=norm_res_type,
                resource_id=norm_res_id,
                details=safe_details,
                ip_address=ip_address.strip() if ip_address else None,
                user_agent=user_agent.strip() if user_agent else None,
            )

            entry.seal(self._last_hash)
            self._last_hash = entry.entry_hash

            self._entries.append(entry)
            if len(self._entries) > DEFAULT_MAX_IN_MEMORY_ENTRIES:
                self._entries = self._entries[-DEFAULT_MAX_IN_MEMORY_ENTRIES:]

            self._total_entries += 1

            logger.info(
                "denetim_kaydi_eklendi",
                entry_id=entry_id,
                user_id=norm_user_id,
                islem=norm_action,
                kaynak=f"{norm_res_type}:{norm_res_id}",
                muhur=entry.entry_hash[:12],
            )

            if self._storage_path:
                self._persist_entry(entry)

            return entry

    @otel_trace("immutable_audit.verify_integrity")
    def verify_integrity(self) -> tuple[bool, str | None]:
        """Tüm bellek içi hash zincirinin kriptografik bütünlüğünü doğrular.

        Zincirdeki her kaydın previous_hash bağı ve kendi SHA-256 içeriği
        baştan sona yeniden hesaplanarak kontrol edilir.

        Returns:
            tuple[bool, str | None]: (Bütünlük geçerli ise True, hata mesajı veya None).
        """
        with self._lock:
            if not self._entries:
                return True, None

            # İlk kaydın genesis bağı kontrolü (eğer başlangıç bloğu halen bellekteyse)
            if self._total_entries == len(self._entries):
                if self._entries[0].previous_hash != GENESIS_HASH:
                    hata = (
                        f"İlk kaydın Genesis bağı geçersiz (id={self._entries[0].entry_id}): "
                        f"beklenen={GENESIS_HASH[:12]}, bulunan={self._entries[0].previous_hash[:12]}"
                    )
                    logger.critical("denetim_genesis_uyusmazligi", hata=hata)
                    return False, hata

            prev_hash = self._entries[0].previous_hash

            for i, entry in enumerate(self._entries):
                if entry.previous_hash != prev_hash:
                    hata = (
                        f"Hash zinciri {i}. kayıtta bozuldu (id={entry.entry_id}): "
                        f"beklenen önceki={prev_hash[:12]}, bulunan={entry.previous_hash[:12]}"
                    )
                    logger.critical("denetim_zinciri_bozuldu", index=i, hata=hata)
                    return False, hata

                expected_hash = entry.compute_hash(prev_hash)
                if entry.entry_hash != expected_hash:
                    hata = (
                        f"Kayıt özeti uyuşmazlığı tespit edildi (id={entry.entry_id}): "
                        f"hesaplanan={expected_hash[:12]}, kayitli={entry.entry_hash[:12]}"
                    )
                    logger.critical("denetim_kayit_ozeti_uyusmuyor", index=i, hata=hata)
                    return False, hata

                prev_hash = entry.entry_hash

            self._total_verified += 1
            return True, None

    @otel_trace("immutable_audit.get_entries")
    def get_entries(
        self,
        user_id: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Kriterlere göre filtrelenmiş denetim kayıtlarını döndürür.

        Args:
            user_id: Kullanıcı filtresi.
            action: İşlem türü filtresi.
            resource_type: Kaynak türü filtresi.
            since: Bu zamandan sonraki kayıtlar.
            limit: Maksimum kayıt sayısı.

        Returns:
            list[dict[str, Any]]: Filtrelenmiş kayıtların sözlük listesi.
        """
        with self._lock:
            entries = list(self._entries)

            if user_id:
                entries = [e for e in entries if e.user_id == user_id]
            if action:
                entries = [e for e in entries if e.action == action]
            if resource_type:
                entries = [e for e in entries if e.resource_type == resource_type]
            if since:
                entries = [e for e in entries if e.timestamp >= since]

            entries.sort(key=lambda e: e.timestamp, reverse=True)
            return [e.to_dict() for e in entries[:limit]]

    @otel_trace("immutable_audit.get_stats")
    def get_stats(self) -> dict[str, Any]:
        """Denetim günlüğü çalışma ve dağılım istatistiklerini döndürür.

        Returns:
            dict[str, Any]: İstatistiksel metrikler sözlüğü.
        """
        with self._lock:
            by_action: dict[str, int] = {}
            by_user: dict[str, int] = {}
            by_resource: dict[str, int] = {}

            for entry in self._entries:
                by_action[entry.action] = by_action.get(entry.action, 0) + 1
                by_user[entry.user_id] = by_user.get(entry.user_id, 0) + 1
                by_resource[entry.resource_type] = by_resource.get(entry.resource_type, 0) + 1

            return {
                "total_entries": self._total_entries,
                "total_verified": self._total_verified,
                "current_entries": len(self._entries),
                "last_hash": self._last_hash[:16] if self._last_hash else None,
                "by_action": by_action,
                "by_user": by_user,
                "by_resource_type": by_resource,
            }

    @otel_trace("immutable_audit.generate_compliance_report")
    def generate_compliance_report(
        self,
        since: datetime | None = None,
    ) -> ComplianceReport:
        """Denetim günlüğü bütünlüğünü teyit eder ve uyumluluk raporu üretir.

        Args:
            since: Rapor başlangıç zamanı (None ise tüm geçmiş).

        Returns:
            ComplianceReport: Doğrulanmış uyumluluk rapor modeli.
        """
        with self._lock:
            entries = list(self._entries)
            if since:
                entries = [e for e in entries if e.timestamp >= since]

            is_valid, error = self.verify_integrity()

            actions: dict[str, int] = {}
            for entry in entries:
                actions[entry.action] = actions.get(entry.action, 0) + 1

            user_activity: dict[str, dict[str, Any]] = {}
            for entry in entries:
                if entry.user_id not in user_activity:
                    user_activity[entry.user_id] = {"count": 0, "last_action": None}
                user_activity[entry.user_id]["count"] += 1
                user_activity[entry.user_id]["last_action"] = entry.timestamp.isoformat()

            return ComplianceReport(
                report_time=datetime.now(UTC).isoformat(),
                period_since=since.isoformat() if since else "all_time",
                entries_count=len(entries),
                is_valid=is_valid,
                error=error,
                total_verified=self._total_verified,
                actions=actions,
                user_activity=user_activity,
                latest_hash=self._last_hash[:16] if self._last_hash else None,
            )

    # -------------------------------------------------
    # POLARS VE DUCKDB VERİ ENTEGRASYONU
    # -------------------------------------------------

    def export_to_polars(self, limit: int = DEFAULT_MAX_IN_MEMORY_ENTRIES) -> pl.DataFrame:
        """Kayıtları Polars DataFrame olarak dışa aktarır.

        Args:
            limit: Döndürülecek maksimum kayıt sayısı.

        Returns:
            pl.DataFrame: Denetim zinciri tablosu.
        """
        with self._lock:
            schema = {
                "entry_id": pl.String,
                "timestamp": pl.Datetime(time_zone="UTC"),
                "user_id": pl.String,
                "action": pl.String,
                "resource_type": pl.String,
                "resource_id": pl.String,
                "details_json": pl.String,
                "ip_address": pl.String,
                "user_agent": pl.String,
                "previous_hash": pl.String,
                "entry_hash": pl.String,
            }

            if not self._entries:
                return pl.DataFrame(schema=schema)

            selected = self._entries[-limit:]
            rows = [
                {
                    "entry_id": e.entry_id,
                    "timestamp": e.timestamp,
                    "user_id": e.user_id,
                    "action": e.action,
                    "resource_type": e.resource_type,
                    "resource_id": e.resource_id,
                    "details_json": orjson.dumps(e.details, default=str).decode("utf-8"),
                    "ip_address": e.ip_address or "",
                    "user_agent": e.user_agent or "",
                    "previous_hash": e.previous_hash,
                    "entry_hash": e.entry_hash,
                }
                for e in selected
            ]
            return pl.DataFrame(rows, schema=schema)

    def export_to_duckdb(
        self,
        db_path: str | Path | None = None,
        limit: int = DEFAULT_MAX_IN_MEMORY_ENTRIES,
    ) -> int:
        """Denetim zinciri kayıtlarını DuckDB `bist_immutable_audit` tablosuna yazar.

        Args:
            db_path: DuckDB dosya yolu.
            limit: Yazılacak maksimum kayıt sayısı.

        Returns:
            int: Eklenen veya güncellenen kayıt adedi.
        """
        df = self.export_to_polars(limit=limit)
        if df.is_empty():
            return 0

        target_path = Path(db_path) if db_path is not None else DEFAULT_AUDIT_DB_PATH
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists() and target_path.is_file() and target_path.stat().st_size == 0:
            target_path.unlink(missing_ok=True)

        con = duckdb.connect(str(target_path))
        try:
            con.execute(f"""
                CREATE TABLE IF NOT EXISTS {DEFAULT_AUDIT_TABLE_NAME} (
                    entry_id VARCHAR PRIMARY KEY,
                    timestamp TIMESTAMPTZ,
                    user_id VARCHAR,
                    action VARCHAR,
                    resource_type VARCHAR,
                    resource_id VARCHAR,
                    details_json VARCHAR,
                    ip_address VARCHAR,
                    user_agent VARCHAR,
                    previous_hash VARCHAR,
                    entry_hash VARCHAR,
                    inserted_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)
            arrow_table = df.to_arrow()
            con.register("audit_arrow", arrow_table)
            con.execute(f"""
                INSERT OR REPLACE INTO {DEFAULT_AUDIT_TABLE_NAME} (
                    entry_id, timestamp, user_id, action, resource_type,
                    resource_id, details_json, ip_address, user_agent, previous_hash, entry_hash
                )
                SELECT
                    entry_id, timestamp, user_id, action, resource_type,
                    resource_id, details_json, ip_address, user_agent, previous_hash, entry_hash
                FROM audit_arrow
            """)
            con.unregister("audit_arrow")
            con.commit()
            return len(df)
        finally:
            con.close()

    @otel_trace("immutable_audit.query_audit_duckdb")
    def query_audit_duckdb(
        self,
        db_path: str | Path | None = None,
        limit: int = DEFAULT_QUERY_LIMIT,
        user_id: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
    ) -> pl.DataFrame:
        """DuckDB bist_immutable_audit tablosundan denetim kayıtlarını Polars olarak sorgular.

        Args:
            db_path: DuckDB dosya yolu.
            limit: Maksimum satır sayısı.
            user_id: İsteğe bağlı kullanıcı filtresi.
            action: İsteğe bağlı işlem türü filtresi.
            resource_type: İsteğe bağlı kaynak türü filtresi.

        Returns:
            pl.DataFrame: Sorgu sonucu denetim kayıtları.
        """
        target_path = Path(db_path) if db_path is not None else DEFAULT_AUDIT_DB_PATH
        schema = {
            "entry_id": pl.String,
            "timestamp": pl.Datetime(time_zone="UTC"),
            "user_id": pl.String,
            "action": pl.String,
            "resource_type": pl.String,
            "resource_id": pl.String,
            "details_json": pl.String,
            "ip_address": pl.String,
            "user_agent": pl.String,
            "previous_hash": pl.String,
            "entry_hash": pl.String,
            "inserted_at": pl.Datetime(time_zone="UTC"),
        }

        if not target_path.exists() or (target_path.is_file() and target_path.stat().st_size == 0):
            return pl.DataFrame(schema=schema)

        con = duckdb.connect(str(target_path), read_only=True)
        try:
            tbl_check = con.execute(
                f"SELECT count(*) FROM information_schema.tables WHERE table_name = '{DEFAULT_AUDIT_TABLE_NAME}'"
            ).fetchone()
            if not tbl_check or tbl_check[0] == 0:
                return pl.DataFrame(schema=schema)

            query = f"SELECT * FROM {DEFAULT_AUDIT_TABLE_NAME} WHERE 1=1"
            params: list[Any] = []

            if user_id:
                query += " AND user_id = ?"
                params.append(user_id.strip())
            if action:
                query += " AND action = ?"
                params.append(action.strip().upper())
            if resource_type:
                query += " AND resource_type = ?"
                params.append(resource_type.strip())

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(max(1, limit))

            return con.execute(query, params).pl()
        except Exception as e:
            logger.error("duckdb_audit_sorgu_hatasi", dosya=str(target_path), hata=str(e))
            return pl.DataFrame(schema=schema)
        finally:
            con.close()

    @otel_trace("immutable_audit.verify_duckdb_integrity")
    def verify_duckdb_integrity(
        self,
        db_path: str | Path | None = None,
    ) -> tuple[bool, str | None]:
        """DuckDB'de depolanan bist_immutable_audit tablosunun zincir bütünlüğünü doğrular.

        Args:
            db_path: DuckDB dosya yolu.

        Returns:
            tuple[bool, str | None]: (Bütünlük geçerli ise True, hata mesajı).
        """
        target_path = Path(db_path) if db_path is not None else DEFAULT_AUDIT_DB_PATH
        if not target_path.exists() or (target_path.is_file() and target_path.stat().st_size == 0):
            return True, None

        con = duckdb.connect(str(target_path), read_only=True)
        try:
            tbl_check = con.execute(
                f"SELECT count(*) FROM information_schema.tables WHERE table_name = '{DEFAULT_AUDIT_TABLE_NAME}'"
            ).fetchone()
            if not tbl_check or tbl_check[0] == 0:
                return True, None

            rows = con.execute(
                f"""
                SELECT entry_id, timestamp, user_id, action, resource_type,
                       resource_id, details_json, ip_address, user_agent, previous_hash, entry_hash
                FROM {DEFAULT_AUDIT_TABLE_NAME}
                ORDER BY timestamp ASC
                """
            ).fetchall()

            if not rows:
                return True, None

            # Hash zinciri haritası oluştur: previous_hash -> row
            by_prev_hash: dict[str, Any] = {r[9]: r for r in rows}
            all_entry_hashes = {r[10] for r in rows}
            root_candidates = [r for r in rows if r[9] not in all_entry_hashes]

            if not root_candidates:
                hata = "DuckDB hash zincirinde döngü tespit edildi; kök kayıt bulunamadı."
                logger.critical("duckdb_denetim_zincir_dongusu", hata=hata)
                return False, hata

            # Genesis kökü varsa öncelikli seç, yoksa en erken zamanlı kökü seç
            genesis_roots = [r for r in root_candidates if r[9] == GENESIS_HASH]
            current_row = genesis_roots[0] if genesis_roots else min(root_candidates, key=lambda x: x[1])

            expected_prev = current_row[9]
            if genesis_roots and expected_prev != GENESIS_HASH:
                hata = (
                    f"DuckDB ilk kaydın Genesis bağı geçersiz (id={current_row[0]}): "
                    f"beklenen={GENESIS_HASH[:12]}, bulunan={expected_prev[:12]}"
                )
                logger.critical("duckdb_denetim_genesis_uyusmazligi", hata=hata)
                return False, hata

            visited_count = 0
            while current_row is not None:
                visited_count += 1
                entry_id, ts, u_id, act, r_type, r_id, det_json, ip, ua, prev_h, ent_h = current_row

                if prev_h != expected_prev:
                    hata = (
                        f"DuckDB hash zinciri {visited_count}. kayıtta bozuldu (id={entry_id}): "
                        f"beklenen={expected_prev[:12]}, bulunan={prev_h[:12]}"
                    )
                    logger.critical("duckdb_denetim_zinciri_bozuldu", index=visited_count, hata=hata)
                    return False, hata

                try:
                    details_dict = orjson.loads(det_json) if det_json else {}
                except Exception:
                    details_dict = {}

                if hasattr(ts, "astimezone"):
                    ts_utc = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
                    ts_iso = ts_utc.isoformat()
                elif hasattr(ts, "isoformat"):
                    ts_iso = ts.isoformat()
                else:
                    ts_iso = str(ts)
                content_dict = {
                    "entry_id": entry_id,
                    "timestamp": ts_iso,
                    "user_id": u_id,
                    "action": act,
                    "resource_type": r_type,
                    "resource_id": r_id,
                    "details": details_dict,
                    "ip_address": ip or "",
                    "user_agent": ua or "",
                }
                content_bytes = orjson.dumps(content_dict, option=orjson.OPT_SORT_KEYS, default=str)
                payload = f"{prev_h}:".encode() + content_bytes
                computed_hash = hashlib.sha256(payload).hexdigest()[:32]

                if ent_h != computed_hash:
                    hata = (
                        f"DuckDB kayıt özeti uyuşmazlığı tespit edildi (id={entry_id}): "
                        f"hesaplanan={computed_hash[:12]}, kayitli={ent_h[:12]}"
                    )
                    logger.critical("duckdb_denetim_kayit_ozeti_uyusmuyor", index=visited_count, hata=hata)
                    return False, hata

                expected_prev = ent_h
                current_row = by_prev_hash.get(ent_h)

            if visited_count != len(rows):
                hata = (
                    f"DuckDB hash zincirinde kopukluk var: {len(rows)} kayıttan yalnızca "
                    f"{visited_count} adedi zincirlenebildi."
                )
                logger.critical("duckdb_denetim_kopuk_zincir", toplam=len(rows), ziyaret=visited_count)
                return False, hata

            return True, None
        except Exception as e:
            logger.error("duckdb_butunluk_dogrulama_hatasi", hata=str(e))
            return False, str(e)
        finally:
            con.close()

    # -------------------------------------------------
    # KALICI DİSK YAZIMI VE TRIGGER ŞABLONLARI
    # -------------------------------------------------

    def _persist_entry(self, entry: AuditEntry, force: bool = False) -> None:
        """Kaydı disk dosyasına yığınlı (batched append-only) olarak yazar.

        SSD koruması amacıyla 10 kayıt veya 60 saniyelik debounce uygular.

        Args:
            entry: Kaydedilecek denetim girdisi.
            force: True ise beklemeden diske yazar.
        """
        if not self._storage_path:
            return

        try:
            serialized = entry.to_orjson_bytes() + b"\n"
        except Exception as e:
            logger.error("denetim_kaydi_serilestirme_hatasi", hata=str(e), entry_id=entry.entry_id)
            return

        with self._lock:
            self._pending_entries.append(serialized)

            now = time.time()
            if (
                not force
                and len(self._pending_entries) < DEFAULT_BATCH_FLUSH_SIZE
                and (now - self._last_flush < DEFAULT_FLUSH_INTERVAL_SECONDS)
            ):
                return

            chunks = self._pending_entries[:]
            try:
                with open(self._storage_path, "ab") as f:
                    for chunk in chunks:
                        f.write(chunk)
                self._pending_entries.clear()
                self._last_flush = now
            except Exception as e:
                logger.error("denetim_kaydi_kalici_yazma_hatasi", dosya=str(self._storage_path), hata=str(e))

    def flush(self) -> None:
        """Kuyrukta bekleyen tüm denetim kayıtlarını diske boşaltır."""
        with self._lock:
            if self._storage_path and self._pending_entries:
                chunks = self._pending_entries[:]
                try:
                    with open(self._storage_path, "ab") as f:
                        for chunk in chunks:
                            f.write(chunk)
                    self._pending_entries.clear()
                    self._last_flush = time.time()
                except Exception as e:
                    logger.error("denetim_kaydi_flush_hatasi", hata=str(e))

    @otel_trace("immutable_audit.export_db_triggers")
    def export_db_triggers(self) -> str:
        """PostgreSQL ve DuckDB veritabanı kurcalama engelleme SQL tetikleyicilerini döndürür.

        Denetim tablosunda UPDATE ve DELETE operasyonlarını veritabanı motoru düzeyinde yasaklar.

        Returns:
            str: SQL tetikleyici ve kural script metni.
        """
        return """
-- ALPHA BIST — Audit Log Immutability Triggers
-- Bu tetikleyiciler audit_log tablosunda UPDATE ve DELETE işlemlerini kesin olarak engeller.

-- PostgreSQL / TimescaleDB Versiyonu:
CREATE OR REPLACE FUNCTION prevent_audit_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Denetim günlüğü kayıtları (audit_log) güncellenemez veya silinemez.';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log;
CREATE TRIGGER audit_log_no_update
    BEFORE UPDATE ON audit_log
    FOR EACH ROW
    EXECUTE FUNCTION prevent_audit_modification();

DROP TRIGGER IF EXISTS audit_log_no_delete ON audit_log;
CREATE TRIGGER audit_log_no_delete
    BEFORE DELETE ON audit_log
    FOR EACH ROW
    EXECUTE FUNCTION prevent_audit_modification();
"""

    def __repr__(self) -> str:
        """Denetim logu Türkçe metin özeti.

        Returns:
            str: Durum ve zincir uzunluğu özeti.
        """
        with self._lock:
            return (
                f"ImmutableAuditLog(kayit_sayisi={len(self._entries)}, "
                f"toplam_islenen={self._total_entries}, dogrulama_sayisi={self._total_verified})"
            )


# =====================================================
# MODÜL DÜZEYİNDE DIŞA AKTARIM VE YARDIMCI FONKSİYONLAR
# =====================================================


def get_immutable_audit_log() -> ImmutableAuditLog:
    """Global ImmutableAuditLog tekil örneğini döner.

    Returns:
        ImmutableAuditLog: Paylaşılan denetim motoru.
    """
    return immutable_audit_log


def log_audit(
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    log_instance: ImmutableAuditLog | None = None,
) -> AuditEntry:
    """Yeni bir denetim kaydı oluşturur ve kriptografik zincire ekler.

    Args:
        user_id: Kullanıcı/servis kimliği.
        action: İşlem türü.
        resource_type: Kaynak tipi.
        resource_id: Kaynak kimliği.
        details: İlave detaylar.
        ip_address: İstemci IP adresi.
        user_agent: İstemci tarayıcı/istemci bilgisi.
        log_instance: Denetim motoru örneği (None ise singleton).

    Returns:
        AuditEntry: Mühürlenmiş denetim kaydı.
    """
    inst = log_instance if log_instance is not None else immutable_audit_log
    return inst.log(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def verify_audit_integrity(
    log_instance: ImmutableAuditLog | None = None,
) -> tuple[bool, str | None]:
    """Denetim günlüğü kriptografik bütünlüğünü doğrular.

    Args:
        log_instance: Denetim motoru örneği.

    Returns:
        tuple[bool, str | None]: (Bütünlük geçerli ise True, hata mesajı).
    """
    inst = log_instance if log_instance is not None else immutable_audit_log
    return inst.verify_integrity()


def generate_compliance_report(
    since: datetime | None = None,
    log_instance: ImmutableAuditLog | None = None,
) -> ComplianceReport:
    """Uyumluluk raporu üretir.

    Args:
        since: Rapor başlangıç zamanı.
        log_instance: Denetim motoru örneği.

    Returns:
        ComplianceReport: Üretilen uyumluluk raporu.
    """
    inst = log_instance if log_instance is not None else immutable_audit_log
    return inst.generate_compliance_report(since=since)


def export_audit_to_polars(
    limit: int = DEFAULT_MAX_IN_MEMORY_ENTRIES,
    log_instance: ImmutableAuditLog | None = None,
) -> pl.DataFrame:
    """Denetim günlüğünü Polars DataFrame olarak dışa aktarır.

    Args:
        limit: Maksimum satır sayısı.
        log_instance: Denetim nesnesi (None ise varsayılan singleton).

    Returns:
        pl.DataFrame: Polars tablosu.
    """
    inst = log_instance if log_instance is not None else immutable_audit_log
    return inst.export_to_polars(limit=limit)


def export_audit_to_duckdb(
    db_path: str | Path | None = None,
    limit: int = DEFAULT_MAX_IN_MEMORY_ENTRIES,
    log_instance: ImmutableAuditLog | None = None,
) -> int:
    """Denetim günlüğünü DuckDB `bist_immutable_audit` tablosuna kaydeder.

    Args:
        db_path: DuckDB dosya yolu.
        limit: Yazılacak kayıt adedi.
        log_instance: Denetim nesnesi.

    Returns:
        int: Kaydedilen kayıt sayısı.
    """
    inst = log_instance if log_instance is not None else immutable_audit_log
    return inst.export_to_duckdb(db_path=db_path, limit=limit)


def flush_audit_log(log_instance: ImmutableAuditLog | None = None) -> None:
    """Bekleyen tüm denetim kayıtlarını diske boşaltır.

    Args:
        log_instance: Denetim motoru nesnesi (None ise singleton).
    """
    inst = log_instance if log_instance is not None else immutable_audit_log
    inst.flush()


def query_immutable_audit_duckdb(
    db_path: str | Path | None = None,
    limit: int = DEFAULT_QUERY_LIMIT,
    user_id: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    log_instance: ImmutableAuditLog | None = None,
) -> pl.DataFrame:
    """DuckDB'deki değiştirilemez denetim kayıtlarını Polars DataFrame olarak sorgular.

    Args:
        db_path: DuckDB dosya yolu.
        limit: Maksimum satır sayısı.
        user_id: İsteğe bağlı kullanıcı filtresi.
        action: İsteğe bağlı işlem filtresi.
        resource_type: İsteğe bağlı kaynak tipi filtresi.
        log_instance: Denetim motoru örneği.

    Returns:
        pl.DataFrame: Sorgulanan denetim kayıtları tablosu.
    """
    inst = log_instance if log_instance is not None else immutable_audit_log
    return inst.query_audit_duckdb(
        db_path=db_path,
        limit=limit,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
    )


def verify_duckdb_integrity(
    db_path: str | Path | None = None,
    log_instance: ImmutableAuditLog | None = None,
) -> tuple[bool, str | None]:
    """DuckDB'de depolanan denetim zincirinin kriptografik bütünlüğünü doğrular.

    Args:
        db_path: DuckDB dosya yolu.
        log_instance: Denetim motoru örneği.

    Returns:
        tuple[bool, str | None]: (Bütünlük geçerli ise True, hata mesajı).
    """
    inst = log_instance if log_instance is not None else immutable_audit_log
    return inst.verify_duckdb_integrity(db_path=db_path)


def get_audit_stats(
    log_instance: ImmutableAuditLog | None = None,
) -> dict[str, Any]:
    """Denetim günlüğü istatistiklerini döndürür.

    Args:
        log_instance: Denetim motoru örneği.

    Returns:
        dict[str, Any]: İstatistikler sözlüğü.
    """
    inst = log_instance if log_instance is not None else immutable_audit_log
    return inst.get_stats()


def get_audit_entries(
    user_id: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
    log_instance: ImmutableAuditLog | None = None,
) -> list[dict[str, Any]]:
    """Filtrelenmiş denetim kayıtlarını liste olarak döndürür.

    Args:
        user_id: Kullanıcı filtresi.
        action: İşlem türü filtresi.
        resource_type: Kaynak türü filtresi.
        since: Zaman filtresi.
        limit: Maksimum kayıt adedi.
        log_instance: Denetim motoru örneği.

    Returns:
        list[dict[str, Any]]: Filtrelenmiş kayıtlar.
    """
    inst = log_instance if log_instance is not None else immutable_audit_log
    return inst.get_entries(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        since=since,
        limit=limit,
    )


# Modül Alias'ları
export_immutable_audit_to_duckdb = export_audit_to_duckdb
export_immutable_audit_to_polars = export_audit_to_polars
query_audit_duckdb = query_immutable_audit_duckdb

# Global Singleton Örneği
immutable_audit_log: Final[ImmutableAuditLog] = ImmutableAuditLog()

__all__: list[str] = [
    "DEFAULT_AUDIT_DB_PATH",
    "DEFAULT_AUDIT_TABLE_NAME",
    "DEFAULT_BATCH_FLUSH_SIZE",
    "DEFAULT_FLUSH_INTERVAL_SECONDS",
    "DEFAULT_IMMUTABLE_AUDIT_DB_PATH",
    "DEFAULT_IMMUTABLE_MAX_IN_MEMORY_ENTRIES",
    "DEFAULT_IMMUTABLE_QUERY_LIMIT",
    "DEFAULT_MAX_IN_MEMORY_ENTRIES",
    "DEFAULT_QUERY_LIMIT",
    "GENESIS_HASH",
    "AuditAction",
    "AuditEntry",
    "ComplianceReport",
    "ImmutableAuditLog",
    "export_audit_to_duckdb",
    "export_audit_to_polars",
    "export_immutable_audit_to_duckdb",
    "export_immutable_audit_to_polars",
    "flush_audit_log",
    "generate_compliance_report",
    "get_audit_entries",
    "get_audit_stats",
    "get_immutable_audit_log",
    "immutable_audit_log",
    "log_audit",
    "query_audit_duckdb",
    "query_immutable_audit_duckdb",
    "verify_audit_integrity",
    "verify_duckdb_integrity",
]
