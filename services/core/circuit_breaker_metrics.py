"""ALPHA BIST — Kurumsal Circuit Breaker Metrik Toplayıcı ve Prometheus/JSON Dışa Aktarıcısı.

Bu modül, mikroservis ve dış veri sağlayıcı devre kesicilerinin (Circuit Breaker)
sağlık, durum ve güvenilirlik metriklerini merkezi olarak toplar, Prometheus ve
orjson formatlarında dışa aktarır (Monitoring / Dashboarding).

Özellikler:
- Thread-Safe: RLock ile eşzamanlı kayıt, metrik dışa aktarımı ve durum takibi.
- O(1) Durum Değişiklik Geçmişi: collections.deque(maxlen=...) ile sabit bellek garantisi.
- Çoklu Sağlayıcı Uyumluluğu: Hem ham CircuitBreaker hem de ProtectedProvider nesnelerinden metrik çekme.
- Prometheus Standartları: Güvenli label escaping ve geçerli gauge/counter çıktıları.
- orjson Entegrasyonu: Yüksek performanslı JSON serileştirme.
"""

from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import orjson
import structlog

from services.core.otel import otel_trace

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = structlog.get_logger(__name__)

# Varsayılan Yapılandırma Sabitleri
DEFAULT_MAX_HISTORY: Final[int] = 1000
DEFAULT_HISTORY_LIMIT: Final[int] = 50


@dataclass(slots=True)
class CircuitBreakerSnapshot:
    """Belirli bir devre kesicinin anlık durum ve sayaç fotoğrafı.

    Attributes:
        name: Devre kesicinin tekil adı.
        state: Anlık devre durumu ("CLOSED", "OPEN", "HALF_OPEN").
        failure_count: Ardışık başarısızlık sayısı.
        success_count: Ardışık veya toplam başarı sayısı.
        failure_threshold: Devreyi OPEN yapan eşik değer.
        recovery_timeout_seconds: Devrenin HALF_OPEN'a geçmesi için bekleme süresi.
        last_failure_time: Son başarısızlık zaman damgası (ISO 8601).
        last_success_time: Son başarı zaman damgası (ISO 8601).
        total_requests: İşlenen toplam istek sayısı.
        total_failures: Toplam başarısız istek sayısı.
        total_successes: Toplam başarılı istek sayısı.
        uptime_percentage: Çalışabilirlik / başarı yüzdesi (%0.0 - %100.0).
    """

    name: str
    state: str
    failure_count: int
    success_count: int
    failure_threshold: int
    recovery_timeout_seconds: int
    last_failure_time: str | None
    last_success_time: str | None
    total_requests: int
    total_failures: int
    total_successes: int
    uptime_percentage: float

    def to_dict(self) -> dict[str, Any]:
        """Snapshot verilerini serileştirilebilir bir sözlüğe dönüştürür.

        Returns:
            dict[str, Any]: JSON uyumlu durum verileri.
        """
        safe_uptime = self.uptime_percentage
        if math.isnan(safe_uptime) or math.isinf(safe_uptime):
            safe_uptime = 100.0

        return {
            "name": self.name,
            "state": self.state,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout_seconds": self.recovery_timeout_seconds,
            "last_failure": self.last_failure_time,
            "last_success": self.last_success_time,
            "total_requests": self.total_requests,
            "total_failures": self.total_failures,
            "total_successes": self.total_successes,
            "uptime_pct": round(min(100.0, max(0.0, safe_uptime)), 2),
        }

    def __repr__(self) -> str:
        """Snapshot için bilgilendirici metin temsili."""
        return (
            f"CircuitBreakerSnapshot(name='{self.name}', state='{self.state}', "
            f"failures={self.failure_count}/{self.failure_threshold}, "
            f"uptime={round(self.uptime_percentage, 1)}%)"
        )


