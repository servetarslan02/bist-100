"""
ALPHA BIST — Derinlemesine Çapraz Sistem Denetim Aracı (Deep System Cross-Audit)
Tüm kod tabanını baştan aşağı tarayarak metodolojik, matematiksel, mimari ve finansal YANLIŞLARI tespit eder.
"""

import glob
import re
import sys

import structlog

logger = structlog.get_logger(__name__)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

findings = {
    "look_ahead_bias": [],
    "global_normalization_leakage": [],
    "unrealistic_execution_assumptions": [],
    "hardcoded_magic_numbers": [],
    "timezone_inconsistencies": [],
    "silent_error_swallowing": [],
    "duplicate_conflicting_engines": [],
    "risk_math_flaws": [],
}

logger.info("=" * 80)
logger.info("ALPHA BIST — DERİNLEMESİNE ÇAPRAZ SİSTEM VE METODOLOJİ DENETİMİ")
logger.info("=" * 80)

# 1. Dosyaları tara
services_files = glob.glob("services/**/*.py", recursive=True)
backtest_files = glob.glob("backtest/**/*.py", recursive=True) + glob.glob("services/backtest/**/*.py", recursive=True)
all_files = list(set(services_files + backtest_files))

for filepath in all_files:
    try:
        with open(filepath, encoding="utf-8", errors="ignore") as f:
            content = f.read()
            lines = content.splitlines()

        # Check 1: Look-Ahead Bias / Shifting without lag
        if "feature" in filepath or "indicator" in filepath or "motor" in filepath:
            for i, line in enumerate(lines, 1):
                if re.search(r"\.shift\s*\(\s*-\s*\d+\s*\)", line):
                    if "target" not in filepath and "label" not in filepath:
                        findings["look_ahead_bias"].append((filepath, i, line.strip()))

        # Check 2: Global Normalization Leakage (fit_transform on entire dataframe)
        for i, line in enumerate(lines, 1):
            if "fit_transform" in line and "train" not in line.lower() and "split" not in line.lower():
                if "feature" in filepath or "ml" in filepath:
                    findings["global_normalization_leakage"].append((filepath, i, line.strip()))

        # Check 3: Silent Error Swallowing (except: pass without log)
        for i, line in enumerate(lines, 1):
            if re.search(r"except\s*(\w+)?\s*:\s*pass\s*$", line.strip()):
                findings["silent_error_swallowing"].append((filepath, i, line.strip()))

        # Check 4: Timezone Inconsistencies (naive datetime.now() without tz in financial paths)
        for i, line in enumerate(lines, 1):
            if "datetime.now()" in line and "timezone" not in line and "_TZ" not in line:
                if any(k in filepath for k in ["market", "order", "session", "execution", "trade"]):
                    findings["timezone_inconsistencies"].append((filepath, i, line.strip()))

        # Check 5: Execution Assumptions (filling 100% order immediately without volume/depth check)
        if "execution" in filepath or "paper" in filepath or "backtest" in filepath:
            for i, line in enumerate(lines, 1):
                if "fill_price" in line or "executed_qty" in line:
                    if "volume" not in content and "liquidity" not in content:
                        findings["unrealistic_execution_assumptions"].append((filepath, i, line.strip()))

    except Exception:
        logger.warning("Caught Exception in module_level", exc_info=True)

# Raporla
logger.info("\n1. 🔍 GELECEĞİ GÖRME & LOOK-AHEAD BİAS ŞÜPHELERİ:")
logger.info(f"Toplam Tespit: {len(findings['look_ahead_bias'])}")
for f, l, code in findings["look_ahead_bias"][:10]:
    logger.info(f"  - [{f}:{l}] -> {code}")

logger.info("\n2. 🔍 GLOBAL NORMALİZASYON SIZINTISI (Veri Sızıntısı - Normalization Leakage):")
logger.info(f"Toplam Tespit: {len(findings['global_normalization_leakage'])}")
for f, l, code in findings["global_normalization_leakage"][:10]:
    logger.info(f"  - [{f}:{l}] -> {code}")

logger.info("\n3. 🔍 SESSİZ HATA YUTMA & FAIL-OPEN ZAFİYETLERİ (except: pass):")
logger.info(f"Toplam Tespit: {len(findings['silent_error_swallowing'])}")
for f, l, code in findings["silent_error_swallowing"][:15]:
    logger.info(f"  - [{f}:{l}] -> {code}")

logger.info("\n4. 🔍 ZAMAN DİLİMİ TUTARSIZLIKLARI (Naive datetime in Financial Paths):")
logger.info(f"Toplam Tespit: {len(findings['timezone_inconsistencies'])}")
for f, l, code in findings["timezone_inconsistencies"][:10]:
    logger.info(f"  - [{f}:{l}] -> {code}")

logger.info("=" * 80)
