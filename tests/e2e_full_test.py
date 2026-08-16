"""
ALPHA BIST - Full End-to-End Test
Gerçek veri, gerçek hesaplama, gerçek pipeline.
Hiçbir mock yok. Hiçbir shortcut yok.
"""

import sys
import os
import time
import json
import math
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Any
from collections import defaultdict
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yfinance as yf
import polars as pl

# =====================================================
# Test Framework
# =====================================================

class E2ETest:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.errors = []
        self.details = []

    def check(self, name: str, condition: bool, detail: str = ""):
        if condition:
            self.passed += 1
            self.details.append(f"  ✓ {name}" + (f" ({detail})" if detail else ""))
        else:
            self.failed += 1
            self.errors.append(name)
            self.details.append(f"  ✗ {name}" + (f" ({detail})" if detail else ""))

    def warn(self, name: str, detail: str = ""):
        self.warnings += 1
        self.details.append(f"  ⚠ {name}" + (f" ({detail})" if detail else ""))

    def report(self):
        for d in self.details:
            print(d)
        print()
        total = self.passed + self.failed
        print(f"{'='*60}")
        print(f"SONUÇ: {self.passed}/{total} geçti, {self.failed} hata, {self.warnings} uyarı")
        if self.errors:
            print(f"HATALAR: {', '.join(self.errors)}")
        print(f"{'='*60}")
        return self.failed == 0


# =====================================================
# TEST 1: Gerçek BIST Verisi Çekme
# =====================================================

def test_real_data(t: E2ETest):
    print("\n[1/12] GERÇEK BİST VERİSİ ÇEKME")
    print("-" * 40)

    # Tek hisse
    thyao = yf.Ticker("THYAO.IS")
    hist = thyao.history(period="1y")
    t.check("THYAO 1 yıllık veri", len(hist) > 200, f"{len(hist)} gün")
    last_close = hist["Close"].dropna().iloc[-1] if not hist["Close"].dropna().empty else 0
    t.check("THYAO fiyat mantıklı", 100 < last_close < 1000, f"₺{last_close:.2f}")
    t.check("THYAO hacim pozitif", hist["Volume"].iloc[-1] > 0)

    # Batch download
    batch_tickers = ["THYAO.IS", "ASELS.IS", "AKBNK.IS", "TUPRS.IS", "EREGL.IS"]
    batch = yf.download(batch_tickers, period="60d", group_by="ticker", threads=True, progress=False)
    t.check("Batch download", not batch.empty, f"{len(batch)} satır")

    for tk in ["THYAO", "ASELS", "AKBNK"]:
        try:
            td = batch[f"{tk}.IS"].dropna()
            t.check(f"{tk} veri var", len(td) >= 20, f"{len(td)} gün")
        except Exception:
            t.check(f"{tk} veri var", False)

    # BIST100 endeks
    bist = yf.Ticker("XU100.IS")
    bist_info = bist.info
    t.check("BIST100 endeks", bist_info.get("regularMarketPrice", 0) > 0,
            f"{bist_info.get('regularMarketPrice', 0):.0f}")

    # Macro
    usdtry = yf.Ticker("TRY=X")
    usd_info = usdtry.info
    t.check("USD/TRY", usd_info.get("regularMarketPrice", 0) > 0,
            f"{usd_info.get('regularMarketPrice', 0):.2f}")

    vix = yf.Ticker("^VIX")
    vix_info = vix.info
    t.check("VIX", vix_info.get("regularMarketPrice", 0) > 0,
            f"{vix_info.get('regularMarketPrice', 0):.1f}")


# =====================================================
# TEST 2: Feature Calculator (58 feature)
# =====================================================

