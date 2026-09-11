"""ALPHA BIST — Feature Engine Service

Gerçek zamanlı feature hesaplama servisi. Market tick event'lerini dinler,
price cache'i günceller, feature pipeline'ını çalıştırır ve sonuçları
Redis (hot state) + ClickHouse (historical) depolar.
"""

from __future__ import annotations

from typing import Any

import asyncio
from datetime import UTC, datetime

import polars as pl
import structlog

from ..core.database import (
    ch_insert,
    close_databases,
    init_databases,
    redis_hset,
)
from ..core.event_bus import (
    EventConsumer,
    EventType,
    ensure_topics,
    publish_event,
)
from ..core.event_schema import CanonicalEvent
from ..core.logging import setup_logging
from .calculator import feature_calculator
from .pipeline import feature_pipeline

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

DEFAULT_MAX_TICK_CACHE: int = 200
DEFAULT_MIN_TICKS_FOR_FEATURE: int = 20
DEFAULT_HEALTH_PORT: int = 8080
DEFAULT_MAX_TICKERS: int = 1000


# ---------------------------------------------------------------------------
# Ana sınıf
# ---------------------------------------------------------------------------


class FeatureEngineService:
    """Feature Engine Service — BIST-100 için gerçek zamanlı feature hesaplama.

    Market tick event'lerini dinler, price cache'i günceller ve
    feature pipeline'ını çalıştırır.

    Özellikler:
        - Gerçek zamanlı tick işleme
        - Rolling price cache yönetimi
        - Feature hesaplama (calculator + pipeline)
        - Redis (hot state) + ClickHouse (historical) depolama
        - Health check HTTP sunucusu
    """

    def __init__(self) -> None:
        """Feature Engine Service başlatıcısı.

        Price cache, pipeline ve çalışma durumunu başlatır.

        Returns:
            None.

        Raises:
            Yok.
        """
        self._running = False
        self._consumer: EventConsumer = None
        self._price_cache: dict[str, list[dict]] = {}
        self._pipeline = feature_pipeline

    def __repr__(self) -> str:
        """FeatureEngineService kısa temsili.

        Returns:
            Çalışma durumu ve cache boyutu.
        """
        return f"FeatureEngineService(running={self._running}, tickers={len(self._price_cache)})"

    async def start(self) -> None:
        """Feature Engine Service'i başlatır.

        Veritabanlarını başlatır, event consumer'ı kurar ve
        tick dinleme döngüsünü başlatır.

        Returns:
            None.
        """
        setup_logging()
        logger.info("feature_engine_starting")
        await init_databases()
        ensure_topics()
        self._running = True
        self._consumer = EventConsumer(
            group_id="feature-engine",
            topics=["market.tick"],
            auto_offset_reset="latest",
        )
        self._consumer.on(EventType.MARKET_TICK, self._on_tick)
        logger.info("feature_engine_started")
        await self._consumer.consume_loop()

    async def stop(self) -> None:
        """Feature Engine Service'i durdurur.

        Returns:
            None.
        """
        self._running = False
        if self._consumer:
            self._consumer.stop()
        await close_databases()
        logger.info("feature_engine_stopped")

    async def _on_tick(self, event: CanonicalEvent) -> None:
        """Gelen tick event'lerini işler — her tick'te price cache'i günceller ve feature hesaplar.

        Args:
            event: CanonicalEvent tick verisi.

        Returns:
            None.

        Raises:
            Yok — hatalar loglanır, service crash olmaz.
        """
        try:
            ticker = event.data.get("ticker")
            instrument_id = event.data.get("instrument_id")
            price = event.data.get("price", 0)
            volume = event.data.get("volume", 0)

            if not ticker or not price:
                return

            # Ticker sayısı limiti
            if ticker not in self._price_cache and len(self._price_cache) >= DEFAULT_MAX_TICKERS:
                logger.warning("max_tickers_reached", count=len(self._price_cache))
                return

            # Update price cache
            if ticker not in self._price_cache:
                self._price_cache[ticker] = []

            self._price_cache[ticker].append(
                {
                    "price": price,
                    "volume": volume,
                    "timestamp": event.timestamp.isoformat(),
                }
            )

            # Keep last N ticks
            self._price_cache[ticker] = self._price_cache[ticker][-DEFAULT_MAX_TICK_CACHE:]

            # Feature hesaplama (minimum tick sayısına ulaşınca)
            if len(self._price_cache[ticker]) >= DEFAULT_MIN_TICKS_FOR_FEATURE:
                features = self._compute_features(ticker, self._price_cache[ticker])

                if features:
                    # Metadata — feature dict'ten ayrı tutulur (tip güvenliği)
                    feature_metadata = {
                        "ticker": ticker,
                        "computed_at": datetime.now(UTC).isoformat(),
                        "data_points": len(self._price_cache[ticker]),
                    }

                    # Store in Redis (hot state)
                    await redis_hset(
                        f"features:{ticker}", {k: str(v) for k, v in features.items() if isinstance(v, (int, float))}
                    )

                    # Store in ClickHouse (historical)
                    self._store_features_ch(instrument_id or 0, ticker, features)

                    # Publish feature update event
                    feat_event = CanonicalEvent(
                        event_type=EventType.FEATURE_UPDATED,
                        source="feature-engine",
                        data={
                            "instrument_id": instrument_id,
                            "ticker": ticker,
                            "features": features,
                            "metadata": feature_metadata,
                        },
                    )
                    publish_event(feat_event, key=ticker)

        except Exception as e:
            logger.error("tick_processing_error", error=str(e))

    def _compute_features(self, ticker: str, price_data: list[dict]) -> dict[str, float]:
        """Price cache'ten feature hesaplar.

        Tick verisini Polars DataFrame'e dönüştürür, OHLCV formatına çevirir
        ve calculator ile tüm feature'ları hesaplar.

        Args:
            ticker: Hisse senedi kodu.
            price_data: Tick verisi listesi (price, volume, timestamp).

        Returns:
            Feature adı → değer sözlüğü. Hata durumunda boş dict.
        """
        try:
            df = pl.DataFrame(price_data)

            required_cols = ["price", "volume", "timestamp"]
            for col in required_cols:
                if col not in df.columns:
                    return {}

            # OHLCV formatına çevir
            rename_map = {}
            if "price" in df.columns:
                rename_map["price"] = "Close"
            if "volume" in df.columns:
                rename_map["volume"] = "Volume"
            if "close" in df.columns:
                rename_map["close"] = "Close"
            if rename_map:
                df = df.rename(rename_map)
            for col in ["Open", "High", "Low"]:
                if col not in df.columns:
                    df = df.with_columns(pl.col("Close").alias(col))

            features = feature_calculator.compute_all_features(df, ticker=ticker)

            # Pipeline entegrasyonu
            try:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._run_pipeline_async(ticker, features, df))
                except RuntimeError:
                    asyncio.run(self._run_pipeline_async(ticker, features, df))
            except Exception as e:
                logger.debug("pipeline_integration_skipped", error=str(e))

            return features

        except Exception as e:
            logger.warning("feature_computation_failed", ticker=ticker, error=str(e))
            return {}

    async def _run_pipeline_async(self, ticker: str, features: dict[str, float], df: Any) -> None:
        """Pipeline'ı async olarak çalıştırır (store, drift detection).

        Args:
            ticker: Hisse senedi kodu.
            features: Hesaplanmış feature sözlüğü.
            df: OHLCV Polars DataFrame.

        Returns:
            None.
        """
        try:
            result = await self._pipeline.run(
                ticker=ticker,
                features=features,
                ohlcv_df=df,
            )
            if result.drift_report and result.drift_report.get("drifted_features", 0) > 0:
                logger.warning(
                    "Feature drift detected via pipeline",
                    ticker=ticker,
                    drifted=result.drift_report.get("drifted_features"),
                )
        except Exception as e:
            logger.debug("Pipeline run failed", ticker=ticker, error=str(e))

    def _store_features_ch(self, instrument_id: int, ticker: str, features: dict[str, float]) -> None:
        """Feature'ları ClickHouse'a depolar.

        Args:
            instrument_id: Enstrüman ID'si.
            ticker: Hisse senedi kodu.
            features: Feature adı → değer sözlüğü.

        Returns:
            None.
        """
        try:
            now = datetime.now(UTC)
            rows = []

            for feature_name, feature_value in features.items():
                if isinstance(feature_value, (int, float)):
                    rows.append(
                        [
                            instrument_id,
                            now,
                            feature_name,
                            float(feature_value),
                            1,  # version
                            "feature-engine",
                        ]
                    )

            if rows:
                ch_insert(
                    "features",
                    rows,
                    column_names=[
                        "instrument_id",
                        "timestamp",
                        "feature_name",
                        "feature_value",
                        "feature_version",
                        "source",
                    ],
                )

        except Exception as e:
            logger.warning("clickhouse_storage_failed", ticker=ticker, error=str(e))


