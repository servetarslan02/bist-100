"""ALPHA BIST — Config Loader with Environment Override v3.0 (Dinamik Yapılandırma Yükleyici)

Bu modül, JSON yapılandırma dosyalarından hiyerarşik ayarları yükler,
ortam (environment) bazlı JSON dosyalarıyla (`alpha_{environment}.json`)
ve çevre değişkenleriyle (environment variables, `ALPHA_*`) harmanlar.

Özellikler:
- JSON dosya tabanlı yapılandırma (orjson ile yüksek hızlı ve UTF-8 güvenli).
- Ortam bazlı geçersiz kılma (development, test, production).
- Çevre değişkeni (ENV) önceliği (`ALPHA_APP_PORT=9000` -> `app.port = 9000`).
- Gizli anahtar (Secret) izolasyonu: Parolalar dosyalarda tutulmaz, ENV'den çekilir.
- Noktalı erişim (Dot notation): `config.get("app.port", 8000)`.
- Tip güvenli getter metotları: `get_int`, `get_float`, `get_bool`, `get_list`.
- Thread-safe singleton mimarisi (`threading.RLock`).
- Polars DataFrame ve DuckDB denetim (audit snapshot) entegrasyonu.
"""

from __future__ import annotations

import contextlib
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# Yapılandırma Dizinleri ve Sabitleri
CONFIG_DIR: Path = Path(__file__).parent.parent.parent / "config"
DEFAULT_CONFIG_PATH: Path = CONFIG_DIR / "alpha_config.json"
DEFAULT_DUCKDB_PATH: Path = Path("data/config_loader.duckdb")
DEFAULT_ENV_PREFIX: str = "ALPHA_"

# Maskelenecek gizli anahtar adları
SENSITIVE_KEY_NAMES: frozenset[str] = frozenset({
    "password",
    "secret",
    "key",
    "token",
    "jwt",
    "credential",
})


