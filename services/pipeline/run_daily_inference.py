"""ALPHA BIST — Günlük Model Çıkarım (Inference) ve Portföy Sinyal Üretim Hattı.

Arka planda veya zamanlayıcı (scheduler) ile periyodik olarak çalışarak:
1. Son 1 yıllık piyasa verisini çeker.
2. AlphaEngine Optuna eğitim döngüsünü yürütür.
3. Güncel tarih için en yüksek potansiyele sahip hisse senetlerini tahmin eder.
4. RiskManager ile makro rejim analizi yaparak sonuçları paper trading portföy tablosuna kaydeder.
"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import orjson
import polars as pl
import structlog

from services.core.alpha_engine import AlphaEngine
from services.core.database import pg_execute
from services.core.risk_manager import RiskManager

logger = structlog.get_logger(__name__)

# Yapılandırma Sabitleri
DEFAULT_LOOKBACK_DAYS: int = 400
MIN_COMMON_DATES_THRESHOLD: int = 200
DEFAULT_TOP_PICKS: int = 10
REGIME_CASH_THRESHOLD: float = 1.0


def run_alpha_engine_sync() -> dict[str, Any] | None:
    """Arka planda AlphaEngine model çıkarımını senkronize çalıştırıp veritabanına kaydeder.

    Piyasa verilerini çeker, Optuna hiperparametre eğitimi yapar, bugünün
    en yüksek skorlu hisse seçimlerini belirler, piyasa rejimini analiz eder
    ve sonuçları PostgreSQL 'paper_trade_portfolio' tablosuna yazar.

    Returns:
        dict[str, Any] | None: Çıkarım özeti (target_date, top_picks, is_cash_regime) veya
            veri yetersiz ise None döner.

    Raises:
        RuntimeError: Kritik veritabanı veya hesaplama hatası oluştuğunda.
    """
    logger.info("AlphaEngine gunluk cikarim dongusu baslatiliyor")

    engine = AlphaEngine()
    rm = RiskManager()

    # 1. Veri Çek (Son 400 günlük veri yeterlidir)
    today = datetime.now(UTC)
    start_date = (today - timedelta(days=DEFAULT_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")

    logger.info("Piyasa verisi cekiliyor", start_date=start_date, end_date=end_date)
    market_data, bm_df, sector_map = engine.fetch_data(start_date, end_date)

    # Eğer piyasa verisi yoksa veya çok eksikse çık
    if bm_df is None or bm_df.empty:
        logger.warning("Benchmark verisi bos, cikarim durduruldu")
        return None

    # Son eğitim döngüsü için ortak tarih kontrolü
    common_dates = list(sorted([d.strftime("%Y-%m-%d") for d in bm_df.index]))
    if len(common_dates) < MIN_COMMON_DATES_THRESHOLD:
        logger.warning(
            "Yetersiz ortak tarih verisi",
            current_count=len(common_dates),
            required=MIN_COMMON_DATES_THRESHOLD,
        )
        return None

    train_start = common_dates[0]
    train_end = common_dates[-2]
    target_date = common_dates[-1]

    # Optuna eğitimi
    logger.info("Model egitimi baslatiliyor", train_start=train_start, train_end=train_end)
    success = engine.train(market_data, bm_df, sector_map, train_start, train_end, optimize=True)

    if not success:
        logger.error("AlphaEngine egitimi basarisiz oldu")
        return None

    # Tahmin (Bugün için)
    logger.info("Hedef tarih icin tahmin uretiliyor", target_date=target_date)
    preds = engine.predict(market_data, bm_df, sector_map, target_date)
    top_picks = preds[:DEFAULT_TOP_PICKS]

    # Makro Rejim Kontrolü
    t_date = pl.Series([target_date])
    regime = rm.get_market_regime(bm_df, t_date)
    is_cash = float(regime) < REGIME_CASH_THRESHOLD

    # JSON yapısını hazırla
    tickers_json = orjson.dumps(top_picks).decode()

    # DB'ye kaydet
    async def save_to_db() -> None:
        """Üretilen günlük portföy sinyallerini asenkron olarak veritabanına yazar.

        Raises:
            Exception: Veritabanı sorgusu başarısız olursa.
        """
        query = """
            INSERT INTO paper_trade_portfolio (target_date, tickers, is_cash_regime)
            VALUES ($1, $2, $3)
        """
        try:
            parsed_target_date = date.fromisoformat(target_date[:10])
        except Exception:
            parsed_target_date = datetime.strptime(target_date[:10], "%Y-%m-%d").date()
        await pg_execute(query, parsed_target_date, tickers_json, is_cash)
        logger.info(
            "Portfoy sinyalleri veritabanina kaydedildi",
            target_date=target_date,
            is_cash=is_cash,
            top_picks_count=len(top_picks),
        )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(save_to_db())
        else:
            loop.run_until_complete(save_to_db())
    except Exception:
        asyncio.run(save_to_db())

    return {
        "status": "SUCCESS",
        "target_date": target_date,
        "top_picks": top_picks,
        "is_cash_regime": is_cash,
    }


__all__ = [
    "DEFAULT_LOOKBACK_DAYS",
    "DEFAULT_TOP_PICKS",
    "MIN_COMMON_DATES_THRESHOLD",
    "REGIME_CASH_THRESHOLD",
    "run_alpha_engine_sync",
]


if __name__ == "__main__":
    run_alpha_engine_sync()
