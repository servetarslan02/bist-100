"""
ALPHA BIST — Config Loader with Environment Override

Özellikler:
- JSON config dosyasından yükleme
- Environment variable override
- development/test/production ayrımı
- Secret değerler config dosyasında tutulmaz
- Nested key desteği (dot notation)

Kullanım:
    config = ConfigLoader.load("config/alpha_config.json")
    port = config.get("app.port", 8000)
    secret = config.get_secret("jwt_secret")  # ENV'den okur
"""

import orjson
import os
from pathlib import Path
from typing import Any, Dict, Optional
import structlog

logger = structlog.get_logger()

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


class ConfigLoader:
    """Config dosyası + environment override."""

    _instance: Optional["ConfigLoader"] = None
    _config: Dict[str, Any] = {}
    _env_prefix: str = "ALPHA_"
    _environment: str = "development"

    @classmethod
    def load(cls, path: str = None, environment: str = None) -> "ConfigLoader":
        """Config yükle (singleton)."""
        if cls._instance is None:
            cls._instance = cls()

        instance = cls._instance
        instance._environment = environment or os.environ.get("APP_ENV", "development")

        # Ana config dosyası
        config_path = path or str(CONFIG_DIR / "alpha_config.json")
        if os.path.exists(config_path):
            with open(config_path) as f:
                instance._config = orjson.loads(f.read())
            logger.info("Config loaded", path=config_path, env=instance._environment)

        # Environment-specific override dosyası
        env_path = str(CONFIG_DIR / f"alpha_{instance._environment}.json")
        if os.path.exists(env_path):
            with open(env_path) as f:
                env_config = orjson.loads(f.read())
            instance._deep_merge(instance._config, env_config)
            logger.info("Environment config loaded", path=env_path)

        # Environment variable override
        instance._apply_env_overrides()

        return instance

    @classmethod
    def reset(cls):
        """Singleton reset (test için)."""
        cls._instance = None
        cls._config = {}

    def get(self, key: str, default: Any = None) -> Any:
        """Dot notation ile config değeri al.

        Örnek: config.get("app.port", 8000)
        """
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value

    def get_secret(self, key: str, env_var: str = None) -> str:
        """Secret değer al (ENV优先, config dosyasından DEĞİL).

        Güvenlik: Secret'lar asla config dosyasında saklanmaz.
        """
        env_key = env_var or f"{self._env_prefix}{key.upper()}"
        value = os.environ.get(env_key, "")

        if not value:
            logger.warning(f"Secret not found in ENV: {env_key}")

        return value

    def get_int(self, key: str, default: int = 0) -> int:
        return int(self.get(key, default))

    def get_float(self, key: str, default: float = 0.0) -> float:
        return float(self.get(key, default))

    def get_bool(self, key: str, default: bool = False) -> bool:
        val = self.get(key, default)
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes")
        return bool(val)

    def get_list(self, key: str, default: list = None) -> list:
        val = self.get(key, default or [])
        return val if isinstance(val, list) else [val]

    @property
    def environment(self) -> str:
        return self._environment

    @property
    def is_production(self) -> bool:
        return self._environment in ("production", "prod")

    @property
    def is_development(self) -> bool:
        return self._environment in ("development", "dev")

    @property
    def is_test(self) -> bool:
        return self._environment == "test"

    def to_dict(self) -> Dict[str, Any]:
        """Config dict (secrets hariç)."""
        return dict(self._config)

    def _apply_env_overrides(self):
        """ALPHA_ prefix ile gelen env değişkenlerini config'e uygula.

        Örnek:
            ALPHA_APP_PORT=9000 → config["app"]["port"] = 9000
            ALPHA_RISK_MAX_DRAWDOWN=20 → config["risk"]["max_drawdown_pct"] = 20
        """
        for key, value in os.environ.items():
            if not key.startswith(self._env_prefix):
                continue
            if key == "APP_ENV":
                continue

            # ALPHA_APP_PORT → app.port
            config_key = key[len(self._env_prefix):].lower().replace("_", ".")

            # Tip dönüşümü
            converted = self._convert_value(value)
            self._set_nested(config_key, converted)

    def _convert_value(self, value: str) -> Any:
        """String değerini uygun tipe çevir."""
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        # JSON array/object
        if value.startswith(("[", "{")):
            try:
                return orjson.loads(value)
            except orjson.JSONDecodeError:
                pass
        return value

    def _set_nested(self, key: str, value: Any):
        """Dot notation ile nested config ayarla."""
        keys = key.split(".")
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value

    @staticmethod
    def _deep_merge(base: Dict, override: Dict):
        """Deep merge: override değerleri base'e uygula."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                ConfigLoader._deep_merge(base[key], value)
            else:
                base[key] = value


# Convenience function
def load_config(path: str = None, environment: str = None) -> ConfigLoader:
    return ConfigLoader.load(path, environment)
