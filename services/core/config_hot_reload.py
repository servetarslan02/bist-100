"""
ALPHA BIST — Config Hot-Reload

Config dosyası değişikliğini izle ve runtime'da yeniden yükle.
Restart gerektirmez.

Özellikler:
1. File watcher (polling tabanlı)
2. Change callback mechanism
3. Validation before apply
4. Rollback on error
5. Change history

Referanslar:
- CORE-NIHAI-SPEC.md - Section 2.3
"""

import os
import json
import time
import asyncio
import hashlib
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import structlog

logger = structlog.get_logger()


@dataclass
class ConfigChange:
    """Config değişiklik kaydı."""
    change_id: str
    timestamp: datetime
    file_path: str
    old_hash: str
    new_hash: str
    changed_keys: List[str]
    applied: bool
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "change_id": self.change_id,
            "timestamp": self.timestamp.isoformat(),
            "file_path": self.file_path,
            "old_hash": self.old_hash[:12],
            "new_hash": self.new_hash[:12],
            "changed_keys": self.changed_keys,
            "applied": self.applied,
            "error": self.error,
        }


class ConfigHotReload:
    """
    Config hot-reload yöneticisi.

    Config dosyasını izler, değişiklik algılar,
    callback'leri tetikler ve güvenli şekilde uygular.

    Kullanım:
        reloader = ConfigHotReload("/path/to/config.json")
        reloader.on_change(my_callback)
        await reloader.start()
    """

    def __init__(
        self,
        config_path: str,
        watch_interval_seconds: float = 5.0,
        auto_apply: bool = True,
        validate_before_apply: bool = True,
    ):
        self._config_path = Path(config_path)
        self._watch_interval = watch_interval_seconds
        self._auto_apply = auto_apply
        self._validate_before_apply = validate_before_apply

        self._callbacks: List[Callable] = []
        self._validators: List[Callable] = []
        self._last_modified: float = 0
        self._last_hash: str = ""
        self._current_config: Dict[str, Any] = {}
        self._running = False
        self._change_history: List[ConfigChange] = []
        self._max_history = 100

    def on_change(self, callback: Callable):
        """
        Değişiklik callback'i ekle.

        Callback imzası: async def callback(old_config, new_config, changed_keys)
        """
        self._callbacks.append(callback)

    def add_validator(self, validator: Callable):
        """
        Validation callback ekle.

        Validator imzası: def validate(config) -> Tuple[bool, Optional[str]]
        Returns: (is_valid, error_message)
        """
        self._validators.append(validator)

    async def start(self):
        """İzlemeyi başlat."""
        if not self._config_path.exists():
            logger.warning("Config file not found, creating empty",
                          path=str(self._config_path))
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._config_path.write_text("{}")

        self._running = True
        self._load_config()

        logger.info("Config hot-reload started",
                    path=str(self._config_path),
                    interval=self._watch_interval)

        while self._running:
            try:
                await self._check_for_changes()
            except Exception as e:
                logger.error("Config watch error", error=str(e))
            await asyncio.sleep(self._watch_interval)

    async def stop(self):
        """İzlemeyi durdur."""
        self._running = False
        logger.info("Config hot-reload stopped")

    def _load_config(self) -> Dict[str, Any]:
        """Config dosyasını yükle."""
        try:
            content = self._config_path.read_text()
            self._last_modified = os.path.getmtime(self._config_path)
            self._last_hash = hashlib.sha256(content.encode()).hexdigest()

            if content.strip():
                self._current_config = json.loads(content)
            else:
                self._current_config = {}

            return self._current_config

        except json.JSONDecodeError as e:
            logger.error("Config file invalid JSON", error=str(e))
            return self._current_config
        except Exception as e:
            logger.error("Config load error", error=str(e))
            return self._current_config

    async def _check_for_changes(self):
        """Dosya değişikliğini kontrol et."""
        try:
            current_modified = os.path.getmtime(self._config_path)

            if current_modified <= self._last_modified:
                return

            # Content hash check (modified time değişmiş ama content aynı olabilir)
            content = self._config_path.read_text()
            current_hash = hashlib.sha256(content.encode()).hexdigest()

            if current_hash == self._last_hash:
                self._last_modified = current_modified
                return

            # Change detected
            logger.info("Config change detected",
                       old_hash=self._last_hash[:12],
                       new_hash=current_hash[:12])

            old_config = self._current_config.copy()
            old_hash = self._last_hash

            new_config = json.loads(content) if content.strip() else {}

            # Find changed keys
            changed_keys = self._find_changed_keys(old_config, new_config)

            # Validate
            if self._validate_before_apply:
                is_valid, error = self._validate_config(new_config)
                if not is_valid:
                    logger.error("Config validation failed, not applying",
                               error=error)
                    self._record_change(old_hash, current_hash, changed_keys,
                                       applied=False, error=error)
                    return

            # Apply
            self._current_config = new_config
            self._last_modified = current_modified
            self._last_hash = current_hash

            self._record_change(old_hash, current_hash, changed_keys, applied=True)

            # Notify callbacks
            if self._auto_apply:
                await self._notify_callbacks(old_config, new_config, changed_keys)

        except json.JSONDecodeError as e:
            logger.error("Config parse error during watch", error=str(e))
        except Exception as e:
            logger.error("Config watch check error", error=str(e))

    def _find_changed_keys(
        self,
        old: Dict[str, Any],
        new: Dict[str, Any],
    ) -> List[str]:
        """Değişen anahtarları bul."""
        changed = []
        all_keys = set(old.keys()) | set(new.keys())

        for key in all_keys:
            old_val = old.get(key)
            new_val = new.get(key)
            if old_val != new_val:
                changed.append(key)

        return changed

    def _validate_config(self, config: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Config'i validate et."""
        for validator in self._validators:
            try:
                is_valid, error = validator(config)
                if not is_valid:
                    return False, error
            except Exception as e:
                return False, f"Validator error: {e}"
        return True, None

    async def _notify_callbacks(
        self,
        old_config: Dict[str, Any],
        new_config: Dict[str, Any],
        changed_keys: List[str],
    ):
        """Callback'leri bildir."""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(old_config, new_config, changed_keys)
                else:
                    callback(old_config, new_config, changed_keys)
            except Exception as e:
                logger.error("Config callback error",
                           callback=callback.__name__,
                           error=str(e))

    def _record_change(
        self,
        old_hash: str,
        new_hash: str,
        changed_keys: List[str],
        applied: bool,
        error: Optional[str] = None,
    ):
        """Değişiklik kaydet."""
        import hashlib as hl
        change_id = hl.md5(
            f"{new_hash}_{time.time()}".encode()
        ).hexdigest()[:12]

        change = ConfigChange(
            change_id=change_id,
            timestamp=datetime.now(timezone.utc),
            file_path=str(self._config_path),
            old_hash=old_hash,
            new_hash=new_hash,
            changed_keys=changed_keys,
            applied=applied,
            error=error,
        )

        self._change_history.append(change)
        if len(self._change_history) > self._max_history:
            self._change_history = self._change_history[-self._max_history:]

    def get_current_config(self) -> Dict[str, Any]:
        """Mevcut config'i döndür."""
        return self._current_config.copy()

    def get_change_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Değişiklik geçmişi."""
        return [c.to_dict() for c in self._change_history[-limit:]]

    def force_reload(self) -> Dict[str, Any]:
        """Zorla yeniden yükle."""
        old_config = self._current_config.copy()
        new_config = self._load_config()

        changed_keys = self._find_changed_keys(old_config, new_config)
        if changed_keys:
            logger.info("Force reload changed keys", keys=changed_keys)

        return new_config


# Singleton
config_hot_reload = ConfigHotReload("config.json")
