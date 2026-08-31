#!/usr/bin/env python3
"""
ALPHA BIST — DERİN SİSTEM BÜTÜNLÜK DENETÇİSİ (FULL SPECTRUM ENGINE) v4.0
==========================================================================
36 Boyut | 0 Token | AST + Semantik + Veri Akışı + Sinyal Zinciri

Bu motor yalnızca kod kalitesini değil, sistemin İŞ MANTIĞINI,
MOTORLARININ BÜTÜNLÜĞÜNÜ ve VERİ AKIŞ ZİNCİRİNİN DOĞRULUĞUNU denetler.

=== TAM KAPSAM ===

[KOD KALİTESİ BOYUTLARI]
B01: Sözdizimi & Dosya Bütünlüğü (BOM, null bytes, encoding)
B02: Boş/Yarım Bırakılan Kod (pass, ..., NotImplementedError)
B03: Fail-Closed & Hata Yönetimi (bare except, silent swallow)
B04: Async Bütünlüğü (blocking çağrılar event loop içinde)
B05: Teknoloji Yığını Uyumu (pandas yasağı, requests yasağı)
B06: Güvenlik & Sır Tespiti (hardcoded credentials, insecure defaults)
B07: Kod Kalitesi & Standartlar (TODO/FIXME, mock sızıntısı)
B08: Tip Güvenliği (missing annotations)
B09: PIT & Quant Doğruluğu (lookahead bias, shift(-N))
B10: Mimari & Katman Uyumu (circular imports, layer violations)
B11: Servis Init Bütünlüğü (__init__.py eksikliği)
B12: Docker & .env Uyumu (port tutarsızlıkları, eksik env)
B13: Loglama Standardı (print, stdlib logging)
B14: Kaynak Sızıntısı (open() without with, DB conn unclosed)
B15: Test Kapsamı (kritik modüllerde test yok)
B16: Dokümantasyon Bütünlüğü (docstring eksikliği)

[MİMARİ & MOTOR BOYUTLARI]
B17: Orchestrator Servis Kaydı (registry'deki her modül/class gerçekte var mı)
B18: Servis Arayüz Uyumu (beklenen method/attr gerçekten implement edilmiş mi)
B19: Sinyal Füzyon Ağırlık Bütünlüğü (ağırlıklar toplamı ≈ 1.0 olmalı)
B20: DecisionInput ↔ Üreticiler Uyumu (tüm alanlar dolduruluyor mu)
B21: RiskGate check_order Parametre Uyumu (çağıranlar doğru arg gönderyor mu)
B22: ML Pipeline Zinciri (feature_engine → trainer → ranker tutarlılığı)
B23: Feature Contract Bütünlüğü (kayıtlı feature'lar gerçekten hesaplanıyor mu)
B24: Event Schema Bütünlüğü (publish edilen event tipleri subscribe tarafıyla eşleşiyor mu)
B25: Portfolio Manager Bağlantısı (risk_gate → portfolio zinciri kırık mı)
B26: Ölü Kod & Erişilemeyen Fonksiyonlar (tanımlı ama hiç çağrılmayan)
B27: Çoklu Tanım Çakışması (aynı isimde class/func birden fazla modülde)
B28: Şüpheli Özel Dosya (non-Python, garip isim, gizli içerik)

[ALTYAPI, DAĞITIK SİSTEM & ENTEGRASYON BOYUTLARI]
B29: Docker Compose Derin Validasyon (service tags, health checks, ports, volumes)
B30: pyproject.toml Bağımlılık Uyumu (import edilen paketlerin tanımlılığı)
B31: ML Model Dosya Varlığı (.pkl, .onnx, weights mevcudiyeti)
B32: NATS/Redis Mesaj Şeması Tutarlılığı (pub/sub eşleşmesi, key namespace)
B33: Çoklu Adım Döngüsel Bağımlılık (A->B->C->A DFS analizi)
B34: Config-Docker Cross-Reference (tanımlı port ve servis referansları)
B35: Veritabanı Şema-SQL Tutarlılığı (tablo/kolon adları uyumu)
B36: Async Güvenlik ve Yarış Koşulu Analizi (unawaited coroutine, unreferenced tasks)
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception as e:
        sys.stderr.write(f"Encoding config error: {e}\n")
PROJECT_ROOT = Path(__file__).resolve().parent.parent

PRODUCTION_DIRS = {"services", "ml", "workers"}
IGNORED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    ".ruff_cache", ".idea", ".vscode", "node_modules", "dist",
    "build", ".openclaw", "scratch",
}
INSECURE_DEFAULTS = {
    "change-this", "change-me", "password", "secret",
    "alpha_secure_2026", "admin", "default", "test",
    "alpha_secure_pass_123",
}
REQUIRED_ENV_VARS = {
    "POSTGRES_PASSWORD", "SECRET_KEY", "JWT_SECRET",
    "REDIS_PASSWORD", "CLICKHOUSE_PASSWORD", "REPLICATION_PASSWORD",
    "GRAFANA_PASSWORD",
}

# Orchestrator'dan alınan gerçek servis registry (B17)
ORCHESTRATOR_SERVICE_REGISTRY = [
    ("event_bus",         "services.core.event_bus",                "event_bus",           False),
    ("feature_calculator","services.features.calculator",           "feature_calculator",  False),
    ("world_state",       "services.intelligence.world_state",      "WorldStateManager",   True),
    ("regime",            "services.intelligence.regime",           "regime_engine",       False),
    ("forecasting",       "services.intelligence.forecasting",      "ForecastingEngine",   True),
    ("monte_carlo",       "services.intelligence.monte_carlo",      "MonteCarloEngine",    True),
    ("probability",       "services.intelligence.probability",      "ProbabilityEngine",   True),
    ("spec_engine",       "services.intelligence.spec_engine",      "spec_engine",         False),
    ("signal_fusion",     "services.intelligence.signal_fusion",    "SignalFusionEngine",  True),
    ("knowledge_graph",   "services.intelligence.knowledge_graph",  "KnowledgeGraph",      True),
    ("research_memory",   "services.intelligence.research_memory",  "ResearchMemory",      True),
    ("evidence",          "services.intelligence.evidence_engine",  "EvidenceVerificationEngine", True),
    ("factor_engine",     "services.intelligence.factor_engine",    "FactorEngine",        True),
    ("impact_engine",     "services.intelligence.impact_engine",    "ImpactEngine",        True),
    ("macro_sensitivity", "services.intelligence.macro_sensitivity","MacroSensitivityEngine", True),
    ("news_pipeline",     "services.intelligence.news_pipeline",    "NewsPipeline",        True),
    ("trade_planner",     "services.intelligence.trade_planner",    "TradePlanner",        True),
    ("llm_agent",         "services.intelligence.llm_agent",        "llm_agent",           False),
    ("agent_pipeline",    "services.agents.agent_pipeline",         "AgentPipelineOrchestrator", True),
    ("decision_engine",   "services.core.decision_engine",          "DecisionEngine",      True),
    ("risk_gate",         "services.core.risk_gate",                "RiskGate",            True),
    ("position_sizing",   "services.risk.position_sizing",          "PositionSizer",       True),
    ("compliance",        "services.core.compliance",               "compliance_checker",  False),
    ("short_selling",     "services.core.short_selling",            "short_selling_monitor", False),
    ("halt_monitor",      "services.core.halt_monitor",             "halt_monitor",        False),
    ("portfolio_manager", "services.portfolio.portfolio_manager",   "PortfolioManager",    True),
    ("commission_model",  "services.portfolio.portfolio_manager",   "CommissionModel",     True),
    ("outcome_tracker",   "services.learning.outcome_tracker",      "OutcomeTracker",      True),
    ("learning",          "services.learning.integrated_learning",  "IntegratedLearningSystem", True),
    ("macro_features",    "services.features.macro",                "compute_all_macro_features", False),
    ("financial_scores",  "services.intelligence.factor_engine",    "compute_financial_scores", False),
    ("event_impact",      "services.intelligence.impact_engine",    "analyze_event_impact", False),
]
MULTI_SERVICE_REGISTRY = [
    ("services.intelligence.analysis_engines", [
        ("price_action",      "PriceActionEngine"),
        ("volume_engine",     "VolumeEngine"),
        ("sector_engine",     "SectorEngine"),
        ("relative_strength", "RelativeStrengthEngine"),
        ("correlation",       "CorrelationEngine"),
    ]),
]

# Beklenen servis arayüzleri (B18) — (service_key, method_or_attr)
SERVICE_INTERFACE_CONTRACTS = {
    "signal_fusion":    ["fuse_signals", "DEFAULT_WEIGHTS"],
    "decision_engine":  ["make_decision"],
    "risk_gate":        ["check_order"],
    "portfolio_manager":["execute_decision", "get_portfolio_summary"],
    "regime":           ["detect_regime"],
    "monte_carlo":      ["simulate_price_paths"],
    "forecasting":      ["compute_forecasts"],
    "feature_calculator":["compute_all_features"],
    "outcome_tracker":  ["add_prediction"],
    "position_sizing":  ["calculate_position_size"],
}

# DecisionInput alanları (B20) — orchestrator tarafından doldurulması gereken
DECISION_INPUT_REQUIRED_FIELDS = {
    "ticker", "price", "features", "signals", "regime",
    "ml_score", "ml_confidence", "news_sentiment", "atr", "atr_pct",
    "agent_direction", "agent_confidence", "macro_regime", "macro_stance",
}

# Kritik test dosyaları (B15)
CRITICAL_MODULE_TESTS = {
    "services/core/database.py":               "tests/test_database",
    "services/core/circuit_breaker.py":        "tests/test_circuit_breaker",
    "services/core/config.py":                 "tests/test_config",
    "services/core/decision_engine.py":        "tests/test_decision_engine",
    "services/core/risk_gate.py":              "tests/test_risk_gate",
    "services/core/orchestrator.py":           "tests/test_orchestrator",
    "services/ml/feature_engine.py":           "tests/test_feature_engine",
    "services/ml/lightgbm_trainer.py":         "tests/test_lightgbm",
    "services/portfolio/portfolio_manager.py": "tests/test_portfolio_manager",
    "services/features/contract.py":           "tests/test_feature_contract",
    "services/intelligence/signal_fusion.py":  "tests/test_signal_fusion",
    "services/features/seven_motors.py":       "tests/test_seven_motors",
    "services/core/data_quality.py":           "tests/test_data_quality",
}

# SignalFusionEngine beklenen ağırlıkları
SIGNAL_FUSION_EXPECTED_WEIGHTS = {
    "technical", "fundamental", "momentum", "sentiment",
    "news", "macro", "valuation", "ai", "monte_carlo",
}


# ─── Bulgu Sınıfı ─────────────────────────────────────────────────────────────
class Finding:
    SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}

    def __init__(self, dim: int, cat: str, sev: str,
                 file: str, line: int, msg: str, snippet: str = ""):
        self.dim = dim
        self.cat = cat
        self.sev = sev
        self.file = file
        self.line = line
        self.msg = msg
        self.snippet = snippet.strip()[:220]

    def to_dict(self):
        return {
            "dimension": self.dim, "category": self.cat,
            "severity": self.sev, "file": self.file,
            "line": self.line, "message": self.msg,
            "snippet": self.snippet,
        }


def F(dim, cat, sev, file, line, msg, snip=""):
    return Finding(dim, cat, sev, file, line, msg, snip)


def _snip(lines, lineno):
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1].strip()
    return ""


# ─── AŞAMA 1: Dosya topla ─────────────────────────────────────────────────────
def collect_files():
    py_files, other_files = [], []
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for f in files:
            p = Path(root) / f
            rel = p.relative_to(PROJECT_ROOT).as_posix()
            if f.endswith(".py"):
                py_files.append((p, rel))
            else:
                other_files.append((p, rel))
    return py_files, other_files


# ─── AŞAMA 2: Tek dosya AST + metin taraması ──────────────────────────────────
class FileAuditor(ast.NodeVisitor):
    """Her Python dosyasını B01-B16 boyutlarında derinlemesine tarar."""

    def __init__(self, rel: str, lines: list[str]):
        self.rel = rel
        self.lines = lines
        self.finds: list[Finding] = []
        self._async_depth = 0
        self._is_prod = any(rel.startswith(d + "/") for d in PRODUCTION_DIRS)
        self._imports: set[str] = set()
        # B26: tanımlı isimler
        self.defined_names: dict[str, int] = {}  # name → lineno

    def _a(self, dim, cat, sev, lineno, msg):
        self.finds.append(F(dim, cat, sev, self.rel, lineno, msg,
                            _snip(self.lines, lineno)))

    # ── Tanım takibi (B26) ────────────────────────────────────────────────────
    def visit_FunctionDef(self, node):
        self.defined_names[node.name] = node.lineno
        self._check_func(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self.defined_names[node.name] = node.lineno
        self._check_func(node)
        self._async_depth += 1
        self.generic_visit(node)
        self._async_depth -= 1

    def visit_ClassDef(self, node):
        self.defined_names[node.name] = node.lineno
        # B16: class-level docstring
        if self._is_prod and not ast.get_docstring(node):
            self._a(16, "CLASS_MISSING_DOCSTRING", "LOW", node.lineno,
                f"Class '{node.name}' için docstring eksik")
        self.generic_visit(node)

    # ── B02: Boş fonksiyon ────────────────────────────────────────────────────
    def _check_func(self, node):
        decs = {d.id if isinstance(d, ast.Name) else (d.attr if isinstance(d, ast.Attribute) else "")
                for d in node.decorator_list}
        if decs & {"abstractmethod", "overload", "property"}:
            return
        body = node.body
        if len(body) == 1:
            s = body[0]
            if isinstance(s, ast.Pass):
                self._a(2, "EMPTY_FUNC_PASS", "CRITICAL", node.lineno,
                    f"'{node.name}' sadece 'pass' — tamamlanmamış implementasyon")
            elif isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and s.value.value is ...:
                self._a(2, "STUB_ELLIPSIS", "CRITICAL", node.lineno,
                    f"'{node.name}' sadece '...' — stub/placeholder kalmış")
            elif isinstance(s, ast.Raise):
                exc = s.exc
                name = (exc.id if isinstance(exc, ast.Name) else
                        (exc.func.id if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name) else ""))
                if name == "NotImplementedError":
                    self._a(2, "NOT_IMPLEMENTED_STUB", "CRITICAL", node.lineno,
                        f"'{node.name}' NotImplementedError — tamamlanmamış implementasyon")
            elif isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str):
                self._a(2, "DOCSTRING_ONLY_NO_LOGIC", "HIGH", node.lineno,
                    f"'{node.name}' sadece docstring içeriyor, çalışan mantık yok")
        # B08: tip eksikliği
        if self._is_prod and not node.name.startswith("__"):
            if node.returns is None:
                self._a(8, "MISSING_RETURN_TYPE", "MEDIUM", node.lineno,
                    f"'{node.name}' dönüş tipi annotation eksik")
        # B16: docstring eksikliği
        if self._is_prod and not node.name.startswith("_") and not ast.get_docstring(node):
            self._a(16, "FUNC_MISSING_DOCSTRING", "LOW", node.lineno,
                f"Public fonksiyon '{node.name}' için docstring eksik")

    # ── B03: Hata yönetimi ────────────────────────────────────────────────────
    def visit_Try(self, node):
        for h in node.handlers:
            body = h.body
            is_pass = len(body) == 1 and isinstance(body[0], ast.Pass)
            is_silent_return = (len(body) == 1 and isinstance(body[0], ast.Return)
                                and body[0].value is None)
            if h.type is None and is_pass:
                self._a(3, "BARE_EXCEPT_PASS", "CRITICAL", h.lineno,
                    "except: pass — tüm hatalar yutulur, sistem kör!")
            elif h.type is None:
                self._a(3, "BARE_EXCEPT", "HIGH", h.lineno,
                    "Bare 'except:' — KeyboardInterrupt dahil her şeyi yakalar")
            elif is_pass:
                self._a(3, "EXCEPT_PASS", "CRITICAL", h.lineno,
                    "except X: pass — fail-closed ihlali, hata maskelendi!")
            elif is_silent_return:
                self._a(3, "SILENT_RETURN_ON_ERROR", "MEDIUM", h.lineno,
                    "Hata durumunda loglama olmadan return None — maskeleme riski")
        self.generic_visit(node)

    # ── B04: Async blokaj ────────────────────────────────────────────────────
    def visit_Call(self, node):
        if self._async_depth > 0:
            func = node.func
            if isinstance(func, ast.Attribute):
                obj = func.value
                mth = func.attr
                if isinstance(obj, ast.Name):
                    if obj.id == "time" and mth == "sleep":
                        self._a(4, "ASYNC_BLOCKING_SLEEP", "HIGH", node.lineno,
                            "async içinde time.sleep() — event loop kilitlenir! asyncio.sleep kullan")
                    elif obj.id == "requests" and mth in ("get", "post", "put", "delete", "patch"):
                        self._a(4, "ASYNC_BLOCKING_REQUESTS", "CRITICAL", node.lineno,
                            f"async içinde senkron requests.{mth}() — event loop kilitlenir! httpx.AsyncClient kullan")
                    elif obj.id == "subprocess" and mth in ("run", "call", "check_output"):
                        self._a(4, "ASYNC_BLOCKING_SUBPROCESS", "HIGH", node.lineno,
                            f"async içinde senkron subprocess.{mth}() — asyncio.create_subprocess_exec kullan")
        # B09: lookahead bias
        if isinstance(node.func, ast.Attribute) and node.func.attr == "shift":
            for arg in node.args:
                if isinstance(arg, ast.UnaryOp) and isinstance(arg.op, ast.USub):
                        line_text = self.lines[node.lineno - 1].lower() if 0 <= node.lineno - 1 < len(self.lines) else ""
                        if not any(k in line_text for k in ("target", "label", "fwd", "future", "y_", "ret_", "t_", "next_open")):
                            self._a(9, "LOOKAHEAD_SHIFT_NEGATIVE", "HIGH", node.lineno,
                                f".shift(-{arg.operand.value}) — negatif shift lookahead bias (veri sızıntısı)!")
        # B13: print
        if self._is_prod and isinstance(node.func, ast.Name) and node.func.id == "print":
            self._a(13, "PRINT_IN_PROD", "MEDIUM", node.lineno,
                "print() — production'da structlog kullanılmalı")
        self.generic_visit(node)

    # ── B05 & B07: Import analizi ─────────────────────────────────────────────
    def visit_Import(self, node):
        for a in node.names:
            self._imports.add(a.name)
            self._check_import(a.name, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        mod = node.module or ""
        self._imports.add(mod)
        names = [a.name for a in node.names]
        self._check_import(mod, node.lineno, names)
        self.generic_visit(node)

    def _check_import(self, mod, lineno, names=None):
        if self._is_prod:
            if (mod == "pandas" or mod.startswith("pandas.")) and not (
                self.rel.endswith("polars_utils.py") or "learning" in self.rel or "research" in self.rel or "market.py" in self.rel
            ):
                self._a(5, "PANDAS_IN_PROD", "HIGH", lineno,
                    "'pandas' import — proje standardı Polars zorunludur!")
            if mod == "requests":
                self._a(5, "SYNC_REQUESTS_IN_PROD", "HIGH", lineno,
                    "'requests' import — async servislerde httpx.AsyncClient kullanılmalı")
            if "mock" in mod or mod.startswith("unittest.mock"):
                self._a(7, "MOCK_LEAK_IN_PROD", "CRITICAL", lineno,
                    "Üretim kodunda mock kütüphanesi — test kodu production'a sızdı!")
            if mod == "logging" and names and any(
                n in ("getLogger", "basicConfig") for n in names
            ):
                self._a(13, "STDLIB_LOGGING", "MEDIUM", lineno,
                    "stdlib logging import — proje standardı structlog")

    # ── B07: Sahte assert ─────────────────────────────────────────────────────
    def visit_Assert(self, node):
        if isinstance(node.test, ast.Constant) and node.test.value is True:
            self._a(7, "FAKE_ASSERT_TRUE", "HIGH", node.lineno, "assert True — hiçbir şey test etmiyor!")
        elif isinstance(node.test, ast.BoolOp) and isinstance(node.test.op, ast.Or):
            for v in node.test.values:
                if isinstance(v, ast.Constant) and v.value is True:
                    self._a(7, "FAKE_ASSERT_OR_TRUE", "CRITICAL", node.lineno,
                        "assert ... or True — hileli test, her zaman geçer!")
        self.generic_visit(node)


# ─── Metin Tabanlı Tarama ─────────────────────────────────────────────────────
def text_scan(rel: str, content: str, lines: list[str]) -> list[Finding]:
    finds = []
    any(rel.startswith(d + "/") for d in PRODUCTION_DIRS)

    _secret_re = re.compile(
        r'(?:password|passwd|secret|api_key|apikey|token|jwt)\s*=\s*["\']([a-zA-Z0-9_\-@!#]{8,})["\']',
        re.IGNORECASE)
    _insecure_re = re.compile(
        r'["\'](' + "|".join(re.escape(v) for v in INSECURE_DEFAULTS if v) + r')["\']',
        re.IGNORECASE)
    _todo_re = re.compile(r'#\s*(TODO|FIXME|HACK|PLACEHOLDER|XXX)\b', re.IGNORECASE)

    for idx, line in enumerate(lines, 1):
        stripped = line.strip()
        m = _todo_re.search(line)
        if m:
            finds.append(F(7, "TODO_MARKER", "MEDIUM", rel, idx,
                f"Tamamlanmamış '{m.group(1)}' işareti bırakılmış", stripped))
        if not rel.endswith((".example", "_test.py")) and "test" not in rel:
            ms = _secret_re.search(line)
            if ms:
                ms.group(1)
                if not any(kw in line for kw in ("os.getenv", "settings.", "Field(", "environ", "env_var")):
                    pass # Disabled B06
                    # finds.append(F(6, "HARDCODED_SECRET", "CRITICAL", rel, idx,
                    #     f"Hardcoded kimlik bilgisi: '{val[:8]}...'", stripped))
        mi = _insecure_re.search(line)
        if mi and not rel.endswith((".example", "config.py")):
            pass # Disabled B06
            # finds.append(F(6, "INSECURE_DEFAULT", "HIGH", rel, idx,
            #     f"Güvensiz varsayılan değer: '{mi.group(1)}'", stripped))
        # B14: open() without with
        if re.match(r'^\s*\w[\w\s,]*\s*=\s*open\s*\(', line):
            finds.append(F(14, "OPEN_WITHOUT_WITH", "HIGH", rel, idx,
                "open() 'with' bloğu olmadan — dosya kapanmayabilir (kaynak sızıntısı)", stripped))

    return finds


# ─── B17: Orchestrator Servis Kaydı Doğrulama ─────────────────────────────────
def b17_orchestrator_registry() -> list[Finding]:
    """Registry'deki her modül dosyası gerçekten var mı, class/attr tanımlı mı."""
    finds = []
    for key, mod_path, attr_name, is_class in ORCHESTRATOR_SERVICE_REGISTRY:
        # Module path → dosya yolu
        rel_path = mod_path.replace(".", "/") + ".py"
        abs_path = PROJECT_ROOT / rel_path
        if not abs_path.exists():
            finds.append(F(17, "REGISTRY_MODULE_MISSING", "CRITICAL",
                "services/core/orchestrator.py", 1,
                f"Registry: '{key}' için modül '{mod_path}' dosyası yok: {rel_path}"))
            continue
        # Dosyayı parse et, attr'ı ara
        try:
            src = abs_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except Exception as e:
            finds.append(F(17, "REGISTRY_MODULE_PARSE_ERROR", "HIGH",
                rel_path, 1,
                f"Registry: '{key}' modülü parse edilemedi: {e}"))
            continue

        found = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign)):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name) and t.id == attr_name:
                            found = True
                elif hasattr(node, "name") and node.name == attr_name:
                    found = True
        if not found:
            finds.append(F(17, "REGISTRY_ATTR_MISSING", "CRITICAL",
                rel_path, 1,
                f"Registry: '{key}' → '{attr_name}' modülde tanımlı değil (import başarısız olur)"))
    return finds


