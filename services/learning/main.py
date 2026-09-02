"""ALPHA BIST - Learning Service (ML Training, Validation, Champion/Challenger)"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import numpy as np
import orjson
import polars as pl
import structlog

from ..core.database import (
    ch_execute,
    close_databases,
    init_databases,
    pg_execute,
    pg_fetch,
    pg_fetchrow,
    pg_fetchval,
)
from ..core.event_bus import (
    EventConsumer,
    ensure_topics,
)
from ..core.logging import setup_logging

logger = structlog.get_logger()


class LearningService:
    """Automated ML training, validation, and model lifecycle management."""

    def __init__(self):
        """Otomatik eklendi."""
        self._running = False
        self._consumer: EventConsumer = None

    async def start(self) -> Any:
        """Start the learning service."""
        setup_logging()
        logger.info("Starting Learning Service")

        await init_databases()
        ensure_topics()

        self._running = True

        # Start periodic training loop
        await asyncio.gather(
            self._training_loop(),
            self._outcome_tracking_loop(),
        )

    async def stop(self) -> Any:
        """Stop the learning service."""
        self._running = False
        await close_databases()
        logger.info("Learning Service stopped")

    async def _training_loop(self) -> Any:
        """Periodic model training loop."""
        while self._running:
            try:
                logger.info("Starting training cycle")

                # Check if training is needed
                last_training = await self._get_last_training_time()
                hours_since = (datetime.now(UTC) - last_training).total_seconds() / 3600 if last_training else 999

                if hours_since >= 24:  # Günlük seans sonrası eğitim
                    await self._train_all_models()
                else:
                    logger.info("Training not needed yet", hours_since=round(hours_since, 1))

                # Wait 1 hour before checking again
                await asyncio.sleep(3600)

            except Exception as e:
                logger.error("Training loop error", error=str(e))
                await asyncio.sleep(3600)

    async def _outcome_tracking_loop(self) -> Any:
        """Track prediction outcomes."""
        while self._running:
            try:
                await self._track_outcomes()
                await asyncio.sleep(3600)  # Check hourly
            except Exception as e:
                logger.error("Outcome tracking error", error=str(e))
                await asyncio.sleep(3600)

    async def _train_all_models(self) -> Any:
        """Train all ML models across full BIST universe using 70+ feature engine."""
        try:
            logger.info("Executing Master 4-Pillar Ranking & Alpha Training across Full BIST Universe...")
            # 1. PRIMARY: 70+ Özellikli Master Ranking Modelini (Tüm 600+ BIST hissesi) eğit ve güncelle
            try:
                from services.ml.train_all_models import train_all_models

                await asyncio.to_thread(train_all_models)
                logger.info("Master 4-pillar swing ranking models updated successfully across full BIST universe")
            except Exception as e:
                logger.error("Master 4-pillar ranking training error", error=str(e), exc_info=True)

            # 2. SECONDARY: Legacy modeller varsa ve veri hazırsa eğit
            training_data = await self._prepare_training_data()
            if training_data is not None and not training_data.is_empty():
                from ml.models import MODEL_CONFIGS, LightGBMModel

                for model_name, config in MODEL_CONFIGS.items():
                    try:
                        feature_cols = [f for f in config.features if f in training_data.columns]
                        target_col = config.target
                        if target_col not in training_data.columns:
                            continue

                        X = training_data.select(feature_cols).to_numpy()
                        y = training_data.select(target_col).to_numpy().ravel()
                        mask = ~(np.isnan(X).any(axis=1) | np.isnan(y))
                        X, y = X[mask], y[mask]
                        if len(X) < 100:
                            continue

                        split_idx = int(len(X) * 0.8)
                        X_train, X_val = X[:split_idx], X[split_idx:]
                        y_train, y_val = y[:split_idx], y[split_idx:]

                        model = LightGBMModel(config)
                        model.train(X_train, y_train, X_val, y_val)

                        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

                        y_pred = model.predict(X_val)
                        metrics = {
                            "rmse": float(np.sqrt(mean_squared_error(y_val, y_pred))),
                            "mae": float(mean_absolute_error(y_val, y_pred)),
                            "r2": float(r2_score(y_val, y_pred)),
                            "training_samples": len(X_train),
                            "validation_samples": len(X_val),
                        }
                        model.metrics = metrics

                        import os

                        model_dir = f"ml/saved_models/{model_name}"
                        os.makedirs(model_dir, exist_ok=True)
                        model.save(f"{model_dir}/{config.version}.pkl")
                        await self._register_model(model_name, config, metrics)
                        logger.info("Secondary model trained", name=model_name, metrics=metrics)
                    except Exception as e:
                        logger.warning("Secondary model training skipped", name=model_name, error=str(e))
        except Exception as e:
            logger.error("Training cycle failed", error=str(e))

    async def _prepare_training_data(self) -> pl.DataFrame | None:
        """Prepare training data from ClickHouse."""
        try:
            # Get historical features and outcomes
            result = ch_execute("""
                SELECT
                    instrument_id,
                    timestamp,
                    feature_name,
                    feature_value
                FROM features
                WHERE timestamp >= now() - INTERVAL 1 YEAR
                ORDER BY instrument_id, timestamp, feature_name
            """)

            if not result.result_rows:
                return None

            # Pivot features
            df = pl.DataFrame(
                result.result_rows, schema=["instrument_id", "timestamp", "feature_name", "feature_value"]
            )

            # This is simplified - in production, you'd do proper pivoting
            # and join with actual return outcomes

            return df

        except Exception as e:
            logger.error("Training data preparation failed", error=str(e))
            return None

    async def _track_outcomes(self) -> Any:
        """Track prediction outcomes."""
        try:
            # Get unresolved predictions
            predictions = await pg_fetch("""
                SELECT mp.id, mp.instrument_id, mp.prediction_date, mp.horizon_days,
                       mp.predicted_direction, mp.predicted_return_pct
                FROM model_predictions mp
                LEFT JOIN model_outcomes mo ON mo.prediction_id = mp.id
                WHERE mo.id IS NULL
                AND mp.prediction_date <= CURRENT_DATE - mp.horizon_days
                LIMIT 100
            """)

            for pred in predictions:
                # Get actual return
                actual = await self._get_actual_return(
                    pred["instrument_id"],
                    pred["prediction_date"],
                    pred["horizon_days"],
                )

                if actual is not None:
                    # Store outcome
                    await pg_execute(
                        """
                        INSERT INTO model_outcomes (prediction_id, actual_return_pct, actual_direction, prediction_error, is_correct, outcome_date)
                        VALUES ($1, $2, $3, $4, $5, CURRENT_DATE)
                    """,
                        pred["id"],
                        actual["return_pct"],
                        actual["direction"],
                        abs(float(pred["predicted_return_pct"]) - actual["return_pct"]),
                        (pred["predicted_direction"] == actual["direction"]),
                    )

        except Exception as e:
            logger.error("Outcome tracking error", error=str(e))

    async def _get_actual_return(self, instrument_id: int, start_date, days: int) -> dict | None:
        """Get actual return for a prediction."""
        try:
            result = ch_execute(
                """
                SELECT
                    argMin(close, timestamp) as start_price,
                    argMax(close, timestamp) as end_price
                FROM ohlcv
                WHERE instrument_id = %(id)s
                AND timeframe = '1d'
                AND timestamp >= %(start)s
                AND timestamp <= %(start)s + INTERVAL %(days)s DAY
            """,
                parameters={"id": instrument_id, "start": start_date, "days": days},
            )

            if result.result_rows and len(result.result_rows) > 0:
                row = result.result_rows[0]
                if row[0] and row[1] and row[0] > 0:
                    return_pct = (row[1] / row[0] - 1) * 100
                    return {
                        "return_pct": float(return_pct),
                        "direction": "UP" if return_pct > 0 else "DOWN",
                    }

            return None

        except Exception:
            return None

    async def _get_last_training_time(self) -> datetime | None:
        """Get last training time."""
        row = await pg_fetchrow("""
            SELECT MAX(created_at) as last_training
            FROM model_versions
            WHERE status IN ('CANDIDATE', 'CHAMPION')
        """)
        return row["last_training"] if row else None

    async def _register_model(self, name: str, config, metrics: dict) -> Any:
        """Register model in database."""
        await pg_execute(
            """
            INSERT INTO models (name, description, model_type, framework, target_variable, features, hyperparameters, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'ACTIVE')
            ON CONFLICT (name) DO UPDATE SET
                features = $6, hyperparameters = $7, updated_at = NOW()
        """,
            name,
            config.description,
            config.model_type,
            "lightgbm",
            config.target,
            orjson.dumps(config.features),
            orjson.dumps(config.hyperparams),
        ).decode()

        model_id = await pg_fetchval("SELECT id FROM models WHERE name = $1", name)

        await pg_execute(
            """
            INSERT INTO model_versions (model_id, version, metrics, status, created_at)
            VALUES ($1, $2, $3, 'CANDIDATE', NOW())
        """,
            model_id,
            config.version,
            orjson.dumps(metrics).decode(),
        )


# =====================================================
# Health Check HTTP Server
# =====================================================


async def _health_server(port: int = 8080) -> Any:
    """Lightweight health check HTTP server for Docker healthcheck."""
    from aiohttp import web

    async def health_handler(request) -> Any:
        """Otomatik eklendi."""
        return web.json_response({"status": "healthy", "service": "learning"})

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


async def main() -> Any:
    """Main entry point for the learning service."""
    await _health_server()
    service = LearningService()
    try:
        await service.start()
    except KeyboardInterrupt:
        await service.stop()
    except Exception as e:
        logger.error("Learning Service crashed", error=str(e))
        await service.stop()
        raise


# =====================================================
# Learning Modül Bağlantıları
# =====================================================
def get_learning_systems() -> dict[str, Any]:
    """Tüm learning servislerini getir."""
    result = {}
    try:
        from .outcome_tracker import OutcomeTracker

        result["outcome_tracker"] = OutcomeTracker()
    except ImportError:
        logger.debug("Optional import not available in get_learning_systems", exc_info=True)
    except Exception as e:
        logger.warning("Failed to load module", module="OutcomeTracker", error=str(e))
    try:
        from .attribution import AttributionEngine

        result["attribution"] = AttributionEngine()
    except ImportError:
        logger.debug("Optional import not available in get_learning_systems", exc_info=True)
    except Exception as e:
        logger.warning("Failed to load module", module="AttributionEngine", error=str(e))
    try:
        from .learning_loop import LearningLoop

        result["learning_loop"] = LearningLoop()
    except ImportError:
        logger.debug("Optional import not available in get_learning_systems", exc_info=True)
    except Exception as e:
        logger.warning("Failed to load module", module="LearningLoop", error=str(e))
    try:
        from .continuous_learning import ContinuousLearning

        result["continuous_learning"] = ContinuousLearning()
    except ImportError:
        logger.debug("Optional import not available in get_learning_systems", exc_info=True)
    except Exception as e:
        logger.warning("Failed to load module", module="ContinuousLearning", error=str(e))
    try:
        from .super_intelligence import SuperIntelligence

        result["super_intelligence"] = SuperIntelligence()
    except ImportError:
        logger.debug("Optional import not available in get_learning_systems", exc_info=True)
    except Exception as e:
        logger.warning("Failed to load module", module="SuperIntelligence", error=str(e))
    return result


if __name__ == "__main__":
    asyncio.run(main())
