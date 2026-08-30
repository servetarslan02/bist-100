from collections import Counter

from services.scanner.bist_ml_scanner import bist_ml_scanner

sigs = bist_ml_scanner.scan_all_opportunities(limit=50)
cats = Counter(s.get('signal_type') for s in sigs)
print("================================================================================")
print("         KATEGORİ VE FİLTRE DAĞILIMI TESTİ (50 ADET SEÇKİN SİNYAL)              ")
print("================================================================================")
print("KATEGORİ DAĞILIMI:", dict(cats))
print("-" * 80)
for s in sigs[:10]:
    t = s.get('ticker')
    strat = s.get('signal_type')
    sc = s.get('score')
    sig = s.get('signal')
    is_high = s.get('is_high_conviction')
    print(f"{t:<7} | Strateji: {strat:<18} | Skor: {sc} | Yüksek Güven: {is_high} | {sig}")
print("================================================================================")
