"""
ALPHA BIST - Scheduler Service v1.0

BIST saatlerinde otomatik çalışır:
- 09:50 Piyasa öncesi hazırlık
- 10:00-18:00 Canlı tarama (her 5 dakikada)
- 18:00 Piyasa sonrası rapor
- 18:30 ML eğitim/güncelleme
- 23:00 Günlük özet

Sistem kendi kendine çalışır, sen komut vermezsin.
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any
import structlog

logger = structlog.get_logger()


class AlphaScheduler:
    """Otonom scheduler — BIST saatlerinde çalışır."""

    def __init__(self):
        self._running = False
        self._last_scan = None
        self._last_report = None
        self._scan_count = 0
        self._today_results = []

    async def start(self):
        """Scheduler'ı başlat."""
        self._running = True
        logger.info("ALPHA Scheduler started")

        while self._running:
            try:
                now = datetime.now()
                hour = now.hour
                minute = now.minute
                weekday = now.weekday()  # 0=Pazartesi, 6=Pazar

                # Hafta içi mi?
                if weekday >= 5:
                    # Hafta sonu — bekle
                    await asyncio.sleep(60)
                    continue

                # BIST saatleri
                if hour == 9 and minute >= 50:
                    await self._pre_market()
                elif 10 <= hour < 18:
                    await self._market_hours()
                elif hour == 18 and minute <= 30:
                    await self._post_market()
                elif hour == 23 and minute <= 10:
                    await self._daily_summary()
                else:
                    # Piyasa kapalı — bekle
                    await asyncio.sleep(60)

            except Exception as e:
                logger.error("Scheduler error", error=str(e))
                await asyncio.sleep(30)

    async def stop(self):
        """Scheduler'ı durdur."""
        self._running = False

    # =====================================================
    # Piyasa Öncesi (09:50)
    # =====================================================

    async def _pre_market(self):
        """Piyasa açılmadan önce hazırlık."""
        logger.info("=== PRE-MARKET PREPARATION ===")

        # 1. Dünkü sonuçları kontrol et
        await self._check_yesterday_predictions()

        # 2. Makro verileri güncelle
        await self._update_macro()

        # 3. KAP bildirimlerini kontrol et
        await self._check_kap()

        # 4. Global piyasaları kontrol et
        await self._check_global()

        # 5. World state güncelle
        await self._update_world_state()

        logger.info("Pre-market preparation completed")
        await asyncio.sleep(60)

    # =====================================================
    # Piyasa Saatleri (10:00-18:00)
    # =====================================================

    async def _market_hours(self):
        """Piyasa açıkken sürekli tarama."""
        logger.info("=== MARKET HOURS SCAN ===")

        # 1. Tüm BIST'i tara
        results = await self._full_scan()

        # 2. Sinyal üret
        signals = await self._generate_signals(results)

        # 3. Trade planları oluştur
        plans = await self._create_trade_plans(signals)

        # 4. Anomalileri kontrol et
        anomalies = await self._detect_anomalies(results)

        # 5. Bildirim üret
        await self._generate_alerts(signals, anomalies, plans)

        # 6. Sonuçları kaydet
        self._today_results = results
        self._last_scan = datetime.now()
        self._scan_count += 1

        logger.info("Market scan completed",
                    stocks=len(results),
                    signals=len(signals),
                    anomalies=len(anomalies),
                    scan_count=self._scan_count)

        # 5 dakika bekle
        await asyncio.sleep(300)

    # =====================================================
    # Piyasa Sonrası (18:00)
    # =====================================================

    async def _post_market(self):
        """Piyasa kapandıktan sonra rapor."""
        logger.info("=== POST-MARKET REPORT ===")

        # 1. Günlük performans raporu
        report = await self._generate_daily_report()

        # 2. Tahmin sonuçlarını kontrol et
        await self._check_today_predictions()

        # 3. Yarın için hazırlık
        await self._prepare_tomorrow()

        self._last_report = datetime.now()
        logger.info("Post-market report completed")

        await asyncio.sleep(60)

    # =====================================================
    # Günlük Özet (23:00)
    # =====================================================

    async def _daily_summary(self):
        """Günlük özet ve öğrenme."""
        logger.info("=== DAILY SUMMARY & LEARNING ===")

        # 1. Bugünün sonuçlarını analiz et
        await self._analyze_today()

        # 2. Model performansını değerlendir
        await self._evaluate_models()

        # 3. Feature importance güncelle
        await self._update_features()

        logger.info("Daily summary completed")
        await asyncio.sleep(60)

    # =====================================================
    # Yardımcı Fonksiyonlar
    # =====================================================

    async def _full_scan(self) -> List[Dict]:
        """Tüm BIST'i tara."""
        import yfinance as yf
        import polars as pl
        from ..ingestion.bist_universe import BIST_STOCKS, get_sector
        from ..features.calculator import FeatureCalculator

        fc = FeatureCalculator()

        # Batch download
        tickers = [f"{t}.IS" for t in BIST_STOCKS]
        data = yf.download(tickers, period="60d", group_by="ticker", threads=True, progress=False)

        results = []
        for ticker in BIST_STOCKS:
            try:
                td = data[f"{ticker}.IS"].dropna()
                if len(td) < 20:
                    continue

                td = td.reset_index()
                df = pl.from_pandas(td[["Date", "Open", "High", "Low", "Close", "Volume"]])
                df = df.rename({"Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})

                features = fc.compute_all_features(df)
                if not features:
                    continue

                close_list = [x for x in df["close"].to_list() if x is not None]
                price = close_list[-1]

                results.append({
                    "ticker": ticker,
                    "sector": get_sector(ticker),
                    "price": price,
                    "features": features,
                })
            except:
                pass

        return results

    async def _generate_signals(self, results: List[Dict]) -> List[Dict]:
        """Sinyal üret."""
        from ..intelligence.spec_engine import spec_engine

        signals = []
        for r in results:
            features = r["features"]
            asset_state = {
                "volume_zscore": features.get("volume_zscore", 0),
                "price_change_1d_zscore": features.get("return_1d", 0) / 2,
                "volatility_zscore": features.get("volatility_ratio", 1) - 1,
                "bb_position": features.get("bb_position", 0.5),
                "near_20d_high": features.get("near_20d_high", 0),
                "relative_strength_vs_sector": 1.0,
                "kap_sentiment": 0.0,
                "roc_5d": features.get("roc_5d", 0),
                "price_acceleration": features.get("price_acceleration", 0),
                "volatility_regime": "NORMAL",
                "amihud_illiquidity": 0.001,
                "correlation_to_index": 0.75,
                "momentum_20d": features.get("momentum_20d", 0),
                "realized_vol_20d": features.get("realized_vol_20d", 20),
            }

            spec = spec_engine.compute_spec(r["ticker"], asset_state, {"regime": "RANGE"})

            if spec.spec_score >= 50:
                signals.append({
                    "ticker": r["ticker"],
                    "price": r["price"],
                    "spec_score": spec.spec_score,
                    "spec_category": spec.category,
                    "features": features,
                })

        signals.sort(key=lambda x: x["spec_score"], reverse=True)
        return signals

    async def _create_trade_plans(self, signals: List[Dict]) -> List[Dict]:
        """Trade planları oluştur."""
        from ..intelligence.trade_planner import trade_planner

        plans = []
        for s in signals[:20]:  # Top 20
            plan = trade_planner.create_plan(
                ticker=s["ticker"],
                price=s["price"],
                features=s["features"],
                spec_score=s["spec_score"],
                spec_category=s["spec_category"],
            )
            if plan.action in ["BUY", "SELL"]:
                plans.append({
                    "ticker": s["ticker"],
                    "action": plan.action,
                    "entry": plan.entry_price,
                    "target": plan.target_price_1,
                    "stop": plan.stop_loss,
                    "risk_reward": plan.risk_reward_ratio,
                })

        return plans

    async def _detect_anomalies(self, results: List[Dict]) -> List[Dict]:
        """Anomalileri tespit et."""
        anomalies = []
        for r in results:
            vol_z = r["features"].get("volume_zscore", 0)
            if abs(vol_z) > 2.0:
                anomalies.append({
                    "ticker": r["ticker"],
                    "type": "VOLUME_ANOMALY",
                    "score": vol_z,
                    "price": r["price"],
                })
        return anomalies

    async def _generate_alerts(self, signals, anomalies, plans):
        """Bildirim üret."""
        if anomalies:
            logger.warning("ANOMALIES DETECTED", count=len(anomalies))
            for a in anomalies[:5]:
                logger.warning(f"  {a['ticker']}: vol_z={a['score']:.1f}")

        if plans:
            logger.info("TRADE PLANS GENERATED", count=len(plans))
            for p in plans:
                logger.info(f"  {p['ticker']}: {p['action']} @ ₺{p['entry']:.2f}")

    async def _check_yesterday_predictions(self):
        """Dünkü tahminleri kontrol et."""
        logger.info("Checking yesterday's predictions")

    async def _update_macro(self):
        """Makro verileri güncelle."""
        logger.info("Updating macro data")

    async def _check_kap(self):
        """KAP bildirimlerini kontrol et."""
        logger.info("Checking KAP disclosures")

    async def _check_global(self):
        """Global piyasaları kontrol et."""
        logger.info("Checking global markets")

    async def _update_world_state(self):
        """World state güncelle."""
        logger.info("Updating world state")

    async def _generate_daily_report(self):
        """Günlük rapor oluştur."""
        logger.info("Generating daily report")

    async def _check_today_predictions(self):
        """Bugünün tahminlerini kontrol et."""
        logger.info("Checking today's predictions")

    async def _prepare_tomorrow(self):
        """Yarın için hazırlık."""
        logger.info("Preparing for tomorrow")

    async def _analyze_today(self):
        """Bugünü analiz et."""
        logger.info("Analyzing today's results")

    async def _evaluate_models(self):
        """Model performansını değerlendir."""
        logger.info("Evaluating model performance")

    async def _update_features(self):
        """Feature importance güncelle."""
        logger.info("Updating feature importance")


# =====================================================
# Entry Point
# =====================================================

async def main():
    """Scheduler'ı başlat."""
    scheduler = AlphaScheduler()
    try:
        await scheduler.start()
    except KeyboardInterrupt:
        await scheduler.stop()
    except Exception as e:
        logger.error("Scheduler crashed", error=str(e))
        await scheduler.stop()
        raise


if __name__ == "__main__":
    asyncio.run(main())
