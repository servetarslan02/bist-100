"""ALPHA BIST — Alarm Politika Konfigürasyon Modülü (Enterprise-Grade).

Kurumsal operasyonlar için tasarlanmış alarm yönetim ve eskalasyon politikası:
- Policy diff (eski/yeni/değişen alanların takibi ve karşılaştırılması)
- Optimistic locking (çakışan politika güncellemelerini engelleme)
- Politika değişikliği bildirimleri (asenkron webhook mekanizması)
- Toplu susturma (batch silence) işlemleri ve veritabanı senkronizasyonu
- Değiştirilemez denetim logu (her yapılandırma adımı için audit trail)
- OpenTelemetry metrik ve izleme entegrasyonu
"""

from __future__ import annotations

import asyncio
import copy
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import orjson
import structlog
from opentelemetry import metrics, trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.alert_policy")
meter = metrics.get_meter("alpha-bist.alert_policy")

_policy_updates = meter.create_counter(
    "alpha.alert_policy.updates.total",
    description="Toplam politika güncellenme sayısı",
)
_policy_silences = meter.create_counter(
    "alpha.alert_policy.silences.total",
    description="Toplam eklenen susturma (silence) kuralı sayısı",
)

DEFAULT_POLICY_PATH = Path(__file__).parent.parent.parent / "config" / "alert_policy.json"

FALLBACK_ESCALATION_TIMEOUT_S: dict[str, int] = {
    "health_change": 300,
    "invariant_failure": 60,
    "lock_deadlock": 120,
    "lock_timeout_spike": 300,
    "cash_negative": 30,
    "drawdown_breach": 180,
}

FALLBACK_NOTIFICATION_ROUTING: dict[str, list[str]] = {
    "INFO": ["log"],
    "WARNING": ["log", "webhook"],
    "CRITICAL": ["log", "webhook", "slack", "discord", "pagerduty", "email"],
}

FALLBACK_SEVERITY_THRESHOLDS: dict[str, float] = {
    "drawdown_warning_pct": 10.0,
    "drawdown_critical_pct": 15.0,
    "lock_timeout_spike_count": 3.0,
}

MAX_BATCH_SILENCE_SIZE: int = 100
WEBHOOK_RETRY_COUNT: int = 3
WEBHOOK_RETRY_DELAY_S: float = 1.0


# =====================================================
# POLICY DIFF
# =====================================================


@dataclass
class PolicyDiff:
    """İki politika konfigürasyonu arasındaki farkları tutan veri sınıfı."""

    changed_fields: list[str] = field(default_factory=list)
    added_keys: list[str] = field(default_factory=list)
    removed_keys: list[str] = field(default_factory=list)
    old_values: dict[str, Any] = field(default_factory=dict)
    new_values: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        """Politika farkının okunabilir dize gösterimi."""
        return (
            f"<PolicyDiff(changed={len(self.changed_fields)}, "
            f"added={len(self.added_keys)}, removed={len(self.removed_keys)})>"
        )

    @property
    def has_changes(self) -> bool:
        """Herhangi bir alanın değişip değişmediğini kontrol eder."""
        return bool(self.changed_fields or self.added_keys or self.removed_keys)

    def to_dict(self) -> dict[str, Any]:
        """Fark nesnesini sözlük formatına dönüştürür.

        Returns:
            dict[str, Any]: Değişiklik alanları ve değerleri.
        """
        return {
            "has_changes": self.has_changes,
            "changed_fields": self.changed_fields,
            "added_keys": self.added_keys,
            "removed_keys": self.removed_keys,
            "old_values": self.old_values,
            "new_values": self.new_values,
        }

    def summary(self) -> str:
        """İnsan tarafından okunabilir fark özeti üretir.

        Returns:
            str: Değişen, eklenen ve silinen anahtarların metinsel özeti.
        """
        parts: list[str] = []
        if self.changed_fields:
            parts.append(f"değişen: {', '.join(self.changed_fields)}")
        if self.added_keys:
            parts.append(f"eklenen: {', '.join(self.added_keys)}")
        if self.removed_keys:
            parts.append(f"silinen: {', '.join(self.removed_keys)}")
        return "; ".join(parts) if parts else "değişiklik yok"


@dataclass
class PolicyAuditEntry:
    """Politika denetim log kaydı veri sınıfı."""

    timestamp: float
    action: str
    version: int
    actor: str
    details: dict[str, Any]
    diff: dict[str, Any] | None = None

    def __repr__(self) -> str:
        """Denetim kaydının dize temsili."""
        return f"<PolicyAuditEntry(action='{self.action}', version={self.version}, actor='{self.actor}')>"

    def to_dict(self) -> dict[str, Any]:
        """Denetim kaydını sözlük formatına serileştirir.

        Returns:
            dict[str, Any]: ISO zaman damgası ve aksiyon detayları.
        """
        result: dict[str, Any] = {
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(self.timestamp, tz=UTC).isoformat(),
            "action": self.action,
            "version": self.version,
            "actor": self.actor,
            "details": self.details,
        }
        if self.diff:
            result["diff"] = self.diff
        return result