class ConfigLoader:
    """Hiyerarşik yapılandırma dosyalarını yükleyen ve ENV ile birleştiren yönetici sınıf."""

    _instance: ConfigLoader | None = None
    _lock: threading.RLock = threading.RLock()

    def __init__(self) -> None:
        """Yeni bir ConfigLoader örneği başlatır."""
        self._config: dict[str, Any] = {}
        self._env_prefix: str = DEFAULT_ENV_PREFIX
        self._environment: str = "development"
        self._instance_lock: threading.RLock = threading.RLock()

    @classmethod
    @otel_trace("config_loader.load")
    def load(
        cls,
        path: str | Path | None = None,
        environment: str | None = None,
    ) -> ConfigLoader:
        """Singleton ConfigLoader örneğini yükler veya mevcut olanı döndürür.

        Args:
            path: Ana JSON yapılandırma dosyasının yolu.
            environment: Çalışma ortamı adı ('development', 'test', 'production').

        Returns:
            Yüklenmiş ve ENV ile birleştirilmiş ConfigLoader nesnesi.
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()

            instance = cls._instance
            with instance._instance_lock:
                instance._environment = (
                    str(environment).strip().lower()
                    if environment
                    else os.environ.get("APP_ENV", "development").strip().lower()
                )

                # 1. Ana config dosyasını yükle
                config_path = Path(path) if path else DEFAULT_CONFIG_PATH
                if config_path.exists() and config_path.stat().st_size > 0:
                    try:
                        raw_bytes = config_path.read_bytes()
                        instance._config = orjson.loads(raw_bytes)
                        logger.info("Konfigurasyon_dosyasi_yuklendi", path=str(config_path), env=instance._environment)
                    except Exception as e:
                        logger.error("konfigurasyon_dosyasi_okunamadi", path=str(config_path), error=str(e))

                # 2. Ortama özel config dosyasını yükle ve birleştir (deep merge)
                env_config_path = CONFIG_DIR / f"alpha_{instance._environment}.json"
                if env_config_path.exists() and env_config_path.stat().st_size > 0:
                    try:
                        env_bytes = env_config_path.read_bytes()
                        env_config = orjson.loads(env_bytes)
                        instance._deep_merge(instance._config, env_config)
                        logger.info("ortam_konfigurasyon_dosyasi_yuklendi", path=str(env_config_path))
                    except Exception as e:
                        logger.error("ortam_konfigurasyonu_okunamadi", path=str(env_config_path), error=str(e))

                # 3. Ortam değişkenleri (ENV overrides) uygula
                instance._apply_env_overrides()

            return instance

    @classmethod
    def reset(cls) -> None:
        """Singleton örneğini ve hafızadaki konfigürasyonu sıfırlar (testler için)."""
        with cls._lock:
            if cls._instance is not None:
                with cls._instance._instance_lock:
                    cls._instance._config = {}
            cls._instance = None

    def get(self, key: str, default: Any = None) -> Any:
        """Noktalı gösterim (dot notation) ile yapılandırma değerini çeker.

        Örnek:
            config.get("app.port", 8000)
            config.get("database.postgres.host", "localhost")

        Args:
            key: Noktalı erişim anahtarı.
            default: Anahtar bulunamazsa dönecek varsayılan değer.

        Returns:
            Yapılandırma değeri veya default.
        """
        with self._instance_lock:
            if not key:
                return default

            keys = key.split(".")
            value: Any = self._config
            for k in keys:
                if isinstance(value, dict):
                    value = value.get(k)
                else:
                    return default
                if value is None:
                    return default
            return value

    def get_secret(self, key: str, env_var: str | None = None) -> str:
        """Gizli anahtarı doğrudan çevre değişkenlerinden (ENV) okur.

        Güvenlik İlkesi: Parola, API key ve token gibi sırlar asla
        yapılandırma dosyalarında tutulmaz; sadece ENV'den okunur.

        Args:
            key: Temel anahtar adı (örn. 'jwt_secret').
            env_var: İsteğe bağlı açık ENV değişken adı (örn. 'JWT_SECRET').

        Returns:
            Çevre değişkeni değeri veya boş string.
        """
        env_key = env_var if env_var else f"{self._env_prefix}{key.upper()}"
        value = os.environ.get(env_key, "")

        if not value:
            # Yedek olarak doğrudan anahtar adıyla kontrol et
            value = os.environ.get(key.upper(), "")

        if not value:
            logger.warning("gizli_anahtar_env_icinde_bulunamadi", key=env_key)

        return value

    def get_int(self, key: str, default: int = 0) -> int:
        """Tamsayı tipinde yapılandırma değeri döndürür.

        Args:
            key: Noktalı anahtar.
            default: Varsayılan tamsayı.

        Returns:
            Tamsayı değeri.
        """
        val = self.get(key, default)
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Kayan noktalı sayı tipinde yapılandırma değeri döndürür.

        Args:
            key: Noktalı anahtar.
            default: Varsayılan float.

        Returns:
            Float değeri.
        """
        val = self.get(key, default)
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Mantıksal (boolean) tipinde yapılandırma değeri döndürür.

        Args:
            key: Noktalı anahtar.
            default: Varsayılan bool.

        Returns:
            Boolean değeri.
        """
        val = self.get(key, default)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() in ("true", "1", "yes", "on", "active")
        if isinstance(val, (int, float)):
            return bool(val)
        return default

    def get_list(self, key: str, default: list[Any] | None = None) -> list[Any]:
        """Liste tipinde yapılandırma değeri döndürür.

        Args:
            key: Noktalı anahtar.
            default: Varsayılan liste.

        Returns:
            Liste değeri.
        """
        val = self.get(key, default or [])
        if isinstance(val, list):
            return val
        return [val] if val is not None else (default or [])

    @property
    def environment(self) -> str:
        """Mevcut çalışma ortamı adını döndürür."""
        return self._environment

    @property
    def is_production(self) -> bool:
        """Sistemin production veya prod ortamında olup olmadığını döndürür."""
        return self._environment in ("production", "prod", "staging")

    @property
    def is_development(self) -> bool:
        """Sistemin development veya dev ortamında olup olmadığını döndürür."""
        return self._environment in ("development", "dev")

    @property
    def is_test(self) -> bool:
        """Sistemin test ortamında olup olmadığını döndürür."""
        return self._environment == "test"

    def to_dict(self, mask_secrets: bool = True) -> dict[str, Any]:
        """Hafızadaki tüm konfigürasyonu sözlük olarak kopyalar.

        Args:
            mask_secrets: True ise hassas anahtar değerleri maskelenir.

        Returns:
            Yapılandırma sözlüğü.
        """
        with self._instance_lock:
            copied = orjson.loads(orjson.dumps(self._config))
            if mask_secrets:
                self._mask_dict(copied)
            return copied

    def to_orjson_bytes(self, mask_secrets: bool = True) -> bytes:
        """Yapılandırmayı orjson bayt dizisine serileştirir."""
        return orjson.dumps(self.to_dict(mask_secrets=mask_secrets))

    def to_json(self, mask_secrets: bool = True) -> str:
        """Yapılandırmayı JSON metnine dönüştürür."""
        return self.to_orjson_bytes(mask_secrets=mask_secrets).decode("utf-8")

    @classmethod
    def _mask_dict(cls, d: dict[str, Any]) -> None:
        """Sözlük içindeki hassas değerleri yerinde maskeler."""
        for k, v in d.items():
            if isinstance(v, dict):
                cls._mask_dict(v)
            elif any(s in k.lower() for s in SENSITIVE_KEY_NAMES) and v:
                str_v = str(v)
                d[k] = f"{str_v[:2]}***{str_v[-2:]}" if len(str_v) > 4 else "***"

    @otel_trace("config_loader._apply_env_overrides")
    def _apply_env_overrides(self) -> None:
        """`ALPHA_` ön eki ile tanımlanan ortam değişkenlerini konfigürasyona uygular."""
        for key, value in os.environ.items():
            if not key.startswith(self._env_prefix) or key == "APP_ENV":
                continue

            config_key = key[len(self._env_prefix) :].lower().replace("_", ".")
            converted = self._convert_value(value)
            self._set_nested(config_key, converted)

    @staticmethod
    def _convert_value(value: str) -> Any:
        """String tipindeki ortam değişkenini uygun Python tipine dönüştürür."""
        val_clean = value.strip()
        val_lower = val_clean.lower()

        if val_lower == "true":
            return True
        if val_lower == "false":
            return False

        # Tamsayı denemesi (sessiz)
        if (val_clean.startswith("-") and val_clean[1:].isdigit()) or val_clean.isdigit():
            with contextlib.suppress(ValueError):
                return int(val_clean)

        # Ondalıklı sayı denemesi (sessiz)
        if "." in val_clean:
            with contextlib.suppress(ValueError):
                return float(val_clean)

        # JSON dizi veya nesne denemesi
        if (val_clean.startswith("[") and val_clean.endswith("]")) or (
            val_clean.startswith("{") and val_clean.endswith("}")
        ):
            try:
                return orjson.loads(val_clean)
            except Exception:
                pass

        return val_clean

    def _set_nested(self, key: str, value: Any) -> None:
        """Noktalı anahtar hiyerarşisine göre değeri ayarlar."""
        keys = key.split(".")
        current = self._config
        for k in keys[:-1]:
            if k not in current or not isinstance(current[k], dict):
                current[k] = {}
            current = current[k]
        current[keys[-1]] = value

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
        """Override sözlüğündeki değerleri base sözlüğüne özyineli olarak uygular."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                ConfigLoader._deep_merge(base[key], value)
            else:
                base[key] = value

    def __repr__(self) -> str:
        with self._instance_lock:
            return (
                f"<ConfigLoader env='{self._environment}' "
                f"keys_count={len(self._config)} "
                f"prefix='{self._env_prefix}'>"
            )


