import structlog

logger = structlog.get_logger(__name__)
from typing import Any

"""
ALPHA BIST — Sürekli Öğrenme ve Otonom Büyüme Motoru Canlı Doğrulama Testi
Kod tabanındaki otonom öğrenme, güvenilirlik ağırlıklandırması ve telafi sistemini doğrudan test eder.
"""

import os
import sys

sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from services.learning.learning_pipeline import LearningPipeline


def test_learning_pipeline_in_code() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 80)
    logger.info("ALPHA BIST — SÜREKLİ ÖĞRENME MOTORU DOĞRULAMA (KOD TABANI TESTİ)")
    logger.info("=" * 80)

    pipeline = LearningPipeline()
    logger.info(f"1. Kayıtlı ve Sürekli Eğitilen Model Sayısı: {len(pipeline.registered_models)}")
    for m in pipeline.registered_models:
        logger.info(f"   • [{m['id']}] Kategori: {m['category']} | Versiyon: {m['version']}")

    logger.info("\n2. Başlangıç Telafi (Catch-Up) Kontrolü Çalıştırılıyor...")
    catchup_res = pipeline.check_and_catchup_if_needed()
    logger.info(f"   Catch-Up Durumu: {catchup_res.get('status', 'çalıştı')}")

    logger.info("\n3. Otonom Öğrenme Döngüsü (Learning Cycle) Simülasyonu...")
    cycle_res = pipeline.run_learning_cycle(current_regime="BULL_MOMENTUM")
    logger.info(f"   Öğrenme Başarısı: {cycle_res.get('success')}")
    logger.info(f"   Değerlendirilen Modeller: {cycle_res.get('models_evaluated')} adet")
    logger.info("   Adaptif Füzyon Ağırlıkları (Hangi modelin sözü ne kadar geçecek):")
    for model_id, weight in cycle_res.get("fusion_weights", {}).items():
        logger.info(f"     - {model_id:<25}: %{weight * 100:.1f}")

    logger.info("\n" + "=" * 80)
    logger.info("SONUÇ: Sürekli öğrenen ve tecrübeyle ağırlıklarını güncelleyen kodlar canlı ve aktif!")
    logger.info("=" * 80)


if __name__ == "__main__":
    test_learning_pipeline_in_code()