# =====================================================
# Health Check HTTP Server
# =====================================================


async def _health_server(port: int = DEFAULT_HEALTH_PORT) -> None:
    """Docker healthcheck için hafif HTTP sunucu başlatır.

    Args:
        port: HTTP sunucu portu. Varsayılan DEFAULT_HEALTH_PORT.

    Returns:
        None.
    """
    from aiohttp import web

    async def health_handler(request: Any) -> Any:
        """Docker healthcheck endpoint'i.

        Servisin çalıştığını ve sağlıklı olduğunu doğrular.

        Args:
            request: HTTP isteği.

        Returns:
            JSON yanıt: {"status": "healthy", "service": "features"}
        """
        return web.json_response({"status": "healthy", "service": "features"})

    app = web.Application()
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Health server started", port=port)


# =====================================================
# Entry Point
# =====================================================


async def main() -> None:
    """Feature Engine Service ana giriş noktası.

    Health sunucusunu başlatır, service'i oluşturur ve çalıştırır.

    Returns:
        None.

    Raises:
        Exception: Service crash durumunda yeniden fırlatılır.
    """
    await _health_server()
    service = FeatureEngineService()
    try:
        await service.start()
    except KeyboardInterrupt:
        await service.stop()
    except Exception as e:
        logger.error("Feature Engine crashed", error=str(e))
        await service.stop()
        raise


if __name__ == "__main__":
    asyncio.run(main())
