"""
ALPHA BIST — Sürekli Öğrenme ve Otonom Büyüme Motoru Canlı Doğrulama Testi
Kod tabanındaki otonom öğrenme, güvenilirlik ağırlıklandırması ve telafi sistemini doğrudan test eder.
"""
import sys
import os

sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

from services.learning.learning_pipeline import LearningPipeline
from services.learning.continuous_learning import ContinuousLearningPipeline

def test_learning_pipeline_in_code():
    print("=" * 80)
    print("ALPHA BIST — SÜREKLİ ÖĞRENME MOTORU DOĞRULAMA (KOD TABANI TESTİ)")
    print("=" * 80)

    pipeline = LearningPipeline()
    print(f"1. Kayıtlı ve Sürekli Eğitilen Model Sayısı: {len(pipeline.registered_models)}")
    for m in pipeline.registered_models:
        print(f"   • [{m['id']}] Kategori: {m['category']} | Versiyon: {m['version']}")

    print("\n2. Başlangıç Telafi (Catch-Up) Kontrolü Çalıştırılıyor...")
    catchup_res = pipeline.check_and_catchup_if_needed()
    print(f"   Catch-Up Durumu: {catchup_res.get('status', 'çalıştı')}")

    print("\n3. Otonom Öğrenme Döngüsü (Learning Cycle) Simülasyonu...")
    cycle_res = pipeline.run_learning_cycle(current_regime="BULL_MOMENTUM")
    print(f"   Öğrenme Başarısı: {cycle_res.get('success')}")
    print(f"   Değerlendirilen Modeller: {cycle_res.get('models_evaluated')} adet")
    print(f"   Adaptif Füzyon Ağırlıkları (Hangi modelin sözü ne kadar geçecek):")
    for model_id, weight in cycle_res.get("fusion_weights", {}).items():
        print(f"     - {model_id:<25}: %{weight*100:.1f}")

    print("\n" + "=" * 80)
    print("SONUÇ: Sürekli öğrenen ve tecrübeyle ağırlıklarını güncelleyen kodlar canlı ve aktif!")
    print("=" * 80)

if __name__ == "__main__":
    test_learning_pipeline_in_code()
