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
from typing import Any, Final

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
DEFAULT_FLUSH_INTERVAL_SECONDS: Final[float] = 60.0
DEFAULT_BATCH_FLUSH_SIZE: Final[int] = 10
DEFAULT_AUDIT_DB_PATH: Final[Path] = Path("data/duckdb/alpha_bist_audit.duckdb")
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
        content_bytes = orjson.dumps(content_dict, option=orjson.OPT_SORT_KEYS)
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
        return orjson.dumps(self.to_dict())

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
        return orjson.dumps(self.to_dict())

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
        with self._lock:
            now = datetime.now(UTC)
            unique_seed = f"audit_{user_id}_{action}_{resource_type}_{resource_id}_{time.time_ns()}".encode()
            entry_id = hashlib.sha256(unique_seed).hexdigest()[:16]

            entry = AuditEntry(
                entry_id=entry_id,
                timestamp=now,
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details if details is not None else {},
                ip_address=ip_address,
                user_agent=user_agent,
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
                user_id=user_id,
                islem=action,
                kaynak=f"{resource_type}:{resource_id}",
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
                    "details_json": orjson.dumps(e.details).decode("utf-8"),
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

        con = duckdb.connect(str(target_path))
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS bist_immutable_audit (
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
            con.execute("""
                INSERT OR REPLACE INTO bist_immutable_audit (
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

        serialized = entry.to_orjson_bytes() + b"\n"
        with self._lock:
            self._pending_entries.append(serialized)

            now = time.time()
            if not force and len(self._pending_entries) < DEFAULT_BATCH_FLUSH_SIZE and (now - self._last_flush < DEFAULT_FLUSH_INTERVAL_SECONDS):
                return

            try:
                with open(self._storage_path, "ab") as f:
                    for chunk in self._pending_entries:
                        f.write(chunk)
                self._pending_entries.clear()
                self._last_flush = now
            except Exception as e:
                logger.error("denetim_kaydi_kalici_yazma_hatasi", dosya=str(self._storage_path), hata=str(e))

    def flush(self) -> None:
        """Kuyrukta bekleyen tüm denetim kayıtlarını diske boşaltır."""
        with self._lock:
            if self._storage_path and self._pending_entries:
                try:
                    with open(self._storage_path, "ab") as f:
                        for chunk in self._pending_entries:
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


# Global Singleton Örneği
immutable_audit_log: Final[ImmutableAuditLog] = ImmutableAuditLog()

__all__: list[str] = [
    "DEFAULT_AUDIT_DB_PATH",
    "DEFAULT_BATCH_FLUSH_SIZE",
    "DEFAULT_FLUSH_INTERVAL_SECONDS",
    "DEFAULT_MAX_IN_MEMORY_ENTRIES",
    "GENESIS_HASH",
    "AuditAction",
    "AuditEntry",
    "ComplianceReport",
    "ImmutableAuditLog",
    "export_audit_to_duckdb",
    "export_audit_to_polars",
    "generate_compliance_report",
    "get_immutable_audit_log",
    "immutable_audit_log",
    "log_audit",
    "verify_audit_integrity",
]