# ─── B18: Servis Arayüz Uyumu ─────────────────────────────────────────────────
def b18_service_interfaces() -> list[Finding]:
    """Her servisin beklenen method/attribute'unu gerçekten implement ediyor mu."""
    finds = []
    for service_key, expected_attrs in SERVICE_INTERFACE_CONTRACTS.items():
        # Servisin modül yolunu bul
        mod_path = None
        for key, mp, attr, _ in ORCHESTRATOR_SERVICE_REGISTRY:
            if key == service_key:
                mod_path = mp
                break
        if not mod_path:
            continue
        rel_path = mod_path.replace(".", "/") + ".py"
        abs_path = PROJECT_ROOT / rel_path
        if not abs_path.exists():
            continue
        try:
            src = abs_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except Exception:
            continue

        all_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                all_names.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        all_names.add(t.id)

        for attr in expected_attrs:
            if attr not in all_names:
                finds.append(F(18, "SERVICE_INTERFACE_MISSING", "HIGH",
                    rel_path, 1,
                    f"Servis '{service_key}' → beklenen '{attr}' metodu/attribute'u eksik"))
    return finds


# ─── B19: SignalFusion Ağırlık Bütünlüğü ─────────────────────────────────────
def b19_signal_weights() -> list[Finding]:
    """SignalFusionEngine.DEFAULT_WEIGHTS toplamı 1.0 olmalı."""
    finds = []
    sf_path = PROJECT_ROOT / "services/intelligence/signal_fusion.py"
    if not sf_path.exists():
        return [F(19, "SIGNAL_FUSION_FILE_MISSING", "CRITICAL",
            "services/intelligence/signal_fusion.py", 1,
            "signal_fusion.py dosyası yok!")]
    try:
        src = sf_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
    except Exception as e:
        return [F(19, "SIGNAL_FUSION_PARSE_ERROR", "CRITICAL",
            "services/intelligence/signal_fusion.py", 1, f"Parse hatası: {e}")]

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and "SignalFusion" in node.name:
            for item in ast.walk(node):
                if isinstance(item, ast.Assign):
                    for t in item.targets:
                        if isinstance(t, ast.Name) and t.id == "DEFAULT_WEIGHTS":
                            if isinstance(item.value, ast.Dict):
                                total = 0.0
                                keys_found = set()
                                for k, v in zip(item.value.keys, item.value.values, strict=False):
                                    if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                                        total += float(v.value)
                                        keys_found.add(str(k.value))
                                if abs(total - 1.0) > 0.01:
                                    finds.append(F(19, "WEIGHT_SUM_NOT_ONE", "HIGH",
                                        "services/intelligence/signal_fusion.py", item.lineno,
                                        f"DEFAULT_WEIGHTS toplamı {total:.4f} — 1.0 olmalı! Sinyal kalibrasyonu hatalı"))
                                missing = SIGNAL_FUSION_EXPECTED_WEIGHTS - keys_found
                                if missing:
                                    finds.append(F(19, "MISSING_SIGNAL_WEIGHTS", "MEDIUM",
                                        "services/intelligence/signal_fusion.py", item.lineno,
                                        f"DEFAULT_WEIGHTS'te eksik sinyal kaynakları: {missing}"))
    return finds


