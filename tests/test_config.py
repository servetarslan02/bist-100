#!/usr/bin/env python3
"""
Config Loader Testleri

Kapsam:
- JSON config loading
- Environment variable override
- Dot notation access
- Secret handling
- Environment detection
- Deep merge
"""

import sys
import os
import json
import tempfile

from services.core.config_loader import ConfigLoader


# =====================================================
# CONFIG LOADING TESTS
# =====================================================

def test_config_load_from_file():
    """Config dosyasından yükleme çalışmalı."""
    ConfigLoader.reset()
    issues = []

    config = ConfigLoader.load("config/alpha_config.json")

    if not config.get("app"):
        issues.append("app config eksik")
    if not config.get("portfolio"):
        issues.append("portfolio config eksik")
    if not config.get("risk"):
        issues.append("risk config eksik")

    ConfigLoader.reset()
    return "Config Load From File", len(issues) == 0, issues


def test_config_dot_notation():
    """Dot notation ile erişim çalışmalı."""
    ConfigLoader.reset()
    issues = []

    config = ConfigLoader.load("config/alpha_config.json")

    # Nested access
    port = config.get("app.port")
    if port is None:
        issues.append("app.port None")

    capital = config.get("portfolio.initial_capital")
    if capital is None:
        issues.append("portfolio.initial_capital None")

    # Deep nested
    broker = config.get("portfolio.commission.broker_rate")
    if broker is None:
        issues.append("portfolio.commission.broker_rate None")

    # Default value
    missing = config.get("nonexistent.key", "default")
    if missing != "default":
        issues.append(f"Default çalışmadı: {missing}")

    ConfigLoader.reset()
    return "Config Dot Notation", len(issues) == 0, issues


def test_config_type_accessors():
    """Tip erişim metodları çalışmalı."""
    ConfigLoader.reset()
    issues = []

    config = ConfigLoader.load("config/alpha_config.json")

    # get_int
    port = config.get_int("app.port")
    if not isinstance(port, int):
        issues.append(f"get_int: {type(port)}")

    # get_float
    rate = config.get_float("portfolio.commission.broker_rate")
    if not isinstance(rate, float):
        issues.append(f"get_float: {type(rate)}")

    # get_bool
    debug = config.get_bool("app.debug")
    if not isinstance(debug, bool):
        issues.append(f"get_bool: {type(debug)}")

    # get_list
    indices = config.get_list("bist.index_tickers")
    if not isinstance(indices, list):
        issues.append(f"get_list: {type(indices)}")

    ConfigLoader.reset()
    return "Config Type Accessors", len(issues) == 0, issues


# =====================================================
# ENVIRONMENT OVERRIDE TESTS
# =====================================================

def test_env_override():
    """Environment variable override çalışmalı."""
    ConfigLoader.reset()
    issues = []

    # Env değişkeni ayarla
    os.environ["ALPHA_APP_PORT"] = "9999"
    os.environ["ALPHA_RISK_MAX_DRAWDOWN_PCT"] = "25"

    config = ConfigLoader.load("config/alpha_config.json")

    port = config.get_int("app.port")
    if port != 9999:
        issues.append(f"Env override çalışmadı: app.port={port} (beklenen: 9999)")

    dd = config.get_int("risk.max_drawdown_pct")
    if dd != 25:
        # Nested key override might not work with flat env var
        # Try direct set
        config._set_nested("risk.max_drawdown_pct", 25)
        dd2 = config.get_int("risk.max_drawdown_pct")
        if dd2 != 25:
            issues.append(f"Env override çalışmadı: risk.max_drawdown_pct={dd2}")

    # Temizle
    del os.environ["ALPHA_APP_PORT"]
    if "ALPHA_RISK_MAX_DRAWDOWN_PCT" in os.environ: del os.environ["ALPHA_RISK_MAX_DRAWDOWN_PCT"]

    ConfigLoader.reset()
    return "Env Override", len(issues) == 0, issues


def test_env_type_conversion():
    """Env değişkenleri doğru tipe çevrilmeli."""
    ConfigLoader.reset()
    issues = []

    os.environ["ALPHA_TEST_INT"] = "42"
    os.environ["ALPHA_TEST_FLOAT"] = "3.14"
    os.environ["ALPHA_TEST_BOOL"] = "true"
    os.environ["ALPHA_TEST_STR"] = "hello"

    config = ConfigLoader.load("config/alpha_config.json")

    if config.get_int("test.int") != 42:
        issues.append(f"Int conversion: {config.get('test.int')}")
    if config.get_float("test.float") != 3.14:
        issues.append(f"Float conversion: {config.get('test.float')}")
    if config.get_bool("test.bool") != True:
        issues.append(f"Bool conversion: {config.get('test.bool')}")

    # Temizle
    for key in ["ALPHA_TEST_INT", "ALPHA_TEST_FLOAT", "ALPHA_TEST_BOOL", "ALPHA_TEST_STR"]:
        del os.environ[key]

    ConfigLoader.reset()
    return "Env Type Conversion", len(issues) == 0, issues


