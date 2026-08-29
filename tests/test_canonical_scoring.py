#!/usr/bin/env python3
import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
ALPHA BIST — Canonical Scoring & Decision Pipeline Tests

Tek karar mimarisi testleri:
- 9 motor feature'larının canonical score pipeline'a ulaşması
- Seasonality'nin gerçekten kullanılması
- Missing/unknown feature'ın yanlışlıkla0 sayılmaması
- Risk ve opportunity score'un ayrı kalması
- Decision Engine'in tek final karar noktası olması
- Aynı input → deterministic aynı karar
- Feature collision olmaması
"""

import sys

# =====================================================
# HELPERS
# =====================================================


def _make_features() -> Any:
    """Test feature seti — tüm motorlardan."""
    return {
        # Calculator
        "rsi_14": 55.0,
        "rsi_5": 58.0,
        "momentum_20d": 5.0,
        "roc_5d": 2.0,
        "roc_20d": 8.0,
        "roc_60d": 15.0,
        "macd_hist": 0.5,
        "bb_position": 0.6,
        "adx": 28.0,
        "atr_pct": 2.5,
        "volume_zscore": 1.5,
        "volume_trend": 10.0,
        "volatility_20d": 20.0,
        "realized_vol_20d": 18.0,
        "price_vs_sma20": 2.0,
        "price_vs_sma50": 5.0,
        "obv": 1000000,
        # Motor 1
        "rs_vs_bist_5d": 3.0,
        "rs_vs_sector_5d": 2.0,
        "rs_trend": 0.5,
        "rs_peer_rank_5d": 0.8,
        # Motor 2
        "trend_slope_20d": 0.3,
        "trend_r2_20d": 0.6,
        "momentum_acceleration": 1.5,
        "momentum_accel_trend": 1.0,
        "near_20d_high": 1.0,
        "drawdown_20d": 3.0,
        "breakout_failure_20d": 0.0,
        "recovery_strength_20d": 0.0,
        # Motor 3
        "volume_percentile_20d": 0.8,
        "tick_rule_20d": 0.3,
        "vwap_deviation_20d": 1.0,
        "volume_up_down_ratio_20d": 1.5,
        "avg_volume_5d": 200000,
        # Motor 4
        "fcf_yield_pct": 5.0,
        "fcf_margin": 10.0,
        "balance_sheet_quality": 75.0,
        "value_score": 60.0,
        "quality_score": 55.0,
        "growth_score": 40.0,
        "raw_roe": 0.15,
        "raw_roa": 0.10,
        "raw_profit_margin": 0.12,
        # Motor 5
        "kap_sentiment_avg": 0.5,
        "kap_sentiment_weighted": 0.5,
        "news_sentiment_weighted": 0.3,
        "combined_sentiment": 0.42,
        "kap_avg_importance": 0.9,
        "sentiment_momentum": 0.2,
        # Motor 6
        "catalyst_count": 2,
        "catalyst_importance": 0.9,
        "catalyst_days_nearest": 5,
        "catalyst_time_decay_score": 0.7,
        # Motor 7
        "is_falling_5d": 0.0,
        "falling_is_temporary": 0.5,
        "catch_falling_knife_risk": 10.0,
        # Motor 8
        "bb_zscore_20d": 0.5,
        "mean_reversion_signal": 0.0,
        "mean_reversion_strength": 0.0,
        # Motor 9
        "seasonality_current_month_avg": 0.3,
        "seasonality_current_month_win_rate": 0.6,
        "seasonality_current_quarter_avg": 1.5,
        # Aliases
        "roe": 0.15,
        "roa": 0.10,
        "profit_margin_pct": 0.12,
        "volume_percentile": 0.8,
        "tick_rule": 0.3,
        "vwap_deviation": 1.0,
        "volume_up_down_ratio": 1.5,
        "rs_peer_rank": 0.8,
        "recovery_strength": 0.0,
        "breakout_failure": 0.0,
        "return_5d": 2.0,
        "return_20d": 8.0,
    }


# =====================================================
# 1. CANONICAL SCORE VECTOR
# =====================================================


def test_score_vector_dimensions() -> Any:
    """ScoreVector12 boyut üretiyor mu?"""
    from services.core.canonical_scoring import canonical_scoring

    issues = []

    features = _make_features()
    sv = canonical_scoring.compute_score_vector("TEST", features, "BULL")

    dims = sv.to_dict()
    expected_dims = [
        "technical",
        "momentum",
        "relative_strength",
        "volume",
        "fundamental",
        "news_sentiment",
        "catalyst",
        "mean_reversion",
        "seasonality",
        "market_regime",
        "risk",
        "data_quality",
    ]

    for dim in expected_dims:
        if dim not in dims:
            issues.append(f"Boyut eksik: {dim}")
        elif not isinstance(dims[dim], (int, float)):
            issues.append(f"Boyut tipi yanlış: {dim} = {type(dims[dim])}")

    return "ScoreVector dimensions", len(issues) == 0, issues


def test_all_motor_dimensions_nonzero() -> Any:
    """Tüm motor boyutları gerçekten0'dan farklı değer üretiyor mu?"""
    from services.core.canonical_scoring import canonical_scoring

    issues = []

    features = _make_features()
    sv = canonical_scoring.compute_score_vector("TEST", features, "BULL")
    dims = sv.to_dict()

    # Seasonality hariç tüm boyutlar0'dan farklı olmalı
    for dim, val in dims.items():
        if val == 0.0 and dim != "seasonality":
            issues.append(f"{dim} = 0.0 (motor katkı yapmıyor)")

    return "Motor dimensions nonzero", len(issues) == 0, issues


