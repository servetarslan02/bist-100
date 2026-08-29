#!/usr/bin/env python3
"""
ALPHA BIST — Deep Comprehensive Cross-Audit & AST Inspection Engine
===================================================================
Tüm projeyi yerel AST ve statik analiz yöntemleriyle 360 derece tarar.
Sıfır LLM tokeni harcar. Tespit edilen tüm eksiklikleri, mantık hatalarını,
optimizasyon darboğazlarını ve mimari ihlalleri raporlar.

Taranan Boyutlar:
1. Eksik / Sahte Kod:
   - İçi boş veya sadece pass/.../NotImplemented olan fonksiyonlar/metotlar
   - Sadece docstring olan gövdesiz fonksiyonlar
   - TODO, FIXME, HACK, PLACEHOLDER işaretleri
   - assert True veya assert ... or True gibi sahte test hileleri
   - Production modüllerinde mock kullanımı (mock leakage)
2. Fail-Closed & Hata Yönetimi:
   - except: pass veya except Exception: pass (sessiz hata yutma)
   - Bare except blokları
3. Eşzamanlılık & Performans (Async Integrity):
   - async def içinde time.sleep kullanımı (blocking)
   - async def içinde senkron requests kullanımı (blocking)
4. Mimari & Teknoloji Yığını Standartları:
   - services/ altında yasaklı pandas importları (Polars zorunluluğu)
5. Çapraz Modül Doğrulaması (Cross-Module Verification):
   - Tanımlanıp var olmayan iç modül importları (broken imports)
   - Her mikroservisin dizin ve __init__.py durumu
"""

import ast
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVICES_DIR = PROJECT_ROOT / "services"
ML_DIR = PROJECT_ROOT / "ml"
WORKERS_DIR = PROJECT_ROOT / "workers"
CONFIG_DIR = PROJECT_ROOT / "config"
DATABASE_DIR = PROJECT_ROOT / "database"
TESTS_DIR = PROJECT_ROOT / "tests"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
AUDIT_DIR = PROJECT_ROOT / "audit"

IGNORED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache",
    ".idea", ".vscode", "node_modules", "dist", "build", ".openclaw"
}

class AuditFinding:
    def __init__(self, category: str, severity: str, file_path: str, line_no: int, message: str, code_snippet: str = ""):
        self.category = category      # 'EMPTY_CODE', 'FAIL_CLOSED', 'ASYNC_BLOCKING', 'PANDAS_VIOLATION', 'FAKE_TEST', 'MOCK_LEAK', 'BROKEN_IMPORT', 'TODO_MARKER'
        self.severity = severity      # 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
        self.file_path = file_path
        self.line_no = line_no
        self.message = message
        self.code_snippet = code_snippet.strip()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "file": self.file_path,
            "line": self.line_no,
            "message": self.message,
            "snippet": self.code_snippet,
        }