class CircuitBreakerMetricsCollector:
    """Merkezi devre kesici metrik toplayıcı ve export yöneticisi.

    Tüm kayıtlı devre kesicilerin durumunu eşzamanlı güvenli (thread-safe)
    olarak takip eder, durum geçişlerinin tarihçesini tutar ve Prometheus / JSON
    formatlarında sunar.
    """

    def __init__(self, max_history: int = DEFAULT_MAX_HISTORY) -> None:
        """Metrik toplayıcıyı başlatır.

        Args:
            max_history: Bellekte saklanacak maksimum durum değişikliği sayısı.
        """
        self._tracked_breakers: dict[str, Any] = {}
        self._max_history: int = max(1, max_history)
        self._history: deque[dict[str, Any]] = deque(maxlen=self._max_history)
        self._lock: threading.RLock = threading.RLock()

    @otel_trace("circuit_breaker_metrics.track")
    def track(self, breaker: Any) -> None:
        """Bir devre kesici veya korumalı sağlayıcıyı merkezi izlemeye alır.

        Args:
            breaker: İzlenecek CircuitBreaker veya ProtectedProvider nesnesi.
        """
        if not hasattr(breaker, "name"):
            logger.warning("gecersiz_breaker_izleme_reddedildi", breaker=str(breaker))
            return

        with self._lock:
            self._tracked_breakers[breaker.name] = breaker

        logger.debug("circuit_breaker_izlemeye_alindi", name=breaker.name)

    def untrack(self, name: str) -> None:
        """Devre kesiciyi merkezi izlemeden çıkarır.

        Args:
            name: İzlemeden çıkarılacak devre kesici adı.
        """
        with self._lock:
            removed = self._tracked_breakers.pop(name, None)

        if removed is not None:
            logger.debug("circuit_breaker_izlemeden_cikarildi", name=name)

    def get_snapshot(self, name: str) -> CircuitBreakerSnapshot | None:
        """Belirtilen devre kesicinin anlık sağlık ve metrik görüntüsünü çıkarır.

        Args:
            name: Devre kesici adı.

        Returns:
            CircuitBreakerSnapshot | None: Varsa snapshot, yoksa None.
        """
        with self._lock:
            breaker = self._tracked_breakers.get(name)

        if not breaker:
            return None

        # Farklı nesne modellerinden (CircuitBreaker veya ProtectedProvider) esnek metrik çekme
        target = getattr(breaker, "circuit", breaker)

        # Durum tespiti
        raw_state = getattr(target, "state", "CLOSED")
        state_str = raw_state.value if hasattr(raw_state, "value") else str(raw_state)

        failure_count = int(getattr(target, "failure_count", 0))
        failure_threshold = int(getattr(target, "failure_threshold", 5))
        recovery_timeout = int(getattr(target, "recovery_timeout_seconds", 30))

        last_fail_raw = getattr(target, "last_failure_time", None)
        last_failure_time = (
            last_fail_raw.isoformat()
            if isinstance(last_fail_raw, datetime)
            else (str(last_fail_raw) if last_fail_raw else None)
        )

        last_succ_raw = getattr(target, "last_success_time", None)
        last_success_time = (
            last_succ_raw.isoformat()
            if isinstance(last_succ_raw, datetime)
            else (str(last_succ_raw) if last_succ_raw else None)
        )

        # İstek sayaçları (doğrudan veya reliability katmanından)
        reliability = getattr(breaker, "reliability", None)
        if reliability is not None and hasattr(reliability, "get_stats"):
            stats = reliability.get_stats()
            total_req = int(stats.get("total_calls", 0))
            total_fail = int(stats.get("total_failures", 0))
            total_succ = max(0, total_req - total_fail)
            success_count = total_succ
        else:
            total_req = int(getattr(breaker, "_total_requests", getattr(target, "_total_requests", 0)))
            total_fail = int(getattr(breaker, "_total_failures", getattr(target, "_total_failures", failure_count)))
            total_succ = int(getattr(breaker, "_total_successes", getattr(target, "_total_successes", 0)))
            success_count = int(getattr(breaker, "success_count", getattr(target, "half_open_calls", total_succ)))

        if total_req > 0:
            uptime = (total_succ / total_req) * 100.0
        else:
            uptime = 100.0 if failure_count == 0 else 0.0

        if math.isnan(uptime) or math.isinf(uptime):
            uptime = 100.0

        return CircuitBreakerSnapshot(
            name=breaker.name,
            state=state_str,
            failure_count=failure_count,
            success_count=success_count,
            failure_threshold=failure_threshold,
            recovery_timeout_seconds=recovery_timeout,
            last_failure_time=last_failure_time,
            last_success_time=last_success_time,
            total_requests=total_req,
            total_failures=total_fail,
            total_successes=total_succ,
            uptime_percentage=uptime,
        )

    def get_all_snapshots(self) -> list[CircuitBreakerSnapshot]:
        """Tüm kayıtlı devre kesicilerin snapshot listesini döner.

        Returns:
            list[CircuitBreakerSnapshot]: Tüm izlenen devre kesicilerin durumları.
        """
        with self._lock:
            names = list(self._tracked_breakers.keys())

        snapshots: list[CircuitBreakerSnapshot] = []
        for name in names:
            snap = self.get_snapshot(name)
            if snap is not None:
                snapshots.append(snap)
        return snapshots

    @otel_trace("circuit_breaker_metrics.export_prometheus")
    def export_prometheus(self) -> str:
        """Prometheus metin formatında tüm devre kesici metriklerini dışa aktarır.

        Returns:
            str: Prometheus uyumlu metrik çıktısı.
        """
        snapshots = self.get_all_snapshots()
        lines: list[str] = [
            "# HELP circuit_breaker_state Circuit breaker durumu (0=CLOSED, 1=HALF_OPEN, 2=OPEN)",
            "# TYPE circuit_breaker_state gauge",
            "# HELP circuit_breaker_failures Mevcut ardışık hata sayısı",
            "# TYPE circuit_breaker_failures gauge",
            "# HELP circuit_breaker_requests Toplam işlenen istek adedi",
            "# TYPE circuit_breaker_requests counter",
            "# HELP circuit_breaker_total_failures Toplam başarısız istek adedi",
            "# TYPE circuit_breaker_total_failures counter",
            "# HELP circuit_breaker_uptime_pct Başarı ve çalışabilirlik yüzdesi",
            "# TYPE circuit_breaker_uptime_pct gauge",
        ]

        state_map = {"CLOSED": 0, "HALF_OPEN": 1, "OPEN": 2}

        for snap in snapshots:
            safe_name = snap.name.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")
            labels = f'name="{safe_name}"'
            state_val = state_map.get(snap.state, -1)

            lines.append(f"circuit_breaker_state{{{labels}}} {state_val}")
            lines.append(f"circuit_breaker_failures{{{labels}}} {snap.failure_count}")
            lines.append(f"circuit_breaker_requests{{{labels}}} {snap.total_requests}")
            lines.append(f"circuit_breaker_total_failures{{{labels}}} {snap.total_failures}")
            lines.append(f"circuit_breaker_uptime_pct{{{labels}}} {snap.uptime_percentage:.2f}")

        return "\n".join(lines) + "\n"

    def export_json(self) -> dict[str, Any]:
        """Tüm metrikleri ve sistem özetini sözlük yapısında döner.

        Returns:
            dict[str, Any]: JSON uyumlu metrik raporu.
        """
        snapshots = self.get_all_snapshots()

        total_count = len(snapshots)
        closed_count = sum(1 for s in snapshots if s.state == "CLOSED")
        open_count = sum(1 for s in snapshots if s.state == "OPEN")
        half_open_count = sum(1 for s in snapshots if s.state == "HALF_OPEN")

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "circuit_breakers": {s.name: s.to_dict() for s in snapshots},
            "summary": {
                "total": total_count,
                "closed": closed_count,
                "open": open_count,
                "half_open": half_open_count,
                "healthy_ratio": round(closed_count / total_count, 3) if total_count > 0 else 1.0,
            },
        }

    def export_orjson_bytes(self) -> bytes:
        """Tüm metrikleri orjson ile yüksek hızlı ikili JSON bayt dizisi olarak üretir.

        Returns:
            bytes: UTF-8 kodlanmış JSON verisi.
        """
        return orjson.dumps(self.export_json())

    @otel_trace("circuit_breaker_metrics.record_state_change")
    def record_state_change(self, name: str, old_state: str, new_state: str) -> None:
        """Devre kesicide meydana gelen bir durum geçişini tarihçeye kaydeder.

        Args:
            name: Devre kesici adı.
            old_state: Önceki durum ("CLOSED", "OPEN", "HALF_OPEN").
            new_state: Yeni durum.
        """
        entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "name": name,
            "old_state": str(old_state),
            "new_state": str(new_state),
        }

        with self._lock:
            self._history.append(entry)

        logger.info(
            "circuit_breaker_durumu_degisti",
            name=name,
            eski_durum=old_state,
            yeni_durum=new_state,
        )

    def get_history(self, limit: int = DEFAULT_HISTORY_LIMIT) -> list[dict[str, Any]]:
        """Son durum geçişi kayıtlarını döner.

        Args:
            limit: Döndürülecek maksimum kayıt sayısı.

        Returns:
            list[dict[str, Any]]: Kronolojik durum değişikliği listesi.
        """
        safe_limit = max(1, min(limit, self._max_history))
        with self._lock:
            # deque sonundan güvenli kopya alma
            history_list = list(self._history)

        return history_list[-safe_limit:]

    def clear(self) -> None:
        """Kayıtlı devre kesicileri ve durum tarihçesini temizler (Testler ve sıfırlama için)."""
        with self._lock:
            self._tracked_breakers.clear()
            self._history.clear()

    def __repr__(self) -> str:
        """Toplayıcının okunabilir dize temsilini döner."""
        with self._lock:
            count = len(self._tracked_breakers)
            history_len = len(self._history)
        return (
            f"CircuitBreakerMetricsCollector(tracked_breakers={count}, "
            f"history_events={history_len}/{self._max_history})"
        )


# Global Singleton Örneği
circuit_breaker_metrics: Final[CircuitBreakerMetricsCollector] = CircuitBreakerMetricsCollector()

__all__: Sequence[str] = [
    "DEFAULT_HISTORY_LIMIT",
    "DEFAULT_MAX_HISTORY",
    "CircuitBreakerMetricsCollector",
    "CircuitBreakerSnapshot",
    "circuit_breaker_metrics",
]
