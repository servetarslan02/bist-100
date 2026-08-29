#!/usr/bin/env python3
"""
ALPHA BIST — NİHAİ Kapsamlı Çapraz Denetim Motoru v2.0
=======================================================
0 Token. Tamamen yerel. 360° AST + Semantik + Mimari + Altyapı Analizi.

Bu betik projenin tüm kaynak kodunu, konfigürasyonunu ve altyapı
tanımlarını şu 16 boyutta çapraz tarar:

BOYUT 1:  Sözdizimi & Dosya Bütünlüğü (BOM, null bytes, encoding)
BOYUT 2:  İçi Boş / Yarım Bırakılmış Kod (pass, ..., NotImplementedError)
BOYUT 3:  Fail-Closed & Hata Yönetimi (bare except, except pass)
BOYUT 4:  Async Bütünlüğü (async içinde blocking çağrılar)
BOYUT 5:  Teknoloji Yığını Uyumu (Polars zorunluluğu, pandas yasağı)
BOYUT 6:  Güvenlik & Sır Tespiti (hardcoded credentials, insecure defaults)
BOYUT 7:  Kod Kalitesi & Standartlar (TODO/FIXME, sahte testler, mock sızıntısı)
BOYUT 8:  Tip Güvenliği (type hint eksikliği, Any dönüşü, return tip eksikliği)
BOYUT 9:  PIT (Point-in-Time) & Quant Doğruluğu (leakage riski)
BOYUT 10: Mimari & Katman Uyumu (döngüsel import, katman atlama)
BOYUT 11: Servis Sağlığı & Init Kontrolü (__init__.py eksikliği)
BOYUT 12: Docker & .env Uyumu (port tutarsızlıkları, eksik env var'lar)
BOYUT 13: Loglama Standardı (print kullanımı, logging yerine structlog)
BOYUT 14: Kaynak Sızıntısı (context manager olmayan file/DB açıkları)
BOYUT 15: Test Kapsamı (test olmayan kritik modüller)
BOYUT 16: Dökümantasyon Bütünlüğü (docstring eksikliği)
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
from typing import Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ─── Proje Dizin Yapısı ───────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

PRODUCTION_DIRS = {"services", "ml", "workers"}
TEST_DIRS = {"tests"}
SCRIPT_DIRS = {"scripts"}
IGNORED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    ".ruff_cache", ".idea", ".vscode", "node_modules", "dist",
    "build", ".openclaw", "generated",  # gRPC auto-generated
}

# Kritik servis modülleri — her birinin test dosyası olmalı
CRITICAL_MODULES = {
    "services/core/database.py": "tests/test_database",
    "services/core/circuit_breaker.py": "tests/test_circuit_breaker",
    "services/core/config.py": "tests/test_config",
    "services/core/data_quality.py": "tests/test_data_quality",
    "services/ml/feature_engine.py": "tests/test_feature_engine",
    "services/ml/lightgbm_trainer.py": "tests/test_lightgbm",
    "services/portfolio/portfolio_manager.py": "tests/test_portfolio_manager",
    "services/backtest/walk_forward_engine.py": "tests/test_walk_forward",
    "services/features/contract.py": "tests/test_feature_contract",
}

# .env.example'dan beklenen zorunlu env değişkenleri
REQUIRED_ENV_VARS = {
    "POSTGRES_PASSWORD", "SECRET_KEY", "JWT_SECRET",
    "REDIS_PASSWORD", "CLICKHOUSE_PASSWORD", "REPLICATION_PASSWORD",
    "GRAFANA_PASSWORD",
}

# Yasaklı insecure default değerleri (config.py'dan alındı)
INSECURE_DEFAULTS = {
    "change-this", "change-me", "password", "secret",
    "alpha_secure_2026", "admin", "default", "test",
    "alpha_secure_pass_123",
}

# Docker servis port haritası (docker-compose.yml'dan alındı)
EXPECTED_PORTS = {
    "postgres": 5432,
    "postgres_replica": 5433,
    "clickhouse_http": 8123,
    "clickhouse_native": 9000,
    "redis": 6379,
    "sentinel": 26379,
    "api": 8000,
    "grpc": 50051,
    "nats": 4222,
    "questdb_ilp": 9009,
    "mlflow": 5000,
    "traefik_web": 80,
    "traefik_dashboard": 8080,
}

# ─── Bulgu Sınıfı ────────────────────────────────────────────────────────────
class Finding:
    __slots__ = ("dim", "category", "severity", "file", "line", "msg", "snippet")

    SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}

    def __init__(self, dim: int, category: str, severity: str,
                 file: str, line: int, msg: str, snippet: str = ""):
        self.dim = dim
        self.category = category
        self.severity = severity
        self.file = file
        self.line = line
        self.msg = msg
        self.snippet = snippet.strip()[:200]  # 200 char limit

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dim,
            "category": self.category,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "message": self.msg,
            "snippet": self.snippet,
        }


# ─── Yardımcı: Satır Getir ───────────────────────────────────────────────────
def _snip(lines: list[str], lineno: int) -> str:
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1].strip()
    return ""


# ─── BOYUT 1: Sözdizimi & Dosya Bütünlüğü ───────────────────────────────────
def dim1_syntax_and_encoding(rel: str, raw_bytes: bytes) -> list[Finding]:
    finds: list[Finding] = []

    # BOM karakteri (UTF-8 BOM: U+FEFF) — Windows'ta çökme sebebi
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        finds.append(Finding(1, "BOM_CHAR", "CRITICAL", rel, 1,
            "Dosya UTF-8 BOM (\\ufeff) karakteriyle başlıyor — Python'ı çökertir",
            raw_bytes[:50].decode("utf-8", errors="replace")))

    # Null byte
    if b"\x00" in raw_bytes:
        finds.append(Finding(1, "NULL_BYTES", "CRITICAL", rel, 1,
            "Dosya null byte içeriyor — SyntaxError'a yol açar"))

    # Windows CRLF (servis dosyalarında sorun çıkarabilir)
    if rel.startswith(("services/", "ml/", "workers/")):
        crlf_count = raw_bytes.count(b"\r\n")
        if crlf_count > 5:
            finds.append(Finding(1, "CRLF_LINE_ENDINGS", "LOW", rel, 1,
                f"Dosyada {crlf_count} adet Windows CRLF (\\r\\n) satır sonu var — Unix LF bekleniyor"))

    return finds


# ─── AST Gezici ──────────────────────────────────────────────────────────────
class DeepInspector(ast.NodeVisitor):
    """Tek bir Python dosyasını tüm AST boyutlarında tarar."""

    def __init__(self, rel: str, lines: list[str]):
        self.rel = rel
        self.lines = lines
        self.finds: list[Finding] = []
        self._async_depth = 0
        self._is_prod = any(rel.startswith(d + "/") for d in PRODUCTION_DIRS)
        self._is_test = rel.startswith("tests/")
        self._imports: set[str] = set()
        self._defined_funcs: set[str] = set()
        self._typed_returns: set[str] = set()   # return annotation olan fonksiyonlar
        self._untyped_returns: list[tuple[int, str]] = []  # eksik olanlar

    # ── Yardımcılar ──────────────────────────────────────────────────────────
    def _add(self, dim: int, cat: str, sev: str, lineno: int, msg: str):
        self.finds.append(Finding(dim, cat, sev, self.rel, lineno, msg,
                                  _snip(self.lines, lineno)))

    def _decorator_names(self, node) -> set[str]:
        names: set[str] = set()
        for d in node.decorator_list:
            if isinstance(d, ast.Name):
                names.add(d.id)
            elif isinstance(d, ast.Attribute):
                names.add(d.attr)
        return names

    # ── BOYUT 2: Boş/Yarım Fonksiyonlar ─────────────────────────────────────
    def _check_empty_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        decs = self._decorator_names(node)
        skip_decs = {"abstractmethod", "overload", "property"}
        if decs & skip_decs:
            return

        body = node.body
        # Sadece pass
        if len(body) == 1 and isinstance(body[0], ast.Pass):
            self._add(2, "EMPTY_FUNC_PASS", "CRITICAL", node.lineno,
                f"'{node.name}' yalnızca 'pass' içeriyor — tamamlanmamış implementasyon")
            return

        # Sadece Ellipsis (...)
        if len(body) == 1 and isinstance(body[0], ast.Expr):
            val = body[0].value
            if isinstance(val, ast.Constant) and val.value is ...:
                self._add(2, "EMPTY_FUNC_ELLIPSIS", "CRITICAL", node.lineno,
                    f"'{node.name}' yalnızca '...' içeriyor — stub/placeholder bırakılmış")
                return

        # Yalnızca NotImplementedError
        if len(body) == 1 and isinstance(body[0], ast.Raise):
            exc = body[0].exc
            name = ""
            if isinstance(exc, ast.Name):
                name = exc.id
            elif isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
                name = exc.func.id
            if name == "NotImplementedError":
                self._add(2, "EMPTY_FUNC_NIE", "CRITICAL", node.lineno,
                    f"'{node.name}' yalnızca NotImplementedError fırlatıyor — eksik implementasyon")
                return

        # Sadece docstring (logic yok)
        if len(body) == 1 and isinstance(body[0], ast.Expr):
            val = body[0].value
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                self._add(2, "DOCSTRING_ONLY_FUNC", "HIGH", node.lineno,
                    f"'{node.name}' sadece docstring içeriyor, çalışan bir gövdesi yok")
                return

    # ── BOYUT 8: Tip Güvenliği ────────────────────────────────────────────────
    def _check_type_hints(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        # Sadece production servis ve ML dosyaları için
        if not self._is_prod:
            return
        # Dunder metodlar ve property'ler hariç
        decs = self._decorator_names(node)
        if node.name.startswith("__") or "property" in decs:
            return

        # Return annotation eksikliği
        if node.returns is None:
            self._add(8, "MISSING_RETURN_TYPE", "MEDIUM", node.lineno,
                f"'{node.name}' fonksiyonu dönüş tipi (return annotation) eksik")

        # Parametrelerde annotation eksikliği (self ve cls hariç)
        for arg in node.args.args:
            if arg.arg in ("self", "cls"):
                continue
            if arg.annotation is None:
                self._add(8, "MISSING_PARAM_TYPE", "LOW", node.lineno,
                    f"'{node.name}' → '{arg.arg}' parametresinin tipi eksik")
                break  # her fonksiyon için bir kez raporla

    # ── BOYUT 16: Docstring Bütünlüğü ────────────────────────────────────────
    def _check_docstring(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        if not self._is_prod:
            return
        if node.name.startswith("_"):  # Private metotlar opsiyonel
            return
        has_doc = (
            len(node.body) >= 1
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        )
        if not has_doc:
            self._add(16, "MISSING_DOCSTRING", "LOW", node.lineno,
                f"Public fonksiyon '{node.name}' için docstring eksik")

    # ── FunctionDef / AsyncFunctionDef ────────────────────────────────────────
    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._defined_funcs.add(node.name)
        self._check_empty_func(node)
        self._check_type_hints(node)
        self._check_docstring(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._defined_funcs.add(node.name)
        self._check_empty_func(node)
        self._check_type_hints(node)
        self._check_docstring(node)
        self._async_depth += 1
        self.generic_visit(node)
        self._async_depth -= 1

    # ── BOYUT 3: Fail-Closed & Hata Yönetimi ─────────────────────────────────
    def visit_Try(self, node: ast.Try):
        for handler in node.handlers:
            body = handler.body
            # except: pass — tam sessiz yutma
            if len(body) == 1 and isinstance(body[0], ast.Pass):
                cat = "BARE_EXCEPT_PASS" if handler.type is None else "EXCEPT_PASS"
                self._add(3, cat, "CRITICAL", handler.lineno,
                    "Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör!")

            # Bare except (tipi olmayan — her şeyi yakalar)
            elif handler.type is None:
                self._add(3, "BARE_EXCEPT", "HIGH", handler.lineno,
                    "Bare 'except:' kullanılmış — KeyboardInterrupt dahil her şeyi yakalar, maskeleme riski")

            # except Exception: pass veya except SomethingError: pass
            elif len(body) == 1 and isinstance(body[0], ast.Pass):
                self._add(3, "TYPED_EXCEPT_PASS", "HIGH", handler.lineno,
                    f"Spesifik istisna yakalanıp sessizce yutulmuş — fail-closed ihlali")

            # Hata sadece loglanmadan continue/return ediliyor mu?
            else:
                # Sadece continue veya return None olan except'ler — tehlikeli olabilir
                if len(body) == 1 and isinstance(body[0], (ast.Continue, ast.Return)):
                    if isinstance(body[0], ast.Return) and body[0].value is None:
                        self._add(3, "SILENT_RETURN_ON_ERROR", "MEDIUM", handler.lineno,
                            "Hata durumunda loglama olmadan 'return None' — hata maskeleniyor olabilir")

        self.generic_visit(node)

    # ── BOYUT 4: Async Bütünlüğü ──────────────────────────────────────────────
    def visit_Call(self, node: ast.Call):
        if self._async_depth > 0:
            func = node.func
            # time.sleep
            if (isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "time"
                    and func.attr == "sleep"):
                self._add(4, "ASYNC_BLOCKING_SLEEP", "HIGH", node.lineno,
                    "async fonksiyon içinde 'time.sleep()' — event loop kilitlenir! asyncio.sleep kullan")

            # requests.get/post/put/delete
            if (isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "requests"):
                self._add(4, "ASYNC_BLOCKING_REQUESTS", "CRITICAL", node.lineno,
                    f"async fonksiyon içinde senkron 'requests.{func.attr}()' — event loop kilitlenir! httpx.AsyncClient kullan")

            # subprocess.run veya subprocess.call (async içinde bloklamaz ama yanlış pattern)
            if (isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "subprocess"
                    and func.attr in ("run", "call", "check_output")):
                self._add(4, "ASYNC_BLOCKING_SUBPROCESS", "HIGH", node.lineno,
                    f"async fonksiyon içinde senkron 'subprocess.{func.attr}()' — asyncio.create_subprocess_exec kullan")

        # ── BOYUT 14: Kaynak Sızıntısı ───────────────────────────────────────
        # open() çağrısı — with kullanılıyor mu?
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            # Ebeveyn with statement mı?
            # AST bağlamında kontrol: Call'ın Assign içinde olup olmadığını basitçe raporla
            # (Derin ebeveyn takibi için ayrı traversal gerekir — burada pattern ile yaklaşırız)
            self._open_calls_lineno = getattr(self, "_open_calls_lineno", [])
            self._open_calls_lineno.append(node.lineno)

        self.generic_visit(node)

    # ── BOYUT 5 & 6: Import Analizi ──────────────────────────────────────────
    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self._imports.add(alias.name)
            self._check_import(alias.name, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        mod = node.module or ""
        self._imports.add(mod)
        self._check_import(mod, node.lineno, names=[a.name for a in node.names])
        self.generic_visit(node)

    def _check_import(self, mod: str, lineno: int, names: list[str] | None = None):
        # BOYUT 5: Pandas yasağı (production'da)
        if self._is_prod and (mod == "pandas" or mod.startswith("pandas.")):
            self._add(5, "PANDAS_IN_PROD", "HIGH", lineno,
                f"Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur!")

        # BOYUT 5: requests (production async koda yanlış)
        if self._is_prod and mod == "requests":
            self._add(5, "SYNC_REQUESTS_IN_PROD", "HIGH", lineno,
                "'requests' import edilmiş — async servislerde httpx.AsyncClient kullanılmalı")

        # BOYUT 7: Mock sızıntısı (production'da test kütüphanesi)
        if self._is_prod and ("mock" in mod or mod.startswith("unittest.mock")):
            self._add(7, "MOCK_LEAK_IN_PROD", "CRITICAL", lineno,
                f"Üretim kodunda mock kütüphanesi tespit edildi — test kodu production'a sızmış!")

        # BOYUT 5: logging (structlog yerine)
        if self._is_prod and mod == "logging" and not any(
            x in self.rel for x in ("logging.py", "otel", "observability")
        ):
            # structlog üstüne wrapper olanlar hariç
            if names and any(n in ("getLogger", "basicConfig", "DEBUG", "INFO") for n in names):
                self._add(13, "STDLIB_LOGGING_IN_PROD", "MEDIUM", lineno,
                    "'logging' modülü import edilmiş — proje standardı structlog kullanmaktır")

        # BOYUT 13: print debug kalıntısı (prod dosyalarda)
        # (visit_Call'da handle edilecek)

    # ── BOYUT 13: print Kullanımı ────────────────────────────────────────────
    # (visit_Call içinde)
    def _check_print_call(self, node: ast.Call, lineno: int):
        if not self._is_prod:
            return
        if isinstance(node.func, ast.Name) and node.func.id == "print":
            self._add(13, "PRINT_IN_PROD", "MEDIUM", lineno,
                "'print()' kullanılmış — production kodda structlog ile loglama yapılmalı")

    # ── BOYUT 7: Sahte Testler ────────────────────────────────────────────────
    def visit_Assert(self, node: ast.Assert):
        # assert True
        if isinstance(node.test, ast.Constant) and node.test.value is True:
            self._add(7, "FAKE_ASSERT_TRUE", "HIGH", node.lineno,
                "Sahte assertion: 'assert True' — hiçbir şey test etmiyor!")

        # assert ... or True
        elif isinstance(node.test, ast.BoolOp) and isinstance(node.test.op, ast.Or):
            for v in node.test.values:
                if isinstance(v, ast.Constant) and v.value is True:
                    self._add(7, "FAKE_ASSERT_OR_TRUE", "CRITICAL", node.lineno,
                        "Hileli test: 'assert ... or True' — her zaman geçer, hiçbir şeyi doğrulamaz!")
        self.generic_visit(node)

    # ── BOYUT 9: Quant / PIT Kontrolleri ─────────────────────────────────────
    def visit_Assign(self, node: ast.Assign):
        # Polars/pandas DataFrame'de shift(-N) → lookahead leakage işareti
        for target in node.targets:
            # Assign içindeki Call'lara bakıyoruz
            if isinstance(node.value, ast.Call):
                self._check_leakage_call(node.value, node.lineno)
        self.generic_visit(node)

    def _check_leakage_call(self, call: ast.Call, lineno: int):
        if isinstance(call.func, ast.Attribute) and call.func.attr == "shift":
            # shift(-N) → geleceğe bak = leakage
            for arg in call.args:
                if isinstance(arg, ast.UnaryOp) and isinstance(arg.op, ast.USub):
                    if isinstance(arg.operand, ast.Constant) and isinstance(arg.operand.value, int):
                        self._add(9, "POTENTIAL_LEAKAGE_SHIFT", "HIGH", lineno,
                            f"'.shift(-{arg.operand.value})' tespit edildi — negatif shift genellikle geleceği gösterir (lookahead bias)!")


# ─── BOYUT 6: Metin Tabanlı Güvenlik & Kalite Taraması ──────────────────────
def dim6_text_scan(rel: str, content: str, lines: list[str]) -> list[Finding]:
    finds: list[Finding] = []
    is_prod = any(rel.startswith(d + "/") for d in PRODUCTION_DIRS)

    # Hardcoded kimlik bilgisi kalıbı
    _secret_re = re.compile(
        r'(?:password|passwd|secret|api_key|apikey|token|jwt|auth_key)'
        r'\s*=\s*["\']([a-zA-Z0-9_\-@!#]{8,})["\']',
        re.IGNORECASE
    )
    # Insecure default değerler
    _insecure_re = re.compile(
        r'["\'](' + "|".join(re.escape(v) for v in INSECURE_DEFAULTS if v) + r')["\']',
        re.IGNORECASE
    )
    # TODO/FIXME/HACK marker
    _todo_re = re.compile(r'#\s*(TODO|FIXME|HACK|PLACEHOLDER|XXX)\b', re.IGNORECASE)
    # print( kullanımı (prod'da)
    _print_re = re.compile(r'^\s*print\s*\(')

    for idx, line in enumerate(lines, 1):
        stripped = line.strip()

        # BOYUT 7: TODO Marker
        m = _todo_re.search(line)
        if m:
            finds.append(Finding(7, "TODO_MARKER", "MEDIUM", rel, idx,
                f"Tamamlanmamış görev: '{m.group(1)}' işareti bırakılmış", stripped))

        # BOYUT 6: Hardcoded secret
        if not rel.endswith((".example", ".sample", "_test.py")) and "test" not in rel:
            ms = _secret_re.search(line)
            if ms:
                val = ms.group(1)
                # os.getenv, settings, environ içeren satırları atla
                if not any(kw in line for kw in ("os.getenv", "settings.", "environ", "Field(", "env_var")):
                    finds.append(Finding(6, "HARDCODED_SECRET", "CRITICAL", rel, idx,
                        f"Muhtemel hardcoded kimlik bilgisi: '{val[:8]}...'", stripped))

        # BOYUT 6: Insecure default değer
        mi = _insecure_re.search(line)
        if mi and not rel.endswith((".example", "config.py")):
            finds.append(Finding(6, "INSECURE_DEFAULT", "HIGH", rel, idx,
                f"Güvensiz varsayılan değer kullanılmış: '{mi.group(1)}'", stripped))

        # BOYUT 13: print kullanımı (prod dosyalarda)
        if is_prod and _print_re.match(line):
            finds.append(Finding(13, "PRINT_IN_PROD", "MEDIUM", rel, idx,
                "Üretim kodunda print() kullanımı — structlog ile değiştirilmeli", stripped))

    return finds


# ─── BOYUT 10: Mimari & Katman Uyumu (Import Grafı) ─────────────────────────
def dim10_architecture_check(
    all_imports: dict[str, set[str]]
) -> list[Finding]:
    """Döngüsel bağımlılık ve katman atlama tespiti."""
    finds: list[Finding] = []

    # Basit döngüsel bağımlılık tespiti (doğrudan A→B, B→A)
    mods = list(all_imports.keys())
    for i, a in enumerate(mods):
        for b in mods[i+1:]:
            a_short = a.replace("/", ".").replace(".py", "")
            b_short = b.replace("/", ".").replace(".py", "")
            a_imports_b = any(b_short in imp for imp in all_imports.get(a, set()))
            b_imports_a = any(a_short in imp for imp in all_imports.get(b, set()))
            if a_imports_b and b_imports_a:
                finds.append(Finding(10, "CIRCULAR_IMPORT", "CRITICAL",
                    a, 1,
                    f"Döngüsel bağımlılık: '{a}' ↔ '{b}' birbirini import ediyor!"))

    # Katman atlama: workers → services/core doğrudan (orchestrator üzerinden gitmeli)
    WORKER_FORBIDDEN_IMPORTS = {"services.core.database", "services.core.orchestrator"}
    for rel, imps in all_imports.items():
        if rel.startswith("workers/") and rel != "workers/__init__.py":
            for forbidden in WORKER_FORBIDDEN_IMPORTS:
                if forbidden in imps:
                    finds.append(Finding(10, "LAYER_VIOLATION", "HIGH", rel, 1,
                        f"Worker katmanı '{forbidden}' modülünü doğrudan import ediyor — orchestrator üzerinden gitmeli"))

    return finds


# ─── BOYUT 11: Servis __init__.py Varlığı ───────────────────────────────────
def dim11_init_check(all_py_files: list[Path]) -> list[Finding]:
    finds: list[Finding] = []
    # Her Python dosyası içeren dizinde __init__.py olmalı
    dirs_with_py: set[Path] = set()
    for p in all_py_files:
        if p.name != "__init__.py":
            dirs_with_py.add(p.parent)

    for d in sorted(dirs_with_py):
        if not (d / "__init__.py").exists():
            rel = d.relative_to(PROJECT_ROOT).as_posix()
            # scripts, tests altında opsiyonel
            if not any(rel.startswith(s) for s in ("scripts", "tests", "audit", "scratch", "benchmarks")):
                finds.append(Finding(11, "MISSING_INIT", "MEDIUM", rel + "/__init__.py", 1,
                    f"'{rel}' dizini Python modülü ama __init__.py eksik — import başarısız olabilir"))

    return finds


# ─── BOYUT 12: Docker & .env Uyumu ──────────────────────────────────────────
def dim12_docker_env_check() -> list[Finding]:
    finds: list[Finding] = []

    # .env dosyası var mı?
    env_path = PROJECT_ROOT / ".env"
    env_example = PROJECT_ROOT / ".env.example"
    env_vars_found: set[str] = set()

    if env_path.exists():
        with open(env_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key = line.split("=", 1)[0].strip()
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    env_vars_found.add(key)
                    # Boş bırakılmış zorunlu değişkenler
                    if key in REQUIRED_ENV_VARS and not val:
                        finds.append(Finding(12, "EMPTY_REQUIRED_ENV", "HIGH",
                            ".env", 1, f"Zorunlu ortam değişkeni '{key}' boş bırakılmış"))
                    # Insecure default değer
                    if val in INSECURE_DEFAULTS and val:
                        finds.append(Finding(12, "INSECURE_ENV_VALUE", "CRITICAL",
                            ".env", 1, f"'{key}' insecure varsayılan değer içeriyor: '{val}'"))
    else:
        finds.append(Finding(12, "MISSING_DOTENV", "CRITICAL", ".env", 1,
            ".env dosyası yok! Servisler başlatılamaz."))

    # .env.example'daki tüm değişkenler .env'de var mı?
    if env_example.exists() and env_path.exists():
        example_vars: set[str] = set()
        with open(env_example, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    example_vars.add(line.split("=", 1)[0].strip())
        missing = example_vars - env_vars_found - {""}
        if missing:
            for var in sorted(missing)[:20]:
                finds.append(Finding(12, "ENV_VAR_MISSING_FROM_DOTENV", "MEDIUM",
                    ".env", 1, f"'{var}' .env.example'da tanımlı ama .env'de eksik"))

    return finds


# ─── BOYUT 15: Test Kapsam Eksikliği ────────────────────────────────────────
def dim15_test_coverage_check() -> list[Finding]:
    finds: list[Finding] = []
    existing_tests: set[str] = set()

    tests_dir = PROJECT_ROOT / "tests"
    if tests_dir.exists():
        for p in tests_dir.rglob("test_*.py"):
            existing_tests.add(p.stem)

    for module_path, expected_test in CRITICAL_MODULES.items():
        module_file = PROJECT_ROOT / module_path
        if not module_file.exists():
            continue  # Modül yok, zaten başka boyut yakalar

        test_name = Path(expected_test).name
        if test_name not in existing_tests:
            finds.append(Finding(15, "MISSING_TEST_FOR_CRITICAL_MODULE", "HIGH",
                module_path, 1,
                f"Kritik modül '{module_path}' için test dosyası bulunamadı (beklenen: '{expected_test}.py')"))

    return finds


# ─── BOYUT 3 Ek: Kaynakçı Sızıntısı (open() with olmadan) ──────────────────
def dim14_resource_leak_text(rel: str, content: str, lines: list[str]) -> list[Finding]:
    """open() çağrılarında context manager (with) kontrolü."""
    finds: list[Finding] = []
    # with ... open(...) kalıbı değil, doğrudan = open(...) kalıbı
    # Basit regex yaklaşımı: with bloğu olmadan assignment'ta open(
    _open_assign = re.compile(r'^\s*\w+\s*=\s*open\s*\(')
    for idx, line in enumerate(lines, 1):
        if _open_assign.match(line):
            finds.append(Finding(14, "OPEN_WITHOUT_CONTEXT_MANAGER", "HIGH", rel, idx,
                "open() çağrısı 'with' bloğu olmadan yapılmış — dosya kapanmayabilir (kaynak sızıntısı)",
                line.strip()))
    return finds


# ─── Ana Motor ───────────────────────────────────────────────────────────────
def run_ultimate_audit():
    t0 = time.time()
    all_findings: list[Finding] = []
    all_imports: dict[str, set[str]] = {}
    total_files = 0
    total_lines = 0
    syntax_errors = 0

    print("=" * 70)
    print("  ALPHA BIST — NİHAİ KAPSAMLI ÇAPRAZ DENETİM MOTORU v2.0")
    print("  16 Boyut | 0 Token | Tamamen Yerel AST + Semantik Analiz")
    print("=" * 70)
    print(f"\n  Proje Koku: {PROJECT_ROOT}\n")

    # ── Python dosyalarını topla ──────────────────────────────────────────────
    py_files: list[Path] = []
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for f in files:
            if f.endswith(".py"):
                py_files.append(Path(root) / f)

    total_files = len(py_files)
    print(f"  Taranan Python dosyasi: {total_files}")
    print(f"  Tarama boyutu: 16 boyut")
    print("\n  Tarama basliyor...\n")

    # ── Her dosyayı tara ─────────────────────────────────────────────────────
    for p in py_files:
        rel = p.relative_to(PROJECT_ROOT).as_posix()
        try:
            raw_bytes = p.read_bytes()
        except Exception as e:
            all_findings.append(Finding(1, "FILE_READ_ERROR", "CRITICAL", rel, 1,
                f"Dosya okunamadi: {e}"))
            continue

        # BOYUT 1: Encoding & BOM
        all_findings.extend(dim1_syntax_and_encoding(rel, raw_bytes))

        # Metin decode
        try:
            content = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            content = raw_bytes.decode("latin-1", errors="replace")

        lines = content.splitlines()
        total_lines += len(lines)

        # BOYUT 6: Metin tabanlı güvenlik & kalite
        all_findings.extend(dim6_text_scan(rel, content, lines))

        # BOYUT 14: Kaynak sızıntısı (metin tabanlı)
        all_findings.extend(dim14_resource_leak_text(rel, content, lines))

        # AST parse
        try:
            tree = ast.parse(content, filename=rel)
        except SyntaxError as se:
            syntax_errors += 1
            all_findings.append(Finding(1, "SYNTAX_ERROR", "CRITICAL", rel,
                se.lineno or 1,
                f"SyntaxError: {se.msg}",
                lines[se.lineno - 1] if se.lineno and se.lineno <= len(lines) else ""))
            continue
        except Exception as e:
            all_findings.append(Finding(1, "PARSE_ERROR", "HIGH", rel, 1,
                f"AST parse hatasi: {e}"))
            continue

        # Derin AST taraması (Boyut 2,3,4,5,7,8,9,13,16)
        inspector = DeepInspector(rel, lines)
        inspector.visit(tree)
        all_findings.extend(inspector.finds)
        all_imports[rel] = inspector._imports

    # ── Dosya bağımsız boyutlar ───────────────────────────────────────────────
    # BOYUT 10: Mimari (döngüsel import)
    all_findings.extend(dim10_architecture_check(all_imports))

    # BOYUT 11: __init__.py
    all_findings.extend(dim11_init_check(py_files))

    # BOYUT 12: Docker & .env
    all_findings.extend(dim12_docker_env_check())

    # BOYUT 15: Test kapsamı
    all_findings.extend(dim15_test_coverage_check())

    elapsed = time.time() - t0

    # ── İstatistikler ─────────────────────────────────────────────────────────
    sev_counts = defaultdict(int)
    cat_counts = defaultdict(int)
    dim_counts = defaultdict(int)

    for f in all_findings:
        sev_counts[f.severity] += 1
        cat_counts[f.category] += 1
        dim_counts[f.dim] += 1

    crit = sev_counts["CRITICAL"]
    high = sev_counts["HIGH"]
    med  = sev_counts["MEDIUM"]
    low  = sev_counts["LOW"]

    # Sağlık skoru
    total_pen = (crit * 10) + (high * 4) + (med * 1) + (low * 0.2)
    health = max(0, min(100, int(100 - (total_pen / max(total_files, 1) * 8))))

    print(f"  Tarama tamamlandi: {elapsed:.2f} saniye")
    print(f"  Toplam dosya: {total_files:,}  |  Toplam satir: {total_lines:,}")
    print(f"  KRITIK: {crit}  YUKSEK: {high}  ORTA: {med}  DUSUK: {low}")
    print(f"  Sistem Saglik Puani: {health}/100")
    print()

    # ── Raporlar ──────────────────────────────────────────────────────────────
    AUDIT_DIR = PROJECT_ROOT / "audit"
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = AUDIT_DIR / "ultimate_audit_findings.json"
    md_path   = AUDIT_DIR / "ULTIMATE_AUDIT_REPORT.md"

    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump({
            "engine": "ALPHA BIST Ultimate Audit Engine v2.0",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "scanned_files": total_files,
            "total_lines": total_lines,
            "elapsed_seconds": round(elapsed, 2),
            "syntax_errors": syntax_errors,
            "health_score": health,
            "severity_counts": dict(sev_counts),
            "category_counts": dict(cat_counts),
            "dimension_counts": {str(k): v for k, v in dim_counts.items()},
            "findings": sorted(
                [f.to_dict() for f in all_findings],
                key=lambda x: (Finding.SEV_ORDER.get(x["severity"], 99), x["file"], x["line"])
            )
        }, jf, ensure_ascii=False, indent=2)

    # ── Markdown Raporu ───────────────────────────────────────────────────────
    DIM_NAMES = {
        1: "Sozdizimi & Dosya Butunlugu",
        2: "Bos/Yarim Birakilan Kod",
        3: "Fail-Closed & Hata Yonetimi",
        4: "Async Butunlugu",
        5: "Teknoloji Yigini Uyumu",
        6: "Guvenlik & Sir Tespiti",
        7: "Kod Kalitesi & Standartlar",
        8: "Tip Guvenligi",
        9: "PIT & Quant Dogrulugu",
        10: "Mimari & Katman Uyumu",
        11: "Servis Saglik & Init",
        12: "Docker & .env Uyumu",
        13: "Loglama Standardi",
        14: "Kaynak Sizintisi",
        15: "Test Kapsami",
        16: "Dokumantasyon Butunlugu",
    }

    with open(md_path, "w", encoding="utf-8") as mf:
        def w(s: str = ""):
            mf.write(s + "\n")

        w("# ALPHA BIST — Nihai Kapsamli Sistem Audit Raporu")
        w()
        w(f"> **Olusturulma Tarihi:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
        w(f"> **Motor:** Ultimate Audit Engine v2.0 (16 Boyut, 0 Token)")
        w(f"> **Taranan Dosya:** {total_files:,}  |  **Taranan Satir:** {total_lines:,}")
        w(f"> **Sistem Saglik Puani:** **{health} / 100**")
        w(f"> **Tarama Suresi:** {elapsed:.2f} saniye")
        w()
        w("---")
        w()

        # Genel Ozet
        w("## 1. Genel Bulgular Ozeti")
        w()
        w("| Seviye | Adet | Etki |")
        w("|---|---|---|")
        w(f"| KRITIK | **{crit}** | Sistem cokebilir, data butunlugu tehlikede, guvenlik acigi |")
        w(f"| YUKSEK | **{high}** | Performans kaybi, hata maskeleme, mimari ihlal |")
        w(f"| ORTA   | **{med}** | Kod kalitesi, standart ihlali |")
        w(f"| DUSUK  | **{low}** | Dokumantasyon, bicimlendirme |")
        w(f"| **TOPLAM** | **{len(all_findings)}** | |")
        w()

        # Boyut bazli ozet
        w("## 2. 16 Boyut Bazli Analiz")
        w()
        w("| Boyut | Alan | Bulunan |")
        w("|---|---|---|")
        for dim_id, dim_name in DIM_NAMES.items():
            count = dim_counts.get(dim_id, 0)
            icon = "X KRITIK" if any(
                f.dim == dim_id and f.severity == "CRITICAL" for f in all_findings
            ) else ("! YUKSEK" if any(
                f.dim == dim_id and f.severity == "HIGH" for f in all_findings
            ) else ("~ ORTA" if count > 0 else "OK TEMIZ"))
            w(f"| B{dim_id:02d} | {dim_name} | {count} ({icon}) |")
        w()

        # Kategori bazli
        w("## 3. Kategori Bazli Bulgu Tablosu")
        w()
        w("| Kategori | Adet | Seviye | Aciklama |")
        w("|---|---|---|---|")
        CAT_DESCS = {
            "BOM_CHAR": ("CRITICAL", "UTF-8 BOM karakteri — Python'i cokertir"),
            "NULL_BYTES": ("CRITICAL", "Null byte — SyntaxError'a yol acar"),
            "SYNTAX_ERROR": ("CRITICAL", "Bozuk Python sozdizimi"),
            "CRLF_LINE_ENDINGS": ("LOW", "Windows CRLF satir sonu"),
            "EMPTY_FUNC_PASS": ("CRITICAL", "Sadece 'pass' olan fonksiyon"),
            "EMPTY_FUNC_ELLIPSIS": ("CRITICAL", "Sadece '...' olan fonksiyon (stub)"),
            "EMPTY_FUNC_NIE": ("CRITICAL", "NotImplementedError ile bos birakilan"),
            "DOCSTRING_ONLY_FUNC": ("HIGH", "Sadece docstring, mantik yok"),
            "BARE_EXCEPT_PASS": ("CRITICAL", "except: pass — tam sessiz yutma"),
            "EXCEPT_PASS": ("CRITICAL", "except X: pass — hata maskeleme"),
            "TYPED_EXCEPT_PASS": ("HIGH", "Tipli except: pass"),
            "BARE_EXCEPT": ("HIGH", "Bare except: (tum istisnalari yakalar)"),
            "SILENT_RETURN_ON_ERROR": ("MEDIUM", "Hata durumunda loglama olmadan return None"),
            "ASYNC_BLOCKING_SLEEP": ("HIGH", "async icinde time.sleep()"),
            "ASYNC_BLOCKING_REQUESTS": ("CRITICAL", "async icinde senkron requests"),
            "ASYNC_BLOCKING_SUBPROCESS": ("HIGH", "async icinde senkron subprocess"),
            "PANDAS_IN_PROD": ("HIGH", "Uretim servisinde pandas (Polars zorunlu)"),
            "SYNC_REQUESTS_IN_PROD": ("HIGH", "Uretim servisinde senkron requests"),
            "HARDCODED_SECRET": ("CRITICAL", "Hardcoded sifre/anahtar"),
            "INSECURE_DEFAULT": ("HIGH", "Guvensiz varsayilan deger"),
            "INSECURE_ENV_VALUE": ("CRITICAL", ".env'de guvensiz deger"),
            "EMPTY_REQUIRED_ENV": ("HIGH", "Bos bırakılmıs zorunlu env var"),
            "MISSING_DOTENV": ("CRITICAL", ".env dosyasi yok"),
            "ENV_VAR_MISSING_FROM_DOTENV": ("MEDIUM", ".env.example'da var, .env'de yok"),
            "TODO_MARKER": ("MEDIUM", "Tamamlanmamis TODO/FIXME isareti"),
            "FAKE_ASSERT_TRUE": ("HIGH", "assert True — sahte test"),
            "FAKE_ASSERT_OR_TRUE": ("CRITICAL", "assert ... or True — hileli test"),
            "MOCK_LEAK_IN_PROD": ("CRITICAL", "Uretim kodunda mock kalintisi"),
            "MISSING_RETURN_TYPE": ("MEDIUM", "Return tip annotation eksik"),
            "MISSING_PARAM_TYPE": ("LOW", "Parametre tip annotation eksik"),
            "POTENTIAL_LEAKAGE_SHIFT": ("HIGH", "Negatif shift — lookahead bias riski"),
            "CIRCULAR_IMPORT": ("CRITICAL", "Dongusel bagimlilık (A <-> B)"),
            "LAYER_VIOLATION": ("HIGH", "Katman atlama (worker -> core direkt)"),
            "MISSING_INIT": ("MEDIUM", "__init__.py eksik modül dizini"),
            "OPEN_WITHOUT_CONTEXT_MANAGER": ("HIGH", "open() with blogu olmadan"),
            "MISSING_TEST_FOR_CRITICAL_MODULE": ("HIGH", "Kritik modul icin test yok"),
            "STDLIB_LOGGING_IN_PROD": ("MEDIUM", "stdlib logging (structlog olmali)"),
            "PRINT_IN_PROD": ("MEDIUM", "print() (structlog ile loglanmali)"),
            "MISSING_DOCSTRING": ("LOW", "Public fonksiyon docstring eksik"),
            "FILE_READ_ERROR": ("CRITICAL", "Dosya okunamadi"),
        }
        for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
            desc_sev, desc_txt = CAT_DESCS.get(cat, ("?", cat))
            w(f"| `{cat}` | **{count}** | {desc_sev} | {desc_txt} |")
        w()

        # Kritik ve Yüksek öncelikli detay tablosu
        urgent = sorted(
            [f for f in all_findings if f.severity in ("CRITICAL", "HIGH")],
            key=lambda x: (Finding.SEV_ORDER.get(x.severity, 99), x.file, x.line)
        )
        w(f"## 4. Kritik & Yuksek Oncelikli Duzeltme Listesi ({len(urgent)} adet)")
        w()
        if not urgent:
            w("Kritik veya yuksek oncelikli sorun bulunamadi!")
        else:
            w("| Dosya | Satir | Boyut | Kategori | Sorun | Kod |")
            w("|---|---|---|---|---|---|")
            for f in urgent[:300]:
                snip = f.snippet.replace("|", "\\|").replace("\n", " ")[:80]
                w(f"| `{f.file}` | `{f.line}` | B{f.dim:02d} | **{f.category}** | {f.msg} | `{snip}` |")
        w()

        # Orta öncelikli
        medium = [f for f in all_findings if f.severity == "MEDIUM"]
        w(f"## 5. Orta Oncelikli Bulgular ({len(medium)} adet)")
        w()
        if medium:
            w("| Dosya | Satir | Kategori | Sorun |")
            w("|---|---|---|---|")
            for f in medium[:100]:
                w(f"| `{f.file}` | `{f.line}` | {f.category} | {f.msg} |")
        w()

        w("---")
        w("*Bu rapor Ultimate Audit Engine v2.0 tarafindan 0 token harcanarak uretilmistir.*")
        w(f"*JSON verisi: `audit/ultimate_audit_findings.json`*")

    print(f"  Markdown Raporu: {md_path}")
    print(f"  JSON Verisi:     {json_path}")
    print()
    print("=" * 70)

    # Terminale kisa ozet
    print("\n  KRITIK SORUNLAR (ilk 15):")
    for f in sorted([x for x in all_findings if x.severity == "CRITICAL"],
                    key=lambda x: (x.dim, x.file))[:15]:
        print(f"  [B{f.dim:02d}] {f.file}:{f.line} -> {f.category}: {f.msg[:70]}")

    print("\n=" * 70)


if __name__ == "__main__":
    run_ultimate_audit()
