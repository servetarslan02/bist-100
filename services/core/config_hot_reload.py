"""ALPHA BIST — Kurumsal Dinamik Konfigürasyon İzleme ve Hot-Reload Motoru.

Bu modül, mikroservislerin ve çekirdek algoritmaların kesintisiz çalışabilmesi için
çalışma zamanı (runtime) ayarlarını izler, doğrular ve güvenli şekilde günceller:

1. SRP (Single Responsibility Principle):
   - `ConfigHotReload`: Dosya seviyesinde değişiklikleri (mtime ve SHA-256 hash) izler,
     doğrulayıcılardan (validators) geçirir ve kayıtlı callback'leri asenkron tetikler.
   - `SettingsBridge`: Pydantic Settings modelinin değişmezlik (immutability) garantisini
     koruyarak atomik referans takası (reference swap) ile ayarları günceller.
2. Güvenlik ve Gizlilik (Zero Leakage / Secret Protection):
   - Hassas alanlar (API Key, Veritabanı ve JWT parolaları) kesinlikle JSON dosyasından
     yüklenemez; tespit edildiğinde doğrulayıcı tarafından işlem fail-closed reddedilir.
3. Atomik Disk Yazma Güvenliği:
   - Config dosyaları yazılırken geçici `.tmp.<uuid>` dosyası üzerinden atomik `os.replace`
     kullanılarak sıfır-bayt bozulmaları (data corruption) engellenir.
4. DuckDB & Polars Denetim İzi (Audit Trail):
   - Gerçekleşen tüm konfigürasyon değişiklikleri kalıcı DuckDB günlüğüne kaydedilir
     ve `export_history_to_polars()` ile sıfır kopyalı Polars DataFrame olarak sunulur.
5. Eşzamanlılık ve Reentrancy Güvenliği:
   - `threading.RLock()` ile callback listeleri, doğrulayıcılar ve durum geçmişi
     eşzamanlı erişime karşı tam koruma altındadır.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import duckdb
import orjson
import polars as pl
import structlog
from opentelemetry import trace

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.config-hot-reload")

# Varsayılan Yapılandırma Sabitleri
DEFAULT_WATCH_INTERVAL_SECONDS: Final[float] = 30.0  # SSD koruma limiti (30s)
DEFAULT_MAX_HISTORY_LEN: Final[int] = 100
DEFAULT_CONFIG_DB_PATH: Final[str] = "data/config_audit.duckdb"


@dataclass(slots=True)
class ConfigChange:
    """Konfigürasyon değişiklik kaydı veri modeli.

    Attributes:
        change_id: Değişikliğin benzersiz özeti/kimliği.
        timestamp: Değişikliğin gerçekleştiği UTC zaman damgası.
        file_path: İzlenen konfigürasyon dosyasının yolu.
        old_hash: Önceki içerik SHA-256 hash özeti.
        new_hash: Yeni içerik SHA-256 hash özeti.
        changed_keys: Değişen konfigürasyon anahtarlarının listesi.
        applied: Değişikliğin başarıyla uygulanıp uygulanmadığı.
        error: Varsa oluşan doğrulama veya uygulama hatası mesajı.
    """

    change_id: str
    timestamp: datetime
    file_path: str
    old_hash: str
    new_hash: str
    changed_keys: list[str]
    applied: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serileştirme ve JSON aktarımı için sözlük temsili üretir."""
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

    def __repr__(self) -> str:
        """Okunabilir nesne hata ayıklama temsili."""
        return (
            f"ConfigChange(id={self.change_id!r}, applied={self.applied}, "
            f"keys={self.changed_keys!r}, error={self.error!r})"
        )