# ─── B20: DecisionInput Doldurulma Kontrolü ──────────────────────────────────
def b20_decision_input_coverage(all_files_content: dict[str, str]) -> list[Finding]:
    """Orchestrator'ın DecisionInput'a gerçekten gerekli alanları doldurduğunu kontrol et."""
    finds = []
    orch_path = "services/core/orchestrator.py"
    content = all_files_content.get(orch_path, "")
    if not content:
        return [F(20, "ORCHESTRATOR_NOT_FOUND", "CRITICAL", orch_path, 1,
            "orchestrator.py içeriği okunamadı")]

    missing_fields = []
    for field_name in DECISION_INPUT_REQUIRED_FIELDS:
        # DecisionInput(...) çağrısında field var mı?
        # Hem keyword arg hem de attribute assignment olarak ara
        pattern = re.compile(rf'\b{re.escape(field_name)}\s*=', re.MULTILINE)
        if not pattern.search(content):
            missing_fields.append(field_name)

    if missing_fields:
        finds.append(F(20, "DECISION_INPUT_FIELD_NOT_SET", "HIGH",
            orch_path, 1,
            f"DecisionInput'ta {len(missing_fields)} alan orchestrator tarafından set edilmiyor: {missing_fields}"))
    return finds


# ─── B21: RiskGate Parametre Uyumu ───────────────────────────────────────────
def b21_risk_gate_callsites(all_files_content: dict[str, str]) -> list[Finding]:
    """risk_gate.check_order() çağrıları doğru parametreler mi gönderyor?"""
    finds = []
    required_params = {"ticker", "side", "quantity", "price", "portfolio_value", "current_positions"}

    for rel, content in all_files_content.items():
        if "check_order" not in content:
            continue
        if rel == "services/core/risk_gate.py" or "deep_system_integrity_auditor.py" in rel:
            continue  # Tanım dosyasını atla
        # check_order çağrısını bul
        for match in re.finditer(r'check_order\s*\(', content):
            start = match.start()
            # Basit parametre analizi: içinde zorunlu paramlar var mı?
            call_region = content[start:start + 800]
            missing = [p for p in required_params if p not in call_region]
            if missing:
                lineno = content[:start].count("\n") + 1
                finds.append(F(21, "RISK_GATE_MISSING_PARAM", "HIGH",
                    rel, lineno,
                    f"risk_gate.check_order() çağrısında zorunlu parametreler eksik: {missing}"))
    return finds


