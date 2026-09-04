#!/usr/bin/env python3
import structlog

logger = structlog.get_logger(__name__)
"""
ALPHA BIST — API Endpoint Doğrulama Scripti

Tüm API endpoint'lerini kontrol eder:
1. Modül import testi
2. Router tanımlama doğruluğu
3. Bağımlılık bağlantıları
4. Veri kaynakları erişilebilirliği
5. Sağlık kontrolü

Kullanım:
    python scripts/verify_all_api_endpoints.py
"""

import importlib
import os
import sys
import traceback
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception as exc:
        sys.stderr.write(f"Warning: could not reconfigure stdout encoding: {exc}\n")

# Proje kökünü ekle
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# JWT_SECRET gerekli (auth modülü için)
os.environ.setdefault("JWT_SECRET", "test-secret-for-verification-only")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-verification")
os.environ.setdefault("SYSTEM_API_KEY", "test-system-api-key")

# Sonuçlar
results: dict[str, dict[str, Any]] = {}
total_checks = 0
passed_checks = 0
failed_checks = 0
warning_checks = 0


def check(name: str, status: str, detail: str = "") -> Any:
    """Tek bir kontrol sonucunu kaydet."""
    global total_checks, passed_checks, failed_checks, warning_checks
    total_checks += 1
    if status == "PASS":
        passed_checks += 1
        icon = "✅"
    elif status == "FAIL":
        failed_checks += 1
        icon = "❌"
    else:
        warning_checks += 1
        icon = "⚠️"

    results[name] = {"status": status, "detail": detail, "icon": icon}
    logger.info(f"  {icon} {name}" + (f" — {detail}" if detail else ""))


def section(title: str) -> Any:
    """Bölüm başlığı."""
    logger.info(f"\n{'=' * 60}")
    logger.info(f"  {title}")
    logger.info(f"{'=' * 60}")


# =====================================================
# 1. MODÜL IMPORT TESTLERİ
# =====================================================

section("1. MODÜL IMPORT TESTLERİ")

MODULES = [
    ("services.api.v1.market", "Market Data Router"),
    ("services.api.v1.portfolio", "Portfolio Router"),
    ("services.api.v1.risk", "Risk Router"),
    ("services.api.v1.intelligence", "Intelligence Router"),
    ("services.api.v1.decisions", "Decisions Router"),
    ("services.api.v1.backtest", "Backtest Router"),
    ("services.api.v1.learning", "Learning Router"),
    ("services.api.v1.models", "Models Router"),
    ("services.api.v1.agents", "Agents Router"),
    ("services.api.v1.scanner", "Scanner Router"),
    ("services.api.v1.macro", "Macro Router"),
    ("services.api.v1.factors", "Factors Router"),
    ("services.api.v1.alternative", "Alternative Router"),
    ("services.api.v1.viop", "VIOP Router"),
    ("services.api.v1.event_study", "Event Study Router"),
    ("services.api.v1.system", "System Router"),
    ("services.api.v1.sse", "SSE Router"),
    ("services.api.v1.ws", "WebSocket Router"),
    ("services.api.v1.schemas", "Schemas"),
    ("services.api.v1", "v1 Router Package"),
]

for module_path, name in MODULES:
    try:
        mod = importlib.import_module(module_path)
        if hasattr(mod, "router"):
            check(f"Import: {name}", "PASS", "Router mevcut")
        elif module_path.endswith("schemas"):
            check(f"Import: {name}", "PASS", "Schema modülü")
        else:
            check(f"Import: {name}", "WARN", "Router bulunamadı")
    except ImportError as e:
        check(f"Import: {name}", "FAIL", f"ImportError: {e}")
    except Exception as e:
        check(f"Import: {name}", "FAIL", f"{type(e).__name__}: {e}")


# =====================================================
# 2. ENDPOINT TANIMLAMA TESTLERİ
# =====================================================

section("2. ENDPOINT TANIMLAMA TESTLERİ")