def test_seasonality_used() -> Any:
    """Seasonality boyutu gerçekten kullanılıyor mu?"""
    from services.core.canonical_scoring import canonical_scoring

    issues = []

    # Seasonality feature'ları var
    features = _make_features()
    sv = canonical_scoring.compute_score_vector("TEST", features, "BULL")

    if sv.seasonality == 0.0:
        issues.append("Seasonality = 0.0 — feature'lar var ama kullanılmıyor")
    elif sv.seasonality == 50.0:
        # 50 nötr — mevsimsellik bilgisi yok anlamına gelebilir
        month_wr = features.get("seasonality_current_month_win_rate", 0)
        if month_wr > 0.5:
            issues.append(f"Seasonality nötr (50) ama win_rate={month_wr} > 0.5")

    return "Seasonality used", len(issues) == 0, issues


# =====================================================
# 2. MISSING FEATURE HANDLING
# =====================================================


def test_missing_not_zero() -> Any:
    """Eksik feature otomatik0'a dönüşmemeli."""
    from services.core.canonical_scoring import canonical_scoring

    issues = []

    # Boş feature seti
    empty_features = {}
    sv = canonical_scoring.compute_score_vector("TEST", empty_features, "UNKNOWN")

    # data_quality düşük olmalı
    if sv.data_quality > 80:
        issues.append(f"Boş feature ile data_quality çok yüksek: {sv.data_quality}")

    # Risk skoru makul olmalı (ne0 ne100)
    if sv.risk == 0.0 or sv.risk == 100.0:
        issues.append(f"Boş feature ile risk aşırı: {sv.risk}")

    return "Missing not zero", len(issues) == 0, issues


def test_data_quality_score() -> Any:
    """Veri kalitesi skoru feature availability'ye bağlı mı?"""
    from services.core.canonical_scoring import canonical_scoring

    issues = []

    # Tam veri
    full = canonical_scoring.compute_score_vector("TEST", _make_features(), "BULL")

    # Eksik veri
    sparse = canonical_scoring.compute_score_vector("TEST", {"rsi_14": 50.0}, "BULL")

    if sparse.data_quality >= full.data_quality:
        issues.append(f"Eksik veri data_quality düşmeli: full={full.data_quality}, sparse={sparse.data_quality}")

    return "Data quality score", len(issues) == 0, issues


# =====================================================
# 3. RISK vs OPPORTUNITY SEPARATION
# =====================================================