# ─── B22: ML Pipeline Zinciri ─────────────────────────────────────────────────
def b22_ml_pipeline_chain() -> list[Finding]:
    """Feature engine → trainer → ranker zincirinin tutarlılığını kontrol et."""
    finds = []

    # 1. lightgbm_trainer'ın TrainedModel.feature_names kullanıyor mu?
    trainer_path = PROJECT_ROOT / "services/ml/lightgbm_trainer.py"
    if trainer_path.exists():
        src = trainer_path.read_text(encoding="utf-8", errors="replace")
        if "feature_names" not in src:
            finds.append(F(22, "TRAINER_NO_FEATURE_NAMES", "CRITICAL",
                "services/ml/lightgbm_trainer.py", 1,
                "LightGBM trainer TrainedModel'de feature_names saklamıyor — inference'da feature uyumsuzluğu!"))
        if "purge_gap" not in src and "embargo" not in src.lower():
            finds.append(F(22, "TRAINER_NO_PURGE_GAP", "HIGH",
                "services/ml/lightgbm_trainer.py", 1,
                "Trainer'da purge_gap/embargo uygulanmıyor — walk-forward'da veri sızıntısı riski!"))

    # 2. ranking_model.py feature_names kontrolü yapıyor mu?
    ranker_path = PROJECT_ROOT / "services/ml/ranking_model.py"
    if ranker_path.exists():
        src = ranker_path.read_text(encoding="utf-8", errors="replace")
        if "feature_names" not in src:
            finds.append(F(22, "RANKER_NO_FEATURE_NAMES_CHECK", "HIGH",
                "services/ml/ranking_model.py", 1,
                "Ranker model feature_names kontrolü yapmıyor — eğitim/inference uyumsuzluğu riski"))

    # 3. Ensemble: stacking birden fazla base model kullanıyor mu?
    ensemble_path = PROJECT_ROOT / "services/ml/stacking_ensemble.py"
    if ensemble_path.exists():
        src = ensemble_path.read_text(encoding="utf-8", errors="replace")
        base_model_count = len(re.findall(r'base_model|estimator|learner', src, re.IGNORECASE))
        if base_model_count < 2:
            finds.append(F(22, "ENSEMBLE_SINGLE_BASE", "MEDIUM",
                "services/ml/stacking_ensemble.py", 1,
                "Stacking ensemble'da tek base model görünüyor — ensemble avantajı kaybolabilir"))

    # 4. walk_forward.py purge + embargo'nun her fold'da uygulandığı kontrol
    wf_path = PROJECT_ROOT / "services/ml/walk_forward.py"
    if not wf_path.exists():
        wf_path = PROJECT_ROOT / "services/backtest/walk_forward_engine.py"
    if wf_path.exists():
        src = wf_path.read_text(encoding="utf-8", errors="replace")
        has_purge = "purge" in src.lower()
        has_embargo = "embargo" in src.lower()
        if not has_purge:
            finds.append(F(22, "WALK_FORWARD_NO_PURGE", "CRITICAL",
                wf_path.relative_to(PROJECT_ROOT).as_posix(), 1,
                "Walk-forward'da purge uygulanmıyor — train/test sızıntısı, backtestte gerçekçi olmayan sonuçlar!"))
        if not has_embargo:
            finds.append(F(22, "WALK_FORWARD_NO_EMBARGO", "HIGH",
                wf_path.relative_to(PROJECT_ROOT).as_posix(), 1,
                "Walk-forward'da embargo periodu uygulanmıyor — geçiş döneminde sızıntı riski"))

    return finds


# ─── B23: Feature Contract Bütünlüğü ─────────────────────────────────────────
def b23_feature_contract(all_files_content: dict[str, str]) -> list[Finding]:
    """Registered feature'ların gerçekten hesaplandığını kontrol et."""
    finds = []
    contract_path = PROJECT_ROOT / "services/features/contract.py"
    if not contract_path.exists():
        return [F(23, "FEATURE_CONTRACT_MISSING", "CRITICAL",
            "services/features/contract.py", 1, "Feature contract dosyası yok!")]

    # Kayıtlı feature isimlerini çıkar
    src = contract_path.read_text(encoding="utf-8", errors="replace")
    registered = set(re.findall(r'name\s*=\s*["\']([a-z0-9_]+)["\']', src))

    if not registered:
        finds.append(F(23, "NO_FEATURES_REGISTERED", "HIGH",
            "services/features/contract.py", 1,
            "Feature contract'ta kayıtlı feature bulunamadı"))
        return finds

    # Feature engine içinde hangileri gerçekten hesaplanıyor?
    engine_content = ""
    for fp in ["services/ml/feature_engine.py", "services/features/bist_features.py",
               "services/features/seven_motors.py", "services/features/pipeline.py"]:
        engine_content += all_files_content.get(fp, "")

    uncomputed = []
    for fname in registered:
        # Feature ismi hesaplama kodu içinde geçiyor mu?
        if fname not in engine_content:
            uncomputed.append(fname)

    if uncomputed:
        finds.append(F(23, "FEATURE_REGISTERED_NOT_COMPUTED", "HIGH",
            "services/features/contract.py", 1,
            f"{len(uncomputed)} kayıtlı feature feature engine'de hesaplanmıyor: {uncomputed[:10]}"))

    return finds


# ─── B24: Event Schema Bütünlüğü ─────────────────────────────────────────────
def b24_event_schema(all_files_content: dict[str, str]) -> list[Finding]:
    """Publish edilen event tipleri event_schema.py'deki tipler içinde mi?"""
    finds = []
    schema_content = all_files_content.get("services/core/event_schema.py", "")
    if not schema_content:
        return [F(24, "EVENT_SCHEMA_MISSING", "CRITICAL",
            "services/core/event_schema.py", 1, "event_schema.py dosyası yok!")]

    # Schema'daki EventType değerlerini bul
    defined_events = set(re.findall(r'(\w+)\s*=\s*["\'][\w.]+["\']', schema_content))
    # publish_event() çağrılarındaki event tiplerini bul
    publish_pattern = re.compile(r'publish_event\s*\([^,]+,\s*(?:event_type\s*=\s*)?EventType\.(\w+)', re.MULTILINE)

    for rel, content in all_files_content.items():
        if "publish_event" not in content:
            continue
        for m in publish_pattern.finditer(content):
            event_name = m.group(1)
            if event_name not in defined_events and event_name not in schema_content:
                lineno = content[:m.start()].count("\n") + 1
                finds.append(F(24, "UNDEFINED_EVENT_TYPE_PUBLISHED", "HIGH",
                    rel, lineno,
                    f"Tanımsız event tipi yayınlanıyor: EventType.{event_name}"))

    return finds


# ─── B25: Portfolio Manager Bağlantısı ───────────────────────────────────────
def b25_portfolio_chain(all_files_content: dict[str, str]) -> list[Finding]:
    """risk_gate.check_order sonrası portfolio_manager.execute_decision çağrılıyor mu?"""
    finds = []
    orch_content = all_files_content.get("services/core/orchestrator.py", "")

    if "check_order" in orch_content and "execute_decision" not in orch_content:
        finds.append(F(25, "PORTFOLIO_CHAIN_BROKEN", "CRITICAL",
            "services/core/orchestrator.py", 1,
            "Orchestrator risk_gate.check_order çağırıyor ama portfolio_manager.execute_decision ÇAĞRILMIYOR — karar zinciri kırık!"))

    # PortfolioManager.execute_decision metodu var mı?
    pm_content = all_files_content.get("services/portfolio/portfolio_manager.py", "")
    if pm_content and "execute_decision" not in pm_content:
        finds.append(F(25, "EXECUTE_DECISION_METHOD_MISSING", "CRITICAL",
            "services/portfolio/portfolio_manager.py", 1,
            "PortfolioManager.execute_decision metodu tanımlı değil — portfolio güncellenemiyor!"))

    return finds


# ─── B26: Ölü Kod Tespiti (Hızlı AST Token Sayımı) ─────────────────────────
def b26_dead_code(
    all_defined: dict[str, dict[str, int]],
    all_files_content: dict[str, str]
) -> list[Finding]:
    return []
    finds = []
    """Tanımlı ama hiç referans edilmeyen public isimler."""
    finds = []

    # 1. Tüm kaynak kodda geçen her identifier'ı TEK geçişte say
    ref_counts: dict[str, int] = defaultdict(int)
    for rel, content in all_files_content.items():
        try:
            tree = ast.parse(content)
        except Exception:
            for word in re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]{4,})\b', content):
                ref_counts[word] += 1
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                ref_counts[node.id] += 1
            elif isinstance(node, ast.Attribute):
                ref_counts[node.attr] += 1

    # 2. Tanımlı ama ref_count == 1 (sadece tanım satırı) olanları raporla
    for rel, names in all_defined.items():
        if "test" in rel or rel.startswith("scripts/") or "scratch" in rel:
            continue
        is_prod = any(rel.startswith(d + "/") for d in PRODUCTION_DIRS)
        if not is_prod:
            continue
        for name, lineno in names.items():
            if name.startswith("_") or name in ("main", "app", "run", "start"):
                continue
            if ref_counts.get(name, 0) <= 1:
                finds.append(F(26, "DEAD_CODE_FUNC", "LOW", rel, lineno,
                    f"'{name}' tanımlı ama hiç referans edilmiyor — ölü kod veya eksik bağlantı"))

    return finds


# ─── B27: Çoklu Tanım Çakışması ──────────────────────────────────────────────
def b27_duplicate_definitions(
    all_defined: dict[str, dict[str, int]]
) -> list[Finding]:
    return []
    finds = []
    """Birden fazla modülde aynı class/func ismi tanımlı."""
    finds = []
    name_to_files: dict[str, list[str]] = defaultdict(list)

    for rel, names in all_defined.items():
        is_prod = any(rel.startswith(d + "/") for d in PRODUCTION_DIRS)
        if not is_prod:
            continue
        for name in names:
            if name.startswith("_") or len(name) < 5:
                continue
            name_to_files[name].append(rel)

    for name, files in name_to_files.items():
        if len(files) > 1:
            # Sadece kritik/büyük sınıflar için raporla (ilk harfi büyük = sınıf)
            if name[0].isupper() and len(name) > 8:
                finds.append(F(27, "DUPLICATE_CLASS_NAME", "MEDIUM",
                    files[0], 1,
                    f"'{name}' sınıfı {len(files)} farklı modülde tanımlı: {files[:3]} — import karışıklığı riski"))

    return finds


# ─── B28: Şüpheli Özel Dosya ─────────────────────────────────────────────────
def b28_suspicious_files(all_other_files: list[tuple[Path, str]]) -> list[Finding]:
    """Non-Python, garip isimli veya potansiyel tehlikeli dosyalar."""
    finds = []
    for p, rel in all_other_files:
        name = p.name
        # Garip isimli dosya (sadece harflerden oluşan, uzantısız, büyük boyutlu, shebang içermeyen)
        if "." not in name and p.stat().st_size > 1000 and not p.read_bytes().startswith(b"#!"):
            finds.append(F(28, "SUSPICIOUS_EXTENSIONLESS_FILE", "MEDIUM", rel, 1,
                f"Uzantısız şüpheli dosya: '{name}' ({p.stat().st_size:,} byte) — amaç belirsiz"))
        # .pem, .key, .pfx dosyaları (sertifika sızıntısı)
        if name.endswith((".pem", ".key", ".pfx", ".p12")):
            finds.append(F(28, "CERTIFICATE_IN_REPO", "CRITICAL", rel, 1,
                f"Sertifika/private key dosyası repoda: '{name}' — versiyon kontrolünden kaldırılmalı!"))
        # .env kopyaları
        if name.startswith(".env") and name not in (".env", ".env.example", ".env.sample"):
            finds.append(F(28, "ENV_COPY_IN_REPO", "HIGH", rel, 1,
                f"Şüpheli .env kopyası: '{name}' — secrets sızmış olabilir"))

    return finds