# =====================================================
# SILENCE RULE
# =====================================================


@dataclass
class SilenceRule:
    """Belirli bir alarm türü veya parmak izi için susturma kuralı."""

    alert_type: str | None = None
    fingerprint: str | None = None
    start_time: float = 0.0
    end_time: float = 0.0
    reason: str = ""
    created_by: str = "system"
    created_at: float = field(default_factory=time.time)

    def __repr__(self) -> str:
        """Susturma kuralının dize temsili."""
        return (
            f"<SilenceRule(type={self.alert_type!r}, fp={self.fingerprint!r}, "
            f"active={self.is_active})>"
        )

    @property
    def is_active(self) -> bool:
        """Kuralın şu anda aktif ve süresinin dolmamış olup olmadığını doğrular."""
        now = time.time()
        return self.start_time <= now <= self.end_time

    @property
    def is_expired(self) -> bool:
        """Kuralın bitiş zamanının geçip geçmediğini kontrol eder."""
        return time.time() > self.end_time

    def matches(self, alert_type: str, fingerprint: str) -> bool:
        """Verilen alarmın bu susturma kuralıyla eşleşip eşleşmediğini kontrol eder.

        Args:
            alert_type: Alarmın türü (örn: 'drawdown_breach').
            fingerprint: Alarmın tekil parmak izi dizesi.

        Returns:
            bool: Kural aktifse ve kriterler uyuşuyorsa True.
        """
        if not self.is_active:
            return False
        if self.alert_type and self.alert_type != alert_type:
            return False
        return not (self.fingerprint and self.fingerprint != fingerprint)

    def to_dict(self) -> dict[str, Any]:
        """Susturma kuralını sözlüğe dönüştürür.

        Returns:
            dict[str, Any]: Kural parametreleri ve durum bilgisi.
        """
        return {
            "alert_type": self.alert_type,
            "fingerprint": self.fingerprint,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "start_iso": self._ts_iso(self.start_time),
            "end_iso": self._ts_iso(self.end_time),
            "reason": self.reason,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "is_active": self.is_active,
            "is_expired": self.is_expired,
        }

    @staticmethod
    def _ts_iso(ts: float) -> str:
        """Zaman damgasını UTC ISO-8601 dizesine dönüştürür."""
        return datetime.fromtimestamp(ts, tz=UTC).isoformat() if ts else ""


# =====================================================
# ALERT POLICY
# =====================================================


class VersionConflictError(Exception):
    """Optimistic locking çakışmasında fırlatılan istisna sınıfı."""