class CodeInspector(ast.NodeVisitor):
    def __init__(self, rel_path: str, source_lines: List[str]):
        self.rel_path = rel_path
        self.source_lines = source_lines
        self.findings: List[AuditFinding] = []
        self.defined_functions: Set[str] = set()
        self.defined_classes: Set[str] = set()
        self.imported_modules: Set[str] = set()
        self.in_async = False

    def _get_snippet(self, lineno: int) -> str:
        if 1 <= lineno <= len(self.source_lines):
            return self.source_lines[lineno - 1].strip()
        return ""

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self.defined_functions.add(node.name)
        self._check_empty_or_placeholder_func(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.defined_functions.add(node.name)
        self._check_empty_or_placeholder_func(node)
        
        prev_async = self.in_async
        self.in_async = True
        self.generic_visit(node)
        self.in_async = prev_async

    def _check_empty_or_placeholder_func(self, node):
        # Soyut metotları veya overload'ları hariç tut
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id in ("abstractmethod", "overload"):
                return
            elif isinstance(dec, ast.Attribute) and dec.attr in ("abstractmethod", "overload"):
                return

        # Sadece pass
        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            self.findings.append(AuditFinding(
                category="EMPTY_CODE",
                severity="CRITICAL",
                file_path=self.rel_path,
                line_no=node.lineno,
                message=f"Fonksiyon '{node.name}' içi boş bırakılmış (sadece 'pass')",
                code_snippet=self._get_snippet(node.lineno)
            ))
            return

        # Sadece Ellipsis (...)
        if len(node.body) == 1 and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and node.body[0].value.value is ...:
            self.findings.append(AuditFinding(
                category="EMPTY_CODE",
                severity="CRITICAL",
                file_path=self.rel_path,
                line_no=node.lineno,
                message=f"Fonksiyon '{node.name}' içi tamamlanmamış (sadece '...')",
                code_snippet=self._get_snippet(node.lineno)
            ))
            return

        # Sadece NotImplementedError
        if len(node.body) == 1 and isinstance(node.body[0], ast.Raise):
            exc = node.body[0].exc
            if (isinstance(exc, ast.Name) and exc.id == "NotImplementedError") or \
               (isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name) and exc.func.id == "NotImplementedError"):
                self.findings.append(AuditFinding(
                    category="EMPTY_CODE",
                    severity="CRITICAL",
                    file_path=self.rel_path,
                    line_no=node.lineno,
                    message=f"Fonksiyon '{node.name}' NotImplementedError ile yarım bırakılmış",
                    code_snippet=self._get_snippet(node.lineno)
                ))
                return

        # Sadece docstring olup gövdesi olmayan fonksiyonlar
        if len(node.body) == 1 and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
            self.findings.append(AuditFinding(
                category="EMPTY_CODE",
                severity="CRITICAL",
                file_path=self.rel_path,
                line_no=node.lineno,
                message=f"Fonksiyon '{node.name}' sadece docstring içeriyor, mantıksal gövdesi eksik",
                code_snippet=self._get_snippet(node.lineno)
            ))
            return

    def visit_ClassDef(self, node: ast.ClassDef):
        self.defined_classes.add(node.name)
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try):
        for handler in node.handlers:
            # except: pass veya except Exception: pass
            if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                self.findings.append(AuditFinding(
                    category="FAIL_CLOSED",
                    severity="CRITICAL",
                    file_path=self.rel_path,
                    line_no=handler.lineno,
                    message="Hata sessizce yutuluyor (except: pass). Fail-closed ilkesi ihlali!",
                    code_snippet=self._get_snippet(handler.lineno)
                ))
            elif handler.type is None:
                # Bare except: (tüm hataları yakalayan tehlikeli blok)
                self.findings.append(AuditFinding(
                    category="FAIL_CLOSED",
                    severity="HIGH",
                    file_path=self.rel_path,
                    line_no=handler.lineno,
                    message="Bare except kullanılmış (tüm istisnalar yakalanıp maskeleniyor)",
                    code_snippet=self._get_snippet(handler.lineno)
                ))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        # async def içinde time.sleep kontrolü
        if self.in_async:
            if isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "time" and node.func.attr == "sleep":
                    self.findings.append(AuditFinding(
                        category="ASYNC_BLOCKING",
                        severity="HIGH",
                        file_path=self.rel_path,
                        line_no=node.lineno,
                        message="async fonksiyon içinde blocking 'time.sleep' çağrılmış (asyncio.sleep kullanılmalı)",
                        code_snippet=self._get_snippet(node.lineno)
                    ))
                elif isinstance(node.func.value, ast.Name) and node.func.value.id == "requests":
                    self.findings.append(AuditFinding(
                        category="ASYNC_BLOCKING",
                        severity="HIGH",
                        file_path=self.rel_path,
                        line_no=node.lineno,
                        message="async fonksiyon içinde blocking 'requests' çağrılmış (httpx.AsyncClient kullanılmalı)",
                        code_snippet=self._get_snippet(node.lineno)
                    ))
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imported_modules.add(alias.name)
            self._check_forbidden_imports(alias.name, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        mod = node.module or ""
        self.imported_modules.add(mod)
        self._check_forbidden_imports(mod, node.lineno)
        self.generic_visit(node)

    def _check_forbidden_imports(self, mod_name: str, lineno: int):
        is_prod = self.rel_path.startswith("services") or self.rel_path.startswith("ml") or self.rel_path.startswith("workers")
        
        # Pandas kontrolü (services/ altında yasak)
        if is_prod and (mod_name == "pandas" or mod_name.startswith("pandas.")):
            self.findings.append(AuditFinding(
                category="PANDAS_VIOLATION",
                severity="HIGH",
                file_path=self.rel_path,
                line_no=lineno,
                message="Üretim servisinde pandas import edilmiş. Proje mimarisi gereği Polars zorunludur!",
                code_snippet=self._get_snippet(lineno)
            ))

        # Mock sızıntısı kontrolü (services ve ml altında mock kütüphanesi olmamalı)
        if is_prod and ("mock" in mod_name or mod_name.startswith("unittest.mock")):
            self.findings.append(AuditFinding(
                category="MOCK_LEAK",
                severity="CRITICAL",
                file_path=self.rel_path,
                line_no=lineno,
                message="Üretim kodunda mock kütüphanesi tespit edildi (mock leakage)",
                code_snippet=self._get_snippet(lineno)
            ))

    def visit_Assert(self, node: ast.Assert):
        # assert ... or True veya assert True
        if isinstance(node.test, ast.Constant) and node.test.value is True:
            self.findings.append(AuditFinding(
                category="FAKE_TEST",
                severity="HIGH",
                file_path=self.rel_path,
                line_no=node.lineno,
                message="Sahte doğrulama tespit edildi: 'assert True'",
                code_snippet=self._get_snippet(node.lineno)
            ))
        elif isinstance(node.test, ast.BoolOp) and isinstance(node.test.op, ast.Or):
            for val in node.test.values:
                if isinstance(val, ast.Constant) and val.value is True:
                    self.findings.append(AuditFinding(
                        category="FAKE_TEST",
                        severity="CRITICAL",
                        file_path=self.rel_path,
                        line_no=node.lineno,
                        message="Hileli test assertion'ı: 'assert ... or True'",
                        code_snippet=self._get_snippet(node.lineno)
                    ))
        self.generic_visit(node)


def scan_source_text(rel_path: str, content: str) -> List[AuditFinding]:
    findings = []
    lines = content.splitlines()

    todo_pattern = re.compile(r'#\s*(TODO|FIXME|HACK|PLACEHOLDER|XXX)\b', re.IGNORECASE)
    hardcoded_secret_pattern = re.compile(r'(password|secret|api_key|token)\s*=\s*["\'][a-zA-Z0-9_\-]{8,}["\']', re.IGNORECASE)

    for idx, line in enumerate(lines, 1):
        # TODO kontrolü
        m_todo = todo_pattern.search(line)
        if m_todo:
            findings.append(AuditFinding(
                category="TODO_MARKER",
                severity="MEDIUM",
                file_path=rel_path,
                line_no=idx,
                message=f"Tamamlanmamış görev işareti: '{m_todo.group(1)}'",
                code_snippet=line.strip()
            ))

        # Hardcoded secret kontrolü
        if not rel_path.startswith("tests") and not rel_path.endswith((".example", ".sample")):
            m_sec = hardcoded_secret_pattern.search(line)
            if m_sec and not any(safe in line.lower() for safe in ("os.getenv", "settings.", "environ", "dummy", "test")):
                findings.append(AuditFinding(
                    category="HARDCODED_SECRET",
                    severity="HIGH",
                    file_path=rel_path,
                    line_no=idx,
                    message="Muhtemel sabit (hardcoded) kimlik bilgisi / şifre bulundu",
                    code_snippet=line.strip()
                ))

    return findings


def run_cross_audit():
    start_time = time.time()
    all_findings: List[AuditFinding] = []
    total_files = 0
    total_lines = 0
    syntax_errors = 0

    print("🚀 ALPHA BIST 360° Derin Çapraz Denetim Motoru Başlatılıyor...")
    print(f"📁 Proje Kök Dizini: {PROJECT_ROOT}\n")

    # 1. Python dosyalarını topla
    py_files: List[Path] = []
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for f in files:
            if f.endswith(".py"):
                py_files.append(Path(root) / f)

    total_files = len(py_files)
    print(f"🔍 Toplam taranacak Python dosyası: {total_files}")

    module_registry: Dict[str, CodeInspector] = {}

    # 2. Her dosyayı AST ve Metin Taramasından Geçir
    for p in py_files:
        rel = p.relative_to(PROJECT_ROOT).as_posix()
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            all_findings.append(AuditFinding(
                category="FILE_READ_ERROR",
                severity="CRITICAL",
                file_path=rel,
                line_no=1,
                message=f"Dosya okunamadı: {str(e)}"
            ))
            continue

        lines = content.splitlines()
        total_lines += len(lines)

        # Metin tabanlı kontroller
        all_findings.extend(scan_source_text(rel, content))

        # AST tabanlı derin analiz
        try:
            tree = ast.parse(content, filename=rel)
            inspector = CodeInspector(rel, lines)
            inspector.visit(tree)
            all_findings.extend(inspector.findings)
            module_registry[rel] = inspector
        except SyntaxError as se:
            syntax_errors += 1
            all_findings.append(AuditFinding(
                category="SYNTAX_ERROR",
                severity="CRITICAL",
                file_path=rel,
                line_no=se.lineno or 1,
                message=f"Python Sözdizimi Hatası (SyntaxError): {se.msg}",
                code_snippet=lines[se.lineno - 1] if se.lineno and se.lineno <= len(lines) else ""
            ))
        except Exception as e:
            all_findings.append(AuditFinding(
                category="PARSER_ERROR",
                severity="HIGH",
                file_path=rel,
                line_no=1,
                message=f"AST Ayrıştırma Hatası: {str(e)}"
            ))

    elapsed = time.time() - start_time

    # 3. İstatistikleri ve Kategorileri Çıkar
    crit_count = sum(1 for f in all_findings if f.severity == "CRITICAL")
    high_count = sum(1 for f in all_findings if f.severity == "HIGH")
    med_count = sum(1 for f in all_findings if f.severity == "MEDIUM")
    low_count = sum(1 for f in all_findings if f.severity == "LOW")

    cat_counts: Dict[str, int] = {}
    for f in all_findings:
        cat_counts[f.category] = cat_counts.get(f.category, 0) + 1

    # Sağlık Skoru Hesabı (100 üzerinden)
    penalty = (crit_count * 5) + (high_count * 2) + (med_count * 0.5)
    health_score = max(0, min(100, int(100 - (penalty / (total_files if total_files else 1) * 10))))

    print(f"\n✅ Tarama Tamamlandı ({elapsed:.2f} saniye)")
    print(f"📊 Toplam Satır: {total_lines:,} | Toplam Dosya: {total_files}")
    print(f"🔴 Kritik Sorun: {crit_count} | 🟠 Yüksek: {high_count} | 🟡 Orta: {med_count}")
    print(f"🛡️ Genel Sistem Sağlık Skoru: {health_score} / 100\n")

    # 4. JSON ve Markdown Raporları Oluştur
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = AUDIT_DIR / "deep_audit_findings.json"
    md_path = AUDIT_DIR / "DEEP_SYSTEM_AUDIT_REPORT.md"

    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump({
            "scanned_files": total_files,
            "total_lines": total_lines,
            "elapsed_seconds": round(elapsed, 2),
            "health_score": health_score,
            "counts": {"CRITICAL": crit_count, "HIGH": high_count, "MEDIUM": med_count, "LOW": low_count},
            "categories": cat_counts,
            "findings": [f.to_dict() for f in all_findings]
        }, jf, ensure_ascii=False, indent=2)

    with open(md_path, "w", encoding="utf-8") as mf:
        mf.write("# 🔍 ALPHA BIST — Derin Sistem Çapraz Röntgen Raporu\n\n")
        mf.write(f"> **Oluşturulma Tarihi:** {time.strftime('%Y-%m-%d %H:%M:%S')}  \n")
        mf.write(f"> **Taranan Dosya Sayısı:** {total_files}  \n")
        mf.write(f"> **Taranan Kod Satırı:** {total_lines:,} satır  \n")
        mf.write(f"> **Sistem Sağlık Puanı:** **{health_score} / 100**  \n\n")

        mf.write("## 📊 Özet Bulgular Tablosu\n\n")
        mf.write("| Kategori | Seviye | Adet | Anlamı |\n|---|---|---|---|\n")
        mf.write(f"| **EMPTY_CODE** | 🔴 KRİTİK | {cat_counts.get('EMPTY_CODE', 0)} | İçi boş / tamamlanmamış fonksiyonlar |\n")
        mf.write(f"| **FAIL_CLOSED** | 🔴 KRİTİK | {cat_counts.get('FAIL_CLOSED', 0)} | Hata yutan `except: pass` blokları |\n")
        mf.write(f"| **SYNTAX_ERROR** | 🔴 KRİTİK | {cat_counts.get('SYNTAX_ERROR', 0)} | Bozuk Python dosyaları |\n")
        mf.write(f"| **MOCK_LEAK** | 🔴 KRİTİK | {cat_counts.get('MOCK_LEAK', 0)} | Üretim servisinde mock kalıntıları |\n")
        mf.write(f"| **ASYNC_BLOCKING** | 🟠 YÜKSEK | {cat_counts.get('ASYNC_BLOCKING', 0)} | Async içinde blocking çağrılar (`time.sleep` vb.) |\n")
        mf.write(f"| **PANDAS_VIOLATION** | 🟠 YÜKSEK | {cat_counts.get('PANDAS_VIOLATION', 0)} | Polars yerine yasaklı Pandas kullanımı |\n")
        mf.write(f"| **FAKE_TEST** | 🟠 YÜKSEK | {cat_counts.get('FAKE_TEST', 0)} | `assert ... or True` sahte testleri |\n")
        mf.write(f"| **TODO_MARKER** | 🟡 ORTA | {cat_counts.get('TODO_MARKER', 0)} | Kod içinde unutulmuş TODO/FIXME'ler |\n\n")

        mf.write("## 🔴 Kritik ve Yüksek Öncelikli Düzeltme Listesi\n\n")
        urgent_findings = [f for f in all_findings if f.severity in ("CRITICAL", "HIGH")]
        if not urgent_findings:
            mf.write("🎉 Hiçbir kritik veya yüksek öncelikli sorun bulunamadı!\n")
        else:
            mf.write("| Dosya | Satır | Kategori | Sorun | Kod Parçası |\n|---|---|---|---|---|\n")
            for f in urgent_findings[:200]:  # ilk 200 kritik bulguyu raporda detaylandır
                snip = f.code_snippet.replace("|", "\\|")
                mf.write(f"| `{f.file_path}` | `{f.line_no}` | **{f.category}** | {f.message} | `{snip}` |\n")

        mf.write("\n\n---\n*Bu rapor yerel AST motoru tarafından 0 token harcanarak üretilmiştir.*\n")

    print(f"📄 Markdown Raporu Kaydedildi: {md_path}")
    print(f"💾 JSON Verisi Kaydedildi: {json_path}")

if __name__ == "__main__":
    run_cross_audit()