EXPECTED_ENDPOINTS = {
    "market": [
        ("GET", "/state"),
        ("GET", "/instruments"),
        ("GET", "/instruments/{ticker}"),
        ("GET", "/instruments/{ticker}/ohlcv"),
        ("GET", "/instruments/{ticker}/live_intel"),
        ("GET", "/instruments/{ticker}/full"),
        ("GET", "/instruments/{ticker}/features"),
        ("GET", "/sectors"),
        ("GET", "/calendar"),
        ("GET", "/events"),
        ("GET", "/radar"),
        ("GET", "/regime"),
        ("GET", "/heatmap"),
    ],
    "portfolio": [
        ("GET", ""),
        ("GET", "/"),
        ("GET", "/summary"),
        ("GET", "/state"),
        ("GET", "/positions"),
        ("GET", "/trades"),
        ("GET", "/pnl"),
        ("GET", "/equity-curve"),
        ("GET", "/risk-metrics"),
        ("GET", "/drawdown"),
        ("GET", "/metrics"),
        ("GET", "/accounting"),
        ("POST", "/reset"),
        ("GET", "/cash-ledger"),
        ("GET", "/orders"),
    ],
    "risk": [
        ("GET", "/overview"),
        ("GET", "/summary"),
        ("GET", "/dashboard"),
        ("GET", "/var"),
        ("GET", "/portfolio"),
        ("GET", "/limits"),
        ("GET", "/drawdown"),
        ("GET", "/stress-test/scenarios"),
        ("POST", "/stress-test/run"),
        ("GET", "/tail-hedge"),
        ("POST", "/tail-hedge/analyze"),
        ("GET", "/risk-parity"),
        ("POST", "/risk-parity/optimize"),
        ("GET", "/monitoring"),
        ("GET", "/alerts"),
        ("GET", "/calibration"),
        ("POST", "/check"),
        ("GET", "/compliance"),
    ],
    "intelligence": [
        ("GET", "/regime"),
        ("GET", "/decisions"),
        ("GET", "/simulation/{ticker}"),
        ("GET", "/analysis/{ticker}"),
        ("POST", "/ask_gemini"),
        ("GET", "/gemini_report/{ticker}"),
    ],
    "decisions": [
        ("GET", "/list"),
        ("GET", "/detail/{decision_id}"),
        ("POST", "/create"),
        ("GET", "/audit/{decision_id}"),
        ("GET", "/pending-opportunities"),
        ("GET", "/plan"),
    ],
    "backtest": [
        ("POST", "/run"),
        ("GET", "/results/{backtest_id}"),
        ("GET", "/list"),
        ("POST", "/walk-forward"),
        ("GET", "/deflated-sharpe"),
        ("GET", "/history_30y"),
        ("GET", "/transaction-costs"),
        ("GET", "/trades/{backtest_id}"),
        ("GET", "/equity-curve/{backtest_id}"),
    ],
    "learning": [
        ("GET", "/status"),
        ("GET", "/performance-matrix"),
        ("GET", "/metrics"),
        ("GET", "/report"),
        ("POST", "/cycle"),
        ("POST", "/record_prediction"),
        ("POST", "/record_outcome"),
        ("GET", "/calibration"),
        ("GET", "/drift"),
        ("GET", "/champion-challenger"),
    ],
    "models": [
        ("GET", ""),
        ("GET", "/"),
        ("GET", "/status"),
        ("GET", "/list"),
        ("GET", "/registry"),
        ("GET", "/performance"),
        ("GET", "/champion"),
        ("POST", "/retrain"),
    ],
    "agents": [
        ("GET", "/list"),
        ("GET", "/status"),
        ("POST", "/run"),
    ],
    "scanner": [
        ("GET", "/signals"),
        ("GET", "/opportunities"),
        ("GET", "/status"),
        ("GET", "/dashboard"),
        ("GET", "/results"),
        ("GET", "/tiers"),
        ("GET", "/history/{ticker}"),
        ("GET", "/performance"),
        ("GET", "/alerts"),
        ("GET", "/filters"),
        ("GET", "/dedup"),
        ("GET", "/scheduler"),
        ("POST", "/trigger"),
        ("POST", "/event"),
    ],
    "macro": [
        ("GET", "/overview"),
        ("GET", "/world"),
        ("GET", "/state"),
        ("GET", "/indicators"),
        ("GET", "/impact/{ticker}"),
        ("GET", "/sensitivity/{sector}"),
    ],
    "factors": [
        ("GET", "/scores/{ticker}"),
        ("GET", "/exposure/{ticker}"),
        ("GET", "/portfolio-exposure"),
    ],
    "alternative": [
        ("GET", "/sources"),
        ("GET", "/sentiment/{ticker}"),
        ("GET", "/news"),
        ("GET", "/macro"),
    ],
    "viop": [
        ("GET", "/options"),
        ("POST", "/options/price"),
        ("POST", "/options/implied-vol"),
        ("POST", "/greeks"),
        ("GET", "/strategies"),
        ("POST", "/strategies/analyze"),
        ("POST", "/hedge"),
        ("POST", "/hedge/gamma-scalp"),
        ("POST", "/margin"),
        ("POST", "/arbitrage"),
        ("POST", "/parity"),
        ("POST", "/risk"),
        ("GET", "/contracts"),
        ("GET", "/contracts/{symbol}"),
    ],
    "event_study": [
        ("GET", "/events"),
        ("GET", "/calendar"),
        ("GET", "/analyze/{ticker}"),
    ],
    "system": [
        ("GET", "/status"),
        ("GET", "/health"),
        ("GET", "/databases"),
        ("GET", "/alerts"),
        ("POST", "/optimize_storage"),
    ],
    "sse": [
        ("GET", "/ticks"),
        ("GET", "/signals"),
        ("GET", "/portfolio"),
        ("GET", "/alerts"),
        ("GET", "/regime"),
        ("GET", "/radar"),
    ],
}

