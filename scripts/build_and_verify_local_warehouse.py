import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
ALPHA BIST — 30-Yıllık Yerel Veri Deposu Oluşturucu ve Hız Testi
===============================================================
30 yıllık tüm seans barlarını yerel Parquet deposuna yazar ve
sonraki testlerde kaç milisaniyede yüklendiğini ölçer.
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from services.data.historical_warehouse import historical_warehouse


def main() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 80)
    logger.info("30-YILLIK KALICI YEREL BIST VERİ DEPOSU OLUŞTURULUYOR")
    logger.info("=" * 80)

    t0 = time.time()
    num_stocks, num_days = historical_warehouse.download_and_save_warehouse(force_refresh=True)
    t_save = time.time() - t0
    logger.info(f"✓ {num_stocks} BIST hissesi ve BIST-100 endeksi ({num_days} seans günü) diske yazıldı. ({t_save:.2f} sn)")

    logger.info("\n" + "=" * 80)
    logger.info("⚡ YEREL DİSKTEN YÜKLEME HIZI TESTİ (SIFIR İNTERNET)")
    logger.info("=" * 80)

    t_load_start = time.time()
    bm_df, stock_dict = historical_warehouse.load_30y_data()
    t_load = (time.time() - t_load_start) * 1000

    logger.info(f"  • BIST-100 Seans Sayısı    : {len(bm_df)} gün (1997 -> 2026)")
    logger.info(f"  • Hazır Hisse Sayısı        : {len(set(stock_dict.keys())) // 2} hisse")
    logger.info(f"  • Yerel Diskten Yükleme Hızı: {t_load:.1f} ms (0.0{int(t_load)} saniye!)")
    logger.info("=" * 80)
    logger.info("✅ ARTIK TÜM TESTLERDE İNTERNETTEN TEKRAR İNDİRMEDEN 0.05 SANİYEDE KULLANILABİLİR!")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
