import sys, json, glob
sys.stdout.reconfigure(encoding="utf-8")
files = sorted(glob.glob("audit/full_spectrum_audit_*.json"))
latest = files[-1]
data = json.load(open(latest, encoding="utf-8"))
findings = data["findings"]
dim_counts = data.get("dimension_counts", {})

for dim in range(29, 37):
    dim_finds = [f for f in findings if f["dimension"] == dim]
    cnt = dim_counts.get(str(dim), 0)
    print(f"--- B{dim:02d} ({cnt} bulgu) ---")
    for f in dim_finds[:10]:
        print(f"  [{f['severity']}] {f['category']}: {f['message'][:95]}")

print()
print("GENEL OZET:")
sc = data.get("severity_counts", {})
print(f"  KRITIK:  {sc.get('CRITICAL',0)}")
print(f"  YUKSEK:  {sc.get('HIGH',0)}")
print(f"  ORTA:    {sc.get('MEDIUM',0)}")
print(f"  DUSUK:   {sc.get('LOW',0)}")
print(f"  Sagl1k:  {data.get('health_score','?')}/100")
print(f"  Dosya:   {data.get('scanned_files','?')}")
print(f"  Satir:   {data.get('total_lines','?')}")