@dataclass
class AlertPolicy:
    """Sistem alarm eşiklerini, bildirim kanallarını ve susturma kurallarını yöneten ana sınıf."""

    escalation_timeouts: dict[str, int] = field(default_factory=lambda: dict(FALLBACK_ESCALATION_TIMEOUT_S))
    notification_routing: dict[str, list[str]] = field(default_factory=lambda: dict(FALLBACK_NOTIFICATION_ROUTING))
    severity_thresholds: dict[str, float] = field(default_factory=lambda: dict(FALLBACK_SEVERITY_THRESHOLDS))
    silence_rules: list[SilenceRule] = field(default_factory=list)
    _config_path: str | None = None
    _last_modified: float = 0.0
    _version: int = 0
    _history: list[dict[str, Any]] = field(default_factory=list)
    _audit_log: list[PolicyAuditEntry] = field(default_factory=list)
    _webhook_urls: list[str] = field(default_factory=list)
    _lock_owner: str | None = None
    _lock_expires: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _last_file_save: float = field(default=0.0, init=False, repr=False)

    def __repr__(self) -> str:
        """Politika yöneticisinin dize temsili."""
        return (
            f"<AlertPolicy(version={self._version}, "
            f"rules={len(self.silence_rules)}, locked={self.is_locked()})>"
        )

    # =====================================================
    # LOAD / RELOAD
    # =====================================================

    @classmethod
    def load(cls, path: str | None = None) -> AlertPolicy:
        """Disk üzerindeki JSON dosyasından politikayı yükler veya varsayılanı döner.

        Args:
            path: Yüklenecek konfigürasyon dosyasının yolu (None ise DEFAULT_POLICY_PATH).

        Returns:
            AlertPolicy: Yüklenmiş veya varsayılan konfigürasyonla oluşturulmuş nesne.
        """
        config_path = path or str(DEFAULT_POLICY_PATH)
        policy = cls(_config_path=config_path)
        if not os.path.exists(config_path):
            return policy
        try:
            with open(config_path, "rb") as f:
                data = orjson.loads(f.read())
            policy = cls._from_dict(data, config_path)
            return policy
        except Exception as e:
            logger.error("alarm_politikasi_yukleme_hatasi", error=str(e), yol=config_path)
            return cls(_config_path=config_path)

    def reload_if_changed(self) -> bool:
        """Dosya son değiştirilme zamanını kontrol ederek güncellenmişse yeniden yükler.

        Returns:
            bool: Dosya değişti ve başarıyla yeniden yüklendiyse True, aksi halde False.
        """
        if not self._config_path or not os.path.exists(self._config_path):
            return False
        with self._lock:
            try:
                mtime = os.path.getmtime(self._config_path)
                if mtime <= self._last_modified:
                    return False
                with open(self._config_path, "rb") as f:
                    data = orjson.loads(f.read())
                new_policy = AlertPolicy._from_dict(data, self._config_path)
                errors = new_policy.validate()
                if errors:
                    logger.error("alarm_politikasi_dogrulama_basarisiz", hatalar=errors)
                    return False
                old_dict = self.to_dict()
                self._save_history()
                self.escalation_timeouts = new_policy.escalation_timeouts
                self.notification_routing = new_policy.notification_routing
                self.severity_thresholds = new_policy.severity_thresholds
                self._last_modified = mtime
                self._version += 1
                diff = self._compute_diff(old_dict, self.to_dict())
                self._add_audit("reload", {"source": "file"}, diff)
                self._notify_change("reload", diff)
                return True
            except Exception as e:
                logger.error("alarm_politikasi_yeniden_yukleme_hatasi", error=str(e))
                return False

    # =====================================================
    # POLICY UPDATE (with optimistic locking)
    # =====================================================

    def update(
        self,
        new_config: dict[str, Any],
        actor: str = "api",
        expected_version: int = 0,
    ) -> dict[str, Any]:
        """Politikayı güvenli şekilde günceller (optimistic locking desteğiyle).

        Args:
            new_config: Uygulanacak yeni konfigürasyon alanları.
            actor: Güncellemeyi gerçekleştiren kullanıcı veya servis kimliği.
            expected_version: Beklenen güncel versiyon numarası (0 = versiyon kontrolü yapılmaz).

        Returns:
            dict[str, Any]: Güncelleme sonucu, yeni versiyon ve oluşan fark sözlüğü.

        Raises:
            VersionConflictError: Beklenen versiyon ile mevcut versiyon eşleşmediğinde.
        """
        with tracer.start_as_current_span("alert_policy.update") as span:
            span.set_attribute("actor", actor)
            span.set_attribute("expected_version", expected_version)
            span.set_attribute("current_version", self._version)

            with self._lock:
                # Optimistic locking denetimi
                if expected_version > 0 and expected_version != self._version:
                    raise VersionConflictError(
                        f"Versiyon uyuşmazlığı: beklenen {expected_version}, güncel {self._version}. "
                        f"Politika başka bir işlem tarafından değiştirilmiş olabilir."
                    )

                # Doğrulama testi
                test_policy = AlertPolicy._from_dict(new_config, "")
                errors = test_policy.validate()
                if errors:
                    return {"success": False, "errors": errors}

                # Diff hesaplama ve geçmiş kaydı
                old_dict = copy.deepcopy(self.to_dict())
                self._save_history()

                # Değişiklikleri uygula
                if "escalation_timeouts" in new_config:
                    self.escalation_timeouts = new_config["escalation_timeouts"]
                if "notification_routing" in new_config:
                    self.notification_routing = new_config["notification_routing"]
                if "severity_thresholds" in new_config:
                    self.severity_thresholds = new_config["severity_thresholds"]

                self._version += 1
                diff = self._compute_diff(old_dict, self.to_dict())

                # Denetim logu ve kalıcılaştırma
                self._add_audit(
                    "update",
                    {
                        "actor": actor,
                        "changes": list(new_config.keys()),
                        "expected_version": expected_version,
                    },
                    diff,
                )
                self._save_to_file()
                self._notify_change("update", diff)

                _policy_updates.add(1)
                span.set_attribute("success", True)
                return {"success": True, "version": self._version, "diff": diff.to_dict()}

    # =====================================================
    # POLICY DIFF
    # =====================================================

    def compute_diff(self, new_config: dict[str, Any]) -> PolicyDiff:
        """Mevcut durum ile yeni bir konfigürasyon arasındaki farkı hesaplar.

        Args:
            new_config: Karşılaştırılacak yeni konfigürasyon sözlüğü.

        Returns:
            PolicyDiff: Hesaplanan fark nesnesi.
        """
        old_dict = self.to_dict()
        return self._compute_diff(old_dict, new_config)

    @staticmethod
    def _compute_diff(old: dict[str, Any], new: dict[str, Any]) -> PolicyDiff:
        """İki sözlük arasındaki anahtar ve değer farklarını hesaplar."""
        diff = PolicyDiff()
        all_keys = set(list(old.keys()) + list(new.keys()))
        for key in all_keys:
            if key.startswith("_"):
                continue
            old_val = old.get(key)
            new_val = new.get(key)

            if key not in old:
                diff.added_keys.append(key)
                diff.new_values[key] = new_val
            elif key not in new:
                diff.removed_keys.append(key)
                diff.old_values[key] = old_val
            elif old_val != new_val:
                diff.changed_fields.append(key)
                diff.old_values[key] = old_val
                diff.new_values[key] = new_val

        return diff

    def three_way_diff(self, base_version: int, version_a: int, version_b: int) -> dict[str, Any]:
        """Üçlü karşılaştırma: Temel versiyon ile iki türetilmiş versiyon arasındaki çakışmaları belirler.

        Args:
            base_version: Referans temel versiyon numarası.
            version_a: Birinci karşılaştırma versiyonu.
            version_b: İkinci karşılaştırma versiyonu.

        Returns:
            dict[str, Any]: Çakışan, ortak değişen ve tek taraflı değişen alanlar.
        """
        base = self._get_history_version(base_version)
        ver_a = self._get_history_version(version_a)
        ver_b = self._get_history_version(version_b)

        if not base or not ver_a or not ver_b:
            return {
                "error": "Bir veya daha fazla versiyon bulunamadı",
                "found": {"base": base is not None, "a": ver_a is not None, "b": ver_b is not None},
            }

        diff_a = self._compute_diff(base, ver_a)
        diff_b = self._compute_diff(base, ver_b)

        skip_keys = {"version", "timestamp"}
        a_changed = set(diff_a.changed_fields + diff_a.added_keys + diff_a.removed_keys) - skip_keys
        b_changed = set(diff_b.changed_fields + diff_b.added_keys + diff_b.removed_keys) - skip_keys

        a_only: dict[str, Any] = {}
        for f in a_changed - b_changed:
            a_only[f] = {"base": base.get(f), "a": ver_a.get(f)}

        b_only: dict[str, Any] = {}
        for f in b_changed - a_changed:
            b_only[f] = {"base": base.get(f), "b": ver_b.get(f)}

        both_changed: dict[str, Any] = {}
        identical: list[str] = []
        for f in a_changed & b_changed:
            val_a = ver_a.get(f)
            val_b = ver_b.get(f)
            if val_a == val_b:
                identical.append(f)
            else:
                both_changed[f] = {"base": base.get(f), "a": val_a, "b": val_b}

        return {
            "base_version": base_version,
            "version_a": version_a,
            "version_b": version_b,
            "a_only": a_only,
            "b_only": b_only,
            "both_changed": both_changed,
            "identical": identical,
            "has_conflicts": len(both_changed) > 0,
            "conflict_fields": list(both_changed.keys()),
        }

    def _get_history_version(self, version: int) -> dict[str, Any] | None:
        """Geçmiş kayıtlarından belirtilen versiyonun sözlük halini döndürür."""
        if version == self._version:
            return self.to_dict()
        for h in self._history:
            if h.get("version") == version:
                return h
        return None

    # =====================================================
    # OPTIMISTIC LOCKING
    # =====================================================

    def acquire_edit_lock(self, owner: str, timeout_s: float = 30.0) -> bool:
        """Politika düzenleme kilidini alır (süresi dolmuş kilitleri otomatik temizler).

        Args:
            owner: Kilidi talep eden operatör veya servis kimliği.
            timeout_s: Kilidin geçerlilik süresi (saniye cinsinden).

        Returns:
            bool: Kilit başarıyla alındıysa True, başka birisi kilitliyse False.
        """
        with self._lock:
            now = time.time()
            if self._lock_owner and self._lock_owner != owner:
                if self._lock_expires > now:
                    return False
                old_owner = self._lock_owner
                old_expires = self._lock_expires
                self._lock_owner = None
                self._lock_expires = 0.0
                self._add_audit(
                    "lock_expired_recovery",
                    {
                        "old_owner": old_owner,
                        "new_owner": owner,
                        "expired_at": old_expires,
                    },
                )
            self._lock_owner = owner
            self._lock_expires = now + timeout_s
            self._add_audit("lock_acquired", {"owner": owner, "timeout_s": timeout_s})
            return True

    def release_edit_lock(self, owner: str) -> bool:
        """Politika düzenleme kilidini serbest bırakır.

        Args:
            owner: Kilidi serbest bırakmak isteyen kimlik.

        Returns:
            bool: Kilit sahibiyle eşleşip bırakıldıysa True, aksi halde False.
        """
        with self._lock:
            if self._lock_owner != owner:
                return False
            self._lock_owner = None
            self._lock_expires = 0.0
            self._add_audit("lock_released", {"owner": owner})
            return True

    def is_locked(self) -> bool:
        """Politikanın şu anda kilitli olup olmadığını sorgular.

        Returns:
            bool: Kilit aktif ve süresi devam ediyorsa True.
        """
        return self._lock_owner is not None and self._lock_expires > time.time()

    def get_lock_info(self) -> dict[str, Any]:
        """Mevcut kilit durumunu ve sahibini ayrıntılı döner.

        Returns:
            dict[str, Any]: Kilitli durumu, sahibi ve ISO son geçerlilik zamanı.
        """
        return {
            "locked": self.is_locked(),
            "owner": self._lock_owner,
            "expires_at": self._lock_expires,
            "expires_iso": (
                datetime.fromtimestamp(self._lock_expires, tz=UTC).isoformat()
                if self._lock_expires
                else None
            ),
        }

    # =====================================================
    # ROLLBACK
    # =====================================================

    def rollback(self, target_version: int = 0, actor: str = "api") -> dict[str, Any]:
        """Politikayı geçmişteki bir versiyona geri döndürür.

        Args:
            target_version: Hedef versiyon numarası (0 ise bir önceki versiyon).
            actor: Geri alma işlemini tetikleyen aktör.

        Returns:
            dict[str, Any]: İşlem sonucu ve yeni durum detayları.
        """
        with self._lock:
            if not self._history:
                return {"success": False, "error": "Geri alınacak geçmiş kaydı bulunamadı"}

            if target_version == 0:
                target = self._history[-1]
            else:
                target = None
                for h in self._history:
                    if h.get("version") == target_version:
                        target = h
                        break
                if not target:
                    return {"success": False, "error": f"Versiyon {target_version} bulunamadı"}

            old_dict = copy.deepcopy(self.to_dict())
            self._save_history()
            self.escalation_timeouts = target.get("escalation_timeouts", dict(FALLBACK_ESCALATION_TIMEOUT_S))
            self.notification_routing = target.get("notification_routing", dict(FALLBACK_NOTIFICATION_ROUTING))
            self.severity_thresholds = target.get("severity_thresholds", dict(FALLBACK_SEVERITY_THRESHOLDS))
            self._version += 1
            diff = self._compute_diff(old_dict, self.to_dict())
            self._add_audit("rollback", {"actor": actor, "target_version": target_version}, diff)
            self._save_to_file()
            self._notify_change("rollback", diff)

            return {"success": True, "version": self._version, "diff": diff.to_dict()}

    # =====================================================
    # WEBHOOK NOTIFICATION
    # =====================================================

    def set_webhook_urls(self, urls: list[str]) -> None:
        """Politika değişikliği bildirimlerinin gönderileceği webhook URL'lerini belirler.

        Args:
            urls: Webhook uç nokta adresleri listesi.
        """
        self._webhook_urls = urls

    def _notify_change(self, action: str, diff: PolicyDiff) -> None:
        """Politika değişikliğini yapılandırılmış webhook'lara asenkron bildirir."""
        if not self._webhook_urls or not diff.has_changes:
            return

        payload = {
            "event": "policy_change",
            "action": action,
            "version": self._version,
            "timestamp": datetime.now(UTC).isoformat(),
            "diff": diff.to_dict(),
        }

        for url in self._webhook_urls:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._send_webhook(url, payload))
            except RuntimeError:
                # Çalışan event loop yoksa yeni bir geçici loop ile çalıştır
                try:
                    asyncio.run(self._send_webhook(url, payload))
                except Exception as e:
                    logger.warning("webhook_bildirim_hatasi", url=url, error=str(e))

    async def _send_webhook(self, url: str, payload: dict[str, Any]) -> bool:
        """Belirtilen URL'ye webhook isteğini HTTP üzerinden güvenli şekilde iletir."""
        last_error: str | None = None
        for attempt in range(WEBHOOK_RETRY_COUNT):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        url,
                        content=orjson.dumps(payload),
                        headers={"Content-Type": "application/json"},
                    )
                    if resp.status_code < 400:
                        logger.info(
                            "webhook_basariyla_gonderildi",
                            url=url,
                            status=resp.status_code,
                            deneme=attempt + 1,
                        )
                        return True
                    last_error = f"HTTP {resp.status_code}"
                    logger.warning(
                        "webhook_yanit_hatasi",
                        url=url,
                        status=resp.status_code,
                        deneme=attempt + 1,
                    )
            except Exception as e:
                last_error = str(e)
                logger.warning("webhook_baglanti_hatasi", url=url, error=str(e), deneme=attempt + 1)

            if attempt < WEBHOOK_RETRY_COUNT - 1:
                await asyncio.sleep(WEBHOOK_RETRY_DELAY_S * (attempt + 1))

        self._add_audit("webhook_failed", {"url": url, "error": last_error, "attempts": WEBHOOK_RETRY_COUNT})
        return False

    # =====================================================
    # SILENCE MANAGEMENT (DB-backed + batch)
    # =====================================================

    def add_silence(
        self,
        alert_type: str | None = None,
        fingerprint: str | None = None,
        duration_s: float = 3600.0,
        reason: str = "",
        created_by: str = "system",
        db: Any = None,
    ) -> SilenceRule:
        """Yeni bir alarm susturma kuralı ekler ve opsiyonel olarak veritabanına kaydeder.

        Args:
            alert_type: Susturulacak alarm türü.
            fingerprint: Susturulacak spesifik parmak izi.
            duration_s: Susturma süresi (saniye).
            reason: Susturma gerekçesi.
            created_by: Kuralı oluşturan aktör.
            db: DuckDB veya veritabanı bağlantısı.

        Returns:
            SilenceRule: Oluşturulan susturma kuralı nesnesi.
        """
        with self._lock:
            rule = SilenceRule(
                alert_type=alert_type,
                fingerprint=fingerprint,
                start_time=time.time(),
                end_time=time.time() + duration_s,
                reason=reason,
                created_by=created_by,
            )
            self.silence_rules.append(rule)
            self._cleanup_expired_silences()
            self._add_audit(
                "silence_add",
                {
                    "alert_type": alert_type,
                    "fingerprint": fingerprint,
                    "duration_s": duration_s,
                    "reason": reason,
                    "created_by": created_by,
                },
            )
            if db:
                self._persist_silence_to_db(rule, db)
            _policy_silences.add(1)
            return rule

    def batch_add_silences(
        self,
        rules_config: list[dict[str, Any]],
        created_by: str = "system",
        db: Any = None,
    ) -> list[dict[str, Any]]:
        """Birden fazla susturma kuralını toplu olarak ekler.

        Args:
            rules_config: Eklenecek kural yapılandırmaları listesi.
            created_by: Kuralları oluşturan aktör.
            db: Opsiyonel veritabanı bağlantısı.

        Returns:
            list[dict[str, Any]]: Her bir kural için işlem sonuçları.
        """
        if len(rules_config) > MAX_BATCH_SILENCE_SIZE:
            return [
                {
                    "success": False,
                    "error": f"Toplu susturma boyutu {len(rules_config)}, sınırı aştı: {MAX_BATCH_SILENCE_SIZE}",
                }
            ]

        with self._lock:
            results: list[dict[str, Any]] = []
            created_rules: list[SilenceRule] = []

            for config in rules_config:
                rule = SilenceRule(
                    alert_type=config.get("alert_type"),
                    fingerprint=config.get("fingerprint"),
                    start_time=time.time(),
                    end_time=time.time() + config.get("duration_s", 3600.0),
                    reason=config.get("reason", ""),
                    created_by=created_by,
                )
                created_rules.append(rule)
                self.silence_rules.append(rule)
                results.append({"success": True, "rule": rule.to_dict()})

            if db and created_rules:
                try:
                    for rule in created_rules:
                        self._persist_silence_to_db(rule, db)
                    if hasattr(db, "commit"):
                        db.commit()
                except Exception as e:
                    if hasattr(db, "rollback"):
                        db.rollback()
                    for rule in created_rules:
                        if rule in self.silence_rules:
                            self.silence_rules.remove(rule)
                    results = [{"success": False, "error": str(e)} for _ in rules_config]

            self._add_audit(
                "batch_silence_add",
                {
                    "count": len(rules_config),
                    "created_by": created_by,
                    "success_count": sum(1 for r in results if r.get("success")),
                },
            )
            return results

    def batch_remove_silences(
        self,
        filters: list[dict[str, str]],
        actor: str = "api",
        db: Any = None,
    ) -> dict[str, int]:
        """Kriterlere uyan susturma kurallarını toplu olarak kaldırır.

        Args:
            filters: Filtre kriterleri listesi (fingerprint veya alert_type).
            actor: Kaldırma işlemini gerçekleştiren aktör.
            db: Opsiyonel veritabanı bağlantısı.

        Returns:
            dict[str, int]: Silinen kural sayısı ('removed').
        """
        with self._lock:
            removed_count = 0
            removed_rules: list[SilenceRule] = []

            for f in filters:
                fp = f.get("fingerprint")
                at = f.get("alert_type")
                to_remove = [
                    r for r in self.silence_rules
                    if (fp and r.fingerprint == fp) or (at and r.alert_type == at)
                ]
                for rule in to_remove:
                    self.silence_rules.remove(rule)
                    removed_rules.append(rule)
                    removed_count += 1

            if db and removed_rules:
                try:
                    for rule in removed_rules:
                        self._remove_silence_from_db(rule, db)
                    if hasattr(db, "commit"):
                        db.commit()
                except Exception as e:
                    logger.warning("veritabani_susturma_kaldirma_hatasi", error=str(e))
                    if hasattr(db, "rollback"):
                        db.rollback()
                    self.silence_rules.extend(removed_rules)
                    removed_count = 0

            self._add_audit(
                "batch_silence_remove",
                {
                    "filters": filters,
                    "actor": actor,
                    "removed_count": removed_count,
                },
            )
            return {"removed": removed_count}

    def remove_silence(
        self,
        fingerprint: str | None = None,
        alert_type: str | None = None,
        actor: str = "api",
        db: Any = None,
    ) -> int:
        """Belirli bir parmak izi veya alarm tipine sahip susturma kuralını kaldırır.

        Args:
            fingerprint: Kaldırılacak parmak izi.
            alert_type: Kaldırılacak alarm türü.
            actor: Kaldırma işlemini gerçekleştiren aktör.
            db: Opsiyonel veritabanı bağlantısı.

        Returns:
            int: Kaldırılan kural sayısı.
        """
        with self._lock:
            before = len(self.silence_rules)
            removed_rules = [
                r for r in self.silence_rules
                if (fingerprint and r.fingerprint == fingerprint) or (alert_type and r.alert_type == alert_type)
            ]
            self.silence_rules = [
                r for r in self.silence_rules
                if not ((fingerprint and r.fingerprint == fingerprint) or (alert_type and r.alert_type == alert_type))
            ]
            removed = before - len(self.silence_rules)
            if removed:
                self._add_audit(
                    "silence_remove",
                    {
                        "fingerprint": fingerprint,
                        "alert_type": alert_type,
                        "actor": actor,
                    },
                )
                if db:
                    for rule in removed_rules:
                        self._remove_silence_from_db(rule, db)
            return removed

    def is_silenced(self, alert_type: str, fingerprint: str) -> bool:
        """Belirtilen alarmın şu anda susturulup susturulmadığını sorgular.

        Args:
            alert_type: Alarm türü.
            fingerprint: Alarm parmak izi.

        Returns:
            bool: Alarm susturulmuşsa True, aksi halde False.
        """
        with self._lock:
            self._cleanup_expired_silences()
            return any(r.matches(alert_type, fingerprint) for r in self.silence_rules)

    def get_active_silences(self) -> list[dict[str, Any]]:
        """Mevcut tüm aktif susturma kurallarını döner.

        Returns:
            list[dict[str, Any]]: Aktif kuralların sözlük listesi.
        """
        with self._lock:
            self._cleanup_expired_silences()
            return [r.to_dict() for r in self.silence_rules if r.is_active]

    def load_silences_from_db(self, db: Any) -> None:
        """Veritabanından gelecekte geçerli susturma kurallarını yükler.

        Args:
            db: DuckDB veya veritabanı bağlantısı.
        """
        with self._lock:
            try:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS alert_silences ("
                    "alert_type VARCHAR, fingerprint VARCHAR, start_time DOUBLE, "
                    "end_time DOUBLE, reason VARCHAR, created_by VARCHAR, created_at DOUBLE)"
                )
                rows = db.execute(
                    "SELECT alert_type, fingerprint, start_time, end_time, reason, created_by, created_at "
                    "FROM alert_silences WHERE end_time > ?",
                    (time.time(),),
                ).fetchall()
                self.silence_rules = []
                for row in rows:
                    if isinstance(row, dict):
                        at = row.get("alert_type")
                        fp = row.get("fingerprint")
                        st = row.get("start_time", 0.0)
                        et = row.get("end_time", 0.0)
                        rs = row.get("reason") or ""
                        cb = row.get("created_by") or "system"
                        ca = row.get("created_at") or time.time()
                    else:
                        at, fp, st, et, rs, cb, ca = row
                    rule = SilenceRule(
                        alert_type=at,
                        fingerprint=fp,
                        start_time=st,
                        end_time=et,
                        reason=rs,
                        created_by=cb,
                        created_at=ca,
                    )
                    self.silence_rules.append(rule)
                logger.info("susturma_kurallari_veritabanindan_yuklendi", adet=len(self.silence_rules))
            except Exception as e:
                logger.warning("susturma_veritabani_yukleme_hatasi", error=str(e))

    def _persist_silence_to_db(self, rule: SilenceRule, db: Any) -> None:
        """Susturma kuralını veritabanına kaydeder (DuckDB uyumlu)."""
        try:
            db.execute(
                "CREATE TABLE IF NOT EXISTS alert_silences ("
                "alert_type VARCHAR, fingerprint VARCHAR, start_time DOUBLE, "
                "end_time DOUBLE, reason VARCHAR, created_by VARCHAR, created_at DOUBLE)"
            )
            db.execute(
                "INSERT INTO alert_silences "
                "(alert_type, fingerprint, start_time, end_time, reason, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    rule.alert_type,
                    rule.fingerprint,
                    rule.start_time,
                    rule.end_time,
                    rule.reason,
                    rule.created_by,
                    rule.created_at,
                ),
            )
        except Exception as e:
            logger.warning("susturma_veritabani_kayit_hatasi", error=str(e))

    def _remove_silence_from_db(self, rule: SilenceRule, db: Any) -> None:
        """Susturma kuralını veritabanından siler."""
        try:
            if rule.fingerprint:
                db.execute("DELETE FROM alert_silences WHERE fingerprint = ?", (rule.fingerprint,))
            elif rule.alert_type:
                db.execute("DELETE FROM alert_silences WHERE alert_type = ?", (rule.alert_type,))
        except Exception as e:
            logger.warning("susturma_veritabani_silme_hatasi", error=str(e))

    # =====================================================
    # VALIDATION / QUERIES
    # =====================================================

    def validate(self) -> list[str]:
        """Politika alanlarını doğrular ve geçersiz olanları listeler.

        Returns:
            list[str]: Hata mesajları listesi (boş liste geçerli demektir).
        """
        errors: list[str] = []
        for alert_type, timeout in self.escalation_timeouts.items():
            if not isinstance(timeout, (int, float)) or timeout < 0:
                errors.append(f"Geçersiz eskalasyon süresi ({alert_type}): {timeout}")
            elif timeout > 86400:
                errors.append(f"Eskalasyon süresi çok uzun ({alert_type}): {timeout}s")

        valid_channels = {"log", "webhook", "slack", "discord", "pagerduty", "email"}
        for severity, channels in self.notification_routing.items():
            if severity not in ("INFO", "WARNING", "CRITICAL"):
                errors.append(f"Geçersiz önem derecesi: {severity}")
            for ch in channels:
                if ch not in valid_channels:
                    errors.append(f"Geçersiz bildirim kanalı: {ch}")
        return errors

    def get_escalation_timeout(self, alert_type: str) -> int | None:
        """Belirtilen alarm tipi için eskalasyon zaman aşımını saniye cinsinden döner."""
        return self.escalation_timeouts.get(alert_type)

    def get_notification_channels(self, severity: str) -> list[str]:
        """Belirtilen önem derecesi için tanımlı bildirim kanallarını döner."""
        return self.notification_routing.get(severity, ["log"])

    def get_threshold(self, key: str, default: float = 0.0) -> float:
        """Belirtilen anahtar için şiddet eşik değerini döner."""
        return self.severity_thresholds.get(key, default)

    def get_history(self) -> list[dict[str, Any]]:
        """Son 20 politika geçmiş kaydını döner."""
        with self._lock:
            return copy.deepcopy(self._history[-20:])

    def get_audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Denetim günlüğündeki son kayıtları döner."""
        with self._lock:
            return [e.to_dict() for e in self._audit_log[-limit:]]

    # =====================================================
    # INTERNAL
    # =====================================================

    def _save_history(self) -> None:
        """Mevcut yapılandırmayı versiyon geçmişine ekler."""
        self._history.append(
            {
                "version": self._version,
                "timestamp": time.time(),
                "escalation_timeouts": dict(self.escalation_timeouts),
                "notification_routing": dict(self.notification_routing),
                "severity_thresholds": dict(self.severity_thresholds),
            }
        )
        if len(self._history) > 50:
            self._history = self._history[-50:]

    def _add_audit(self, action: str, details: dict[str, Any], diff: PolicyDiff | None = None) -> None:
        """Denetim günlüğüne yeni bir işlem kaydeder."""
        entry = PolicyAuditEntry(
            timestamp=time.time(),
            action=action,
            version=self._version,
            actor=details.get("actor", "system"),
            details=details,
            diff=diff.to_dict() if diff else None,
        )
        self._audit_log.append(entry)
        if len(self._audit_log) > 500:
            self._audit_log = self._audit_log[-500:]

    def _save_to_file(self) -> None:
        """Politikayı diske kaydeder (SSD koruması için 30 saniye debounce ile)."""
        if not self._config_path:
            return
        now = time.time()
        if now - self._last_file_save < 30.0:
            return
        self._last_file_save = now
        try:
            os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
            with open(self._config_path, "wb") as f:
                f.write(orjson.dumps(self.to_dict(), option=orjson.OPT_INDENT_2))
        except Exception as e:
            logger.warning("alarm_politikasi_kayit_hatasi", error=str(e))

    def _cleanup_expired_silences(self) -> None:
        """Süresi dolmuş susturma kurallarını listeden temizler."""
        self.silence_rules = [r for r in self.silence_rules if not r.is_expired]

    def to_dict(self) -> dict[str, Any]:
        """Politikanın tüm konfigürasyonunu serileştirilebilir sözlüğe dönüştürür."""
        return {
            "version": self._version,
            "escalation_timeouts": self.escalation_timeouts,
            "notification_routing": self.notification_routing,
            "severity_thresholds": self.severity_thresholds,
        }

    @classmethod
    def _from_dict(cls, data: dict[str, Any], config_path: str = "") -> AlertPolicy:
        """Sözlük verisinden AlertPolicy örneği inşa eder."""
        policy = cls(_config_path=config_path)
        policy._last_modified = os.path.getmtime(config_path) if config_path and os.path.exists(config_path) else 0.0
        policy._version = data.get("version", 0)
        if "escalation_timeouts" in data:
            policy.escalation_timeouts = data["escalation_timeouts"]
        if "notification_routing" in data:
            policy.notification_routing = data["notification_routing"]
        if "severity_thresholds" in data:
            policy.severity_thresholds = data["severity_thresholds"]
        return policy


def ensure_default_config(path: str | None = None) -> None:
    """Varsayılan alarm politikası konfigürasyon dosyasının diskte var olmasını garanti eder.

    Args:
        path: Opsiyonel dosya yolu (None ise varsayılan config dizini kullanılır).
    """
    config_path = path or str(DEFAULT_POLICY_PATH)
    if os.path.exists(config_path):
        return
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "wb") as f:
        f.write(orjson.dumps({"version": 1, **AlertPolicy().to_dict()}, option=orjson.OPT_INDENT_2))


__all__ = [
    "AlertPolicy",
    "PolicyAuditEntry",
    "PolicyDiff",
    "SilenceRule",
    "VersionConflictError",
    "ensure_default_config",
]
