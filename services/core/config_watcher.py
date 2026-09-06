"""ALPHA BIST — Config Hot Reload Watcher v3.0 (Dinamik Yapılandırma İzleyici)

Bu modül, diskteki yapılandırma dosyalarının son değişiklik zamanlarını (mtime)
veya içerik karmalarını asenkron olarak izler; değişiklik algılandığında
doğrulama (validation) süzgecinden geçirerek güvenli sıcak yeniden yükleme (hot reload)
ve denetim kaydı (audit logging) gerçekleştirir.

Özellikler:
- Dosya değişikliği algılama (mtime ve boyut tabanlı).
- Geçersiz yapılandırma koruması (fail-safe rollback): Geçersiz yapılandırmada
  eski kararlı konfigürasyon korunur.
- Eşzamanlılık güvenliği: `threading.RLock` ile çoklu iş parçacığı koruması.
- Windows UTF-8 ve ikili okuma güvenliği (`Path.read_bytes()`).
- Polars DataFrame ve DuckDB tabanlı denetim günlüğü (audit log) dışa aktarımı.
- OpenTelemetry span entegrasyonu.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# Sabitler
DEFAULT_WATCH_INTERVAL_SECONDS: float = 30.0  # SSD aşınmasını önlemek için 30 saniye
DEFAULT_MAX_AUDIT_LOG_ENTRIES: int = 500
DEFAULT_DUCKDB_PATH: Path = Path("data/config_watcher.duckdb")


@dataclass(slots=True)
class ConfigAuditEntry:
    """Yapılandırma değişikliği veya yeniden yükleme denetim kaydı.

    Attributes:
        timestamp: Olayın gerçekleştiği Unix zaman damgası.
        action: Gerçekleşen eylem ('reload', 'reload_failed', 'validation_failed', 'force_reload').
        config_path: İzlenen dosyanın yolu.
        old_version: Değişiklik öncesi sürüm / durum bilgisi.
        new_version: Yeni yüklenen sürüm bilgisi.
        error: Hata oluştuysa açıklayıcı hata metni.
    """

    timestamp: float
    action: str
    config_path: str
    old_version: Any = None
    new_version: Any = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Denetim kaydını sözlük formatına dönüştürür."""
        return {
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(self.timestamp, tz=UTC).isoformat(),
            "action": self.action,
            "config_path": self.config_path,
            "old_version": str(self.old_version) if self.old_version is not None else None,
            "new_version": str(self.new_version) if self.new_version is not None else None,
            "error": self.error,
        }

    def to_orjson_bytes(self) -> bytes:
        """Denetim kaydını orjson bayt dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    def to_json(self) -> str:
        """Denetim kaydını JSON metnine dönüştürür."""
        return self.to_orjson_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConfigAuditEntry:
        """Sözlükten ConfigAuditEntry nesnesi oluşturur."""
        return cls(
            timestamp=float(data.get("timestamp", time.time())),
            action=str(data.get("action", "unknown")),
            config_path=str(data.get("config_path", "")),
            old_version=data.get("old_version"),
            new_version=data.get("new_version"),
            error=str(data.get("error", "")),
        )

    def __repr__(self) -> str:
        return (
            f"<ConfigAuditEntry action='{self.action}' path='{self.config_path}' "
            f"error='{self.error[:30]}' ts={self.timestamp:.0f}>"
        )


class ConfigWatcher:
    """Yapılandırma dosyasını izleyerek sıcak yeniden yükleme sağlayan izleyici sınıf."""

    def __init__(
        self,
        config_path: str | Path,
        reload_fn: Callable[[], Any],
        validate_fn: Callable[[dict[str, Any]], Any] | None = None,
        watch_interval_s: float = DEFAULT_WATCH_INTERVAL_SECONDS,
        on_change: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        """ConfigWatcher örneğini başlatır.

        Args:
            config_path: İzlenecek dosyanın dosya yolu.
            reload_fn: Değişiklik onaylandığında çağrılacak yeniden yükleme fonksiyonu.
            validate_fn: Yeni konfigürasyonu doğrulamak için çağrılacak fonksiyon (hata listesi döner).
            watch_interval_s: Disk kontrol periyodu (saniye).
            on_change: Başarılı reload sonrasında çağrılacak geri çağırma (callback) fonksiyonu.
        """
        self._config_path: Path = Path(config_path)
        self._reload_fn: Callable[[], Any] = reload_fn
        self._validate_fn: Callable[[dict[str, Any]], Any] | None = validate_fn
        self._watch_interval_s: float = max(1.0, float(watch_interval_s))
        self._on_change: Callable[[dict[str, Any]], Any] | None = on_change

        self._last_mtime: float = 0.0
        self._last_config: dict[str, Any] | None = None
        self._audit_log: deque[ConfigAuditEntry] = deque(maxlen=DEFAULT_MAX_AUDIT_LOG_ENTRIES)
        self._task: asyncio.Task[None] | None = None
        self._running: bool = False
        self._reload_count: int = 0
        self._error_count: int = 0
        self._lock: threading.RLock = threading.RLock()

    @property
    def is_running(self) -> bool:
        """İzleyicinin çalışır durumda olup olmadığını döndürür."""
        with self._lock:
            return self._running

    @otel_trace("config_watcher.start")
    def start(self) -> None:
        """Yapılandırma izleyicisini asenkron olarak başlatır."""
        with self._lock:
            if self._running:
                return
            self._running = True

            # Başlangıç mtime'ını kaydet
            if self._config_path.exists():
                with contextlib.suppress(OSError):
                    self._last_mtime = self._config_path.stat().st_mtime

            try:
                loop = asyncio.get_running_loop()
                self._task = loop.create_task(self._watch_loop())
            except RuntimeError:
                # Çalışan bir event loop yoksa, arka plan görevi loop başladığında devralacaktır
                logger.info("config_watcher_loop_bulunamadi_manuel_veya_harici_tetikleme_bekleniyor")

            logger.info("Config watcher başlatıldı", path=str(self._config_path), interval_s=self._watch_interval_s)

    @otel_trace("config_watcher.stop")
    def stop(self) -> None:
        """Yapılandırma izleyicisini güvenle durdurur."""
        with self._lock:
            self._running = False
            if self._task and not self._task.done():
                self._task.cancel()
                self._task = None
            logger.info(
                "Config watcher durduruldu",
                path=str(self._config_path),
                reloads=self._reload_count,
                errors=self._error_count,
            )

    async def _watch_loop(self) -> None:
        """Periyodik dosya değişiklik kontrolü döngüsü."""
        while self.is_running:
            try:
                await asyncio.sleep(self._watch_interval_s)
                await self.check_and_reload()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("config_watcher_dongu_hatasi", error=str(e))

    @otel_trace("config_watcher.check_and_reload")
    async def check_and_reload(self) -> bool:
        """Dosya değişikliğini asenkron kontrol eder ve gerekirse yeniden yükler."""
        return self.check_and_reload_sync()

    def check_and_reload_sync(self) -> bool:
        """Dosya değişikliğini senkron olarak kontrol eder ve yeniden yükler.

        Returns:
            Yeniden yükleme yapıldıysa True, yapılmadıysa veya hata oluştuysa False.
        """
        with self._lock:
            if not self._config_path.exists():
                return False

            try:
                current_mtime = self._config_path.stat().st_mtime
            except OSError:
                return False

            if current_mtime <= self._last_mtime:
                return False

            logger.info(
                "Config dosyası değişti, yeniden yükleniyor",
                path=str(self._config_path),
                old_mtime=self._last_mtime,
                new_mtime=current_mtime,
            )

            old_config = self._last_config
            old_version = old_config.get("version") if isinstance(old_config, dict) else None

            try:
                raw_bytes = self._config_path.read_bytes()
                suffix = self._config_path.suffix.lower()
                if suffix in (".yaml", ".yml"):
                    import yaml

                    parsed = yaml.safe_load(raw_bytes.decode("utf-8-sig"))
                    new_config = parsed if isinstance(parsed, dict) else {}
                else:
                    try:
                        parsed = orjson.loads(raw_bytes)
                        new_config = parsed if isinstance(parsed, dict) else {}
                    except orjson.JSONDecodeError:
                        import yaml

                        parsed = yaml.safe_load(raw_bytes.decode("utf-8-sig"))
                        new_config = parsed if isinstance(parsed, dict) else {}

                if not isinstance(new_config, dict):
                    self._error_count += 1
                    self._record_audit(
                        action="validation_failed",
                        old_version=old_version,
                        error="Yapılandırma kök nesnesi bir sözlük (dictionary/mapping) olmalıdır.",
                    )
                    self._last_mtime = current_mtime
                    return False

                # Validasyon süzgeci
                if self._validate_fn:
                    validation_errors = self._validate_fn(new_config)
                    # Hata varsa (liste doluysa veya boolean False ise)
                    if validation_errors:
                        self._error_count += 1
                        self._record_audit(
                            action="validation_failed",
                            old_version=old_version,
                            error=str(validation_errors),
                        )
                        logger.error("Config validasyonu başarısız, eski konfigürasyon korunuyor", errors=validation_errors)
                        self._last_mtime = current_mtime
                        return False

                # Yeniden yükleme fonksiyonunu çalıştır
                self._reload_fn()
                self._last_config = new_config
                self._last_mtime = current_mtime
                self._reload_count += 1

                new_version = new_config.get("version") if isinstance(new_config, dict) else None
                self._record_audit(
                    action="reload",
                    old_version=old_version,
                    new_version=new_version,
                )
                logger.info("Config başarıyla yenilendi", version=new_version, total_reloads=self._reload_count)

                # Değişiklik bildirim callback'i
                if self._on_change:
                    try:
                        self._on_change(new_config)
                    except Exception as cb_err:
                        logger.warning("config_on_change_callback_hatasi", error=str(cb_err))

                return True

            except orjson.JSONDecodeError as jde:
                self._error_count += 1
                self._record_audit(
                    action="reload_failed",
                    error=f"JSON ayrıştırma hatası: {jde}",
                )
                logger.error("Config reload başarısız (geçersiz JSON), eski konfigürasyon korunuyor", error=str(jde))
                self._last_mtime = current_mtime
                return False

            except Exception as e:
                self._error_count += 1
                self._record_audit(
                    action="reload_failed",
                    error=str(e),
                )
                logger.error("Config reload genel hatası, eski konfigürasyon korunuyor", error=str(e))
                self._last_mtime = current_mtime
                return False

    @otel_trace("config_watcher.force_reload")
    def force_reload(self) -> bool:
        """Değişiklik zamanına bakılmaksızın zorla yeniden yüklemeyi tetikler.

        Returns:
            Yeniden yükleme başarılı ise True, başarısız ise False.
        """
        with self._lock:
            try:
                self._reload_fn()
                self._reload_count += 1
                self._record_audit(action="force_reload")
                logger.info("Config force_reload başarılı", total_reloads=self._reload_count)
                return True
            except Exception as e:
                self._error_count += 1
                self._record_audit(action="reload_failed", error=str(e))
                logger.error("Config force_reload başarısız", error=str(e))
                return False

    def get_audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Geçmiş denetim kayıtlarını sözlük listesi olarak döndürür.

        Args:
            limit: Döndürülecek maksimum kayıt sayısı.

        Returns:
            Denetim kayıtları listesi.
        """
        with self._lock:
            items = list(self._audit_log)[-limit:]
            return [e.to_dict() for e in items]

    def get_status(self) -> dict[str, Any]:
        """İzleyicinin anlık çalışma durumunu döndürür."""
        with self._lock:
            return {
                "running": self._running,
                "config_path": str(self._config_path),
                "reload_count": self._reload_count,
                "error_count": self._error_count,
                "last_mtime": self._last_mtime,
                "watch_interval_s": self._watch_interval_s,
                "audit_entries_count": len(self._audit_log),
            }

    def _record_audit(
        self,
        action: str,
        old_version: Any = None,
        new_version: Any = None,
        error: str = "",
    ) -> None:
        """Denetim günlüğüne yeni bir kayıt ekler."""
        entry = ConfigAuditEntry(
            timestamp=time.time(),
            action=action,
            config_path=str(self._config_path),
            old_version=old_version,
            new_version=new_version,
            error=error,
        )
        self._audit_log.append(entry)

    def export_audit_log_to_polars(self) -> pl.DataFrame:
        """Denetim geçmişini Polars DataFrame olarak döndürür."""
        with self._lock:
            logs = [e.to_dict() for e in self._audit_log]

        schema = {
            "timestamp": pl.Float64,
            "timestamp_iso": pl.Utf8,
            "action": pl.Utf8,
            "config_path": pl.Utf8,
            "old_version": pl.Utf8,
            "new_version": pl.Utf8,
            "error": pl.Utf8,
        }
        if not logs:
            return pl.DataFrame(schema=schema)

        return pl.DataFrame(logs, schema=schema)

    def export_audit_log_to_duckdb(
        self,
        db_path: str | Path = DEFAULT_DUCKDB_PATH,
        table_name: str = "bist_config_watcher_audit",
    ) -> int:
        """Denetim geçmişini DuckDB tablosuna kaydeder.

        Args:
            db_path: DuckDB dosya yolu.
            table_name: Hedef tablo adı.

        Returns:
            Kaydedilen kayıt sayısı.
        """
        df = self.export_audit_log_to_polars()
        if df.is_empty():
            return 0

        path_obj = Path(db_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        if path_obj.exists() and path_obj.stat().st_size == 0:
            with contextlib.suppress(OSError):
                path_obj.unlink()

        try:
            with duckdb.connect(str(path_obj)) as conn:
                from services.core.debounce import configure_duckdb_wal

                configure_duckdb_wal(conn)
                conn.register("df_audit_snap", df.to_arrow())
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM df_audit_snap WHERE 1=0"
                )
                conn.execute(f"INSERT INTO {table_name} SELECT * FROM df_audit_snap")
            return len(df)
        except Exception as e:
            logger.error("export_config_watcher_to_duckdb_failed", error=str(e))
            return 0

    def query_audit_log_duckdb(
        self,
        db_path: str | Path = DEFAULT_DUCKDB_PATH,
        table_name: str = "bist_config_watcher_audit",
        limit: int = 100,
    ) -> pl.DataFrame:
        """DuckDB üzerinden geçmiş izleyici kayıtlarını sorgular.

        Args:
            db_path: DuckDB dosya yolu.
            table_name: Tablo adı.
            limit: Maksimum satır sayısı.

        Returns:
            Polars DataFrame.
        """
        schema = {
            "timestamp": pl.Float64,
            "timestamp_iso": pl.Utf8,
            "action": pl.Utf8,
            "config_path": pl.Utf8,
            "old_version": pl.Utf8,
            "new_version": pl.Utf8,
            "error": pl.Utf8,
        }
        empty_df = pl.DataFrame(schema=schema)
        path_obj = Path(db_path)
        if not path_obj.exists() or path_obj.stat().st_size == 0:
            return empty_df

        try:
            with duckdb.connect(str(path_obj), read_only=True) as conn:
                tables = conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_name = ?",
                    [table_name],
                ).fetchall()
                if not tables:
                    return empty_df

                query = f"SELECT * FROM {table_name} ORDER BY timestamp DESC LIMIT ?"
                arrow_res = conn.execute(query, [limit]).arrow()
                return pl.from_arrow(arrow_res)
        except Exception as e:
            logger.error("query_config_watcher_duckdb_failed", error=str(e))
            return empty_df

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"<ConfigWatcher path='{self._config_path}' running={self._running} "
                f"reloads={self._reload_count} errors={self._error_count}>"
            )


__all__ = [
    "DEFAULT_WATCH_INTERVAL_SECONDS",
    "DEFAULT_MAX_AUDIT_LOG_ENTRIES",
    "DEFAULT_DUCKDB_PATH",
    "ConfigAuditEntry",
    "ConfigWatcher",
]
