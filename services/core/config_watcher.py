"""
ALPHA BIST — Config Hot Reload Watcher

Runtime config değişiklik algılama, güvenli reload, audit logging.

Özellikler:
- Dosya değişikliği algılama (mtime-based)
- Geçersiz config → eski config koruma
- Config değişiklik audit log
- Concurrent access safety

Kullanım:
    watcher = ConfigWatcher("config/alpha_config.json", ConfigLoader.load)
    watcher.start()
    # Config değişirse otomatik reload
    watcher.stop()
"""

import asyncio
import orjson
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class ConfigAuditEntry:
    timestamp: float
    action: str  # reload, reload_failed, validation_failed, rollback
    config_path: str
    old_version: Any = None
    new_version: Any = None
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            "action": self.action,
            "config_path": self.config_path,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "error": self.error,
        }


class ConfigWatcher:
    """Config dosyası hot reload watcher."""

    def __init__(
        self,
        config_path: str,
        reload_fn: Callable,
        validate_fn: Optional[Callable] = None,
        watch_interval_s: float = 5.0,
        on_change: Optional[Callable] = None,
    ):
        self._config_path = config_path
        self._reload_fn = reload_fn
        self._validate_fn = validate_fn
        self._watch_interval_s = watch_interval_s
        self._on_change = on_change
        self._last_mtime: float = 0
        self._last_config: Optional[Dict] = None
        self._audit_log: List[ConfigAuditEntry] = []
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._reload_count = 0
        self._error_count = 0

    def start(self):
        """Watcher'ı başlat."""
        if self._running:
            return
        self._running = True
        try:
            self._task = asyncio.ensure_future(self._watch_loop())
        except RuntimeError:
            pass
        logger.info("Config watcher started", path=self._config_path)

    def stop(self):
        """Watcher'ı durdur."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
        logger.info("Config watcher stopped", path=self._config_path,
                   reloads=self._reload_count, errors=self._error_count)

    async def _watch_loop(self):
        """Periyodik dosya değişiklik kontrolü."""
        # İlk yükleme
        if os.path.exists(self._config_path):
            self._last_mtime = os.path.getmtime(self._config_path)

        while self._running:
            try:
                await asyncio.sleep(self._watch_interval_s)
                await self._check_and_reload()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Config watcher error", error=str(e))

    async def _check_and_reload(self):
        """Dosya değişikliği kontrolü ve reload."""
        if not os.path.exists(self._config_path):
            return

        current_mtime = os.path.getmtime(self._config_path)
        if current_mtime <= self._last_mtime:
            return

        logger.info("Config file changed", path=self._config_path,
                   old_mtime=self._last_mtime, new_mtime=current_mtime)

        # Eski config'i sakla
        old_config = self._last_config
        old_version = old_config.get("version") if isinstance(old_config, dict) else None

        try:
            # Yeni config'i oku
            with open(self._config_path) as f:
                new_config = orjson.loads(f.read())

            # Validation
            if self._validate_fn:
                errors = self._validate_fn(new_config)
                if errors:
                    self._error_count += 1
                    self._audit_log.append(ConfigAuditEntry(
                        timestamp=time.time(), action="validation_failed",
                        config_path=self._config_path,
                        old_version=old_version,
                        error=str(errors),
                    ))
                    logger.error("Config validation failed, keeping old config",
                               errors=errors)
                    # mtime güncelle (tekrar denemeyi engelle)
                    self._last_mtime = current_mtime
                    return

            # Reload
            self._reload_fn()
            self._last_config = new_config
            self._last_mtime = current_mtime
            self._reload_count += 1

            new_version = new_config.get("version") if isinstance(new_config, dict) else None

            self._audit_log.append(ConfigAuditEntry(
                timestamp=time.time(), action="reload",
                config_path=self._config_path,
                old_version=old_version, new_version=new_version,
            ))

            logger.info("Config reloaded successfully",
                       version=new_version, total_reloads=self._reload_count)

            # Callback
            if self._on_change:
                try:
                    self._on_change(new_config)
                except Exception as e:
                    logger.warning("Config change callback failed", error=str(e))

        except orjson.JSONDecodeError as e:
            self._error_count += 1
            self._audit_log.append(ConfigAuditEntry(
                timestamp=time.time(), action="reload_failed",
                config_path=self._config_path, error=f"JSON error: {e}",
            ))
            logger.error("Config reload failed (invalid JSON), keeping old config",
                        error=str(e))
            self._last_mtime = current_mtime

        except Exception as e:
            self._error_count += 1
            self._audit_log.append(ConfigAuditEntry(
                timestamp=time.time(), action="reload_failed",
                config_path=self._config_path, error=str(e),
            ))
            logger.error("Config reload failed, keeping old config", error=str(e))
            self._last_mtime = current_mtime

    def get_audit_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Config değişiklik audit log."""
        return [e.to_dict() for e in self._audit_log[-limit:]]

    def get_status(self) -> Dict[str, Any]:
        """Watcher durumu."""
        return {
            "running": self._running,
            "config_path": self._config_path,
            "reload_count": self._reload_count,
            "error_count": self._error_count,
            "last_mtime": self._last_mtime,
            "watch_interval_s": self._watch_interval_s,
        }

    def force_reload(self) -> bool:
        """Manuel reload tetikle."""
        try:
            self._reload_fn()
            self._reload_count += 1
            self._audit_log.append(ConfigAuditEntry(
                timestamp=time.time(), action="force_reload",
                config_path=self._config_path,
            ))
            return True
        except Exception as e:
            self._error_count += 1
            self._audit_log.append(ConfigAuditEntry(
                timestamp=time.time(), action="reload_failed",
                config_path=self._config_path, error=str(e),
            ))
            return False