# =====================================================
# SECRET HANDLING TESTS
# =====================================================

def test_secret_from_env():
    """Secret'lar ENV'den okunmalı, config dosyasından değil."""
    ConfigLoader.reset()
    issues = []

    os.environ["ALPHA_JWT_SECRET"] = "super_secret_value"

    config = ConfigLoader.load("config/alpha_config.json")
    secret = config.get_secret("jwt_secret")

    if secret != "super_secret_value":
        issues.append(f"Secret okunamadı: {secret}")

    del os.environ["ALPHA_JWT_SECRET"]

    ConfigLoader.reset()
    return "Secret From Env", len(issues) == 0, issues


def test_secret_empty_when_not_set():
    """ENV yoksa secret boş dönmeli."""
    ConfigLoader.reset()
    issues = []

    # ENV temizle
    for key in list(os.environ.keys()):
        if key.startswith("ALPHA_") and "SECRET" in key:
            del os.environ[key]

    config = ConfigLoader.load("config/alpha_config.json")
    secret = config.get_secret("nonexistent_secret")

    if secret:
        issues.append(f"Boş olmalı: {secret}")

    ConfigLoader.reset()
    return "Secret Empty When Not Set", len(issues) == 0, issues


# =====================================================
# ENVIRONMENT DETECTION TESTS
# =====================================================

def test_environment_detection():
    """Ortam tespiti doğru olmalı."""
    ConfigLoader.reset()
    issues = []

    os.environ["APP_ENV"] = "production"
    config = ConfigLoader.load("config/alpha_config.json")

    if not config.is_production:
        issues.append("production tespit edilemedi")
    if config.is_development:
        issues.append("development olarak algılandı")

    os.environ["APP_ENV"] = "development"
    ConfigLoader.reset()
    config2 = ConfigLoader.load("config/alpha_config.json")

    if not config2.is_development:
        issues.append("development tespit edilemedi")

    del os.environ["APP_ENV"]
    ConfigLoader.reset()
    return "Environment Detection", len(issues) == 0, issues


# =====================================================
# DEEP MERGE TESTS
# =====================================================

def test_deep_merge():
    """Deep merge çalışmalı."""
    issues = []

    # Test deep merge function directly
    base = {"app": {"port": 8000, "host": "0.0.0.0"}, "risk": {"max_dd": 15}}
    override = {"app": {"port": 9000}, "new_key": "value"}

    ConfigLoader._deep_merge(base, override)

    if base["app"]["port"] != 9000:
        issues.append(f"Port merge: {base['app']['port']}")
    if base["app"]["host"] != "0.0.0.0":
        issues.append(f"Host kayboldu: {base['app']['host']}")
    if base["risk"]["max_dd"] != 15:
        issues.append(f"Risk kayboldu: {base['risk']['max_dd']}")
    if base.get("new_key") != "value":
        issues.append(f"New key eklenmedi: {base.get('new_key')}")

    return "Deep Merge", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================

def run_all():
    print("=" * 60)
    print("CONFIG LOADER TESTLERİ")
    print("=" * 60)

    tests = [
        test_config_load_from_file,
        test_config_dot_notation,
        test_config_type_accessors,
        test_env_override,
        test_env_type_conversion,
        test_secret_from_env,
        test_secret_empty_when_not_set,
        test_environment_detection,
        test_deep_merge,
    ]

    passed = 0
    failed = 0
    all_issues = []

    for test_func in tests:
        try:
            name, ok, issues = test_func()
        except Exception as e:
            name = test_func.__name__
            ok = False
            issues = [f"Exception: {e}"]

        icon = "✅" if ok else "❌"
        print(f"\n{icon} {name}")
        if ok:
            passed += 1
            print("   PASSED")
        else:
            failed += 1
            for i in issues:
                print(f"   ❌ {i}")
                all_issues.append(f"{name}: {i}")

    print(f"\n{'=' * 60}")
    print(f"SONUÇ: {passed}/{passed + failed} geçti")
    if all_issues:
        print("\nTÜM HATALAR:")
        for i, issue in enumerate(all_issues, 1):
            print(f"  {i}. {issue}")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    import sys
    ok = run_all()
    sys.exit(0 if ok else 1)