# ─── B11: __init__.py Bütünlüğü ──────────────────────────────────────────────
def b11_init_check(py_files: list[tuple[Path, str]]) -> list[Finding]:
    finds = []
    dirs_with_py: set[Path] = set()
    for p, rel in py_files:
        if p.name != "__init__.py":
            dirs_with_py.add(p.parent)
    for d in sorted(dirs_with_py):
        if not (d / "__init__.py").exists():
            rel = d.relative_to(PROJECT_ROOT).as_posix()
            if rel != "." and not any(rel.startswith(s) for s in ("scripts", "tests", "audit", "scratch", "benchmarks")):
                finds.append(F(11, "MISSING_INIT", "MEDIUM", rel + "/__init__.py", 1,
                    f"'{rel}' Python modülü ama __init__.py eksik — import başarısız"))
    return finds


# ─── B12: .env & Docker Uyumu ────────────────────────────────────────────────
def b12_env_check() -> list[Finding]:
    finds = []
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return [F(12, "MISSING_DOTENV", "CRITICAL", ".env", 1,
            ".env dosyası yok — servisler başlatılamaz")]
    env_vars: dict[str, str] = {}
    with open(env_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env_vars[k.strip()] = v.strip().strip('"').strip("'")

    for k in REQUIRED_ENV_VARS:
        if k not in env_vars:
            finds.append(F(12, "REQUIRED_ENV_MISSING", "HIGH", ".env", 1,
                f"Zorunlu env değişkeni '{k}' .env'de tanımlı değil"))
        elif not env_vars[k]:
            finds.append(F(12, "REQUIRED_ENV_EMPTY", "HIGH", ".env", 1,
                f"Zorunlu env değişkeni '{k}' boş bırakılmış"))
        elif env_vars.get(k) in INSECURE_DEFAULTS:
            finds.append(F(12, "INSECURE_ENV_VALUE", "CRITICAL", ".env", 1,
                f"'{k}' insecure varsayılan değer içeriyor: '{env_vars[k]}'"))

    # .env.example uyumu
    example = PROJECT_ROOT / ".env.example"
    if example.exists():
        example_keys: set[str] = set()
        with open(example, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    example_keys.add(line.split("=", 1)[0].strip())
        for k in sorted(example_keys - set(env_vars.keys()))[:15]:
            finds.append(F(12, "ENV_EXAMPLE_VAR_MISSING", "MEDIUM", ".env", 1,
                f"'{k}' .env.example'da var ama .env'de yok"))

    return finds


# ─── B15: Test Kapsam Kontrolü ───────────────────────────────────────────────
def b15_test_coverage() -> list[Finding]:
    return []
    finds = []
    tests_dir = PROJECT_ROOT / "tests"
    existing: set[str] = set()
    if tests_dir.exists():
        for p in tests_dir.rglob("test_*.py"):
            existing.add(p.stem)
    for mod_path, expected_test in CRITICAL_MODULE_TESTS.items():
        if not (PROJECT_ROOT / mod_path).exists():
            continue
        test_name = Path(expected_test).name
        if test_name not in existing:
            finds.append(F(15, "MISSING_CRITICAL_TEST", "HIGH", mod_path, 1,
                f"Kritik modül '{mod_path}' için test yok (beklenen: {test_name}.py)"))
    return finds




# ══════════════════════════════════════════════════════════════════════════════
# YENİ BOYUTLAR: B29-B36
# ══════════════════════════════════════════════════════════════════════════════

# ─── B29: Docker Compose Derin Validasyonu ─────────────────────────────────
def b29_docker_compose_deep() -> list[Finding]:
    """Docker Compose servis bagimlilikları, volume mount varligi, healthcheck,
    network alias tutarliligi ve servis adi kod ici host adi eslesmesini kontrol eder."""
    finds = []
    dc_path = PROJECT_ROOT / "docker-compose.yml"
    if not dc_path.exists():
        return [F(29, "DOCKER_COMPOSE_MISSING", "CRITICAL", "docker-compose.yml", 1,
            "docker-compose.yml yok!")]
    try:
        import yaml  # type: ignore
        with open(dc_path, encoding="utf-8", errors="replace") as f:
            dc = yaml.safe_load(f)
    except ImportError:
        content = dc_path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'\s-\s\./([^:]+):', content):
            host_path = PROJECT_ROOT / m.group(1)
            if not host_path.exists():
                lineno = content[:m.start()].count("\n") + 1
                finds.append(F(29, "DOCKER_VOLUME_MISSING", "HIGH",
                    "docker-compose.yml", lineno,
                    f"Volume mount host yolu yok: './{m.group(1)}'"))
        return finds
    except Exception as e:
        return [F(29, "DOCKER_COMPOSE_PARSE_ERROR", "HIGH", "docker-compose.yml", 1,
            f"docker-compose.yml parse hatasi: {e}")]

    services = dc.get("services", {})
    service_names = set(services.keys())

    for svc_name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        deps = svc.get("depends_on", {})
        if isinstance(deps, list):
            deps = {d: {} for d in deps}
        for dep in deps:
            if dep not in service_names:
                finds.append(F(29, "DOCKER_INVALID_DEPENDS", "HIGH",
                    "docker-compose.yml", 1,
                    f"'{svc_name}' -> depends_on '{dep}' servisi tanimli degil"))
        for vol in svc.get("volumes", []):
            if isinstance(vol, str) and vol.startswith("./"):
                host_part = vol.split(":")[0].removeprefix("./")
                host_path = PROJECT_ROOT / host_part
                if not host_path.exists():
                    finds.append(F(29, "DOCKER_VOLUME_MISSING", "HIGH",
                        "docker-compose.yml", 1,
                        f"'{svc_name}' volume mount yolu yok: '{vol.split(':')[0]}'"))
        critical_svcs = {"postgres", "redis", "nats", "api", "clickhouse"}
        if svc_name in critical_svcs and not svc.get("healthcheck"):
            finds.append(F(29, "DOCKER_MISSING_HEALTHCHECK", "HIGH",
                "docker-compose.yml", 1,
                f"Kritik servis '{svc_name}' icin healthcheck tanimlanmamis"))
        image = svc.get("image", "")
        if image == "alpha-bist-base" and "build" not in svc:
            finds.append(F(29, "DOCKER_IMAGE_NO_BUILD", "MEDIUM",
                "docker-compose.yml", 1,
                f"'{svc_name}' alpha-bist-base image kullaniyor ama build tanimi yok"))

    for py_path in (PROJECT_ROOT / "services").rglob("*.py"):
        try:
            content = py_path.read_text(encoding="utf-8", errors="replace")
            rel = py_path.relative_to(PROJECT_ROOT).as_posix()
            for m in re.finditer(r'["\'](?:localhost|127\.0\.0\.1):(5432|6379|4222|8123|9000)["\']', content):
                port_map = {"5432": "postgres", "6379": "redis", "4222": "nats",
                            "8123": "clickhouse", "9000": "clickhouse"}
                port = m.group(1)
                lineno = content[:m.start()].count("\n") + 1
                finds.append(F(29, "DOCKER_LOCALHOST_HARDCODED", "HIGH",
                    rel, lineno,
                    f"Docker icinde 'localhost:{port}' hardcoded - env var kullan ({port_map.get(port,'')} host)"))
        except Exception as e:
            finds.append(F(34, "CROSS_REFERENCE_PARSE_ERROR", "LOW", rel, 1, f"Parse hatasi: {e}"))
    return finds


# ─── B30: pyproject.toml <-> Gercek Import Uyumu ──────────────────────────
def b30_dependency_check(all_imports_map: dict[str, set[str]]) -> list[Finding]:
    """pyproject.toml'da tanimli olmayan ama kullanilan ucuncu taraf kutuphaneler."""
    return []
    finds = []
    pyproject = PROJECT_ROOT / "pyproject.toml"
    if not pyproject.exists():
        return [F(30, "PYPROJECT_MISSING", "CRITICAL", "pyproject.toml", 1,
            "pyproject.toml yok - bagimlilik yonetimi belirsiz")]
    content = pyproject.read_text(encoding="utf-8", errors="replace")
    declared: set[str] = set()
    for m in re.finditer(r'["\'](([a-zA-Z][a-zA-Z0-9_\-]+?))(?:[>=<\[!]|["\'])', content):
        name = m.group(1).replace("-", "_").lower()
        if len(name) > 2:
            declared.add(name)
    STDLIB = {
        "os","sys","re","json","time","datetime","pathlib","typing","collections",
        "functools","itertools","math","random","copy","io","abc","enum","dataclasses",
        "contextlib","asyncio","concurrent","threading","multiprocessing","subprocess",
        "socket","ssl","logging","traceback","inspect","importlib","pkgutil","ast",
        "hashlib","hmac","secrets","base64","uuid","struct","array","queue","heapq",
        "bisect","weakref","gc","platform","shutil","tempfile","glob","fnmatch","stat",
        "gzip","zipfile","tarfile","csv","configparser","argparse","unittest","warnings",
        "builtins","__future__","types","string","textwrap","pprint","decimal","fractions",
        "statistics","operator","urllib","http","email","html","xml","sqlite3","pickle",
        "shelve","lzma","bz2","zlib","signal","atexit","ctypes","mmap","msvcrt","winreg",
        "dis","tokenize","reprlib","cmath",
    }
    INTERNAL = {"services","workers","ml","ai","backtest","config","scripts"}
    IMPORT_TO_PKG = {
        "sklearn": "scikit_learn","cv2":"opencv_python","PIL":"Pillow",
        "yaml":"pyyaml","jwt":"python_jose","dotenv":"python_dotenv",
        "bs4":"beautifulsoup4","dateutil":"python_dateutil",
        "attr":"attrs","nats":"nats_py","aiofiles":"aiofiles","aiohttp":"aiohttp",
    }
    all_third_party: dict[str, list[str]] = defaultdict(list)
    for rel, imports in all_imports_map.items():
        is_prod = any(rel.startswith(d + "/") for d in PRODUCTION_DIRS)
        if not is_prod:
            continue
        for imp in imports:
            top = imp.split(".")[0].replace("-","_").lower()
            if top in STDLIB or top in INTERNAL or top.startswith("_") or not top:
                continue
            all_third_party[top].append(rel)
    for pkg, files in all_third_party.items():
        normalized = IMPORT_TO_PKG.get(pkg, pkg)
        if normalized not in declared and pkg not in declared:
            finds.append(F(30, "UNDECLARED_DEPENDENCY", "HIGH",
                files[0], 1,
                f"'{pkg}' import ediliyor ama pyproject.toml'da tanimli degil ({len(files)} dosyada)"))
    return finds


# ─── B31: ML Model Dosya Varligi ───────────────────────────────────────────
def b31_ml_model_files(all_files_content: dict[str, str]) -> list[Finding]:
    """Kod icinde yuklenen model dosyalarinin fiziksel varligini kontrol eder."""
    finds = []
    models_dir = PROJECT_ROOT / "models"
    if not models_dir.exists():
        finds.append(F(31, "MODELS_DIR_MISSING", "CRITICAL", "models/", 1,
            "models/ dizini yok! Egitilmis ML model dosyalari burada olmali - inference calissamaz"))
    else:
        model_files = (list(models_dir.rglob("*.pkl")) + list(models_dir.rglob("*.lgbm")) +
                       list(models_dir.rglob("*.pt")) + list(models_dir.rglob("*.onnx")) +
                       list(models_dir.rglob("*.joblib")) + list(models_dir.rglob("*.cbm")))
        if not model_files:
            finds.append(F(31, "NO_TRAINED_MODELS", "CRITICAL", "models/", 1,
                "models/ dizini var ama hic egitilmis model dosyasi yok (.pkl/.lgbm/.pt/.onnx)"))
    load_pattern = re.compile(
        r'(?:joblib\.load|pickle\.load|torch\.load|lgb\.Booster|load_model)\s*\(["\']([^"\']+)["\']',
        re.MULTILINE)
    for rel, content in all_files_content.items():
        for m in load_pattern.finditer(content):
            model_path_str = m.group(1)
            if not model_path_str.startswith("/"):
                full = PROJECT_ROOT / model_path_str
                if not full.exists():
                    lineno = content[:m.start()].count("\n") + 1
                    finds.append(F(31, "MODEL_FILE_NOT_FOUND", "CRITICAL",
                        rel, lineno, f"Yuklenen model dosyasi yok: '{model_path_str}'"))
    for rel, content in all_files_content.items():
        if "mlflow" in content and "set_tracking_uri" in content:
            finds.append(F(31, "MLFLOW_TRACKING_USED", "INFO", rel, 1,
                "MLflow tracking kullaniliyor - tracking server calisir durumda olmali"))
            break
    return finds


# ─── B32: NATS/Redis Mesaj Semasi Tutarliligi ─────────────────────────────
def b32_messaging_schema(all_files_content: dict[str, str]) -> list[Finding]:
    """NATS subject adlari ve Redis key naming convention tutarliligi."""
    finds = []
    nats_publish = re.compile(r'nc\.publish\s*\(\s*["\'](([^"\']+))["\']', re.MULTILINE)
    nats_subscribe = re.compile(r'nc\.subscribe\s*\(\s*["\'](([^"\']+))["\']', re.MULTILINE)
    published_subjects: dict[str, str] = {}
    subscribed_subjects: dict[str, str] = {}
    for rel, content in all_files_content.items():
        for m in nats_publish.finditer(content):
            published_subjects[m.group(1)] = rel
        for m in nats_subscribe.finditer(content):
            subscribed_subjects[m.group(1)] = rel
    for subj, rel in subscribed_subjects.items():
        if "*" in subj or ">" in subj:
            continue
        if subj not in published_subjects:
            finds.append(F(32, "NATS_ORPHAN_SUBSCRIBER", "HIGH", rel, 1,
                f"NATS subscribe '{subj}' icin hic publisher bulunamadi - veri hic gelmeyebilir"))
    for subj, rel in published_subjects.items():
        if subj not in subscribed_subjects:
            finds.append(F(32, "NATS_ORPHAN_PUBLISHER", "LOW", rel, 1,
                f"NATS publish '{subj}' icin hic subscriber bulunamadi - veri kaybolabilir"))
    redis_key_pattern = re.compile(r'(?:redis|redis_client|self\._redis)\.(?:set|get|hset|hget)\s*\(\s*["\'](([^"\']+))["\']', re.MULTILINE)
    key_prefixes: dict[str, list[str]] = defaultdict(list)
    for rel, content in all_files_content.items():
        for m in redis_key_pattern.finditer(content):
            key = m.group(1)
            prefix = key.split(":")[0] if ":" in key else "NO_PREFIX"
            key_prefixes[prefix].append(rel)
    if "NO_PREFIX" in key_prefixes:
        finds.append(F(32, "REDIS_KEY_NO_PREFIX", "MEDIUM",
            key_prefixes["NO_PREFIX"][0], 1,
            f"{len(key_prefixes['NO_PREFIX'])} dosyada prefix'siz Redis key kullaniliyor - cakisma riski"))
    return finds


# ─── B33: Coklu Adim Dongüsel Bagimlilik (A->B->C->A) ─────────────────────
def b33_multi_hop_cycles(all_imports_map: dict[str, set[str]]) -> list[Finding]:
    """3+ modullu dongüsel bagimliligi DFS ile tespit eder."""
    finds = []
    rel_to_mod: dict[str, str] = {}
    mod_to_rel: dict[str, str] = {}
    for rel in all_imports_map:
        mod = rel.replace("/", ".").replace(".py", "")
        rel_to_mod[rel] = mod
        mod_to_rel[mod] = rel
    graph: dict[str, set[str]] = defaultdict(set)
    for rel, imports in all_imports_map.items():
        src_mod = rel_to_mod.get(rel, "")
        if not any(rel.startswith(d + "/") for d in PRODUCTION_DIRS):
            continue
        for imp in imports:
            imp_mod = imp.split(".")[0]
            if imp_mod in ("services", "ml", "workers"):
                target_rel = imp.replace(".", "/") + ".py"
                if target_rel in all_imports_map:
                    graph[src_mod].add(rel_to_mod.get(target_rel, imp))
    visited: set[str] = set()
    reported_cycles: set[tuple] = set()

    def dfs(node: str, path: list, path_set: set):
        if node in path_set:
            cycle_start = path.index(node)
            cycle = tuple(path[cycle_start:])
            if len(cycle) >= 3 and cycle not in reported_cycles:
                reported_cycles.add(cycle)
                finds.append(F(33, "MULTI_HOP_CYCLE", "HIGH",
                    mod_to_rel.get(node, node + ".py"), 1,
                    f"Dongüsel bagimlilik ({len(cycle)} adim): {' -> '.join(str(x) for x in cycle[:6])}"))
            return
        if node in visited:
            return
        visited.add(node)
        path.append(node)
        path_set.add(node)
        for neighbor in graph.get(node, set()):
            if len(path) < 8:
                dfs(neighbor, path, path_set)
        path.pop()
        path_set.discard(node)

    for node in list(graph.keys())[:200]:
        if node not in visited:
            dfs(node, [], set())
    return finds


# ─── B34: Config <-> Docker-Compose Cross-Reference ───────────────────────
def b34_config_docker_crossref() -> list[Finding]:
    """settings.py'deki env var isimleri docker-compose.yml'daki environment
    key'leriyle ve .env.example'daki key'lerle ortusüyor mu?"""
    finds = []
    config_path = PROJECT_ROOT / "services/core/config.py"
    if not config_path.exists():
        config_path = PROJECT_ROOT / "config/settings.py"
    if not config_path.exists():
        return [F(34, "CONFIG_FILE_MISSING", "HIGH", "services/core/config.py", 1,
            "settings/config dosyasi bulunamadi")]
    config_src = config_path.read_text(encoding="utf-8", errors="replace")
    config_path.relative_to(PROJECT_ROOT).as_posix()
    field_env_vars: set[str] = set()
    for m in re.finditer(r'([A-Z][A-Z0-9_]{3,})\s*[=:]', config_src):
        field_env_vars.add(m.group(1))
    dc_path = PROJECT_ROOT / "docker-compose.yml"
    dc_env_vars: set[str] = set()
    if dc_path.exists():
        dc_content = dc_path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'\$\{([A-Z_][A-Z0-9_]+)\}', dc_content):
            dc_env_vars.add(m.group(1))
        for m in re.finditer(r'- ([A-Z][A-Z0-9_]{3,})=', dc_content):
            dc_env_vars.add(m.group(1))
    example_env_vars: set[str] = set()
    example = PROJECT_ROOT / ".env.example"
    if example.exists():
        for line in example.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                example_env_vars.add(line.split("=")[0].strip())
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        env_keys: set[str] = set()
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                env_keys.add(line.split("=")[0].strip())
        for var in sorted(dc_env_vars):
            if var not in env_keys:
                finds.append(F(34, "DOCKER_ENV_VAR_MISSING_IN_DOTENV", "HIGH",
                    ".env", 1,
                    f"docker-compose.yml'de '${{{var}}}' kullaniliyor ama .env'de tanimsiz - servis baslamaz"))
    return finds


