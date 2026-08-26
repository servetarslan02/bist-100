"""
ALPHA BIST — Likidite Kısıtı ve Gap Risk Testleri

Red-team kontrol listesindeki iki eksik madde için doğrulama:
1. Likidite kısıtı: günlük hacmin max_volume_participation_pct'ini aşan
   emirler artık ya kısılıyor ya da (hacim verisi yoksa) tamamen atlanıyor.
2. Gap risk: önceki kapanışa göre gap_limit_pct'i aşan açılışlarda emir
   gerçekleşmiyor (tavan/taban kilidi varsayımı).

Sentetik veri, ayırt edilebilir (round olmayan) sayılarla kuruluyor ki
"tesadüfen doğru çıktı" ihtimali olmasın.
"""

import polars as pl
import pytest

from services.backtest.multi_asset_engine import (
    MultiAssetBacktestEngine, MultiAssetConfig,
)


def _make_two_day_data(d0_close, d0_volume, d1_open, d1_volume, ticker="TEST1"):
    """D günü sinyal üretilir (score=80 → BUY), D+1 günü execution olur."""
    dates = pl.Series(["2024-01-01", "2024-01-02"])
    market_data = pl.DataFrame([
        {"date": dates[0], "ticker": ticker, "open": d0_close * 0.99,
         "high": d0_close * 1.01, "low": d0_close * 0.98,
         "close": d0_close, "volume": d0_volume},
        {"date": dates[1], "ticker": ticker, "open": d1_open,
         "high": d1_open * 1.01, "low": d1_open * 0.98,
         "close": d1_open, "volume": d1_volume},
    ])
    signal_data = pl.DataFrame([
        {"date": dates[0], "ticker": ticker, "score": 80.0, "confidence": 0.8},
        {"date": dates[1], "ticker": ticker, "score": 50.0, "confidence": 0.5},
    ])
    sector_map = {ticker: "test_sector"}
    return market_data, signal_data, sector_map


class TestLiquidityConstraint:
    """Likidite kısıtı testleri."""

    def test_large_order_capped_by_daily_volume(self):
        """Doğal pozisyon büyüklüğü hacmin %10'unu aşıyorsa, emir kısılmalı."""
        market_data, signal_data, sector_map = _make_two_day_data(
            d0_close=100.0, d0_volume=500, d1_open=101.0, d1_volume=500,
        )
        config = MultiAssetConfig(
            initial_capital=1_000_000.0,
            max_positions=5,
            max_position_pct=10.0,          # naif hedef: ~9,900 TL / 101 ≈ 990 adet
            max_volume_participation_pct=10.0,  # kısıt: 500 * %10 = 50 adet
            gap_limit_pct=10.0,
            enable_bias_detection=False,
        )
        engine = MultiAssetBacktestEngine(config=config)
        result = engine.run(market_data, signal_data, sector_map)

        buys = [t for t in result.trade_log if t["side"] == "BUY"]
        assert len(buys) == 1, "Hacim düşük olsa da likit bir miktar alınabilmeli"
        assert buys[0]["quantity"] <= 50, (
            f"Likidite kısıtı çalışmıyor: {buys[0]['quantity']} adet, "
            f"günlük hacmin %10'u olan 50'yi aşmamalı"
        )
        assert buys[0]["quantity"] > 0

    def test_zero_volume_skips_trade_entirely(self):
        """Hacim verisi 0/yoksa emir hiç gerçekleşmemeli (güvenli taraf)."""
        market_data, signal_data, sector_map = _make_two_day_data(
            d0_close=100.0, d0_volume=0, d1_open=101.0, d1_volume=0,
        )
        config = MultiAssetConfig(
            initial_capital=1_000_000.0,
            max_volume_participation_pct=10.0,
            gap_limit_pct=10.0,
            enable_bias_detection=False,
        )
        engine = MultiAssetBacktestEngine(config=config)
        result = engine.run(market_data, signal_data, sector_map)

        buys = [t for t in result.trade_log if t["side"] == "BUY"]
        assert len(buys) == 0, "Hacim verisi olmayan bir günde işlem yapılmamalı"

    def test_participation_limit_disabled_when_zero(self):
        """max_volume_participation_pct=0 kısıtı tamamen kapatmalı (geriye dönük uyumluluk)."""
        market_data, signal_data, sector_map = _make_two_day_data(
            d0_close=100.0, d0_volume=500, d1_open=101.0, d1_volume=500,
        )
        config = MultiAssetConfig(
            initial_capital=1_000_000.0,
            max_position_pct=10.0,
            max_volume_participation_pct=0.0,  # kısıt kapalı
            gap_limit_pct=0.0,                 # gap kontrolü de kapalı
            enable_bias_detection=False,
        )
        engine = MultiAssetBacktestEngine(config=config)
        result = engine.run(market_data, signal_data, sector_map)

        buys = [t for t in result.trade_log if t["side"] == "BUY"]
        assert len(buys) == 1
        # Kısıt kapalıyken naif boyutlandırma (~990 adet) uygulanmalı
        assert buys[0]["quantity"] > 50


