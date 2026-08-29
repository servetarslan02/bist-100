import structlog
logger = structlog.get_logger(__name__)
from typing import Any
import logging

logging.basicConfig(level=logging.ERROR)


def test_data_quality() -> Any:
    """Otomatik eklendi."""
    from services.core.data_quality import TradabilityMask, data_quality

    mask = TradabilityMask(
        "THYAO", "2026-08-21T00:00:00Z", is_tradable=False, reasons=["test"], price_mask=0.0, volume_mask=0.0
    )
    raw_data = {"open": 10.0, "high": 11.0, "low": 9.0, "close": 11.0, "volume": 0, "some_other_field": 42}
    result = data_quality.apply_mask(raw_data, mask)
    logger.info("--- data_quality test ---")
    logger.info("EXPECTED: close=None, volume=None, some_other_field=42")
    logger.info(
        f"ACTUAL: close={result.get('close')}, volume={result.get('volume')}, some_other_field={result.get('some_other_field')}"
    )
    if result.get("close") is None and result.get("volume") is None and result.get("some_other_field") == 42:
        logger.info("PASS")
    else:
        logger.info("FAIL")


def test_event_bus() -> Any:
    """Otomatik eklendi."""
    import asyncio

    from services.core.event_bus import InMemoryRedis

    redis = InMemoryRedis()

    async def run() -> Any:
        """Otomatik eklendi."""
        redis._queues = None
        try:
            await redis.publish("test", "data")
            logger.info("--- event_bus test ---")
            logger.info("PASS")
        except Exception as e:
            logger.info("FAIL: Exception crashed the caller:", type(e).__name__)

    asyncio.run(run())


def test_canonical_scoring() -> Any:
    """Otomatik eklendi."""
    from services.core.canonical_scoring import canonical_scoring

    class FakeMLModel:
        """Otomatik eklendi."""
        def predict(self, X) -> Any:
            """Otomatik eklendi."""
            raise ValueError("ML Failed")

    canonical_scoring._ml_model = FakeMLModel()
    try:
        score = canonical_scoring.score("THYAO", {"trend": 1})
        logger.info("--- canonical_scoring test ---")
        logger.info(f"ACTUAL: Score returned type {type(score).__name__}")
        logger.info("PASS")
    except Exception as e:
        logger.info("--- canonical_scoring test ---")
        logger.info("FAIL: Exception leaked out:", type(e).__name__)


def test_regime_detector() -> Any:
    """Otomatik eklendi."""
    from services.core.regime_detector import regime_detector

    probs = regime_detector._estimate_transition_probability("LOW_VOL")
    logger.info("--- regime_detector test ---")
    if sum(probs.values()) == 1.0 and len(probs) == 5:
        logger.info("PASS")
    else:
        logger.info("FAIL")


test_data_quality()
test_event_bus()
test_canonical_scoring()
test_regime_detector()
