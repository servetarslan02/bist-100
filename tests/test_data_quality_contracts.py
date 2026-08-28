"""
ALPHA BIST — Financial Data Quality & Data Contracts Test Suite
Doğrulanan Özellikler:
1. Finansal Veri Kontratları (Data Quality Engine Expectations Suite):
   - Fiyat Pozitifliği (ExpectColumnValuesToBePositive)
   - OHLCV Tutarlılığı (ExpectOHLCGeometry)
   - BIST Tavan/Taban Devre Kesici Tespiti (ExpectCircuitBreakerLimits)
   - Hacim ve Halt Kontrolleri (ExpectVolumeLiquidityProfile)
2. Tradability Maske Uygulama (apply_mask)
3. DataIntegrityValidator (Startup veri bütünlüğü ve tazelik raporlama)
"""

import pytest
from datetime import datetime, UTC

from services.core.data_quality import DataQualityEngine, TradabilityMask, DataQualityChecker
from services.core.data_integrity import DataIntegrityValidator

try:
    import polars as pl
except ImportError:
    pl = None


class TestFinancialDataContracts:
    """Temel finansal veri doğruluğu ve kontrat testleri."""

    def test_valid_bar_is_tradable(self):
        engine = DataQualityEngine()
        mask = engine.check_tradability(
            ticker="THYAO",
            open_price=300.0,
            high=305.0,
            low=298.0,
            close=302.0,
            volume=500000.0,
            prev_close=300.0,
        )
        assert mask.is_tradable is True
        assert mask.price_mask == 1.0
        assert mask.volume_mask == 1.0
        assert mask.reasons == ["OK"]

    def test_invalid_negative_or_zero_price(self):
        engine = DataQualityEngine()
        mask = engine.check_tradability(
            ticker="THYAO",
            open_price=0.0,
            high=305.0,
            low=-5.0,
            close=302.0,
            volume=500000.0,
            prev_close=300.0,
        )
        assert mask.is_tradable is False
        assert mask.price_mask == 0.0
        assert any("Columns <= 0" in r for r in mask.reasons)

    def test_invalid_ohlc_geometry(self):
        engine = DataQualityEngine()
        # High lower than Low
        mask = engine.check_tradability(
            ticker="ASELS",
            open_price=60.0,
            high=55.0,
            low=65.0,
            close=58.0,
            volume=100000.0,
            prev_close=60.0,
        )
        assert mask.is_tradable is False
        assert mask.price_mask == 0.0
        assert any("Anormal fiyat yapısı" in r for r in mask.reasons)

    def test_circuit_breaker_limit_up_down(self):
        engine = DataQualityEngine()
        # %9.9 artış (Tavan)
        mask = engine.check_tradability(
            ticker="EREGL",
            open_price=50.0,
            high=55.0,
            low=50.0,
            close=54.95,
            volume=2000000.0,
            prev_close=50.0,
        )
        assert mask.is_tradable is False
        assert mask.price_mask == 0.0
        assert any("Tavan/taban" in r for r in mask.reasons)

    def test_zero_volume_and_halt_detection(self):
        engine = DataQualityEngine()
        # Sıfır hacim ve tüm fiyatlar eşit (Halt)
        mask = engine.check_tradability(
            ticker="GARAN",
            open_price=120.0,
            high=120.0,
            low=120.0,
            close=120.0,
            volume=0.0,
            prev_close=120.0,
        )
        assert mask.is_tradable is False
        assert mask.volume_mask == 0.0
        assert mask.price_mask == 0.0
        assert any("Sıfır hacim ve Halt edilmiş" in r for r in mask.reasons)

    def test_apply_mask_to_dict(self):
        engine = DataQualityEngine()
        mask = engine.check_tradability(
            ticker="THYAO",
            open_price=0.0,
            high=300.0,
            low=0.0,
            close=0.0,
            volume=0.0,
            prev_close=300.0,
        )
        data = {"ticker": "THYAO", "open": 0.0, "close": 0.0, "volume": 0.0}
        masked = engine.apply_mask(data, mask, copy=True)
        assert masked["open"] is None
        assert masked["volume"] is None


class TestDataIntegrityValidator:
    """Sistem veri bütünlüğü doğrulayıcı testleri."""

    @pytest.mark.asyncio
    async def test_validate_on_startup_structure(self):
        validator = DataIntegrityValidator()
        results = await validator.validate_on_startup(
            clickhouse_client=None,
            pg_pool=None,
            redis_client=None,
        )
        assert "timestamp" in results
        assert "checks" in results
        assert "has_issues" in results
        assert isinstance(results["issues"], list)