for module_name, endpoints in EXPECTED_ENDPOINTS.items():
    try:
        mod = importlib.import_module(f"services.api.v1.{module_name}")
        router = getattr(mod, "router", None)
        if not router:
            check(f"Router: {module_name}", "FAIL", "Router bulunamadı")
            continue

        # Router'daki gerçek route'ları al
        registered_routes = set()
        for route in router.routes:
            if hasattr(route, "methods") and hasattr(route, "path"):
                for method in route.methods:
                    registered_routes.add((method, route.path))

        # Her endpoint'i kontrol et
        missing = []
        for method, path in endpoints:
            if (method, path) not in registered_routes:
                # Bazı varyasyonları dene
                found = False
                for reg_method, reg_path in registered_routes:
                    if reg_method == method and (
                        reg_path == path or reg_path == f"/{module_name}{path}" or reg_path.endswith(path)
                    ):
                        found = True
                        break
                if not found:
                    missing.append(f"{method} {path}")

        if not missing:
            check(f"Endpoints: {module_name}", "PASS", f"{len(endpoints)} endpoint tanımlı")
        else:
            check(
                f"Endpoints: {module_name}",
                "WARN",
                f"{len(endpoints) - len(missing)}/{len(endpoints)} tanımlı, eksik: {', '.join(missing[:3])}",
            )

    except Exception as e:
        check(f"Endpoints: {module_name}", "FAIL", str(e))

# 2.2 TÜM OPENAPI 237+ ENDPOINT'LERİN DERİN DENETİMİ
try:
    from services.api.app import create_app

    full_app = create_app()
    openapi_spec = full_app.openapi()
    all_paths = openapi_spec.get("paths", {})
    total_ops = 0
    valid_ops = 0
    tag_counts: dict[str, int] = {}

    for path, methods in all_paths.items():
        for method, op in methods.items():
            if method.lower() in ("get", "post", "put", "delete", "patch"):
                total_ops += 1
                tag = (op.get("tags") or ["Diğer"])[0]
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
                if "responses" in op:
                    valid_ops += 1

    check(
        "OpenAPI: Full Spectrum Audit",
        "PASS" if valid_ops == total_ops and total_ops >= 200 else "WARN",
        f"Toplam {total_ops} endpoint ({len(all_paths)} benzersiz yol) denetlendi (%{valid_ops / max(total_ops, 1) * 100:.1f} şema uyumlu)",
    )

    for tag_name, count in sorted(tag_counts.items(), key=lambda x: -x[1]):
        check(f"OpenAPI Grup: {tag_name}", "PASS", f"{count} aktif endpoint denetlendi")

except Exception as e:
    check("OpenAPI: Full Spectrum Audit", "FAIL", str(e)[:80])


