from typing import Any

"""
ALPHA BIST — Model Eğitimi & Kilitli Validasyon Çalıştırıcısı
============================================================
1. 30 Yıllık Feature Matrisi Üretimi (ml/dataset_builder_30y.py)
2. LightGBM + XGBoost + CatBoost Ensemble Eğitimi (ml/ensemble_trainer.py)
3. Model Ağırlıklarının 'ml/saved_models/' Dizinine Kaydı
4. Metriklerin 'data/model_metrics.json' ve Dashboard için Hazırlanması
"""

import os
import sys
import time

import structlog

logger = structlog.get_logger(__name__)

# Windows UTF-8 Terminal desteği
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        logger.debug("Silent exception caught", exc_info=True)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ml.dataset_builder_30y import DatasetBuilder30Y
from ml.ensemble_trainer import BistEnsembleTrainer

logger = structlog.get_logger(__name__)


def main() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 105)
    logger.info("🤖 ALPHA BIST — 30-YILLIK MAKİNE ÖĞRENİMİ ENSEMBLE EĞİTİMİ (1997 - 2026)")
    logger.info("=" * 105)

    start_t = time.time()

    # 1. Feature Matrix Oluşturma
    logger.info("\n📦 1. 30 YILLIK FEATURE MATRİSİ VE KOŞULLU BEKLENTİ ÖZELLİKLERİ HESAPLANIYOR...")
    builder = DatasetBuilder30Y()
    train_df, oos_df = builder.build_feature_matrix()
    logger.info(f"  • Train Seti (1997-2023) : {len(train_df):,} satır")
    logger.info(f"  • OOS Seti   (2024-2026) : {len(oos_df):,} satır")

    # 2. Ensemble Eğitimi
    logger.info("\n🧠 2. ÇOK MODELLİ ENSEMBLE EĞİTİLİYOR (LightGBM + XGBoost + CatBoost)...")
    trainer = BistEnsembleTrainer(train_df=train_df, oos_df=oos_df)
    summary = trainer.train_all()

    elapsed = time.time() - start_t

    # 3. Sonuç Raporu
    logger.info("\n" + "=" * 105)
    logger.info(f"🏆 MODEL EĞİTİMİ VE DOĞRULAMA TAMAMLANDI! (Toplam Süre: {elapsed:.1f} saniye)")
    logger.info("=" * 105)
    logger.info("📊 ENSEMBLE PERFORMANS METRİKLERİ:")
    logger.info(f"  • OOS Information Coefficient (IC) : {summary['ensemble_metrics']['oos_information_coefficient_ic']:.4f}")
    logger.info(f"  • OOS R² Skoru                     : {summary['ensemble_metrics']['oos_r2_score']:.4f}")
    logger.info(f"  • Eğitilen Modeller                : {', '.join(summary['models_trained'])}")

    logger.info("\n🔑 EN ÖNEMLİ 5 ÖZNİTELİK (SHAP / FEATURE IMPORTANCE):")
    for idx, (feat, imp) in enumerate(list(summary["top_feature_importances"].items())[:5], 1):
        logger.info(f"  {idx}. {feat:<20} : %{imp:.2f}")

    logger.info("\n💾 Modeller başarıyla kaydedildi: 'ml/saved_models/'")
    logger.info("📁 Metrikler kaydedildi: 'data/model_metrics.json'")
    logger.info("=" * 105)


if __name__ == "__main__":
    main()