# =====================================================
# POLARS & DUCKDB DENETİM FONKSİYONLARI
# =====================================================


def export_config_to_polars(
    loader: ConfigLoader | None = None,
    mask_secrets: bool = True,
) -> pl.DataFrame:
    """Hiyerarşik yapılandırmayı düzleştirip Polars DataFrame formatında döndürür.

    Args:
        loader: İsteğe bağlı ConfigLoader örneği (None ise singleton kullanılır).
        mask_secrets: Hassas anahtarların maskelenme durumu.

    Returns:
        'key', 'value', 'type' sütunlarına sahip Polars DataFrame.
    """
    inst = loader or ConfigLoader.load()
    flat_items: list[dict[str, str]] = []

    def _flatten(d: dict[str, Any], prefix: str = "") -> None:
        for k, v in d.items():
            full_k = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                _flatten(v, full_k)
            else:
                flat_items.append({
                    "key": full_k,
                    "value": str(v) if v is not None else "",
                    "type": type(v).__name__,
                })

    cfg_dict = inst.to_dict(mask_secrets=mask_secrets)
    _flatten(cfg_dict)

    schema = {
        "key": pl.Utf8,
        "value": pl.Utf8,
        "type": pl.Utf8,
    }
    return pl.DataFrame(flat_items, schema=schema)


