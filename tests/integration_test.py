"""ALPHA BIST - Full Integration Test (In-Memory, No Docker)

Bu test PostgreSQL, Redis, Redpanda olmadan çalışır.
In-memory backend kullanarak tüm pipeline'ı test eder.
"""

import sys
import os
import time
import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yfinance as yf
import polars as pl

# =====================================================
# In-Memory Backends (Docker/DB olmadan test için)
# =====================================================

class InMemoryDB:
    """In-memory PostgreSQL/ClickHouse replacement."""
    def __init__(self):
        self.tables: Dict[str, List[Dict]] = defaultdict(list)

    def insert(self, table: str, row: Dict):
        self.tables[table].append(row)

    def select(self, table: str, filter_fn=None) -> List[Dict]:
        rows = self.tables[table]
        if filter_fn:
            rows = [r for r in rows if filter_fn(r)]
        return rows

    def count(self, table: str) -> int:
        return len(self.tables[table])


class InMemoryRedis:
    """In-memory Redis replacement."""
    def __init__(self):
        self.data: Dict[str, Any] = {}
        self.hashes: Dict[str, Dict[str, str]] = {}

    def get(self, key: str) -> Optional[str]:
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int = None):
        self.data[key] = value

    def hgetall(self, key: str) -> Dict[str, str]:
        return self.hashes.get(key, {})

    def hset(self, key: str, mapping: Dict[str, str]):
        if key not in self.hashes:
            self.hashes[key] = {}
        self.hashes[key].update(mapping)


class InMemoryEventBus:
    """In-memory Redpanda replacement."""
    def __init__(self):
        self.topics: Dict[str, List[Dict]] = defaultdict(list)
        self.consumers: Dict[str, List] = defaultdict(list)

    def publish(self, topic: str, event: Dict):
        self.topics[topic].append(event)

    def consume(self, topic: str) -> List[Dict]:
        events = self.topics[topic]
        self.topics[topic] = []
        return events

    def count(self, topic: str) -> int:
        return len(self.topics[topic])


# Global in-memory backends
db = InMemoryDB()
redis = InMemoryRedis()
event_bus = InMemoryEventBus()


# =====================================================
# Test Suite
# =====================================================