class TestGapRisk:
    """Gap risk (tavan/taban kilidi) testleri."""

    def test_large_gap_blocks_trade(self):
        """Açılış, önceki kapanışa göre %10'u aşan bir sıçrama yapıyorsa
        emir gerçekleşmemeli (limit kilidi varsayımı)."""
        market_data, signal_data, sector_map = _make_two_day_data(
            d0_close=100.0, d0_volume=10_000_000,
            d1_open=115.0,  # %15 gap - %10 bandını aşıyor
            d1_volume=10_000_000,
        )
        config = MultiAssetConfig(
            initial_capital=1_000_000.0,
            max_volume_participation_pct=10.0,
            gap_limit_pct=10.0,
            enable_bias_detection=False,
        )
        engine = MultiAssetBacktestEngine(config=config)
        result = engine.run(market_data, signal_data, sector_map)

        buys = [t for t in result.trade_log if t["side"] == "BUY"]
        assert len(buys) == 0, "Bandı aşan gap'te işlem gerçekleşmemeli"

    def test_small_gap_allows_trade(self):
        """Bandın içindeki normal bir açılış farkında işlem gerçekleşmeli."""
        market_data, signal_data, sector_map = _make_two_day_data(
            d0_close=100.0, d0_volume=10_000_000,
            d1_open=103.0,  # %3 gap - bandın içinde
            d1_volume=10_000_000,
        )
        config = MultiAssetConfig(
            initial_capital=1_000_000.0,
            max_volume_participation_pct=10.0,
            gap_limit_pct=10.0,
            enable_bias_detection=False,
        )
        engine = MultiAssetBacktestEngine(config=config)
        result = engine.run(market_data, signal_data, sector_map)

        buys = [t for t in result.trade_log if t["side"] == "BUY"]
        assert len(buys) == 1
        assert buys[0]["price"] > 0

    def test_gap_check_disabled_when_zero(self):
        """gap_limit_pct=0 kontrolü tamamen kapatmalı."""
        market_data, signal_data, sector_map = _make_two_day_data(
            d0_close=100.0, d0_volume=10_000_000,
            d1_open=130.0,  # %30 gap - normalde kilitlenirdi
            d1_volume=10_000_000,
        )
        config = MultiAssetConfig(
            initial_capital=1_000_000.0,
            max_volume_participation_pct=10.0,
            gap_limit_pct=0.0,  # kapalı
            enable_bias_detection=False,
        )
        engine = MultiAssetBacktestEngine(config=config)
        result = engine.run(market_data, signal_data, sector_map)

        buys = [t for t in result.trade_log if t["side"] == "BUY"]
        assert len(buys) == 1, "Kontrol kapalıyken büyük gap'te bile işlem geçmeli"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