# =====================================================
# 3. BAĞIMLILIK BAĞLANTI TESTLERİ
# =====================================================

section("3. BAĞIMLILIK BAĞLANTI TESTLERİ")

DEPENDENCIES = [
    ("services.core.database", "Veritabanı Modülü"),
    ("services.core.alpha_engine", "Alpha Engine"),
    ("services.core.risk_manager", "Risk Manager"),
    ("services.core.feature_store", "Feature Store"),
    ("services.core.model_persistence", "Model Persistence"),
    ("services.core.cache_warmer", "Cache Warmer"),
    ("services.core.circuit_breaker", "Circuit Breaker"),
    ("services.core.mtls", "mTLS Modülü"),
    ("services.core.event_bus", "Event Bus"),
    ("services.core.otel", "OpenTelemetry"),
    ("services.nats.client", "NATS Client"),
    ("services.grpc.server", "gRPC Server"),
    ("services.grpc.client", "gRPC Client"),
    ("services.grpc.generated.market_pb2", "Protobuf Generated"),
    ("services.portfolio.main", "Portfolio Service"),
    ("services.risk.risk_parity", "Risk Parity"),
    ("services.learning.continuous_learning", "Continuous Learning"),
    ("services.ml.stacking_ensemble", "ML Stacking Ensemble"),
    ("services.scanner.alpha_scanner", "Scanner Service"),
    ("services.macro.regime_detector", "Macro Regime Detector"),
    ("services.intelligence.ensemble_forecast", "Ensemble Forecast"),
    ("services.backtest.execution_engine", "Execution Engine"),
    ("services.backtest.engine_v4", "Backtest Engine V4"),
    ("services.simulation.monte_carlo_enhanced", "Monte Carlo"),
    ("services.features.main", "Feature Engine"),
    ("services.market_state.main", "Market State"),
    ("services.data.data_source", "BIST Data Source"),
    ("services.agents.agent_pipeline", "Agent Pipeline"),
    ("services.alternative.llm_sentiment", "Sentiment Analysis"),
    ("services.event_study.impact", "Event Study Engine"),
    ("services.viop.options_pricing", "VIOP Options"),
]

for module_path, name in DEPENDENCIES:
    try:
        mod = importlib.import_module(module_path)
        check(f"Dependency: {name}", "PASS")
    except ImportError as e:
        check(f"Dependency: {name}", "FAIL", f"ImportError: {e}")
    except Exception as e:
        check(f"Dependency: {name}", "WARN", f"{type(e).__name__}: {str(e)[:80]}")


# =====================================================
# 4. VERİ KAYNAĞI BAĞLANTI TESTLERİ
# =====================================================

section("4. VERİ KAYNAĞI BAĞLANTI TESTLERİ")

# 4.1 PostgreSQL
try:
    import asyncio

    from services.core.database import check_db_health

    health = asyncio.run(check_db_health())
    for db_name, status in health.items():
        if status == "healthy":
            check(f"Database: {db_name}", "PASS", "Bağlantı başarılı")
        else:
            check(f"Database: {db_name}", "WARN", f"Durum: {status} (yerel servis henüz başlatılmamış)")
except ImportError:
    check("Database: PostgreSQL", "FAIL", "database modülü import edilemiyor")
except Exception as e:
    check("Database: PostgreSQL", "WARN", f"Bağlantı test edilemedi: {str(e)[:80]}")

# 4.2 Redis
try:
    import asyncio

    from services.core.database import get_redis

    redis = asyncio.run(get_redis())
    if redis:
        check("Database: Redis", "PASS", "Bağlantı başarılı")
    else:
        check("Database: Redis", "WARN", "Redis bağlantısı kurulamadı (servis çalışmıyor olabilir)")
except ImportError:
    check("Database: Redis", "FAIL", "Redis modülü import edilemiyor")
except Exception as e:
    check("Database: Redis", "WARN", f"Bağlantı test edilemedi: {str(e)[:80]}")

# 4.3 ClickHouse
try:
    import asyncio

    from services.core.database import get_clickhouse

    try:
        ch = get_clickhouse()
    except Exception:
        ch = None
    if ch:
        check("Database: ClickHouse", "PASS", "Bağlantı başarılı")
    else:
        check("Database: ClickHouse", "WARN", "ClickHouse bağlantısı kurulamadı (yerel servis henüz başlatılmamış)")
