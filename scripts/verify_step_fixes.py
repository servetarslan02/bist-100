
import httpx

client = httpx.Client(base_url="http://localhost:8000", timeout=30.0)

# 1. Genel Liste (Dual sort: Score & Expected Return)
r_all = client.get("/api/v1/scanner/signals?limit=10")
print("ALL STATUS:", r_all.status_code)
sigs = r_all.json().get("signals", [])
print(f"Total fetched: {len(sigs)}")
print("TOP 5 SORTED BY SCORE & RETURN:")
for s in sigs[:5]:
    t = s.get("ticker", "")
    sc = s.get("score", 0)
    ret = s.get("expected_return_pct", 0)
    cat = s.get("spec_category", "")
    stype = s.get("signal_type", "")
    print(f"  {t:<7} | Score: {sc:<4} | ExpReturn: +%{ret:<4}% | Category: {cat:<15} | Type: {stype}")

# 2. Filter: VOLUME_BREAKOUT
r_vb = client.get("/api/v1/scanner/signals?category=VOLUME_BREAKOUT")
sigs_vb = r_vb.json().get("signals", [])
print(f"\nVOLUME_BREAKOUT count: {len(sigs_vb)}")
if sigs_vb:
    print(f"  Sample: {sigs_vb[0]['ticker']} -> cat: {sigs_vb[0]['spec_category']}, type: {sigs_vb[0]['signal_type']}")

# 3. Filter: HIGH_CONVICTION
r_hc = client.get("/api/v1/scanner/signals?category=HIGH_CONVICTION")
sigs_hc = r_hc.json().get("signals", [])
print(f"HIGH_CONVICTION count: {len(sigs_hc)}")
if sigs_hc:
    print(f"  Sample: {sigs_hc[0]['ticker']} -> cat: {sigs_hc[0]['spec_category']}, type: {sigs_hc[0]['signal_type']}")

# 4. Filter: PULLBACK_BOUNCE
r_pb = client.get("/api/v1/scanner/signals?category=PULLBACK_BOUNCE")
sigs_pb = r_pb.json().get("signals", [])
print(f"PULLBACK_BOUNCE count: {len(sigs_pb)}")
if sigs_pb:
    print(f"  Sample: {sigs_pb[0]['ticker']} -> cat: {sigs_pb[0]['spec_category']}, type: {sigs_pb[0]['signal_type']}")

# 5. Filter: MOMENTUM_LEADER
r_ml = client.get("/api/v1/scanner/signals?category=MOMENTUM_LEADER")
sigs_ml = r_ml.json().get("signals", [])
print(f"MOMENTUM_LEADER count: {len(sigs_ml)}")
if sigs_ml:
    print(f"  Sample: {sigs_ml[0]['ticker']} -> cat: {sigs_ml[0]['spec_category']}, type: {sigs_ml[0]['signal_type']}")
