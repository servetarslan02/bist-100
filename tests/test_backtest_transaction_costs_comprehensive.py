"""ALPHA BIST — Gerçekçi İşlem Maliyeti (Transaction Costs) Kapsamlı Test Paketi.

services/backtest/transaction_costs.py modülünün tüm bileşenlerini ve uç durumlarını sınar:
1. Enum sınıfları: MarketCapCategory ve LiquidityTier.
2. BISTFeeStructure yasal ücret ve komisyon modeli:
   - broker, BIST tescil, MKK, Takasbank, BSMV oranı ve asgari tutarlar
   - total_exchange_fee_pct ve total_base_fee_pct hesaplamaları
   - negatif komisyon ve geçersiz oran sınır kontrolleri
3. SpreadModel dinamik alış-satış makas modeli:
   - Likidite katmanlarına (tier 1..4) göre baz spread
   - Volatilite ve hacim sapmalarında çarpan etkisi
4. SlippageModel kayma modeli:
   - Emir yönü, volatilite ve emir boyutu (order_size_pct) etkileri
5. MarketImpactModel Square-Root etki modeli:
   - Lot adedi ve günlük hacme göre kalıcı ve geçici piyasa etkisi
   - Sıfır ve negatif değer sınır korumaları
6. TransactionCostEngine ana motor:
   - classify_liquidity (işlem hacmine göre katman belirleme)
   - calculate_total_cost (BUY ve SELL yönünde execution_price, commission, BSMV, spread, slippage, impact)
   - Devre kesici (post_circuit_breaker) ve brüt takas (is_gross_settlement) spread genişlemeleri
   - estimate_round_trip_cost (Al-Sat tur maliyeti ve başabaş getiri eşiği)
   - compute_costs_df (Polars DataFrame işlem tablosuna vektörel maliyet sütunu ekleme)
7. Thread-safety (çoklu iş parçacığında eşzamanlı maliyet hesaplama güvenliği).
"""

from __future__ import annotations

import concurrent.futures

import polars as pl
import pytest

from services.backtest.transaction_costs import (
    BPS_DIVISOR,
    PERCENT_DIVISOR,
    TIER_1_MIN_VOLUME_TL,
    TIER_2_MIN_VOLUME_TL,
    TIER_3_MIN_VOLUME_TL,
    BISTCostParams,
    BISTFeeStructure,
    LiquidityTier,
    MarketCapCategory,
    MarketImpactModel,
    SlippageModel,
    SpreadModel,
    TransactionCostEngine,
    bist_transaction_cost,
)


def test_enums_and_constants():
    """Enum kategorileri ve matematiksel sabitlerin doğrulanması."""
    assert MarketCapCategory.LARGE_CAP.value == "large"
    assert "LARGE_CAP" in repr(MarketCapCategory.LARGE_CAP)

    assert LiquidityTier.TIER_1.value == "tier_1"
    assert "TIER_1" in repr(LiquidityTier.TIER_1)

    assert BPS_DIVISOR == 10000.0
    assert PERCENT_DIVISOR == 100.0
    assert TIER_1_MIN_VOLUME_TL > TIER_2_MIN_VOLUME_TL > TIER_3_MIN_VOLUME_TL


def test_bist_fee_structure_and_validations():
    """BIST yasal ücret tarifesi ve negatif parametre kontrolleri."""
    fees = BISTFeeStructure(
        broker_commission_pct=0.04,
        bist_fee_pct=0.0056,
        mkk_fee_pct=0.00109,
        takasbank_fee_pct=0.0001,
        min_commission_tl=2.5,
        bsmv_rate=0.05,
    )

    assert abs(fees.total_exchange_fee_pct - (0.0056 + 0.00109 + 0.0001)) < 1e-7
    assert abs(fees.total_base_fee_pct - (0.04 + fees.total_exchange_fee_pct)) < 1e-7
    assert "BISTFeeStructure" in repr(fees)

    # Validasyon hataları
    with pytest.raises(ValueError, match="negatif olamaz"):
        BISTFeeStructure(broker_commission_pct=-0.01)

    with pytest.raises(ValueError, match="negatif olamaz"):
        BISTFeeStructure(min_commission_tl=-1.0)

    with pytest.raises(ValueError, match="BSMV oranı"):
        BISTFeeStructure(bsmv_rate=1.5)

    with pytest.raises(ValueError, match="Stopaj oranı"):
        BISTFeeStructure(stopaj_rate=-0.1)