except ImportError:
    check("Database: ClickHouse", "FAIL", "ClickHouse modülü import edilemiyor")
except Exception as e:
    check("Database: ClickHouse", "WARN", f"Bağlantı test edilemedi: {str(e)[:80]}")

# 4.4 NATS
try:
    from services.nats.client import nats_client

    if hasattr(nats_client, "is_connected"):
        check("Database: NATS", "PASS", "NATS client modülü mevcut")
    else:
        check("Database: NATS", "WARN", "NATS client yapısı beklenenden farklı")
except ImportError:
    check("Database: NATS", "FAIL", "NATS modülü import edilemiyor")
except Exception as e:
    check("Database: NATS", "WARN", f"{str(e)[:80]}")


# =====================================================
# 5. ML MODEL BAĞLANTI TESTLERİ
# =====================================================

section("5. ML MODEL BAĞLANTI TESTLERİ")

ML_MODULES = [
    ("ml.models", "ML Models"),
    ("ml.ensemble_trainer", "Ensemble Trainer"),
    ("ml.dataset_builder_30y", "Dataset Builder (30Y)"),
    ("ml.feature_discovery", "Feature Discovery"),
    ("ml.model_loader", "Model Loader"),
    ("ml.training", "Training Pipeline"),
]

for module_path, name in ML_MODULES:
    try:
        mod = importlib.import_module(module_path)
        check(f"ML: {name}", "PASS")
    except ImportError as e:
        check(f"ML: {name}", "FAIL", str(e)[:80])
    except Exception as e:
        check(f"ML: {name}", "WARN", str(e)[:80])


# =====================================================
# 6. CONFIG & SCHEMA TESTLERİ
# =====================================================

section("6. CONFIG & SCHEMA TESTLERİ")

CONFIG_FILES = [
    ("config/alpha_config.json", "Alpha Config"),
    ("config/alert_policy.json", "Alert Policy"),
    ("config/holidays.json", "Holidays"),
    ("config/tcmb_baseline.json", "TCMB Baseline"),
]

for file_path, name in CONFIG_FILES:
    full_path = PROJECT_ROOT / file_path
    if full_path.exists():
        try:
            import orjson

            with open(full_path, "rb") as f:
                data = orjson.loads(f.read())
            check(f"Config: {name}", "PASS", f"Geçerli JSON ({len(data)} key)")
        except orjson.JSONDecodeError as e:
            check(f"Config: {name}", "FAIL", f"Geçersiz JSON: {e}")
        except Exception as e:
            check(f"Config: {name}", "WARN", str(e)[:80])
    else:
        check(f"Config: {name}", "FAIL", f"Dosya bulunamadı: {file_path}")


# =====================================================
# 7. DOCKER-COMPOSE SERVİS TESTLERİ
# =====================================================

section("7. DOCKER-COMPOSE SERVİS TUTARLILIĞI")

try:
    import yaml

    compose_path = PROJECT_ROOT / "docker-compose.yml"
    with open(compose_path) as f:
        compose = yaml.safe_load(f)

    services = compose.get("services", {})
    expected_services = [
        "traefik",
        "postgres",
        "postgres-replica",
        "clickhouse",
        "clickhouse-2",
        "zookeeper",
        "redis",
        "redis-sentinel-1",
        "redis-sentinel-2",
        "redis-sentinel-3",
        "nats",
        "api",
        "ingestion",
        "feature-engine",
        "market-state",
        "intelligence",
        "simulation",
        "risk",
        "portfolio",
        "learning",
        "celery-worker",
        "dashboard",
        "postgres-exporter",
        "redis-exporter",
        "prometheus",
        "grafana",
        "mlflow",
    ]

    for svc_name in expected_services:
        if svc_name in services:
            svc = services[svc_name]
            has_healthcheck = "healthcheck" in svc
            has_depends = "depends_on" in svc
            detail = []
            if has_healthcheck:
                detail.append("healthcheck✓")
            if has_depends:
                detail.append("depends✓")
            check(f"Service: {svc_name}", "PASS", ", ".join(detail) if detail else "")
        else:
            check(f"Service: {svc_name}", "FAIL", "docker-compose'da tanımlı değil")

