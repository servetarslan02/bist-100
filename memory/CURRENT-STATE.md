# ALPHA BIST - Mevcut Denetim Durumu
Bu dosya sistemin güncel denetim durumunu yansýtýr.

## Denetim Süreci (21.08.2026)
### 1. services/core
- **Durum:** DEVAM EDÝYOR / BEKLEMEDE
- **Bulunan Hatalar:**
  - data_quality.py: Mask-First ihlali (P1). pply_mask feature'larý null yapmak yerine direkt input raw veriyi maskeleyecek þekilde düzeltildi. Ayrýca volume sýfýr olma durumunun olume < 1000 tarafýndan ezilmesi mantýk hatasý giderildi.
  - event_bus.py: Sessiz hata yönetimi (P2). 4 adet except Exception as e: pass satýrý logger.error / logger.debug ile deðiþtirildi.
  - egime_detector.py: Rejim geçiþ olasýlýðý (transition probability) matrisinde 'LOW_VOL' eksikti, ve matris satýr toplamlarý 1.0 yapmýyordu. Düzeltildi.


- [21.08.2026] core klasÃ¶rÃ¼ndeki 64 dosyanÄ±n tamamÄ± Regex ile sessiz hata / mock patternlerine karÅŸÄ± tarandÄ±. canonical_scoring.py ve risk_gate.py iÃ§erisindeki 2 sessiz hata dÃ¼zeltildi.
- market_calendar.py, market_session.py ve regime_detector.py dosyalarÄ±nÄ±n 'Dead Code' (sistemin baÅŸka yerlerinde baÅŸka isimlerle re-implement edildiÄŸi iÃ§in kullanÄ±lmayan) kodlar olduÄŸu tespit edildi.

## 64/64 DOSYA TAM MANUEL Ä°NCELEME TAMAMLANDI (21.08.2026)
- Core altÄ±ndaki 64 dosyanÄ±n 64'Ã¼ de satÄ±r satÄ±r okundu ve kategorize edildi.
- Stop-loss uyumsuzluÄŸu giderildi: Decision Engine (%5 fallback) ile Canonical Strategy (-%6.5 hard stop, 2.5x ATR, min %4.0) eÅŸitlendi.
- RiskGate zafiyeti (negatif miktar/fiyat kontrol eksikliÄŸi) giderildi.
- Orchestrator risk bypass hatasÄ± (dict yanÄ±tÄ± ezilmesi) giderildi.
- short_selling.py dosyasÄ±nÄ±n risk_gate.py tarafÄ±ndan aktif kullanÄ±ldÄ±ÄŸÄ± kanÄ±tlandÄ± (DEAD CODE deÄŸil).
- 6 kapsamlÄ± regression testi PASS oldu.