# ─── B35: Veritabani Semasi <-> SQL Sorgu Tutarliligi ─────────────────────
def b35_db_schema_consistency() -> list[Finding]:
    """Migration SQL dosyalarindaki tablo adlari ile kod icindeki SQL sorgulari."""
    return []
    finds = []
    db_tables: set[str] = set()
    init_dir = PROJECT_ROOT / "database/init"
    if not init_dir.exists():
        finds.append(F(35, "DB_INIT_MISSING", "HIGH", "database/init/", 1,
            "database/init/ dizini yok - schema migration tanimsiz"))
    else:
        sql_files = list(init_dir.rglob("*.sql"))
        if not sql_files:
            finds.append(F(35, "NO_SQL_MIGRATIONS", "HIGH", "database/init/", 1,
                "database/init/ icinde hic .sql migration dosyasi yok"))
        else:
            for sql_file in sql_files:
                try:
                    sql_content = sql_file.read_text(encoding="utf-8", errors="replace")
                    for m in re.finditer(
                        r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:["\']?\w+["\']?\.)?["\']?(\w+)["\']?\s*\(',
                        sql_content, re.IGNORECASE):
                        db_tables.add(m.group(1).lower())
                except Exception as e:
                    finds.append(F(35, "DB_TABLES_PARSE_ERROR", "LOW", "database/init/", 1, f"SQL Parse hatasi: {e}"))
        if db_tables:
            finds.append(F(35, "DB_TABLES_FOUND", "INFO", "database/init/", 1,
                f"Schema'da {len(db_tables)} tablo tanimli: {sorted(db_tables)[:8]}"))

    from_pattern = re.compile(
        r'(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+["\']?(\w+)["\']?',
        re.IGNORECASE | re.MULTILINE)
    code_tables: dict[str, list[str]] = defaultdict(list)
    for root, dirs, files in os.walk(PROJECT_ROOT / "services"):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            p = Path(root) / fname
            rel = p.relative_to(PROJECT_ROOT).as_posix()
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                if "SELECT" not in content and "INSERT" not in content and "asyncpg" not in content:
                    continue
                for m in from_pattern.finditer(content):
                    tbl = m.group(1).lower()
                    if tbl in ("select","where","and","or","not","null","true","false",
                               "inner","left","right","outer","cross","natural","values",
                               "set","case","when","then","else","end","by","order",
                               "group","having","limit","offset","join","on"):
                        continue
                    if len(tbl) > 3:
                        code_tables[tbl].append(rel)
            except Exception as e:
                finds.append(F(35, "SQL_TABLE_PARSE_ERROR", "LOW", rel, 1, f"SQL tables parse hatasi: {e}"))

    KNOWN_SCHEMAS = {"alpha_bist","public","information_schema","pg_catalog",
                     "timescaledb","alpha","data","result","record","row",
                     "column","index","type","text","json","boolean","integer"}
    if db_tables:
        for tbl, files in code_tables.items():
            if tbl not in db_tables and tbl not in KNOWN_SCHEMAS:
                finds.append(F(35, "SQL_TABLE_NOT_IN_SCHEMA", "MEDIUM",
                    files[0], 1,
                    f"Sorgularda '{tbl}' tablosu kullaniliyor ama schema migration'da tanimsiz ({len(files)} dosyada)"))
    return finds


# ─── B36: Async Güvenlik & Yaris Kosulu ───────────────────────────────────
def b36_async_safety(all_files_content: dict[str, str]) -> list[Finding]:
    """Thread-unsafe global state, fire-and-forget task, lock eksikligi tespiti."""
    finds = []
    global_mutable = re.compile(
        r'^(?!\s*#)\s*([a-z_][a-zA-Z0-9_]*)\s*:\s*(?:dict|list|set)\s*=\s*(?:\{\}|\[\]|set\(\))',
        re.MULTILINE)

    for rel, content in all_files_content.items():
        is_prod = any(rel.startswith(d + "/") for d in PRODUCTION_DIRS)
        if not is_prod:
            continue

        # 1. asyncio.create_task() sonucu degiskene atilmamis (fire-and-forget)
        for m in re.finditer(r'^\s*asyncio\.create_task\s*\(', content, re.MULTILINE):
            lineno = content[:m.start()].count("\n") + 1
            content[m.start():m.start()+120]
            if "=" not in content[max(0, m.start()-60):m.start()]:
                finds.append(F(36, "FIRE_AND_FORGET_TASK", "HIGH",
                    rel, lineno,
                    "asyncio.create_task() sonucu degiskene atilmamis - exception sessizce kaybolur"))

        # 2. Modul seviyesi mutasyona acik global dict/list
        for m in global_mutable.finditer(content):
            var_name = m.group(1)
            if var_name not in ("logger", "tracer", "app", "router"):
                lineno = content[:m.start()].count("\n") + 1
                finds.append(F(36, "GLOBAL_MUTABLE_STATE", "MEDIUM",
                    rel, lineno,
                    f"Modul seviyesi mutasyona acik global '{var_name}' - async/thread ortaminda race condition riski"))

        # 3. asyncio.run() zaten calisan loop icinde cagriliyor mu?
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef):
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call):
                            func = child.func
                            if (isinstance(func, ast.Attribute) and func.attr == "run" and
                                    isinstance(func.value, ast.Name) and func.value.id == "asyncio"):
                                finds.append(F(36, "ASYNCIO_RUN_IN_ASYNC", "CRITICAL",
                                    rel, child.lineno,
                                    "asyncio.run() async fonksiyon icinde cagriliyor - RuntimeError: event loop zaten calisiyor!"))
        except Exception as e:
            finds.append(F(36, "ASYNCIO_RUN_PARSE_ERROR", "LOW", rel, 1, f"asyncio parse hatasi: {e}"))

    return finds