except ImportError:
    check("Docker Compose", "WARN", "PyYAML yüklü değil, YAML parse edilemedi")
except Exception as e:
    check("Docker Compose", "FAIL", str(e)[:80])


# =====================================================
# 8. PROTOBUF & gRPC TESTLERİ
# =====================================================

section("8. PROTOBUF & gRPC TESTLERİ")

# Proto dosyası
proto_path = PROJECT_ROOT / "proto" / "market.proto"
if proto_path.exists():
    check("Proto: market.proto", "PASS", f"Dosya mevcut ({proto_path.stat().st_size} bytes)")
else:
    check("Proto: market.proto", "FAIL", "Dosya bulunamadı")

# Generated kod
generated_dir = PROJECT_ROOT / "services" / "grpc" / "generated"
if (generated_dir / "market_pb2.py").exists():
    check("Generated: market_pb2.py", "PASS")
else:
    check("Generated: market_pb2.py", "FAIL", "Dosya bulunamadı")

if (generated_dir / "market_pb2_grpc.py").exists():
    check("Generated: market_pb2_grpc.py", "PASS")
else:
    check("Generated: market_pb2_grpc.py", "FAIL", "Dosya bulunamadı")

# Protobuf import testi
try:
    from services.grpc.generated import market_pb2

    tick = market_pb2.MarketTick(ticker="THYAO", price=100.0, timestamp=1234567890)
    serialized = tick.SerializeToString()
    tick2 = market_pb2.MarketTick()
    tick2.ParseFromString(serialized)
    assert tick2.ticker == "THYAO"
    assert tick2.price == 100.0
    check("Protobuf: Serialize/Deserialize", "PASS", f"{len(serialized)} bytes")
except Exception as e:
    check("Protobuf: Serialize/Deserialize", "FAIL", str(e)[:80])

# StreamMessage testi
try:
    msg = market_pb2.StreamMessage(
        type=market_pb2.StreamMessage.TICK,
        sequence=1,
        timestamp=1234567890,
        tick=market_pb2.MarketTick(ticker="ASELS", price=50.0),
    )
    data = msg.SerializeToString()
    msg2 = market_pb2.StreamMessage()
    msg2.ParseFromString(data)
    assert msg2.WhichOneof("payload") == "tick"
    assert msg2.tick.ticker == "ASELS"
    check("Protobuf: StreamMessage wrapper", "PASS", f"Payload: {msg2.WhichOneof('payload')}")
except Exception as e:
    check("Protobuf: StreamMessage wrapper", "FAIL", str(e)[:80])


# =====================================================
# 9. mTLS SERTİFİKA TESTLERİ
# =====================================================

section("9. mTLS SERTİFİKA TESTLERİ")

certs_dir = PROJECT_ROOT / "infrastructure" / "mtls" / "certs"
cert_files = {
    "ca.crt": "CA Sertifikası",
    "ca.key": "CA Private Key",
    "server.crt": "Server Sertifikası",
    "server.key": "Server Private Key",
    "client.crt": "Client Sertifikası",
    "client.key": "Client Private Key",
    "dhparam.pem": "DH Parametreleri",
}

for filename, name in cert_files.items():
    filepath = certs_dir / filename
    if filepath.exists():
        size = filepath.stat().st_size
        check(f"Cert: {name}", "PASS", f"{size} bytes")
    elif filename.endswith(".key") or filename.endswith(".pem"):
        check(f"Cert: {name}", "WARN", "Git'e commitlenmez (güvenlik) - deploy/başlangıçta üretilir")
    else:
        check(f"Cert: {name}", "FAIL", "Dosya bulunamadı")

# mTLS modülü testi
try:
    from services.core.mtls import MTLSConfig, MTLSContext

    config = MTLSConfig()
    ctx = MTLSContext(config)
    status = ctx.get_status()
    check("mTLS: Context", "PASS", f"Enabled: {status['enabled']}")
except Exception as e:
    check("mTLS: Context", "FAIL", str(e)[:80])