def export_config_to_duckdb(
    loader: ConfigLoader | None = None,
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    table_name: str = "bist_config_loader_audit",
    mask_secrets: bool = True,
) -> int:
    """Yapılandırma anlık görüntüsünü DuckDB tablosuna kaydeder.

    Args:
        loader: ConfigLoader örneği.
        db_path: DuckDB veritabanı dosya yolu.
        table_name: Hedef tablo adı.
        mask_secrets: Sırların maskelenme durumu.

    Returns:
        Kaydedilen parametre sayısı.
    """
    df = export_config_to_polars(loader=loader, mask_secrets=mask_secrets)
    if df.is_empty():
        return 0

    now_ts = datetime.now(UTC).isoformat()
    df_snapshot = df.with_columns(pl.lit(now_ts).alias("snapshot_timestamp"))

    path_obj = Path(db_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    if path_obj.exists() and path_obj.stat().st_size == 0:
        with contextlib.suppress(OSError):
            path_obj.unlink()

    try:
        with duckdb.connect(str(path_obj)) as conn:
            from services.core.debounce import configure_duckdb_wal

            configure_duckdb_wal(conn)
            conn.register("df_loader_snap", df_snapshot.to_arrow())
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM df_loader_snap WHERE 1=0"
            )
            conn.execute(f"INSERT INTO {table_name} SELECT * FROM df_loader_snap")
        return len(df_snapshot)
    except Exception as e:
        logger.error("export_config_loader_to_duckdb_failed", error=str(e))
        return 0


def query_config_duckdb(
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    table_name: str = "bist_config_loader_audit",
    key_prefix: str | None = None,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB üzerinden geçmiş yapılandırma kayıtlarını sorgular.

    Args:
        db_path: DuckDB veritabanı dosya yolu.
        table_name: Tablo adı.
        key_prefix: İsteğe bağlı anahtar önek filtresi.
        limit: Maksimum satır sayısı.

    Returns:
        Polars DataFrame.
    """
    schema = {
        "key": pl.Utf8,
        "value": pl.Utf8,
        "type": pl.Utf8,
        "snapshot_timestamp": pl.Utf8,
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

            if key_prefix:
                query = f"SELECT * FROM {table_name} WHERE key LIKE ? ORDER BY snapshot_timestamp DESC LIMIT ?"
                arrow_res = conn.execute(query, [f"{key_prefix}%", limit]).arrow()
            else:
                query = f"SELECT * FROM {table_name} ORDER BY snapshot_timestamp DESC LIMIT ?"
                arrow_res = conn.execute(query, [limit]).arrow()

            return pl.from_arrow(arrow_res)
    except Exception as e:
        logger.error("query_config_loader_duckdb_failed", error=str(e))
        return empty_df


# Kolaylık ve geri uyumluluk fonksiyonu
def load_config(
    path: str | Path | None = None,
    environment: str | None = None,
) -> ConfigLoader:
    """ConfigLoader.load() çağrısı için fonksiyonel sarmalayıcı."""
    return ConfigLoader.load(path=path, environment=environment)


__all__ = [
    "CONFIG_DIR",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_ENV_PREFIX",
    "SENSITIVE_KEY_NAMES",
    "ConfigLoader",
    "load_config",
    "export_config_to_polars",
    "export_config_to_duckdb",
    "query_config_duckdb",
]