def test_risk_opportunity_separate() -> Any:
    """Risk ve opportunity ayrı kavramlar mı?"""
    from services.core.canonical_scoring import canonical_scoring

    issues = []

    # Yüksek fırsat + yüksek risk
    features = _make_features()
    features["atr_pct"] = 8.0  # Yüksek volatilite
    features["drawdown_20d"] = 20.0  # Büyük düşüş
    features["momentum_20d"] = 15.0  # Güçlü momentum

    cs = canonical_scoring.compute_canonical_score("TEST", features, "BULL")

    # Opportunity yüksek olmalı (momentum sayesinde)
    if cs.opportunity_score < 50:
        issues.append(f"Opportunity çok düşük: {cs.opportunity_score}")

    # Risk düşük olmalı (yüksek volatilite nedeniyle)
    if cs.risk_score > 50:
        issues.append(f"Risk çok yüksek (güvenli): {cs.risk_score} — atr_pct=8, dd=20")

    # İkisi farklı şey ölçüyor olmalı
    if abs(cs.opportunity_score - cs.risk_score) < 10:
        issues.append(f"Risk ve opportunity birbirine çok yakın: opp={cs.opportunity_score}, risk={cs.risk_score}")

    return "Risk vs opportunity separate", len(issues) == 0, issues


# =====================================================
# 4. DECISION ENGINE — TEK KARAR NOKTASI
# =====================================================


def test_decision_from_canonical() -> Any:
    """Decision Engine canonical score'dan karar üretiyor mu?"""
    from services.core.canonical_scoring import canonical_scoring
    from services.core.decision_engine import decision_engine

    issues = []

    features = _make_features()
    cs = canonical_scoring.compute_canonical_score("TEST", features, "BULL")

    decision = decision_engine.decide_from_canonical(cs, price=100.0)

    if decision.action not in ("BUY", "SELL", "HOLD", "NO_ACTION"):
        issues.append(f"Geçersiz action: {decision.action}")

    if decision.ticker != "TEST":
        issues.append(f"Ticker yanlış: {decision.ticker}")

    if decision.direction not in ("LONG", "SHORT", "NEUTRAL"):
        issues.append(f"Geçersiz direction: {decision.direction}")

    if not decision.reasons:
        issues.append("Reasons boş")

    return "Decision from canonical", len(issues) == 0, issues


def test_decision_is_deterministic() -> Any:
    """Aynı input → aynı karar (deterministic)."""
    from services.core.canonical_scoring import canonical_scoring
    from services.core.decision_engine import decision_engine

    issues = []

    features = _make_features()

    cs1 = canonical_scoring.compute_canonical_score("TEST", features, "BULL")
    cs2 = canonical_scoring.compute_canonical_score("TEST", features, "BULL")

    d1 = decision_engine.decide_from_canonical(cs1)
    d2 = decision_engine.decide_from_canonical(cs2)

    if d1.action != d2.action:
        issues.append(f"Non-deterministic: {d1.action} != {d2.action}")
    if d1.score != d2.score:
        issues.append(f"Non-deterministic score: {d1.score} != {d2.score}")
    if d1.conviction != d2.conviction:
        issues.append(f"Non-deterministic conviction: {d1.conviction} != {d2.conviction}")

    return "Deterministic decision", len(issues) == 0, issues


def test_decision_blocks_high_risk() -> Any:
    """Yüksek riskli durumda BUY engelleniyor mu?"""
    from services.core.canonical_scoring import canonical_scoring
    from services.core.decision_engine import decision_engine

    issues = []

    features = _make_features()
    features["atr_pct"] = 10.0  # Çok yüksek volatilite
    features["drawdown_20d"] = 30.0  # Büyük düşüş
    features["catch_falling_knife_risk"] = 80.0

    cs = canonical_scoring.compute_canonical_score("TEST", features, "BEAR")
    decision = decision_engine.decide_from_canonical(cs)

    # Risk skoru düşükse BUY engellenmeli
    if cs.risk_score < 30 and decision.action == "BUY":
        issues.append(f"Yüksek risk ({cs.risk_score:.0f}) rağmen BUY engellenmedi")

    return "Decision blocks high risk", len(issues) == 0, issues


def test_decision_low_confidence() -> Any:
    """Düşük confidence ile NO_ACTION üretiliyor mu?"""
    from services.core.canonical_scoring import canonical_scoring
    from services.core.decision_engine import decision_engine

    issues = []

    # Çok az feature → düşük confidence
    sparse_features = {"rsi_14": 50.0}
    cs = canonical_scoring.compute_canonical_score("TEST", sparse_features, "UNKNOWN")

    if cs.confidence > 0.5:
        issues.append(f"Confidence çok yüksek (sparse): {cs.confidence}")

    decision = decision_engine.decide_from_canonical(cs)
    if decision.action != "NO_ACTION":
        issues.append(f"Düşük confidence ile NO_ACTION beklenen: {decision.action}")

    return "Low confidence NO_ACTION", len(issues) == 0, issues


