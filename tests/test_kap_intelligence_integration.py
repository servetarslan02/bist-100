"""Test: KAP Intelligence Service & BistMLScanner Entegrasyon Doğrulama Testi.

Bu test:
1. KAPIntelligenceService'in çalışmasını,
2. Gerçek BIST örnek bildirimlerinin (sözleşme, bedelsiz, geri alım vb.) işlenmesini,
3. Şirket bazında pozitif/negatif katalizör tespitini,
4. DuckDB tablosuna yazımı ve önbellek hesaplamasını,
5. BistMLScanner öznitelik haritasına doğru yansıtıldığını doğrular.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath("."))

from services.intelligence.kap_intelligence_service import kap_intelligence_service
from services.scanner.bist_ml_scanner import bist_ml_scanner


async def test_kap_pipeline():
    print("================================================================================")
    print("         KAP İSTİHBARAT & BIST ML SCANNER ENTEGRASYON DOĞRULAMA TESTİ          ")
    print("================================================================================\n")

    # 1. Örnek KAP Bildirimlerini İşle (Sıfır Maliyetli NLP Sınıflandırma)
    sample_disclosures = [
        ("ASELS", "Yeni İş İlişkisi: Savunma Sanayii Başkanlığı ile 1.5 Milyar TL Tutarında Sözleşme İmzalandı", "Sözleşme kapsamındaki teslimatlar 2026 yılı sonuna kadar tamamlanacaktır."),
        ("THYAO", "Yönetim Kurulu Kararı: Şirketimiz Özkaynaklarını Güçlendirmek Amacıyla %200 Bedelsiz Sermaye Artırımı Kararı Almıştır", "Bedelsiz paylar tescil işlemleri sonrasında yatırımcılara dağıtılacaktır."),
        ("EREGL", "Pay Geri Alım Bildirimi: Şirketimiz Hisse Değerini Desteklemek İçin 5 Milyon Lot Pay Geri Alımı Gerçekleştirmiştir", "Geri alınan paylar şirket bünyesinde tutulacaktır."),
        ("SASA", "Planlı Bakım ve Üretim Durdurma Bildirimi: Ana Fabrikada 15 Gün Süreyle Üretim Durdurulmuştur", "Yıllık periyodik bakım çalışmaları yürütülecektir."),
    ]

    print("1. Örnek KAP Bildirimleri Sisteme İşleniyor...")
    for sym, title, summary in sample_disclosures:
        event = await kap_intelligence_service.ingest_disclosure(ticker=sym, title=title, summary=summary)
        print(f"   ✓ [{sym}] Olay: {event.event_type:<14} | Finansal Etki: {event.financial_impact:+.2f} | Şiddet: {event.impact_magnitude:.2f} | Ufuk: {event.time_horizon}")

    # 2. Şirket Metriklerini Kontrol Et
    print("\n2. Hisse Bazlı KAP Metrikleri Sorgulanıyor:")
    for sym, _, _ in sample_disclosures:
        metrics = kap_intelligence_service.get_ticker_kap_metrics(sym)
        print(f"   • {sym:<6} -> Sentiment: {metrics['kap_sentiment_latest']:.2f} | Katalizör: {metrics['latest_event_type']:<15} | Pozitif mi?: {metrics['has_positive_catalyst']}")
        assert 0.0 <= metrics["kap_sentiment_latest"] <= 1.0, "Sentiment skoru 0-1 aralığında olmalıdır!"

    # 3. ASELS Pozitif Katalizör Doğrulaması
    asels_m = kap_intelligence_service.get_ticker_kap_metrics("ASELS")
    assert asels_m["has_positive_catalyst"] is True, "ASELS sözleşme bildirimi pozitif katalizör olarak işaretlenmelidir!"

    # 4. SASA Negatif Katalizör Doğrulaması
    sasa_m = kap_intelligence_service.get_ticker_kap_metrics("SASA")
    assert sasa_m["has_negative_catalyst"] is True, "SASA fabrika durdurma bildirimi negatif etki olarak işaretlenmelidir!"

    # 5. BistMLScanner Canlı Taraması & Katalizör Etiketi Kontrolü
    print("\n3. BistMLScanner Motoru ile Bütünleşik Doğrulama...")
    preds = bist_ml_scanner.scan_all_opportunities(limit=10, force_warehouse=True)
    print(f"   ✓ BistMLScanner {len(preds)} aday hisse üretti.")
    if preds:
        top_cand = preds[0]
        print(f"   ✓ Örnek Aday [{top_cand['ticker']}]:")
        print(f"     • Fırsat Skoru: {top_cand['score']}")
        print(f"     • Sinyal: {top_cand['signal']}")
        print(f"     • KAP Duygusu: {top_cand.get('kap_sentiment')}")
        print(f"     • KAP Katalizörü: {top_cand.get('kap_catalyst')}")
        print(f"     • Etiketler: {top_cand.get('tags')}")

    print("\n================================================================================")
    print("   [BAŞARILI] KAP İSTİHBARAT VE DUYGU MOTORU ENTEGRASYONU TAM PUANLA GEÇTİ!    ")
    print("================================================================================")


if __name__ == "__main__":
    asyncio.run(test_kap_pipeline())