def test_spread_model_estimation():
    """Likidite katmanlarına ve piyasa oynaklığına göre bid/ask spread hesabı."""
    sm = SpreadModel(
        tier_1_spread_bps=5.0,
        tier_2_spread_bps=15.0,
        tier_3_spread_bps=30.0,
        tier_4_spread_bps=75.0,
    )
    assert "SpreadModel" in repr(sm)

    # Tier 1 normal koşul (volatility_ratio=1.0, volume_ratio=1.0)
    # 5 bps = 0.0005
    sp_t1 = sm.estimate_spread(LiquidityTier.TIER_1, 1.0, 1.0)
    assert abs(sp_t1 - 0.0005) < 1e-6

    # Tier 4 sığ tahta: 75 bps = 0.0075
    sp_t4 = sm.estimate_spread("tier_4", 1.0, 1.0)
    assert abs(sp_t4 - 0.0075) < 1e-6

    # Yüksek volatilite (volatility_ratio = 2.0) ve düşük hacim (volume_ratio = 0.5) -> Spread açılmalı
    sp_stressed = sm.estimate_spread(LiquidityTier.TIER_1, volatility_ratio=2.0, volume_ratio=0.5)
    assert sp_stressed > sp_t1


def test_slippage_and_market_impact_models():
    """Kayma ve Square-Root piyasa etkisi modelleri."""
    # Slippage
    slip_model = SlippageModel(base_slippage_bps=5.0)
    assert "SlippageModel" in repr(slip_model)
    slip_buy = slip_model.estimate_slippage("BUY", 1.0, 1.0, 0.01)
    assert slip_buy > 0.0

    # Market Impact
    impact_model = MarketImpactModel(eta=0.5, permanent_ratio=0.3)
    assert "MarketImpactModel" in repr(impact_model)

    # Sıfır veya geçersiz parametre durumunda 0.0 dönmeli
    zero_imp, perm_zero = impact_model.estimate_impact(0, 10000, 0.02, 100.0)
    assert zero_imp == 0.0 and perm_zero == 0.0

    # Normal işlem: 50.000 lot emir, 1.000.000 lot günlük hacim (katılım %5)
    total_imp, perm_imp = impact_model.estimate_impact(
        order_quantity=50000,
        avg_daily_volume=1000000,
        volatility=0.02,
        price=100.0,
    )
    assert total_imp > 0.0
    assert abs(perm_imp - (total_imp * 0.3)) < 1e-7


def test_transaction_cost_engine_single_trade():
    """Tekil alım ve satım emrinde tüm maliyet kalemlerinin ve icra fiyatının hesaplanması."""
    engine = TransactionCostEngine()
    assert repr(engine).startswith("TransactionCostEngine")

    # Likidite sınıflandırması
    assert engine.classify_liquidity(600_000_000.0) == LiquidityTier.TIER_1
    assert engine.classify_liquidity(200_000_000.0) == LiquidityTier.TIER_2
    assert engine.classify_liquidity(50_000_000.0) == LiquidityTier.TIER_3
    assert engine.classify_liquidity(5_000_000.0) == LiquidityTier.TIER_4

    # 1. Alış emri (BUY): 100 TL fiyat, 1.000 adet (100.000 TL notional)
    buy_res = engine.calculate_total_cost(
        side="BUY",
        price=100.0,
        quantity=1000,
        ticker="THYAO",
        avg_daily_volume=800_000_000.0,  # Tier 1
    )

    assert buy_res["ticker"] == "THYAO"
    assert buy_res["side"] == "BUY"
    assert buy_res["notional"] == 100000.0
    assert buy_res["total_cost"] > 0.0
    assert "commission" in buy_res["costs"]
    assert "bsmv" in buy_res["costs"]
    assert "spread" in buy_res["costs"]
    assert "slippage" in buy_res["costs"]
    assert "market_impact" in buy_res["costs"]

    # Alışta icra fiyatı karar fiyatından YÜKSEK olmalıdır (spread + slippage + impact aleyhe işler)
    assert buy_res["execution_price"] > 100.0

    # 2. Satış emri (SELL)
    sell_res = engine.calculate_total_cost(
        side="SELL",
        price=100.0,
        quantity=1000,
        ticker="THYAO",
        avg_daily_volume=800_000_000.0,
    )
    # Satışta icra fiyatı karar fiyatından DÜŞÜK olmalıdır
    assert sell_res["execution_price"] < 100.0

    # 3. Sıfır veya geçersiz miktar durumu
    zero_res = engine.calculate_total_cost("BUY", 0.0, 0, "TEST")
    assert zero_res["total_cost"] == 0.0
    assert zero_res["execution_price"] == 0.0

    # 4. Geçersiz yön
    with pytest.raises(ValueError, match="Geçersiz emir yönü"):
        engine.calculate_total_cost("INVALID_SIDE", 100.0, 10, "TEST")


