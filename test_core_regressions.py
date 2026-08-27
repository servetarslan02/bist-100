import logging

logging.basicConfig(level=logging.ERROR)


def test_data_quality():
    from services.core.data_quality import TradabilityMask, data_quality

    mask = TradabilityMask(
        "THYAO", "2026-08-21T00:00:00Z", is_tradable=False, reasons=["test"], price_mask=0.0, volume_mask=0.0
    )
    raw_data = {"open": 10.0, "high": 11.0, "low": 9.0, "close": 11.0, "volume": 0, "some_other_field": 42}
    result = data_quality.apply_mask(raw_data, mask)
    print("--- data_quality test ---")
    print("EXPECTED: close=None, volume=None, some_other_field=42")
    print(
        f"ACTUAL: close={result.get('close')}, volume={result.get('volume')}, some_other_field={result.get('some_other_field')}"
    )
    if result.get("close") is None and result.get("volume") is None and result.get("some_other_field") == 42:
        print("PASS")
    else:
        print("FAIL")


def test_event_bus():
    import asyncio

    from services.core.event_bus import InMemoryRedis

    redis = InMemoryRedis()

    async def run():
        redis._queues = None
        try:
            await redis.publish("test", "data")
            print("--- event_bus test ---")
            print("PASS")
        except Exception as e:
            print("FAIL: Exception crashed the caller:", type(e).__name__)

    asyncio.run(run())


def test_canonical_scoring():
    from services.core.canonical_scoring import canonical_scoring

    class FakeMLModel:
        def predict(self, X):
            raise ValueError("ML Failed")

    canonical_scoring._ml_model = FakeMLModel()
    try:
        score = canonical_scoring.score("THYAO", {"trend": 1})
        print("--- canonical_scoring test ---")
        print(f"ACTUAL: Score returned type {type(score).__name__}")
        print("PASS")
    except Exception as e:
        print("--- canonical_scoring test ---")
        print("FAIL: Exception leaked out:", type(e).__name__)


def test_regime_detector():
    from services.core.regime_detector import regime_detector

    probs = regime_detector._estimate_transition_probability("LOW_VOL")
    print("--- regime_detector test ---")
    if sum(probs.values()) == 1.0 and len(probs) == 5:
        print("PASS")
    else:
        print("FAIL")


test_data_quality()
test_event_bus()
test_canonical_scoring()
test_regime_detector()