class ConfigHotReload:
    """Çalışma zamanı konfigürasyon dosyası izleyicisi ve tetikleyicisi.

    Belirtilen konfigürasyon dosyasının disk üzerindeki değişimini SHA-256
    kontrolü ile izler; doğrulayıcılardan başarıyla geçen güncellemeleri
    kayıtlı dinleyicilere asenkron olarak iletir.
    """

    def __init__(
        self,
        config_path: str,
        watch_interval_seconds: float = DEFAULT_WATCH_INTERVAL_SECONDS,
        auto_apply: bool = True,
        validate_before_apply: bool = True,
        db_path: str = DEFAULT_CONFIG_DB_PATH,
    ) -> None:
        """ConfigHotReload izleyicisini başlatır.

        Args:
            config_path: İzlenecek konfigürasyon JSON dosyasının yolu.
            watch_interval_seconds: Dosya tarama sıklığı (saniye).
            auto_apply: Değişikliklerin doğrulanınca otomatik uygulanıp uygulanmayacağı.
            validate_before_apply: Uygulama öncesinde doğrulayıcıların çalıştırılması.
            db_path: Değişiklik geçmişinin saklanacağı DuckDB veritabanı yolu.
        """
        self._config_path = Path(config_path)
        self._watch_interval = max(1.0, float(watch_interval_seconds))
        self._auto_apply = auto_apply
        self._validate_before_apply = validate_before_apply
        self._db_path = db_path

        self._lock = threading.RLock()
        self._callbacks: list[Callable[..., Any]] = []
        self._validators: list[Callable[[dict[str, Any]], tuple[bool, str | None]]] = []
        self._last_modified: float = 0.0
        self._last_hash: str = ""
        self._current_config: dict[str, Any] = {}
        self._running: bool = False
        self._change_history: deque[ConfigChange] = deque(maxlen=DEFAULT_MAX_HISTORY_LEN)

        self._conn: duckdb.DuckDBPyConnection | None = None
        self._init_db()

    def _init_db(self) -> None:
        """Kalıcı DuckDB denetim tablosunu hazırlar."""
        try:
            db_file = Path(self._db_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            self._conn = duckdb.connect(str(db_file))
            with self._lock:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS config_audit_log (
                        id BIGINT PRIMARY KEY,
                        timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                        change_id VARCHAR NOT NULL,
                        file_path VARCHAR NOT NULL,
                        old_hash VARCHAR NOT NULL,
                        new_hash VARCHAR NOT NULL,
                        changed_keys VARCHAR NOT NULL,
                        applied BOOLEAN NOT NULL,
                        error VARCHAR
                    );
                    CREATE SEQUENCE IF NOT EXISTS seq_config_audit_id START 1;
                    """
                )
            logger.info("config_audit_store_hazirlandi", db_path=self._db_path)
        except Exception as exc:
            logger.error("config_db_baslatma_hatasi", error=str(exc), path=self._db_path)
            self._conn = None

    def close(self) -> None:
        """DuckDB bağlantısını güvenle kapatır."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception as exc:
                    logger.debug("config_db_kapatma_hatasi", error=str(exc))
                finally:
                    self._conn = None

    def on_change(self, callback: Callable[..., Any]) -> None:
        """Yeni bir konfigürasyon değişiklik dinleyicisi (callback) ekler.

        Callback imzası: async def callback(old_config, new_config, changed_keys)
        veya senkron def callback(old_config, new_config, changed_keys)

        Args:
            callback: Tetiklenecek fonksiyon.
        """
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def add_validator(
        self,
        validator: Callable[[dict[str, Any]], tuple[bool, str | None]],
    ) -> None:
        """Konfigürasyon doğrulama kuralı ekler.

        Validator imzası: def validator(config) -> tuple[bool, str | None]

        Args:
            validator: Doğrulama fonksiyonu.
        """
        with self._lock:
            if validator not in self._validators:
                self._validators.append(validator)

    async def start(self) -> None:
        """Konfigürasyon izleme döngüsünü başlatır.

        Dosya diskte mevcut değilse boş bir JSON şablonu atomik olarak oluşturulur.
        """
        if not self._config_path.exists():
            logger.warning("config_dosyasi_bulunamadi_olusturuluyor", path=str(self._config_path))
            self.save_config_safely({})

        with self._lock:
            self._running = True
            self._load_config()

        logger.info(
            "config_hot_reload_baslatildi",
            path=str(self._config_path),
            interval=self._watch_interval,
        )

        while self._running:
            try:
                await self._check_for_changes()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("config_izleme_dongu_hatasi", error=str(exc))

            try:
                await asyncio.sleep(self._watch_interval)
            except asyncio.CancelledError:
                break

    async def stop(self) -> None:
        """Konfigürasyon izleme döngüsünü durdurur."""
        with self._lock:
            self._running = False
        logger.info("config_hot_reload_durduruldu", path=str(self._config_path))

    def _load_config(self) -> dict[str, Any]:
        """Diskteki konfigürasyon dosyasını okur ve SHA-256 özetini günceller."""
        with self._lock:
            try:
                if not self._config_path.exists():
                    self._current_config = {}
                    return self._current_config

                content = self._config_path.read_text(encoding="utf-8")
                self._last_modified = os.path.getmtime(self._config_path)
                self._last_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

                if content.strip():
                    self._current_config = orjson.loads(content)
                else:
                    self._current_config = {}

                return self._current_config.copy()
            except Exception as exc:
                logger.error("config_yukleme_hatasi", error=str(exc), path=str(self._config_path))
                return self._current_config.copy()

    def save_config_safely(self, new_config: dict[str, Any]) -> bool:
        """Yeni konfigürasyonu atomik olarak diske kaydeder (Crash-Resilient).

        Args:
            new_config: Kaydedilecek konfigürasyon sözlüğü.

        Returns:
            bool: Kayıt başarılı ise True, aksi halde False.
        """
        with self._lock:
            tmp_path = self._config_path.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")
            try:
                self._config_path.parent.mkdir(parents=True, exist_ok=True)
                raw_bytes = orjson.dumps(new_config, option=orjson.OPT_INDENT_2)
                tmp_path.write_bytes(raw_bytes)
                os.replace(tmp_path, self._config_path)
                self._current_config = new_config.copy()
                self._last_modified = os.path.getmtime(self._config_path)
                self._last_hash = hashlib.sha256(raw_bytes).hexdigest()
                return True
            except Exception as exc:
                logger.error("config_atomik_kayit_hatasi", error=str(exc))
                if tmp_path.exists():
                    with contextlib.suppress(Exception):
                        tmp_path.unlink()
                return False

    async def _check_for_changes(self) -> None:
        """Dosya modifikasyon zamanı ve hash'ini denetleyerek değişiklikleri yönetir."""
        if not self._config_path.exists():
            return

        try:
            current_mtime = os.path.getmtime(self._config_path)
            if current_mtime <= self._last_modified:
                return

            content = self._config_path.read_text(encoding="utf-8")
            current_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            if current_hash == self._last_hash:
                self._last_modified = current_mtime
                return

            with tracer.start_as_current_span("config.change_detected") as span:
                span.set_attribute("config.file", str(self._config_path))
                span.set_attribute("config.old_hash", self._last_hash[:12])
                span.set_attribute("config.new_hash", current_hash[:12])

                logger.info(
                    "config_degisikligi_tespit_edildi",
                    old_hash=self._last_hash[:12],
                    new_hash=current_hash[:12],
                )

                with self._lock:
                    old_config = self._current_config.copy()
                    old_hash = self._last_hash

                new_config: dict[str, Any] = orjson.loads(content) if content.strip() else {}
                changed_keys = self._find_changed_keys(old_config, new_config)

                if self._validate_before_apply:
                    is_valid, error = self._validate_config(new_config)
                    if not is_valid:
                        logger.error("config_dogrulama_basarisiz_uygulanmiyor", error=error)
                        self._record_change(old_hash, current_hash, changed_keys, applied=False, error=error)
                        return

                with self._lock:
                    self._current_config = new_config
                    self._last_modified = current_mtime
                    self._last_hash = current_hash

                self._record_change(old_hash, current_hash, changed_keys, applied=True)

                if self._auto_apply:
                    await self._notify_callbacks(old_config, new_config, changed_keys)

        except orjson.JSONDecodeError as exc:
            logger.error("config_json_cozme_hatasi", error=str(exc))
        except Exception as exc:
            logger.error("config_degisiklik_kontrol_hatasi", error=str(exc))

    def _find_changed_keys(
        self,
        old: dict[str, Any],
        new: dict[str, Any],
    ) -> list[str]:
        """İki konfigürasyon sözlüğü arasındaki değişen anahtarları listeler."""
        all_keys = set(old.keys()) | set(new.keys())
        return [key for key in sorted(all_keys) if old.get(key) != new.get(key)]

    def _validate_config(self, config: dict[str, Any]) -> tuple[bool, str | None]:
        """Tüm kayıtlı doğrulayıcıları çalıştırır."""
        with self._lock:
            validators = list(self._validators)

        for validator in validators:
            try:
                is_valid, error = validator(config)
                if not is_valid:
                    return False, error
            except Exception as exc:
                return False, f"Doğrulayıcı istisnası: {exc}"
        return True, None

    async def _notify_callbacks(
        self,
        old_config: dict[str, Any],
        new_config: dict[str, Any],
        changed_keys: list[str],
    ) -> None:
        """Kayıtlı callback fonksiyonlarını eşzamanlı/asenkron güvenlikle bilgilendirir."""
        with self._lock:
            callbacks = list(self._callbacks)

        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(old_config, new_config, changed_keys)
                else:
                    callback(old_config, new_config, changed_keys)
            except Exception as exc:
                callback_name = getattr(callback, "__name__", str(callback))
                logger.error("config_callback_hatasi", callback=callback_name, error=str(exc))

    def _record_change(
        self,
        old_hash: str,
        new_hash: str,
        changed_keys: list[str],
        applied: bool,
        error: str | None = None,
    ) -> None:
        """Değişikliği RAM kuyruğuna ve kalıcı DuckDB günlüğüne yazar."""
        change_id = hashlib.md5(f"{new_hash}_{time.time()}".encode()).hexdigest()[:12]
        now = datetime.now(UTC)

        change = ConfigChange(
            change_id=change_id,
            timestamp=now,
            file_path=str(self._config_path),
            old_hash=old_hash,
            new_hash=new_hash,
            changed_keys=changed_keys,
            applied=applied,
            error=error,
        )

        with self._lock:
            self._change_history.append(change)

            if self._conn is not None:
                try:
                    changed_keys_str = orjson.dumps(changed_keys).decode("utf-8")
                    self._conn.execute(
                        """
                        INSERT INTO config_audit_log (
                            id, timestamp, change_id, file_path, old_hash,
                            new_hash, changed_keys, applied, error
                        ) VALUES (
                            nextval('seq_config_audit_id'), ?, ?, ?, ?, ?, ?, ?, ?
                        );
                        """,
                        [
                            now,
                            change_id,
                            str(self._config_path),
                            old_hash,
                            new_hash,
                            changed_keys_str,
                            applied,
                            error,
                        ],
                    )
                except Exception as exc:
                    logger.warning("config_audit_db_kayit_hatasi", error=str(exc))

    def get_current_config(self) -> dict[str, Any]:
        """Mevcut aktif konfigürasyonun bir kopyasını döndürür."""
        with self._lock:
            return self._current_config.copy()

    def get_change_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Değişiklik geçmişini sözlük listesi olarak döndürür."""
        with self._lock:
            items = list(self._change_history)
            return [c.to_dict() for c in items[-limit:]]

    def force_reload(self) -> dict[str, Any]:
        """Diskteki dosyayı beklemeden anında zorla yükler."""
        with self._lock:
            old_config = self._current_config.copy()
            new_config = self._load_config()
            changed_keys = self._find_changed_keys(old_config, new_config)
            if changed_keys:
                logger.info("force_reload_degisen_anahtarlar", keys=changed_keys)
            return new_config

    def export_history_to_polars(self, limit: int = 100) -> pl.DataFrame:
        """Değişiklik geçmişini sıfır kopyalı Polars DataFrame olarak sunar."""
        if self._conn is None:
            with self._lock:
                history_dicts = [c.to_dict() for c in self._change_history][-limit:]
                if not history_dicts:
                    return pl.DataFrame()
                return pl.DataFrame(history_dicts)

        with self._lock:
            try:
                arrow_table = self._conn.execute(
                    """
                    SELECT id, timestamp, change_id, file_path, old_hash,
                           new_hash, changed_keys, applied, error
                    FROM config_audit_log
                    ORDER BY id DESC
                    LIMIT ?;
                    """,
                    [limit],
                ).arrow()
                return pl.from_arrow(arrow_table)  # type: ignore[return-value]
            except Exception as exc:
                logger.error("config_history_polars_hatasi", error=str(exc))
                return pl.DataFrame()

    def __repr__(self) -> str:
        """Motorun okunabilir durum temsilini döndürür."""
        return (
            f"ConfigHotReload(path={str(self._config_path)!r}, "
            f"running={self._running}, keys_count={len(self._current_config)})"
        )


# Singleton Oluşturma
def _create_singleton() -> ConfigHotReload:
    """Singleton nesneyi çalışma ortamına en uygun konfigürasyon yolu ile başlatır."""
    candidates = [
        "config.json",
        "config/runtime.json",
        "config/hot_reload.json",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ConfigHotReload(path)
    return ConfigHotReload("config/runtime.json")


config_hot_reload: Final[ConfigHotReload] = _create_singleton()


# ==============================================================================
# SETTINGS BRIDGE — Pydantic Settings + Hot-Reload Entegrasyonu
# ==============================================================================


class SettingsBridge:
    """Pydantic Settings ile dinamik Hot-Reload arasındaki kurumsal köprü.

    Güvenlik ve Mimari İlkeler:
    - Secret Koruma: Gizli anahtarlar (API anahtarları, şifreler) JSON dosyasında
      asla kabul edilmez, reddedilir.
    - Immutability: Pydantic Settings değişmezliği korunarak atomik referans
      değişimi (reference swap) ile yeni instance oluşturulur.
    - Rollback: Geçersiz bir parametre durumunda eski Settings örneği korunur.
    """

    # JSON'dan yüklenebilecek güvenli alanlar (secret olmayan)
    _SAFE_FIELDS: Final[set[str]] = {
        "app_debug",
        "app_host",
        "app_port",
        "interval_feature_calculation",
        "interval_live_inference",
        "interval_health_check",
        "interval_market_data",
        "interval_ranking",
        "breadth_mcclellan_ema_short",
        "breadth_mcclellan_ema_long",
        "breadth_thrust_threshold",
        "breadth_liquidity_volume_min",
        "regime_hmm_weight",
        "regime_score_weight",
        "regime_gmm_weight",
        "regime_rolling_window",
        "regime_confidence_min",
        "regime_transition_stability_window",
        "risk_appetite_breadth_weight",
        "risk_appetite_momentum_weight",
        "risk_appetite_volatility_weight",
        "risk_appetite_rsi_weight",
        "risk_appetite_sentiment_weight",
        "risk_appetite_macro_weight",
        "multi_tf_intraday_interval",
        "multi_tf_daily_interval",
        "multi_tf_weekly_interval",
        "multi_tf_monthly_interval",
        "liquidity_spread_threshold",
        "liquidity_volume_participation_min",
        "sentiment_news_weight",
        "sentiment_social_weight",
        "sentiment_options_weight",
        "db_pool_min",
        "db_pool_max",
        "db_command_timeout",
    }

    # Secret alanlar — ASLA JSON'dan yüklenemez
    _SECRET_FIELDS: Final[set[str]] = {
        "secret_key",
        "jwt_secret",
        "postgres_password",
        "redis_password",
        "clickhouse_password",
        "broker_api_key",
        "broker_api_secret",
        "tcmb_evds_api_key",
        "news_api_key",
        "alpha_vantage_key",
        "kap_api_key",
    }

    def __init__(self, reloader: ConfigHotReload | None = None) -> None:
        """SettingsBridge köprüsünü başlatır.

        Args:
            reloader: Bağlanılacak ConfigHotReload motoru (None ise global singleton).
        """
        self._reloader = reloader or config_hot_reload
        self._lock = threading.RLock()
        self._watching = False
        self._settings_history: deque[tuple[datetime, dict[str, Any]]] = deque(maxlen=DEFAULT_MAX_HISTORY_LEN)

    def start_watching(self) -> None:
        """Hot-reload izleyicisine doğrulayıcı ve callback ekleyerek köprüyü aktif eder."""
        with self._lock:
            if self._watching:
                return

            self._reloader.add_validator(self._validate_no_secrets)
            self._reloader.on_change(self._on_config_change)
            self._watching = True
            logger.info("settings_bridge_baslatildi")

    def stop_watching(self) -> None:
        """İzleme köprüsünü devre dışı bırakır."""
        with self._lock:
            self._watching = False
            logger.info("settings_bridge_durduruldu")

    def _validate_no_secrets(self, config: dict[str, Any]) -> tuple[bool, str | None]:
        """JSON config içinde yetkisiz secret alan tespiti yaparsa işlemi reddeder."""
        for key in config:
            if key.lower() in self._SECRET_FIELDS:
                return (
                    False,
                    f"Gizli alan '{key}' JSON dosyasında tanımlanamaz! "
                    f"Yalnızca ortam değişkenlerini (environment variables) kullanınız.",
                )
        return True, None

    async def _on_config_change(
        self,
        old_config: dict[str, Any],
        new_config: dict[str, Any],
        changed_keys: list[str],
    ) -> None:
        """Konfigürasyon değiştiğinde Pydantic Settings nesnesini atomik olarak yeniler."""
        safe_changes = {k: v for k, v in new_config.items() if k.lower() in self._SAFE_FIELDS}

        if not safe_changes:
            logger.info("settings_guncellenecek_guvenli_alan_yok")
            return

        try:
            import services.core.config as config_module

            with self._lock:
                old_settings_dict = config_module.settings.model_dump()
                merged = {**old_settings_dict, **safe_changes}
                new_settings = config_module.Settings(**merged)

                # Global settings referansını atomik olarak takas et
                config_module.settings = new_settings
                self._settings_history.append((datetime.now(UTC), safe_changes))

            logger.info(
                "settings_hot_reload_ile_guncellendi",
                changed_keys=list(safe_changes.keys()),
                count=len(safe_changes),
            )
        except Exception as exc:
            logger.error(
                "settings_hot_reload_hatasi_eski_ayarlar_korundu",
                error=str(exc),
                changed_keys=changed_keys,
            )

    def get_settings_history(self) -> list[dict[str, Any]]:
        """Settings değişiklik geçmişini liste halinde döndürür."""
        with self._lock:
            return [{"timestamp": ts.isoformat(), "changes": changes} for ts, changes in self._settings_history]

    @classmethod
    def get_safe_fields(cls) -> set[str]:
        """JSON konfigürasyonundan güncellenebilir güvenli alanlar kümesi."""
        return cls._SAFE_FIELDS.copy()

    @classmethod
    def get_secret_fields(cls) -> set[str]:
        """JSON konfigürasyonuna girişi engellenmiş hassas alanlar kümesi."""
        return cls._SECRET_FIELDS.copy()

    def __repr__(self) -> str:
        """Köprünün okunabilir durum temsilini döndürür."""
        return f"SettingsBridge(watching={self._watching}, history_count={len(self._settings_history)})"


# Global tekil köprü (Singleton)
settings_bridge: Final[SettingsBridge] = SettingsBridge()

__all__: Final[list[str]] = [
    "ConfigChange",
    "ConfigHotReload",
    "DEFAULT_CONFIG_DB_PATH",
    "DEFAULT_MAX_HISTORY_LEN",
    "DEFAULT_WATCH_INTERVAL_SECONDS",
    "SettingsBridge",
    "config_hot_reload",
    "settings_bridge",
]