def test_special_bist_conditions_and_round_trip():
    """Devre kesici, brüt takas ve al-sat (round-trip) maliyet testleri."""
    engine = TransactionCostEngine()

    # Normal durum
    normal_cost = engine.calculate_total_cost("BUY", 50.0, 1000, "GARAN", 500_000_000.0)

    # Devre kesici sonrası: spread %50 açılır
    cb_cost = engine.calculate_total_cost(
        "BUY", 50.0, 1000, "GARAN", 500_000_000.0, post_circuit_breaker=True
    )
    assert cb_cost["costs"]["spread"] > normal_cost["costs"]["spread"]

    # Brüt takaslı hisse: spread %30 açılır
    gs_cost = engine.calculate_total_cost(
        "BUY", 50.0, 1000, "GARAN", 500_000_000.0, is_gross_settlement=True
    )
    assert gs_cost["costs"]["spread"] > normal_cost["costs"]["spread"]

    # Round trip (Al-Sat tur maliyeti)
    rt = engine.estimate_round_trip_cost(
        ticker="THYAO",
        entry_price=300.0,
        quantity=500,
        avg_daily_volume=600_000_000.0,
    )
    assert "buy" in rt
    assert "sell" in rt
    assert rt["round_trip_cost"] > 0.0
    assert rt["break_even_return_pct"] > 0.0


def test_compute_costs_df_polars_vectorized():
    """Polars işlem DataFrame'ine toplu maliyet hesaplaması ekleme."""
    engine = TransactionCostEngine()

    trades = pl.DataFrame({
        "ticker": ["THYAO", "GARAN", "ASELS"],
        "side": ["BUY", "SELL", "ALIS"],
        "price": [300.0, 120.0, 60.0],
        "quantity": [100, 250, 500],
    })

    result_df = engine.compute_costs_df(trades)

    assert "calculated_total_cost" in result_df.columns
    assert "calculated_cost_pct" in result_df.columns
    assert "calculated_exec_price" in result_df.columns
    assert len(result_df) == 3
    assert all(c > 0.0 for c in result_df["calculated_total_cost"].to_list())

    # Boş DataFrame
    empty_df = pl.DataFrame()
    assert engine.compute_costs_df(empty_df).is_empty()

    # Tip kontrolü ve eksik sütun
    with pytest.raises(TypeError, match="Polars DataFrame olmalıdır"):
        engine.compute_costs_df([{"ticker": "THYAO"}])  # type: ignore

    bad_cols = pl.DataFrame({"ticker": ["THYAO"]})
    with pytest.raises(ValueError, match="zorunlu sütunlar eksik"):
        engine.compute_costs_df(bad_cols)


def test_transaction_cost_concurrency_and_alias():
    """Çoklu iş parçacığında işlem maliyeti hesaplama ve singleton kontrolleri."""
    engine = TransactionCostEngine()
    n_threads = 6
    trades_per_thread = 50

    def worker(tid: int):
        for i in range(trades_per_thread):
            engine.calculate_total_cost(
                side="BUY" if i % 2 == 0 else "SELL",
                price=50.0 + float(i),
                quantity=100 + i,
                ticker=f"TICK_{tid}",
                avg_daily_volume=100_000_000.0,
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as executor:
        futures = [executor.submit(worker, tid) for tid in range(n_threads)]
        for f in futures:
            f.result()

    # Alias ve singleton
    assert BISTCostParams is BISTFeeStructure
    assert isinstance(bist_transaction_cost, TransactionCostEngine)
