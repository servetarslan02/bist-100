import structlog

logger = structlog.get_logger(__name__)
import glob
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
files = sorted(glob.glob("audit/full_spectrum_audit_*.json"))
latest = files[-1]
data = json.load(open(latest, encoding="utf-8"))
findings = data["findings"]
dim_counts = data.get("dimension_counts", {})

for dim in range(29, 37):
    dim_finds = [f for f in findings if f["dimension"] == dim]
    cnt = dim_counts.get(str(dim), 0)
    logger.info(f"--- B{dim:02d} ({cnt} bulgu) ---")
    for f in dim_finds[:10]:
        logger.info(f"  [{f['severity']}] {f['category']}: {f['message'][:95]}")

logger.info()
logger.info("GENEL OZET:")
sc = data.get("severity_counts", {})
logger.info(f"  KRITIK:  {sc.get('CRITICAL', 0)}")
logger.info(f"  YUKSEK:  {sc.get('HIGH', 0)}")
logger.info(f"  ORTA:    {sc.get('MEDIUM', 0)}")
logger.info(f"  DUSUK:   {sc.get('LOW', 0)}")
logger.info(f"  Sagl1k:  {data.get('health_score', '?')}/100")
logger.info(f"  Dosya:   {data.get('scanned_files', '?')}")
logger.info(f"  Satir:   {data.get('total_lines', '?')}")