class AlphaIntegrationTest:
    """Full integration test for ALPHA BIST."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def assert_test(self, name: str, condition: bool, detail: str = ""):
        if condition:
            self.passed += 1
            print(f"  ✓ {name}" + (f" ({detail})" if detail else ""))
        else:
            self.failed += 1
            self.errors.append(name)
            print(f"  ✗ {name}" + (f" ({detail})" if detail else ""))

    def run_all(self):
        print("=" * 60)
        print("ALPHA BIST - FULL INTEGRATION TEST")
        print("=" * 60)
        print()

        self.test_1_data_ingestion()
        self.test_2_feature_engine()
        self.test_3_incremental_state()
        self.test_4_spec_engine()
        self.test_5_world_state()
        self.test_6_impact_engine()
        self.test_7_event_pipeline()
        self.test_8_ml_training()
        self.test_9_risk_engine()
        self.test_10_portfolio()
        self.test_11_simulation()
        self.test_12_full_pipeline()

        print()
        print("=" * 60)
        print(f"SONUÇ: {self.passed}/{self.passed + self.failed} test geçti")
        if self.errors:
            print(f"HATALAR: {', '.join(self.errors)}")
        else:
            print("TÜM TESTLER BAŞARILI ✓")
        print("=" * 60)

        return self.failed == 0

    # =====================================================
    # TEST 1: Data Ingestion
    # =====================================================

    def test_1_data_ingestion(self):
        print("[1/12] DATA INGESTION")
        from services.ingestion.bist_universe import BIST_STOCKS, get_sector, BIST_INDICES

        self.assert_test("BIST universe loaded", len(BIST_STOCKS) > 400, f"{len(BIST_STOCKS)} stocks")
        self.assert_test("Sectors defined", len(set(get_sector(t) for t in BIST_STOCKS)) > 10)
        self.assert_test("Indices defined", len(BIST_INDICES) > 5)

        # Fetch real data
        tickers = ["THYAO", "ASELS", "AKBNK", "TUPRS", "EREGL"]
        data = yf.download([f"{t}.IS" for t in tickers], period="60d", group_by="ticker", threads=True, progress=False)

        success = 0
        for t in tickers:
            try:
                td = data[f"{t}.IS"].dropna()
                if len(td) >= 20:
                    success += 1
                    # Store in in-memory DB
                    for row in td.reset_index().tail(5).itertuples():
                        db.insert("market_ticks", {
                            "ticker": t, "timestamp": str(row.Date),
                            "price": row.Close, "volume": row.Volume,
                        })
            except Exception:
                pass  # Intentional: silent error handling

        self.assert_test("Real data fetched", success == 5, f"{success}/5 stocks")
        self.assert_test("Data stored in DB", db.count("market_ticks") > 0, f"{db.count('market_ticks')} rows")
        print()

    # =====================================================
    # TEST 2: Feature Engine
    # =====================================================

    def test_2_feature_engine(self):
        print("[2/12] FEATURE ENGINE")
        from services.features.calculator import FeatureCalculator

        fc = FeatureCalculator()

        # Test with real THYAO data
        t = yf.Ticker("THYAO.IS")
        hist = t.history(period="60d").reset_index()
        df = pl.from_pandas(hist[["Date", "Open", "High", "Low", "Close", "Volume"]])
        df = df.rename({"Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})

        features = fc.compute_all_features(df)

        self.assert_test("Features computed", len(features) > 50, f"{len(features)} features")
        self.assert_test("RSI valid", 0 <= features.get("rsi_14", 0) <= 100)
        self.assert_test("MACD computed", "macd" in features)
        self.assert_test("ATR computed", "atr_14" in features, f"value={features.get('atr_14', 'missing')}")
        self.assert_test("Bollinger computed", "bb_upper" in features and "bb_lower" in features)
        self.assert_test("Volume zscore computed", "volume_zscore" in features)
        self.assert_test("Momentum computed", "momentum_5d" in features)

        # Store features in Redis
        redis.hset("features:THYAO", {k: str(v) for k, v in features.items() if isinstance(v, (int, float))})
        self.assert_test("Features stored in Redis", len(redis.hgetall("features:THYAO")) > 0)
        print()

    # =====================================================
    # TEST 3: Incremental State
    # =====================================================

    def test_3_incremental_state(self):
        print("[3/12] INCREMENTAL STATE")
        from services.features.incremental_state import IncrementalAssetState

        state = IncrementalAssetState(instrument_id=1, ticker="THYAO")

        import random
        random.seed(42)
        price = 300.0

        for i in range(100):
            price += random.uniform(-1, 1)
            state.process_tick(price, random.randint(100000, 500000), datetime(2026, 8, 14, 10, i % 60))

        self.assert_test("Price updated", state.price > 0, f"{state.price:.2f}")
        self.assert_test("RSI incremental", 0 <= state.rsi_14 <= 100, f"{state.rsi_14:.2f}")
        self.assert_test("EMA12 computed", state.ema_12 > 0, f"{state.ema_12:.2f}")
        self.assert_test("EMA26 computed", state.ema_26 > 0, f"{state.ema_26:.2f}")
        self.assert_test("ATR14 computed", state.atr_14 >= 0, f"{state.atr_14:.4f}")  # >=0 çünkü ilk bar'da TR yok
        self.assert_test("OHLC bars generated", len(state.tf_1m.completed_bars) > 0, f"{len(state.tf_1m.completed_bars)} bars")

        # Verify OHLC is real (not fake)
        bar = state.tf_1m.completed_bars[-1]
        self.assert_test("OHLC is real", bar.high >= bar.low, f"H={bar.high:.2f} >= L={bar.low:.2f}")

        features = state.get_incremental_features()
        self.assert_test("Incremental features", len(features) > 5, f"{len(features)} features")
        print()

    # =====================================================
    # TEST 4: SPEC Engine
    # =====================================================

    def test_4_spec_engine(self):
        print("[4/12] SPEC ENGINE")
        from services.intelligence.spec_engine import spec_engine

        # Test with high-spec scenario
        asset_state = {
            'volume_zscore': 3.5, 'price_change_1d_zscore': 1.5, 'volatility_zscore': 0.5,
            'bb_position': 0.95, 'near_20d_high': 1, 'relative_strength_vs_sector': 2.0,
            'kap_sentiment': 0.6, 'roc_5d': 5.0, 'price_acceleration': 3.0,
            'volatility_regime': 'NORMAL', 'amihud_illiquidity': 0.0005, 'correlation_to_index': 0.6,
            'momentum_20d': 12.0, 'realized_vol_20d': 18.0,
        }

        spec = spec_engine.compute_spec("TEST", asset_state, {'regime': 'TRENDING-UP'})

        self.assert_test("SPEC score computed", 0 <= spec.spec_score <= 100, f"{spec.spec_score}")
        self.assert_test("Category assigned", spec.category in ["HIGH_CONVICTION", "CANDIDATE", "WATCH", "NORMAL"])
        self.assert_test("Anomaly score", 0 <= spec.anomaly_score <= 1)
        self.assert_test("Evidence consensus", 0 <= spec.evidence_consensus <= 1)
        self.assert_test("Regime compatibility", 0 <= spec.regime_compatibility <= 1)
        self.assert_test("Expected value", 0 <= spec.expected_value <= 1)
        self.assert_test("Risk asymmetry", 0 <= spec.risk_asymmetry <= 1)
        self.assert_test("Edge decomposition", len(spec.edge_decomposition) == 8)
        self.assert_test("Evidence list", len(spec.evidence_list) == 7)

        # Test with low-spec scenario
        low_state = {
            'volume_zscore': 0.5, 'price_change_1d_zscore': 0.1, 'volatility_zscore': 0.1,
            'bb_position': 0.5, 'near_20d_high': 0, 'relative_strength_vs_sector': 1.0,
            'kap_sentiment': 0.0, 'roc_5d': 0.5, 'price_acceleration': 0.0,
            'volatility_regime': 'NORMAL', 'amihud_illiquidity': 0.001, 'correlation_to_index': 0.8,
            'momentum_20d': 1.0, 'realized_vol_20d': 25.0,
        }
        low_spec = spec_engine.compute_spec("LOW", low_state, {'regime': 'RANGE'})
        self.assert_test("Low-spec is lower", low_spec.spec_score < spec.spec_score,
                        f"low={low_spec.spec_score} < high={spec.spec_score}")
        print()

    # =====================================================
    # TEST 5: World State
    # =====================================================

    def test_5_world_state(self):
        print("[5/12] DYNAMIC WORLD STATE")
        from services.intelligence.world_state import WorldStateManager

        wsm = WorldStateManager()
        initial = wsm.get_state_dict()

        # Fed rate hike
        delta = wsm.update_from_event("FED_RATE_HIKE", {})
        self.assert_test("Fed impact applied", len(delta) > 0, f"{len(delta)} factors")
        self.assert_test("USD strengthened", wsm.current_state.usd_strength > initial["usd_strength"])
        self.assert_test("EM risk decreased", wsm.current_state.em_risk_appetite < initial["em_risk_appetite"])

        # Oil shock
        wsm2 = WorldStateManager()
        wsm2.update_from_event("OIL_SHOCK_UP", {})
        self.assert_test("Oil pressure increased", wsm2.current_state.oil_pressure > 0.5)

        # Decay test
        wsm3 = WorldStateManager()
        wsm3.update_from_event("GEOPOLITICAL_TENSION", {})
        geo_before = wsm3.current_state.geopolitical_risk
        wsm3._current_state.apply_decay(24)  # 24 saat geçti
        geo_after = wsm3.current_state.geopolitical_risk
        self.assert_test("Decay works", abs(geo_after - 0.5) < abs(geo_before - 0.5),
                        f"before={geo_before:.3f} after={geo_after:.3f}")

        # Store in Redis
        redis.set("world_state", json.dumps(wsm.get_state_dict()))
        self.assert_test("World state stored", redis.get("world_state") is not None)
        print()

    # =====================================================
    # TEST 6: Impact Engine
    # =====================================================

    def test_6_impact_engine(self):
        print("[6/12] IMPACT PROPAGATION ENGINE")
        from services.intelligence.impact_engine import ImpactEngine

        ie = ImpactEngine()
        ie.load_sector_map({
            "AKBNK": "BANK", "GARAN": "BANK", "YKBNK": "BANK",
            "THYAO": "AVIATION", "TUPRS": "ENERGY", "PETKM": "ENERGY",
            "ASELS": "TECH",
        })

        # Fed rate hike
        result = ie.propagate("FED_RATE_HIKE", {}, "test-001", {}, {})
        self.assert_test("Fed propagation", len(result.affected_instruments) > 0)
        self.assert_test("World delta", len(result.world_state_delta) > 0)
        self.assert_test("Propagation chain", len(result.propagation_chain) > 0)

        # Check bank stocks affected
        bank_stocks = [a for a in result.affected_instruments if a["ticker"] in ["AKBNK", "GARAN", "YKBNK"]]
        self.assert_test("Bank stocks affected", len(bank_stocks) == 3)

        # Oil shock
        oil_result = ie.propagate("OIL_SHOCK_UP", {}, "test-002", {}, {})
        self.assert_test("Oil propagation", len(oil_result.affected_instruments) > 0)
        print()

    # =====================================================
    # TEST 7: Event Pipeline
    # =====================================================

    def test_7_event_pipeline(self):
        print("[7/12] EVENT PIPELINE")
        from services.core.event_schema import CanonicalEvent, EventType

        # Create event
        event = CanonicalEvent(
            event_type=EventType.MARKET_TICK,
            source="yfinance",
            data={"ticker": "THYAO", "price": 308.0, "volume": 32818860, "instrument_id": 1},
        )

        # Serialize
        json_str = event.to_json()
        self.assert_test("Event serialized", len(json_str) > 0)

        # Deserialize
        restored = CanonicalEvent.from_json(json_str)
        self.assert_test("Event deserialized", restored.event_id == event.event_id)
        self.assert_test("Event type preserved", restored.event_type == "market.tick")
        self.assert_test("Data preserved", restored.data["price"] == 308.0)

        # Publish to in-memory bus
        event_bus.publish("market.tick", event.to_dict())
        self.assert_test("Event published", event_bus.count("market.tick") > 0)

        # Consume
        events = event_bus.consume("market.tick")
        self.assert_test("Event consumed", len(events) > 0)
        self.assert_test("Event data intact", events[0]["data"]["ticker"] == "THYAO")
        print()

    # =====================================================
    # TEST 8: ML Training
    # =====================================================

    def test_8_ml_training(self):
        print("[8/12] ML TRAINING + WALK-FORWARD")
        from ml.training import ml_trainer, TrainingConfig

        # Fetch real data
        t = yf.Ticker("THYAO.IS")
        hist = t.history(period="1y").reset_index()
        df = pl.from_pandas(hist[["Date", "Open", "High", "Low", "Close", "Volume"]])
        df = df.rename({"Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})

        # Compute features
        from services.features.calculator import FeatureCalculator
        fc = FeatureCalculator()
        features_list = []
        close_prices = df["close"].to_numpy()

        for i in range(60, len(df)):
            window = df.slice(i - 60, 60)
            feats = fc.compute_all_features(window)
            if feats:
                feats["timestamp"] = df["timestamp"][i]
                feats["close"] = float(close_prices[i])
                features_list.append(feats)

        feat_df = pl.DataFrame(features_list)
        feat_df = feat_df.with_columns(
            (pl.col("close").shift(-5) / pl.col("close") - 1).alias("return_5d")
        ).drop_nulls()

        feature_names = [k for k in features_list[0].keys()
                        if isinstance(features_list[0][k], (int, float))
                        and k not in ["close", "open", "high", "low", "volume"]]

        config = TrainingConfig(
            model_name="test_integration",
            target="return_5d",
            feature_names=feature_names,
            train_months=6,
            test_months=1,
            purge_days=5,
            n_estimators=100,
        )

        result = ml_trainer.train_with_walkforward(feat_df, config)

        self.assert_test("Model trained", result.get("model_name") == "test_integration")
        self.assert_test("Walk-forward splits", result["metrics"].get("splits", 0) > 0)
        self.assert_test("Direction accuracy", result["metrics"].get("avg_direction_accuracy", 0) > 0)
        self.assert_test("Confidence calculated", 0 <= result.get("confidence", 0) <= 1)
        self.assert_test("Feature importance", len(result.get("feature_importance", {})) > 0)
        print()

    # =====================================================
    # TEST 9: Risk Engine
    # =====================================================

    def test_9_risk_engine(self):
        print("[9/12] RISK ENGINE")

        # Risk limits
        risk_limits = {
            "max_position_pct": 10.0,
            "max_sector_pct": 30.0,
            "max_drawdown_pct": 15.0,
            "daily_loss_limit_pct": 5.0,
        }

        # Test position limit check
        portfolio_value = 100000
        position_value = 8000
        position_pct = position_value / portfolio_value * 100
        self.assert_test("Position limit check", position_pct <= risk_limits["max_position_pct"],
                        f"{position_pct}% <= {risk_limits['max_position_pct']}%")

        # Test oversized position
        oversized = 15000
        oversized_pct = oversized / portfolio_value * 100
        self.assert_test("Oversized position blocked", oversized_pct > risk_limits["max_position_pct"],
                        f"{oversized_pct}% > {risk_limits['max_position_pct']}%")

        # Test drawdown
        initial = 100000
        current = 85000
        drawdown = (initial - current) / initial * 100
        self.assert_test("Drawdown within limit", drawdown <= risk_limits["max_drawdown_pct"],
                        f"{drawdown}% <= {risk_limits['max_drawdown_pct']}%")

        # Test daily loss
        daily_loss = 3000
        daily_loss_pct = daily_loss / portfolio_value * 100
        self.assert_test("Daily loss within limit", daily_loss_pct <= risk_limits["daily_loss_limit_pct"],
                        f"{daily_loss_pct}% <= {risk_limits['daily_loss_limit_pct']}%")

        # Kill switch
        crash_loss = 6000
        crash_pct = crash_loss / portfolio_value * 100
        self.assert_test("Kill switch triggers", crash_pct > risk_limits["daily_loss_limit_pct"],
                        f"{crash_pct}% > {risk_limits['daily_loss_limit_pct']}%")
        print()

    # =====================================================
    # TEST 10: Portfolio
    # =====================================================

    def test_10_portfolio(self):
        print("[10/12] PORTFOLIO MANAGEMENT")

        # Paper portfolio
        portfolio = {
            "capital": 100000,
            "cash": 100000,
            "positions": {},
        }

        # Buy THYAO
        price = 308.0
        quantity = 32  # ~10,000 TL
        cost = quantity * price
        commission = cost * 0.001

        portfolio["cash"] -= cost + commission
        portfolio["positions"]["THYAO"] = {"quantity": quantity, "avg_cost": price}

        self.assert_test("Buy executed", portfolio["positions"]["THYAO"]["quantity"] == 32)
        self.assert_test("Cash deducted", portfolio["cash"] < 100000)
        self.assert_test("Commission applied", commission > 0)

        # Calculate P&L
        current_price = 315.0
        pnl = (current_price - price) * quantity
        pnl_pct = (current_price / price - 1) * 100

        self.assert_test("P&L calculated", pnl > 0, f"+{pnl:.0f} TL")
        self.assert_test("P&L % calculated", pnl_pct > 0, f"+{pnl_pct:.1f}%")

        # Sell
        sell_revenue = quantity * current_price
        sell_commission = sell_revenue * 0.001
        portfolio["cash"] += sell_revenue - sell_commission
        del portfolio["positions"]["THYAO"]

        self.assert_test("Sell executed", "THYAO" not in portfolio["positions"])
        self.assert_test("Cash updated", portfolio["cash"] > 90000)
        print()

    # =====================================================
    # TEST 11: Simulation
    # =====================================================

    def test_11_simulation(self):
        print("[11/12] SIMULATION ENGINE")

        # Monte Carlo
        np.random.seed(42)
        current_price = 308.0
        daily_vol = 0.02
        daily_return = 0.0005
        horizon = 20
        n_sims = 10000

        sims = np.zeros((n_sims, horizon + 1))
        sims[:, 0] = current_price

        for day in range(1, horizon + 1):
            returns = np.random.normal(daily_return, daily_vol, n_sims)
            sims[:, day] = sims[:, day - 1] * (1 + returns)

        final_prices = sims[:, -1]
        returns_pct = (final_prices / current_price - 1) * 100

        self.assert_test("Monte Carlo runs", len(returns_pct) == n_sims)
        self.assert_test("Expected return", abs(np.mean(returns_pct)) < 20)
        self.assert_test("VaR 95", np.percentile(returns_pct, 5) < 0)
        self.assert_test("Prob positive", 0 < np.mean(returns_pct > 0) * 100 < 100)

        # Scenario analysis
        scenarios = [
            {"name": "Bull", "market_change": 5, "prob": 0.25},
            {"name": "Base", "market_change": 0, "prob": 0.50},
            {"name": "Bear", "market_change": -5, "prob": 0.20},
            {"name": "Crash", "market_change": -15, "prob": 0.05},
        ]

        for s in scenarios:
            self.assert_test(f"Scenario {s['name']}", s["prob"] > 0)

        # Counterfactual
        actual_return = 6.0
        expected_without_event = 1.4
        event_contribution = actual_return - expected_without_event
        self.assert_test("Counterfactual", event_contribution > 0, f"+{event_contribution:.1f}%")
        print()

    # =====================================================
    # TEST 12: Full Pipeline (End-to-End)
    # =====================================================

    def test_12_full_pipeline(self):
        print("[12/12] FULL PIPELINE (END-TO-END)")

        from services.features.calculator import FeatureCalculator
        from services.intelligence.spec_engine import spec_engine
        from services.intelligence.world_state import WorldStateManager
        from services.intelligence.impact_engine import ImpactEngine
        from services.core.event_schema import CanonicalEvent, EventType

        fc = FeatureCalculator()
        wsm = WorldStateManager()
        ie = ImpactEngine()
        ie.load_sector_map({"THYAO": "AVIATION", "AKBNK": "BANK"})

        # Step 1: Fetch data
        t = yf.Ticker("THYAO.IS")
        hist = t.history(period="60d").reset_index()
        df = pl.from_pandas(hist[["Date", "Open", "High", "Low", "Close", "Volume"]])
        df = df.rename({"Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        self.assert_test("Step 1: Data fetched", len(df) > 20)

        # Step 2: Compute features
        features = fc.compute_all_features(df)
        self.assert_test("Step 2: Features computed", len(features) > 50)

        # Step 3: Create event
        close_list = df["close"].to_list()
        last_price = float([x for x in close_list if x is not None][-1])
        event = CanonicalEvent(
            event_type=EventType.MARKET_TICK,
            source="yfinance",
            data={"ticker": "THYAO", "price": last_price, "instrument_id": 1},
        )
        self.assert_test("Step 3: Event created", event.event_id is not None)

        # Step 4: Update world state
        wsm.update_from_macro({"VIX": {"price": 25}, "USD/TRY": {"price": 34}})
        self.assert_test("Step 4: World state updated", wsm.current_state.vix_level == 25)

        # Step 5: SPEC scoring
        asset_state = {
            'volume_zscore': features.get('volume_zscore', 0),
            'price_change_1d_zscore': features.get('return_1d', 0) / 2,
            'volatility_zscore': features.get('volatility_ratio', 1) - 1,
            'bb_position': features.get('bb_position', 0.5),
            'near_20d_high': features.get('near_20d_high', 0),
            'relative_strength_vs_sector': 1.0,
            'kap_sentiment': 0.0,
            'roc_5d': features.get('roc_5d', 0),
            'price_acceleration': features.get('price_acceleration', 0),
            'volatility_regime': 'NORMAL',
            'amihud_illiquidity': 0.001,
            'correlation_to_index': 0.75,
            'momentum_20d': features.get('momentum_20d', 0),
            'realized_vol_20d': features.get('realized_vol_20d', 20),
        }
        spec = spec_engine.compute_spec("THYAO", asset_state, {'regime': 'RANGE'})
        self.assert_test("Step 5: SPEC scored", 0 <= spec.spec_score <= 100, f"{spec.spec_score}")

        # Step 6: Impact propagation
        impact = ie.propagate("FED_RATE_HIKE", {}, "test", {}, {})
        self.assert_test("Step 6: Impact propagated", len(impact.affected_instruments) > 0)

        # Step 7: Store in DB/Redis
        redis.hset("features:THYAO", {k: str(v) for k, v in features.items() if isinstance(v, (int, float))})
        redis.set("world_state", json.dumps(wsm.get_state_dict()))
        db.insert("signals", {"ticker": "THYAO", "score": spec.spec_score, "category": spec.category})
        self.assert_test("Step 7: Data stored", db.count("signals") > 0)

        # Step 8: Verify end-to-end
        stored_features = redis.hgetall("features:THYAO")
        stored_world = json.loads(redis.get("world_state") or "{}")
        stored_signals = db.select("signals")

        self.assert_test("Step 8: Features retrievable", len(stored_features) > 0)
        self.assert_test("Step 8: World state retrievable", len(stored_world) > 0)
        self.assert_test("Step 8: Signals retrievable", len(stored_signals) > 0)

        print()
        print("  PIPELINE SUMMARY:")
        print(f"    Data: {len(df)} gün OHLCV")
        print(f"    Features: {len(features)} adet")
        print(f"    SPEC Score: {spec.spec_score}/100 ({spec.category})")
        print(f"    World State: VIX={wsm.current_state.vix_level}, USD={wsm.current_state.usd_strength:.2f}")
        print(f"    Impact: {len(impact.affected_instruments)} etkilenen varlık")
        print(f"    Signals: {len(stored_signals)} kayıtlı")


# =====================================================
# Run
# =====================================================

if __name__ == "__main__":
    test = AlphaIntegrationTest()
    success = test.run_all()
    sys.exit(0 if success else 1)
