"""
ALPHA BIST — Model Eğitimi & Kilitli Validasyon Çalıştırıcısı
============================================================
1. 30 Yıllık Feature Matrisi Üretimi (ml/dataset_builder_30y.py)
2. LightGBM + XGBoost + CatBoost Ensemble Eğitimi (ml/ensemble_trainer.py)
3. Model Ağırlıklarının 'ml/saved_models/' Dizinine Kaydı
4. Metriklerin 'data/model_metrics.json' ve Dashboard için Hazırlanması
"""

import sys
import os
import json
import time

# Windows UTF-8 Terminal desteği
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ml.dataset_builder_30y import DatasetBuilder30Y
from ml.ensemble_trainer import BistEnsembleTrainer


def main():
    print("=" * 105)
    print("🤖 ALPHA BIST — 30-YILLIK MAKİNE ÖĞRENİMİ ENSEMBLE EĞİTİMİ (1997 - 2026)")
    print("=" * 105)

    start_t = time.time()

    # 1. Feature Matrix Oluşturma
    print("\n📦 1. 30 YILLIK FEATURE MATRİSİ VE KOŞULLU BEKLENTİ ÖZELLİKLERİ HESAPLANIYOR...")
    builder = DatasetBuilder30Y()
    train_df, oos_df = builder.build_feature_matrix()
    print(f"  • Train Seti (1997-2023) : {len(train_df):,} satır")
    print(f"  • OOS Seti   (2024-2026) : {len(oos_df):,} satır")

    # 2. Ensemble Eğitimi
    print("\n🧠 2. ÇOK MODELLİ ENSEMBLE EĞİTİLİYOR (LightGBM + XGBoost + CatBoost)...")
    trainer = BistEnsembleTrainer(train_df=train_df, oos_df=oos_df)
    summary = trainer.train_all()

    elapsed = time.time() - start_t

    # 3. Sonuç Raporu
    print("\n" + "=" * 105)
    print(f"🏆 MODEL EĞİTİMİ VE DOĞRULAMA TAMAMLANDI! (Toplam Süre: {elapsed:.1f} saniye)")
    print("=" * 105)
    print("📊 ENSEMBLE PERFORMANS METRİKLERİ:")
    print(f"  • OOS Information Coefficient (IC) : {summary['ensemble_metrics']['oos_information_coefficient_ic']:.4f}")
    print(f"  • OOS R² Skoru                     : {summary['ensemble_metrics']['oos_r2_score']:.4f}")
    print(f"  • Eğitilen Modeller                : {', '.join(summary['models_trained'])}")

    print("\n🔑 EN ÖNEMLİ 5 ÖZNİTELİK (SHAP / FEATURE IMPORTANCE):")
    for idx, (feat, imp) in enumerate(list(summary["top_feature_importances"].items())[:5], 1):
        print(f"  {idx}. {feat:<20} : %{imp:.2f}")

    print("\n💾 Modeller başarıyla kaydedildi: 'ml/saved_models/'")
    print("📁 Metrikler kaydedildi: 'data/model_metrics.json'")
    print("=" * 105)


if __name__ == "__main__":
    main()