# =====================================================
# 5. REGIME EFFECT
# =====================================================


def test_regime_changes_scoring() -> Any:
    """Rejim değişince skor değişiyor mu?"""
    from services.core.canonical_scoring import canonical_scoring

    issues = []

    features = _make_features()

    bull = canonical_scoring.compute_canonical_score("TEST", features, "BULL")
    bear = canonical_scoring.compute_canonical_score("TEST", features, "BEAR")

    if bull.opportunity_score == bear.opportunity_score:
        issues.append(f"BULL ve BEAR aynı skor: {bull.opportunity_score}")

    # BULL'da momentum daha ağır, BEAR'da risk daha ağır
    bull_mom_weight = canonical_scoring.REGIME_WEIGHTS["BULL"]["momentum"]
    bear_mom_weight = canonical_scoring.REGIME_WEIGHTS["BEAR"]["momentum"]
    if bull_mom_weight <= bear_mom_weight:
        issues.append("BULL momentum ağırlığı BEAR'dan büyük olmalı")

    return "Regime changes scoring", len(issues) == 0, issues


# =====================================================
# 6. BACKWARD COMPATIBILITY
# =====================================================


def test_existing_ranking_unchanged() -> Any:
    """Mevcut ranking model hala çalışıyor mu?"""
    from services.ml.ranking_model import ranking_model

    issues = []

    features_map = {"TEST": _make_features(), "TEST2": _make_features()}

    try:
        result = ranking_model.rank(features_map, regime="BULL")
        if len(result.scores) != 2:
            issues.append(f"Ranking sonucu: {len(result.scores)} != 2")
    except Exception as e:
        issues.append(f"Ranking çalışmadı: {e}")

    return "Existing ranking unchanged", len(issues) == 0, issues


def test_existing_decision_input_still_works() -> Any:
    """Mevcut DecisionInput API'si hala çalışıyor mu?"""
    from services.core.decision_engine import DecisionEngine, DecisionInput

    issues = []

    engine = DecisionEngine()
    inp = DecisionInput(
        ticker="TEST",
        price=100.0,
        ml_score=70,
        ml_confidence=0.8,
        features={"momentum_20d": 5, "rsi_14": 55},
    )

    try:
        decision = engine.decide(inp)
        if decision.action not in ("BUY", "SELL", "HOLD", "NO_ACTION"):
            issues.append(f"Geçersiz action: {decision.action}")
    except Exception as e:
        issues.append(f"DecisionInput API çalışmadı: {e}")

    return "Existing DecisionInput API", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================


def run_all() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 60)
    logger.info("  Canonical Scoring & Decision Pipeline Tests")
    logger.info("=" * 60)

    tests = [
        test_score_vector_dimensions,
        test_all_motor_dimensions_nonzero,
        test_seasonality_used,
        test_missing_not_zero,
        test_data_quality_score,
        test_risk_opportunity_separate,
        test_decision_from_canonical,
        test_decision_is_deterministic,
        test_decision_blocks_high_risk,
        test_decision_low_confidence,
        test_regime_changes_scoring,
        test_existing_ranking_unchanged,
        test_existing_decision_input_still_works,
    ]

    passed = failed = 0
    all_issues = []

    for test_func in tests:
        try:
            name, ok, issues = test_func()
        except Exception as e:
            name, ok, issues = test_func.__name__, False, [f"Exception: {e}"]
            import traceback

            traceback.print_exc()

        icon = "✅" if ok else "❌"
        logger.info(f"{icon} {name}")
        if ok:
            passed += 1
        else:
            failed += 1
            for i in issues:
                logger.info(f"   ❌ {i}")
                all_issues.append(f"{name}: {i}")

    logger.info(f"\n{'=' * 60}")
    logger.info(f"  SONUÇ: {passed}/{passed + failed} geçti")
    if all_issues:
        logger.info("\n  HATALAR:")
        for i, issue in enumerate(all_issues, 1):
            logger.info(f"    {i}. {issue}")
    logger.info("=" * 60)
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