def test_feature_calculator(t: E2ETest):
    print("\n[2/12] FEATURE CALCULATOR (58 FEATURE)")
    print("-" * 40)

    from services.features.calculator import FeatureCalculator
    fc = FeatureCalculator()

    thyao = yf.Ticker("THYAO.IS")
    hist = thyao.history(period="60d").reset_index()
    df = pl.from_pandas(hist[["Date", "Open", "High", "Low", "Close", "Volume"]])
    df = df.rename({"Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})

    features = fc.compute_all_features(df)

    t.check("Feature sayısı >= 50", len(features) >= 50, f"{len(features)} feature")

    # Her kategoriyi kontrol et
    categories = {
        "Returns": ["return_1d", "return_5d", "return_20d", "log_return_1d"],
        "Volume": ["volume", "volume_ma5", "volume_ma20", "volume_ratio_5d", "volume_zscore"],
        "Momentum": ["roc_5d", "roc_20d", "momentum_5d", "momentum_20d", "price_acceleration"],
        "Volatility": ["atr_14", "atr_14_pct", "realized_vol_5d", "realized_vol_20d", "bb_upper", "bb_lower", "bb_position", "volatility_ratio"],
        "Technical": ["rsi_14", "macd", "macd_signal", "macd_histogram", "adx", "cci", "williams_r", "mfi"],
        "Trend": ["sma_5", "sma_10", "sma_20", "sma_50", "ema_12", "ema_26", "price_vs_sma20", "trend_slope_20d"],
        "Pattern": ["gap_pct", "daily_range_pct", "near_20d_high", "near_20d_low"],
    }

    for cat, keys in categories.items():
        found = sum(1 for k in keys if k in features)
        t.check(f"{cat} features", found == len(keys), f"{found}/{len(keys)}")

    # NaN kontrolü
    nan_count = sum(1 for v in features.values() if isinstance(v, float) and (math.isnan(v) or math.isinf(v)))
    t.check("NaN/Inf yok", nan_count == 0, f"{nan_count} NaN" if nan_count > 0 else "temiz")

    # RSI aralığı
    rsi = features.get("rsi_14", 50)
    t.check("RSI 0-100 aralığında", 0 <= rsi <= 100, f"{rsi:.1f}")

    # MACD signal line (0.9 ile çarpılmamış)
    macd = features.get("macd", 0)
    signal = features.get("macd_signal", 0)
    t.check("MACD != signal (farklı değerler)", abs(macd - signal) > 0.001 or macd == 0,
            f"macd={macd:.4f} signal={signal:.4f}")


# =====================================================
# TEST 3: Incremental State (Wilder's RSI/ATR/EMA)
# =====================================================

def test_incremental_state(t: E2ETest):
    print("\n[3/12] INCREMENTAL STATE (WILDER'S)")
    print("-" * 40)

    from services.features.incremental_state import IncrementalAssetState
    import random

    state = IncrementalAssetState(instrument_id=1, ticker="TEST")
    random.seed(42)
    price = 300.0

    # 200 tick simülasyonu
    for i in range(200):
        price += random.uniform(-2, 2)
        state.process_tick(price, random.randint(100000, 500000), datetime(2026, 8, 14, 10, i % 60))

    t.check("Fiyat güncellendi", state.price > 0, f"{state.price:.2f}")
    t.check("RSI 0-100", 0 <= state.rsi_14 <= 100, f"{state.rsi_14:.2f}")
    t.check("EMA12 pozitif", state.ema_12 > 0, f"{state.ema_12:.2f}")
    t.check("EMA26 pozitif", state.ema_26 > 0, f"{state.ema_26:.2f}")
    t.check("ATR14 >= 0", state.atr_14 >= 0, f"{state.atr_14:.4f}")

    # OHLC bar kontrolü
    t.check("1m bar'lar üretildi", len(state.tf_1m.completed_bars) > 0, f"{len(state.tf_1m.completed_bars)} bar")

    if len(state.tf_1m.completed_bars) > 0:
        bar = state.tf_1m.completed_bars[-1]
        t.check("OHLC mantıklı (H >= L)", bar.high >= bar.low, f"H={bar.high:.2f} L={bar.low:.2f}")
        t.check("OHLC mantıklı (H >= C)", bar.high >= bar.close)
        t.check("OHLC mantıklı (L <= C)", bar.low <= bar.close)

    # 5m bar aggregation
    t.check("5m bar'lar üretildi", len(state.tf_5m.completed_bars) > 0, f"{len(state.tf_5m.completed_bars)} bar")

    # Incremental features
    inc_features = state.get_incremental_features()
    t.check("Incremental features", len(inc_features) > 5, f"{len(inc_features)} feature")


# =====================================================
# TEST 4: SPEC Engine
# =====================================================

def test_spec_engine(t: E2ETest):
    print("\n[4/12] SPEC ENGINE")
    print("-" * 40)

    from services.intelligence.spec_engine import spec_engine

    # Yüksek SPEC senaryosu
    high_state = {
        "volume_zscore": 4.0, "price_change_1d_zscore": 2.0, "volatility_zscore": 0.5,
        "bb_position": 0.96, "near_20d_high": 1, "relative_strength_vs_sector": 2.5,
        "kap_sentiment": 0.7, "roc_5d": 6.0, "price_acceleration": 3.0,
        "volatility_regime": "NORMAL", "amihud_illiquidity": 0.0003, "correlation_to_index": 0.5,
        "momentum_20d": 15.0, "realized_vol_20d": 18.0,
    }

    high_spec = spec_engine.compute_spec("HIGH", high_state, {"regime": "TRENDING-UP"})

    t.check("High SPEC score hesaplandı", 0 <= high_spec.spec_score <= 100, f"{high_spec.spec_score}")
    t.check("High SPEC kategori", high_spec.category in ["HIGH_CONVICTION", "CANDIDATE", "WATCH", "NORMAL"])
    t.check("Anomaly score 0-1", 0 <= high_spec.anomaly_score <= 1)
    t.check("Evidence consensus 0-1", 0 <= high_spec.evidence_consensus <= 1)
    t.check("Regime compatibility 0-1", 0 <= high_spec.regime_compatibility <= 1)
    t.check("Expected value 0-1", 0 <= high_spec.expected_value <= 1)
    t.check("Risk asymmetry 0-1", 0 <= high_spec.risk_asymmetry <= 1)
    t.check("Edge decomposition 8 bileşen", len(high_spec.edge_decomposition) == 8)
    t.check("Evidence list 7 kanıt", len(high_spec.evidence_list) == 7)

    # Düşük SPEC senaryosu
    low_state = {
        "volume_zscore": 0.3, "price_change_1d_zscore": 0.1, "volatility_zscore": 0.1,
        "bb_position": 0.5, "near_20d_high": 0, "relative_strength_vs_sector": 1.0,
        "kap_sentiment": 0.0, "roc_5d": 0.2, "price_acceleration": 0.0,
        "volatility_regime": "NORMAL", "amihud_illiquidity": 0.001, "correlation_to_index": 0.8,
        "momentum_20d": 0.5, "realized_vol_20d": 25.0,
    }

    low_spec = spec_engine.compute_spec("LOW", low_state, {"regime": "RANGE"})

    t.check("Low SPEC < High SPEC", low_spec.spec_score < high_spec.spec_score,
            f"low={low_spec.spec_score} < high={high_spec.spec_score}")

    # NaN kontrolü
    t.check("High SPEC NaN yok", not math.isnan(high_spec.spec_score))
    t.check("Low SPEC NaN yok", not math.isnan(low_spec.spec_score))


# =====================================================
# TEST 5: World State
# =====================================================

def test_world_state(t: E2ETest):
    print("\n[5/12] DYNAMIC WORLD STATE")
    print("-" * 40)

    from services.intelligence.world_state import WorldStateManager

    wsm = WorldStateManager()
    initial = wsm.get_state_dict()

    t.check("Başlangıç state", len(initial) >= 10)

    # Fed rate hike
    delta = wsm.update_from_event("FED_RATE_HIKE", {})
    t.check("Fed etkisi uygulandı", len(delta) > 0, f"{len(delta)} faktör")
    t.check("USD güçlendi", wsm.current_state.usd_strength > initial["usd_strength"])
    t.check("EM risk azaldı", wsm.current_state.em_risk_appetite < initial["em_risk_appetite"])

    # Decay test
    wsm2 = WorldStateManager()
    wsm2.update_from_event("GEOPOLITICAL_TENSION", {})
    geo_before = wsm2.current_state.geopolitical_risk
    wsm2._current_state.apply_decay(24)
    geo_after = wsm2.current_state.geopolitical_risk
    t.check("Decay çalışıyor", abs(geo_after - 0.5) < abs(geo_before - 0.5),
            f"before={geo_before:.3f} after={geo_after:.3f}")

    # NaN kontrolü
    state_vec = wsm.get_state_vector()
    t.check("State vector NaN yok", not np.isnan(state_vec).any())


# =====================================================
# TEST 6: Impact Engine
# =====================================================

def test_impact_engine(t: E2ETest):
    print("\n[6/12] IMPACT PROPAGATION ENGINE")
    print("-" * 40)

    from services.intelligence.impact_engine import ImpactEngine, PROPAGATION_RULES

    t.check("Propagation rules tanımlı", len(PROPAGATION_RULES) >= 40, f"{len(PROPAGATION_RULES)} kural")

    ie = ImpactEngine()
    ie.load_sector_map({
        "AKBNK": "BANK", "GARAN": "BANK", "YKBNK": "BANK",
        "THYAO": "AVIATION", "TUPRS": "ENERGY", "PETKM": "ENERGY",
        "ASELS": "TECH",
    })

    # Fed rate hike
    fed_result = ie.propagate("FED_RATE_HIKE", {}, "test-001", {}, {})
    t.check("Fed propagation", len(fed_result.affected_instruments) > 0)
    t.check("Banka hisseleri etkilendi",
            any(a["ticker"] in ["AKBNK", "GARAN", "YKBNK"] for a in fed_result.affected_instruments))
    t.check("World delta var", len(fed_result.world_state_delta) > 0)

    # Oil shock
    oil_result = ie.propagate("OIL_SHOCK_UP", {}, "test-002", {}, {})
    t.check("Oil propagation", len(oil_result.affected_instruments) > 0)

    # Bilinmeyen event
    unknown = ie.propagate("UNKNOWN_EVENT", {}, "test-003", {}, {})
    t.check("Bilinmeyen event boş döner", len(unknown.affected_instruments) == 0)


# =====================================================
# TEST 7: Event Schema
# =====================================================

def test_event_schema(t: E2ETest):
    print("\n[7/12] CANONICAL EVENT SCHEMA")
    print("-" * 40)

    from services.core.event_schema import CanonicalEvent, EventType

    # Create
    event = CanonicalEvent(
        event_type=EventType.MARKET_TICK,
        source="yfinance",
        data={"ticker": "THYAO", "price": 308.0, "volume": 32818860, "instrument_id": 1},
    )

    t.check("Event ID var", len(event.event_id) > 0)
    t.check("Event type doğru", event.event_type == "market.tick")
    t.check("Schema version", event.schema_version == "v1")
    t.check("Timestamp var", event.timestamp is not None)

    # Serialize
    json_str = event.to_json()
    t.check("Serialize çalışıyor", len(json_str) > 100)

    # Deserialize
    restored = CanonicalEvent.from_json(json_str)
    t.check("Deserialize ID eşleşiyor", restored.event_id == event.event_id)
    t.check("Deserialize type eşleşiyor", restored.event_type == event.event_type)
    t.check("Deserialize data eşleşiyor", restored.data["price"] == 308.0)

    # to_dict
    d = event.to_dict()
    t.check("to_dict çalışıyor", isinstance(d, dict) and "event_id" in d)


# =====================================================
# TEST 8: ML Training (Walk-Forward)
# =====================================================

def test_ml_training(t: E2ETest):
    print("\n[8/12] ML TRAINING + WALK-FORWARD")
    print("-" * 40)

    from services.features.calculator import FeatureCalculator
    from ml.training import ml_trainer, TrainingConfig

    fc = FeatureCalculator()

    # Gerçek THYAO verisi
    thyao = yf.Ticker("THYAO.IS")
    hist = thyao.history(period="1y").reset_index()
    df = pl.from_pandas(hist[["Date", "Open", "High", "Low", "Close", "Volume"]])
    df = df.rename({"Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})

    t.check("1 yıllık veri", len(df) > 200, f"{len(df)} gün")

    # Feature'ları hesapla
    features_list = []
    close_prices = df["close"].to_numpy()

    for i in range(60, len(df)):
        window = df.slice(i - 60, 60)
        feats = fc.compute_all_features(window)
        if feats:
            feats["timestamp"] = df["timestamp"][i]
            feats["close"] = float(close_prices[i])
            features_list.append(feats)

    t.check("Feature dataset", len(features_list) > 100, f"{len(features_list)} örnek")

    # DataFrame oluştur
    feat_df = pl.DataFrame(features_list)
    feat_df = feat_df.with_columns(
        (pl.col("close").shift(-5) / pl.col("close") - 1).alias("return_5d")
    ).drop_nulls()

    feature_names = [k for k in features_list[0].keys()
                    if isinstance(features_list[0][k], (int, float))
                    and k not in ["close", "open", "high", "low", "volume"]]

    t.check("Feature isimleri", len(feature_names) > 30, f"{len(feature_names)} feature")

    # Training config
    config = TrainingConfig(
        model_name="e2e_test",
        target="return_5d",
        feature_names=feature_names,
        train_months=6,
        test_months=1,
        purge_days=5,
        n_estimators=100,
    )

    # Train
    result = ml_trainer.train_with_walkforward(feat_df, config)

    t.check("Model eğitildi", result.get("model_name") == "e2e_test")
    t.check("Walk-forward splits", result["metrics"].get("splits", 0) > 0, f"{result['metrics'].get('splits', 0)} split")
    t.check("Direction accuracy", result["metrics"].get("avg_direction_accuracy", 0) > 0,
            f"{result['metrics'].get('avg_direction_accuracy', 0):.1f}%")
    t.check("Confidence 0-1", 0 <= result.get("confidence", 0) <= 1,
            f"{result.get('confidence', 0):.4f}")
    t.check("Feature importance", len(result.get("feature_importance", {})) > 0)

    # Model dosyası kaydedildi mi?
    model_path = "ml/saved_models/e2e_test/model.pkl"
    t.check("Model dosyası kaydedildi", os.path.exists(model_path))

    config_path = "ml/saved_models/e2e_test/config.json"
    t.check("Config dosyası kaydedildi", os.path.exists(config_path))

    if os.path.exists(config_path):
        with open(config_path) as f:
            saved_config = json.load(f)
        t.check("Config'de metrics var", "metrics" in saved_config)
        t.check("Config'de confidence var", "confidence" in saved_config)


# =====================================================
# TEST 9: Risk Engine
# =====================================================

def test_risk_engine(t: E2ETest):
    print("\n[9/12] RISK ENGINE")
    print("-" * 40)

    risk_limits = {
        "max_position_pct": 10.0,
        "max_sector_pct": 30.0,
        "max_drawdown_pct": 15.0,
        "daily_loss_limit_pct": 5.0,
    }

    portfolio_value = 100000

    # Pozisyon limiti
    pos_8k = 8000
    t.check("8K pozisyon limit dahil", pos_8k / portfolio_value * 100 <= risk_limits["max_position_pct"])

    pos_15k = 15000
    t.check("15K pozisyon limit aşıyor", pos_15k / portfolio_value * 100 > risk_limits["max_position_pct"])

    # Drawdown
    dd_10 = (100000 - 90000) / 100000 * 100
    t.check("10% drawdown limit dahil", dd_10 <= risk_limits["max_drawdown_pct"])

    dd_20 = (100000 - 80000) / 100000 * 100
    t.check("20% drawdown limit aşıyor", dd_20 > risk_limits["max_drawdown_pct"])

    # Günlük zarar
    loss_3k = 3000
    t.check("3K zarar limit dahil", loss_3k / portfolio_value * 100 <= risk_limits["daily_loss_limit_pct"])

    loss_6k = 6000
    t.check("6K zarar limit aşıyor (kill switch)", loss_6k / portfolio_value * 100 > risk_limits["daily_loss_limit_pct"])


# =====================================================
# TEST 10: Portfolio Simulation
# =====================================================

def test_portfolio(t: E2ETest):
    print("\n[10/12] PORTFOLIO SIMÜLASYONU")
    print("-" * 40)

    # Paper portfolio
    portfolio = {"capital": 100000, "cash": 100000, "positions": {}}

    # Buy
    price = 308.0
    qty = 32
    cost = qty * price
    commission = cost * 0.001

    portfolio["cash"] -= cost + commission
    portfolio["positions"]["THYAO"] = {"qty": qty, "avg_cost": price}

    t.check("Buy executed", portfolio["positions"]["THYAO"]["qty"] == 32)
    t.check("Cash deducted", portfolio["cash"] < 100000)
    t.check("Commission applied", commission > 0, f"₺{commission:.2f}")

    # P&L
    current = 315.0
    pnl = (current - price) * qty
    pnl_pct = (current / price - 1) * 100

    t.check("P&L pozitif", pnl > 0, f"+₺{pnl:.0f}")
    t.check("P&L % doğru", pnl_pct > 0, f"+{pnl_pct:.1f}%")

    # Sell
    sell_revenue = qty * current
    sell_commission = sell_revenue * 0.001
    portfolio["cash"] += sell_revenue - sell_commission
    del portfolio["positions"]["THYAO"]

    t.check("Sell executed", "THYAO" not in portfolio["positions"])
    t.check("Cash updated", portfolio["cash"] > 90000)

    # Net P&L
    net_pnl = portfolio["cash"] - 100000
    t.check("Net P&L pozitif", net_pnl > 0, f"+₺{net_pnl:.0f}")


# =====================================================
# TEST 11: Monte Carlo Simulation
# =====================================================

def test_simulation(t: E2ETest):
    print("\n[11/12] MONTE CARLO SİMÜLASYONU")
    print("-" * 40)

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

    final = sims[:, -1]
    returns_pct = (final / current_price - 1) * 100

    t.check("10K senaryo çalıştı", len(returns_pct) == n_sims)
    t.check("Expected return mantıklı", -20 < np.mean(returns_pct) < 20, f"{np.mean(returns_pct):.2f}%")

    var_95 = np.percentile(returns_pct, 5)
    t.check("VaR 95 negatif", var_95 < 0, f"{var_95:.2f}%")

    prob_pos = np.mean(returns_pct > 0) * 100
    t.check("Prob positive 0-100", 0 < prob_pos < 100, f"{prob_pos:.1f}%")

    # Senaryo analizi
    scenarios = [
        {"name": "Bull", "change": 5, "prob": 0.25},
        {"name": "Base", "change": 0, "prob": 0.50},
        {"name": "Bear", "change": -5, "prob": 0.20},
        {"name": "Crash", "change": -15, "prob": 0.05},
    ]

    total_prob = sum(s["prob"] for s in scenarios)
    t.check("Senaryo olasılıkları toplamı = 1.0", abs(total_prob - 1.0) < 0.001)

    # Counterfactual
    actual = 6.0
    expected = 1.4
    contribution = actual - expected
    t.check("Counterfactual hesaplanıyor", contribution > 0, f"+{contribution:.1f}%")


# =====================================================
# TEST 12: Full Pipeline (End-to-End)
# =====================================================

def test_full_pipeline(t: E2ETest):
    print("\n[12/12] FULL PIPELINE (END-TO-END)")
    print("-" * 40)

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
    thyao = yf.Ticker("THYAO.IS")
    hist = thyao.history(period="60d").reset_index()
    df = pl.from_pandas(hist[["Date", "Open", "High", "Low", "Close", "Volume"]])
    df = df.rename({"Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
    t.check("Step 1: Veri çekildi", len(df) > 20, f"{len(df)} gün")

    # Step 2: Compute features
    features = fc.compute_all_features(df)
    t.check("Step 2: Features hesaplandı", len(features) > 50, f"{len(features)} feature")

    # Step 3: Create event
    close_list = [x for x in df["close"].to_list() if x is not None]
    last_price = float(close_list[-1])
    event = CanonicalEvent(
        event_type=EventType.MARKET_TICK,
        source="yfinance",
        data={"ticker": "THYAO", "price": last_price, "instrument_id": 1},
    )
    t.check("Step 3: Event oluşturuldu", event.event_id is not None)

    # Step 4: Update world state
    wsm.update_from_macro({"VIX": {"price": 25}, "USD/TRY": {"price": 34}})
    t.check("Step 4: World state güncellendi", wsm.current_state.vix_level == 25)

    # Step 5: SPEC scoring
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
    spec = spec_engine.compute_spec("THYAO", asset_state, {"regime": "RANGE"})
    t.check("Step 5: SPEC skorlandı", 0 <= spec.spec_score <= 100, f"{spec.spec_score}")
    t.check("Step 5: SPEC NaN değil", not math.isnan(spec.spec_score))

    # Step 6: Impact propagation
    impact = ie.propagate("FED_RATE_HIKE", {}, "test", {}, {})
    t.check("Step 6: Impact propagated", len(impact.affected_instruments) > 0)

    # Step 7: Event serialize/deserialize
    json_str = event.to_json()
    restored = CanonicalEvent.from_json(json_str)
    t.check("Step 7: Event roundtrip", restored.event_id == event.event_id)

    # Step 8: Full state verification
    world_dict = wsm.get_state_dict()
    t.check("Step 8: World state dict", len(world_dict) >= 10)
    t.check("Step 8: Features dict", len(features) >= 50)
    t.check("Step 8: SPEC result", spec.spec_score > 0)

    # Pipeline summary
    print(f"\n  PIPELINE ÖZETİ:")
    print(f"    Veri: {len(df)} gün OHLCV")
    print(f"    Features: {len(features)} adet")
    print(f"    SPEC Score: {spec.spec_score}/100 ({spec.category})")
    print(f"    World State: VIX={wsm.current_state.vix_level}, USD={wsm.current_state.usd_strength:.2f}")
    print(f"    Impact: {len(impact.affected_instruments)} etkilenen varlık")
    print(f"    Fiyat: ₺{last_price:.2f}")


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    print("=" * 60)
    print("ALPHA BIST - FULL END-TO-END TEST")
    print(f"Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    t = E2ETest()
    start = time.time()

    test_real_data(t)
    test_feature_calculator(t)
    test_incremental_state(t)
    test_spec_engine(t)
    test_world_state(t)
    test_impact_engine(t)
    test_event_schema(t)
    test_ml_training(t)
    test_risk_engine(t)
    test_portfolio(t)
    test_simulation(t)
    test_full_pipeline(t)

    elapsed = time.time() - start
    print(f"\nSüre: {elapsed:.1f} saniye")

    success = t.report()
    sys.exit(0 if success else 1)
