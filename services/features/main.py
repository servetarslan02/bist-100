"""ALPHA BIST - Feature Engine Service (Main Entry Point)"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Any
import polars as pl
import structlog

from ..core.config import settings
from ..core.database import (
    init_databases, close_databases, get_pg_pool,
    ch_insert, ch_execute, redis_hset, redis_hgetall,
)
from ..core.event_schema import CanonicalEvent
from ..core.event_bus import (
    ensure_topics, EventType,
    EventConsumer, publish_event, flush_producer,
)
from ..core.logging import setup_logging
from .calculator import feature_calculator
from .pipeline import feature_pipeline, PipelineConfig

logger = structlog.get_logger()


class FeatureEngineService:
    """Computes and stores features for all instruments."""

    def __init__(self):
        self._running = False
        self._consumer: EventConsumer = None
        self._price_cache: Dict[str, List[Dict]] = {}  # ticker -> recent prices
        # Pipeline — drift detection, BIST features, store entegrasyonu
        self._pipeline = feature_pipeline

    async def start(self):
        """Start the feature engine service."""
        setup_logging()
        logger.info("Starting Feature Engine Service")

        await init_databases()
        ensure_topics()

        self._running = True

        # Set up event consumer
        self._consumer = EventConsumer(
            group_id="feature-engine",
            topics=["market.tick"],
            auto_offset_reset="latest",
        )
        self._consumer.on(EventType.MARKET_TICK, self._on_tick)

        logger.info("Feature Engine Service started")
        await self._consumer.consume_loop()

    async def stop(self):
        """Stop the feature engine service."""
        self._running = False
        if self._consumer:
            self._consumer.stop()
        await close_databases()
        logger.info("Feature Engine Service stopped")

    async def _on_tick(self, event: CanonicalEvent):
        """Handle incoming tick events — her tick'te feature güncelle."""
        try:
            ticker = event.data.get("ticker")
            instrument_id = event.data.get("instrument_id")
            price = event.data.get("price", 0)
            volume = event.data.get("volume", 0)

            if not ticker or not price:
                return

            # Update price cache
            if ticker not in self._price_cache:
                self._price_cache[ticker] = []

            self._price_cache[ticker].append({
                "price": price,
                "volume": volume,
                "timestamp": event.timestamp.isoformat(),
            })

            # Keep last 200 ticks
            self._price_cache[ticker] = self._price_cache[ticker][-200:]

            # Her tick'te feature güncelle (20+ tick varsa)
            if len(self._price_cache[ticker]) >= 20:
                features = self._compute_features(ticker, self._price_cache[ticker])

                if features:
                    # Store in Redis (hot state) — anlık erişim için
                    await redis_hset(f"features:{ticker}", {
                        k: str(v) for k, v in features.items() if isinstance(v, (int, float))
                    })

                    # Store in ClickHouse (historical)
                    self._store_features_ch(instrument_id or 0, ticker, features)

                    # Publish feature update event — market state ve scanner'a gider
                    feat_event = CanonicalEvent(
                        event_type=EventType.FEATURE_UPDATED,
                        source="feature-engine",
                        data={
                            "instrument_id": instrument_id,
                            "ticker": ticker,
                            "features": features,
                        },
                    )
                    publish_event(feat_event, key=ticker)

        except Exception as e:
            logger.error("Tick processing error", error=str(e))

    def _compute_features(self, ticker: str, price_data: List[Dict]) -> Dict[str, float]:
        """Compute features from price cache."""
        try:
            # Convert to DataFrame
            df = pl.DataFrame(price_data)

            # Ensure columns exist
            required_cols = ["price", "volume", "timestamp"]
            for col in required_cols:
                if col not in df.columns:
                    return {}

            # Rename to OHLCV format (we only have close price from ticks)
            # NOT: calculator.compute_all() buyuk harfli Close/Open/High/Low/Volume
            # kolon adlari bekliyor - kucuk harfle KeyError('Close') ile sessizce {}
            # donuyor ve feature hic hesaplanmiyor (bkz. try/except).
            df = df.rename({"price": "Close", "volume": "Volume"})
            df = df.with_columns([
                pl.col("Close").alias("Open"),
                pl.col("Close").alias("High"),
                pl.col("Close").alias("Low"),
            ])

            # Compute features
            features = feature_calculator.compute_all_features(df)

            # Add metadata
            features["ticker"] = ticker
            features["computed_at"] = datetime.now(timezone.utc).isoformat()
            features["data_points"] = len(df)

            # === PIPELINE ENTEGRASYONU ===
            # Feature store'a kaydet, drift detection çalıştır
            try:
                import asyncio as _asyncio
                try:
                    loop = _asyncio.get_running_loop()
                    # Zaten bir loop içinde — background task olarak çalıştır
                    loop.create_task(self._run_pipeline_async(ticker, features, df))
                except RuntimeError:
                    # Loop yok — yeni oluştur
                    _asyncio.run(self._run_pipeline_async(ticker, features, df))
            except Exception as e:
                logger.debug("Pipeline integration skipped", error=str(e))

            return features

        except Exception as e:
            logger.warning("Feature computation failed", ticker=ticker, error=str(e))
            return {}

    async def _run_pipeline_async(self, ticker: str, features: Dict[str, float], df):
        """Pipeline'ı async olarak çalıştır (store, drift detection)."""
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

    def _store_features_ch(self, instrument_id: int, ticker: str, features: Dict[str, float]):
        """Store features in ClickHouse."""
        try:
            now = datetime.now(timezone.utc)
            rows = []

            for feature_name, feature_value in features.items():
                if isinstance(feature_value, (int, float)):
                    rows.append([
                        instrument_id,
                        now,
                        feature_name,
                        float(feature_value),
                        1,  # version
                        "feature-engine",
                    ])

            if rows:
                ch_insert(
                    "features",
                    rows,
                    column_names=["instrument_id", "timestamp", "feature_name", "feature_value", "feature_version", "source"],
                )

        except Exception as e:
            logger.warning("ClickHouse feature storage failed", ticker=ticker, error=str(e))


# =====================================================
# Entry Point
# =====================================================

async def main():
    """Main entry point for the feature engine service."""
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