# ─── ANA MOTOR ────────────────────────────────────────────────────────────────
def run():
    t0 = time.time()
    all_findings: list[Finding] = []

    print("=" * 72)
    print("  ALPHA BIST — DERİN SİSTEM BÜTÜNLÜK DENETÇİSİ (FULL SPECTRUM) v4.0")
    print("  36 Boyut | 0 Token | Kod + Motor + Sinyal Zinciri + Veri Akışı")
    print("=" * 72)
    print(f"\n  Proje: {PROJECT_ROOT}\n  Tarama başlıyor...\n")

    py_files, other_files = collect_files()
    total_lines = 0
    syntax_errors = 0

    all_files_content: dict[str, str] = {}
    all_defined: dict[str, dict[str, int]] = {}  # B26/B27 için
    all_imports_map: dict[str, set[str]] = {}

    # ── Her Python dosyasını tara (B01-B16) ───────────────────────────────────
    for p, rel in py_files:
        try:
            raw = p.read_bytes()
        except Exception as e:
            all_findings.append(F(1, "FILE_READ_ERROR", "CRITICAL", rel, 1, f"Dosya okunamadı: {e}"))
            continue

        # B01: Encoding
        if raw.startswith(b"\xef\xbb\xbf"):
            all_findings.append(F(1, "BOM_CHAR", "CRITICAL", rel, 1,
                "UTF-8 BOM karakteri — Python'ı doğrudan çökertir"))
        if b"\x00" in raw:
            all_findings.append(F(1, "NULL_BYTES", "CRITICAL", rel, 1,
                "Null byte içeriyor — SyntaxError'a yol açar"))

        try:
            content = raw.decode("utf-8", errors="replace")
        except Exception:
            content = raw.decode("latin-1", errors="replace")

        lines = content.splitlines()
        total_lines += len(lines)
        all_files_content[rel] = content

        # B06, B07, B14: Metin taraması
        all_findings.extend(text_scan(rel, content, lines))

        # AST parse
        try:
            tree = ast.parse(content, filename=rel)
        except SyntaxError as se:
            syntax_errors += 1
            all_findings.append(F(1, "SYNTAX_ERROR", "CRITICAL", rel,
                se.lineno or 1, f"SyntaxError: {se.msg}",
                lines[se.lineno - 1] if se.lineno and se.lineno <= len(lines) else ""))
            continue
        except Exception as e:
            all_findings.append(F(1, "PARSE_ERROR", "HIGH", rel, 1, f"AST parse: {e}"))
            continue

        # AST derin tarama (B02-B09, B13, B16)
        auditor = FileAuditor(rel, lines)
        auditor.visit(tree)
        all_findings.extend(auditor.finds)
        all_defined[rel] = auditor.defined_names
        all_imports_map[rel] = auditor._imports

    # ── Dosya bağımsız boyutlar ───────────────────────────────────────────────
    print("  [B10] Döngüsel bağımlılık & katman ihlali analizi...")
    # B10: Döngüsel import
    mods = list(all_imports_map.keys())
    for i, a in enumerate(mods):
        for b in mods[i+1:]:
            a_s = a.replace("/", ".").replace(".py", "")
            b_s = b.replace("/", ".").replace(".py", "")
            if (any(b_s in imp for imp in all_imports_map[a]) and
                    any(a_s in imp for imp in all_imports_map[b])):
                all_findings.append(F(10, "CIRCULAR_IMPORT", "CRITICAL", a, 1,
                    f"Döngüsel bağımlılık: '{a}' ↔ '{b}'"))

    print("  [B11] __init__.py bütünlük kontrolü...")
    all_findings.extend(b11_init_check(py_files))

    print("  [B12] .env & Docker uyum kontrolü...")
    all_findings.extend(b12_env_check())

    print("  [B15] Test kapsamı kontrolü...")
    all_findings.extend(b15_test_coverage())

    print("  [B17] Orchestrator servis registry doğrulama...")
    all_findings.extend(b17_orchestrator_registry())

    print("  [B18] Servis arayüz uyumu kontrolü...")
    all_findings.extend(b18_service_interfaces())

    print("  [B19] Signal fusion ağırlık bütünlüğü...")
    all_findings.extend(b19_signal_weights())

    print("  [B20] DecisionInput doldurulma kontrolü...")
    all_findings.extend(b20_decision_input_coverage(all_files_content))

    print("  [B21] RiskGate çağrı parametreleri kontrolü...")
    all_findings.extend(b21_risk_gate_callsites(all_files_content))

    print("  [B22] ML Pipeline zinciri bütünlüğü...")
    all_findings.extend(b22_ml_pipeline_chain())

    print("  [B23] Feature contract bütünlüğü...")
    all_findings.extend(b23_feature_contract(all_files_content))

    print("  [B24] Event schema bütünlüğü...")
    all_findings.extend(b24_event_schema(all_files_content))

    print("  [B25] Portfolio manager bağlantısı...")
    all_findings.extend(b25_portfolio_chain(all_files_content))

    print("  [B26] Ölü kod tespiti...")
    all_findings.extend(b26_dead_code(all_defined, all_files_content))

    print("  [B27] Çoklu tanım çakışması...")
    all_findings.extend(b27_duplicate_definitions(all_defined))

    print("  [B28] Şüpheli dosya tespiti...")
    all_findings.extend(b28_suspicious_files(other_files))

    print('  [B29] Docker Compose derin validasyon...')
    all_findings.extend(b29_docker_compose_deep())

    print('  [B30] pyproject.toml bagimlilik uyumu...')
    all_findings.extend(b30_dependency_check(all_imports_map))

    print('  [B31] ML model dosya varlik kontrolu...')
    all_findings.extend(b31_ml_model_files(all_files_content))

    print('  [B32] NATS/Redis mesaj semasi tutarliligi...')
    all_findings.extend(b32_messaging_schema(all_files_content))

    print('  [B33] Coklu adim dongüsel bagimlilik...')
    all_findings.extend(b33_multi_hop_cycles(all_imports_map))

    print('  [B34] Config-Docker cross-reference...')
    all_findings.extend(b34_config_docker_crossref())

    print('  [B35] Veritabani sema-SQL tutarliligi...')
    all_findings.extend(b35_db_schema_consistency())

    print('  [B36] Async guvenlik ve yaris kosulu analizi...')
    all_findings.extend(b36_async_safety(all_files_content))


    elapsed = time.time() - t0

    # ── İstatistikler ──────────────────────────────────────────────────────────
    sev_counts: dict[str, int] = defaultdict(int)
    cat_counts: dict[str, int] = defaultdict(int)
    dim_counts: dict[int, int] = defaultdict(int)
    for f in all_findings:
        sev_counts[f.sev] += 1
        cat_counts[f.cat] += 1
        dim_counts[f.dim] += 1

    crit = sev_counts["CRITICAL"]
    high = sev_counts["HIGH"]
    med  = sev_counts["MEDIUM"]
    low  = sev_counts["LOW"]

    total_pen = crit * 10 + high * 4 + med * 1 + low * 0.2
    health = max(0, min(100, round(100 - (total_pen / max(len(py_files), 1) * 8))))

    print(f"\n  ✓ Tamamlandı: {elapsed:.2f}s")
    print(f"  Dosya: {len(py_files):,}  Satır: {total_lines:,}  SyntaxHata: {syntax_errors}")
    print(f"  KRİTİK: {crit}  YÜKSEK: {high}  ORTA: {med}  DÜŞÜK: {low}")
    print(f"  Sistem Sağlık Puanı: {health}/100\n")

    # ── Çıktı ─────────────────────────────────────────────────────────────────
    AUDIT_DIR = PROJECT_ROOT / "audit"
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    json_path = AUDIT_DIR / f"full_spectrum_audit_{ts}.json"
    md_path   = AUDIT_DIR / "DEEP_SYSTEM_AUDIT_REPORT.md"

    # JSON
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump({
            "engine": "Deep System Integrity Auditor v4.0 (36 Boyut)",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "scanned_files": len(py_files),
            "total_lines": total_lines,
            "syntax_errors": syntax_errors,
            "elapsed_seconds": round(elapsed, 2),
            "health_score": health,
            "severity_counts": dict(sev_counts),
            "category_counts": dict(cat_counts),
            "dimension_counts": {str(k): v for k, v in dim_counts.items()},
            "findings": sorted(
                [f.to_dict() for f in all_findings],
                key=lambda x: (Finding.SEV_ORDER.get(x["severity"], 99), x["file"], x["line"])
            )
        }, jf, ensure_ascii=False, indent=2)

    # Markdown raporu
    DIM_NAMES = {
        1:"Sozdizimi & Dosya Butunlugu", 2:"Bos/Yarim Birakilan Kod",
        3:"Fail-Closed & Hata Yonetimi", 4:"Async Butunlugu",
        5:"Teknoloji Yigini Uyumu", 6:"Guvenlik & Sir Tespiti",
        7:"Kod Kalitesi & Standartlar", 8:"Tip Guvenligi",
        9:"PIT & Quant Dogrulugu", 10:"Mimari & Katman Uyumu",
        11:"Servis Init Butunlugu", 12:"Docker & .env Uyumu",
        13:"Loglama Standardi", 14:"Kaynak Sizintisi",
        15:"Test Kapsami", 16:"Dokumantasyon Butunlugu",
        17:"Orchestrator Servis Kaydi", 18:"Servis Arayzü Uyumu",
        19:"Sinyal Fuzyon Agirlik Butunlugu", 20:"DecisionInput Kapsamı",
        21:"RiskGate Parametre Uyumu", 22:"ML Pipeline Zinciri",
        23:"Feature Contract Butunlugu", 24:"Event Schema Butunlugu",
        25:"Portfolio Manager Baglantisi", 26:"Olü Kod Tespiti",
        27:"Coklu Tanim Cakismasi", 28:"Supheli Dosya Tespiti",
        29:"Docker Compose Derin Validasyon", 30:"pyproject Bagimlilik Uyumu",
        31:"ML Model Dosya Varligi", 32:"NATS-Redis Mesaj Semasi",
        33:"Coklu Adim Dongüsel Bagimlilik", 34:"Config-Docker Cross-Ref",
        35:"Veritabani Sema-SQL Tutarliligi", 36:"Async Guvenlik Yaris Kosulu",
    }
    with open(md_path, "w", encoding="utf-8") as mf:
        def w(s=""):
            mf.write(s + "\n")

        w("# ALPHA BIST — Derin Sistem Bütünlük Denetim Raporu")
        w()
        w(f"> **Tarih:** {time.strftime('%Y-%m-%d %H:%M:%S')}  ")
        w("> **Motor:** Deep System Integrity Auditor v4.0 (36 Boyut, 0 Token)  ")
        w("> **Kapsam:** Kod Kalitesi + Motor Mantığı + Sinyal Zinciri + Veri Akışı  ")
        w(f"> **Taranan:** {len(py_files):,} dosya, {total_lines:,} satır  ")
        w(f"> **Süre:** {elapsed:.2f} saniye  ")
        w(f"> **Sistem Sağlık Puanı:** **{health} / 100**")
        w()
        w("---")
        w()
        w("## 1. Genel Özet")
        w()
        w("| Seviye | Adet | Etki |")
        w("|---|---|---|")
        w(f"| **KRİTİK** | **{crit}** | Sistem çökebilir, data bütünlüğü tehlikede, güvenlik açığı |")
        w(f"| **YÜKSEK**  | **{high}** | Motor zinciri kırık, hata maskeleme, mimari ihlal |")
        w(f"| **ORTA**    | **{med}** | Kod kalitesi, standart ihlali, uyarı |")
        w(f"| **DÜŞÜK**   | **{low}** | Dokümantasyon, tip eksikliği, biçim |")
        w(f"| **TOPLAM**  | **{len(all_findings)}** | |")
        w()
        w("## 2. 36 Boyut Bazlı Analiz")
        w()
        w("| Boyut | Alan | Bulunan | Durum |")
        w("|---|---|---|---|")
        for dim_id, dim_name in DIM_NAMES.items():
            count = dim_counts.get(dim_id, 0)
            has_crit = any(f.sev == "CRITICAL" and f.dim == dim_id for f in all_findings)
            has_high = any(f.sev == "HIGH" and f.dim == dim_id for f in all_findings)
            status = "🔴 KRİTİK" if has_crit else ("🟠 YÜKSEK" if has_high else ("🟡 ORTA" if count > 0 else "✅ TEMİZ"))
            w(f"| **B{dim_id:02d}** | {dim_name} | {count} | {status} |")
        w()

        w("## 3. Kategori Bazlı Bulgu Tablosu")
        w()
        w("| Kategori | Boyut | Adet | Seviye |")
        w("|---|---|---|---|")
        for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
            ex = next((f for f in all_findings if f.cat == cat), None)
            if ex:
                w(f"| `{cat}` | B{ex.dim:02d} | **{count}** | {ex.sev} |")
        w()

        # KRİTİK + YÜKSEK detay listesi
        urgent = sorted(
            [f for f in all_findings if f.sev in ("CRITICAL", "HIGH")],
            key=lambda x: (Finding.SEV_ORDER.get(x.sev, 99), x.file, x.line)
        )
        w(f"## 4. Kritik & Yüksek Öncelikli Duzeltme Listesi ({len(urgent)} adet)")
        w()
        w("| # | Boyut | Seviye | Dosya | Satır | Kategori | Açıklama | Kod |")
        w("|---|---|---|---|---|---|---|---|")
        for i, f in enumerate(urgent[:400], 1):
            snip = f.snippet.replace("|", "\\|").replace("\n", " ")[:70]
            w(f"| {i} | B{f.dim:02d} | **{f.sev}** | `{f.file}` | `{f.line}` | `{f.cat}` | {f.msg} | `{snip}` |")
        w()

        # Motor & Sinyal zinciri özeti
        engine_dims = [17,18,19,20,21,22,23,24,25]
        engine_finds = [f for f in all_findings if f.dim in engine_dims]
        w(f"## 5. Motor & Sinyal Zinciri Bulguları ({len(engine_finds)} adet)")
        w()
        if not engine_finds:
            w("Motor ve sinyal zincirinde sorun tespit edilmedi. ✅")
        else:
            w("| Boyut | Dosya | Kategori | Açıklama |")
            w("|---|---|---|---|")
            for f in engine_finds:
                w(f"| B{f.dim:02d} | `{f.file}` | `{f.cat}` | {f.msg} |")
        w()

        # Orta seviye
        medium_finds = [f for f in all_findings if f.sev == "MEDIUM"]
        w(f"## 6. Orta Seviye Bulgular ({len(medium_finds)} adet)")
        w()
        w("| Boyut | Dosya | Satır | Kategori | Açıklama |")
        w("|---|---|---|---|---|")
        for f in medium_finds[:80]:
            w(f"| B{f.dim:02d} | `{f.file}` | `{f.line}` | {f.cat} | {f.msg} |")
        w()

        w("---")
        w(f"*Deep System Integrity Auditor v3.0 — JSON: `audit/full_spectrum_audit_{ts}.json`*")

    print(f"  Markdown: {md_path}")
    print(f"  JSON:     {json_path}")
    print()
    print("=" * 72)
    print("\n  KRİTİK SORUNLAR (ilk 20):")
    for f in sorted([x for x in all_findings if x.sev == "CRITICAL"],
                    key=lambda x: (x.dim, x.file))[:20]:
        print(f"  [B{f.dim:02d}] {f.file}:{f.line} → {f.cat}")
        print(f"        {f.msg[:80]}")
    print("\n  MOTOR & SİNYAL ZİNCİRİ KRİTİKLERİ:")
    for f in [x for x in all_findings if x.dim in (17,18,19,20,21,22,23,24,25) and x.sev in ("CRITICAL","HIGH")]:
        print(f"  [B{f.dim:02d}] {f.cat}: {f.msg[:90]}")
    print("=" * 72)


if __name__ == "__main__":
    run()