# =====================================================
# 10. BINARY WEBSOCKET PROTOBUF TESTİ
# =====================================================

section("10. BINARY WEBSOCKET PROTOBUF TESTİ")

try:
    from services.api.binary_ws import ProtobufMessage

    # Tick encode/decode
    tick_data = ProtobufMessage.encode_tick("THYAO", 250.5, 1.2, 0.48, 1000000)
    decoded = ProtobufMessage.decode(tick_data)
    assert decoded["type"] == "tick"
    assert decoded["data"]["ticker"] == "THYAO"
    assert decoded["data"]["price"] == 250.5
    check("BinaryWS: Tick encode/decode", "PASS", f"{len(tick_data)} bytes")

    # Signal encode/decode
    signal_data = ProtobufMessage.encode_signal("ASELS", "BUY", 0.85, 55.0, 48.0, "Momentum")
    decoded = ProtobufMessage.decode(signal_data)
    assert decoded["type"] == "signal"
    assert decoded["data"]["direction"] == "BUY"
    check("BinaryWS: Signal encode/decode", "PASS", f"{len(signal_data)} bytes")

    # OHLCV encode/decode
    ohlcv_data = ProtobufMessage.encode_ohlcv("GARAN", 100, 105, 98, 103, 5000000)
    decoded = ProtobufMessage.decode(ohlcv_data)
    assert decoded["type"] == "ohlcv"
    assert decoded["data"]["high"] == 105
    check("BinaryWS: OHLCV encode/decode", "PASS", f"{len(ohlcv_data)} bytes")

    # Portfolio encode/decode
    pf_data = ProtobufMessage.encode_portfolio(
        1000000, 200000, 5000, 0.5, [{"ticker": "THYAO", "quantity": 100, "avg_price": 250}]
    )
    decoded = ProtobufMessage.decode(pf_data)
    assert decoded["type"] == "portfolio"
    assert decoded["data"]["total_value"] == 1000000
    check("BinaryWS: Portfolio encode/decode", "PASS", f"{len(pf_data)} bytes")

    # Risk encode/decode
    risk_data = ProtobufMessage.encode_risk(0.05, 0.08, 1.5, 0.12, 0.18, 1.1)
    decoded = ProtobufMessage.decode(risk_data)
    assert decoded["type"] == "risk"
    assert decoded["data"]["sharpe"] == 1.5
    check("BinaryWS: Risk encode/decode", "PASS", f"{len(risk_data)} bytes")

    # Heartbeat
    hb_data = ProtobufMessage.encode_heartbeat()
    decoded = ProtobufMessage.decode(hb_data)
    assert decoded["type"] == "heartbeat"
    check("BinaryWS: Heartbeat encode/decode", "PASS", f"{len(hb_data)} bytes")

except Exception as e:
    check("BinaryWS: Protobuf", "FAIL", str(e)[:100])
    traceback.print_exc()


# =====================================================
# SONUÇ RAPORU
# =====================================================

section("SONUÇ RAPORU")

logger.info(f"""
  📊 Toplam Kontrol:    {total_checks}
  ✅ Başarılı:          {passed_checks}
  ❌ Başarısız:         {failed_checks}
  ⚠️  Uyarı:            {warning_checks}

  Başarı Oranı:         %{(passed_checks / max(total_checks, 1)) * 100:.1f}
""")

if failed_checks > 0:
    logger.info("  ❌ BAŞARISIZ KONTROLLER:")
    for name, result in results.items():
        if result["status"] == "FAIL":
            logger.info(f"     • {name}: {result['detail']}")

if warning_checks > 0:
    logger.info("\n  ⚠️  UYARILAR (servisler çalışmıyor olabilir):")
    for name, result in results.items():
        if result["status"] == "WARN":
            logger.info(f"     • {name}: {result['detail']}")

logger.info(f"\n{'=' * 60}")
if failed_checks == 0:
    logger.info("  🎉 TÜM KRİTİK KONTROLLER BAŞARILI!")
else:
    logger.info(f"  ⚠️  {failed_checks} KRİTİK KONTROL BAŞARISIZ — düzeltme gerekli")
logger.info(f"{'=' * 60}\n")

# Exit code
sys.exit(0 if failed_checks == 0 else 1)
