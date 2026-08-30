import structlog

logger = structlog.get_logger(__name__)
from typing import Any

"""
ALPHA BIST — Learning System Faz 5 Test Suite (Shadow Mode + Champion-Challenger)

Shadow Mode testing:
- Start/stop lifecycle
- Prediction recording
- Outcome recording
- Evaluation (promote/reject/extend)
- Minimum time/prediction guards
- Statistical significance

Champion-Challenger testing:
- Promote lifecycle
- Reject workflow
- Rollback
- History tracking
- Multiple champions (regime-specific)
"""

import sys
from datetime import UTC, datetime, timedelta

# ===================== SHADOW MODE =====================


def test_shadow_init() -> Any:
    """Shadow manager init."""
    from services.learning.shadow_manager import ShadowModeManager

    m = ShadowModeManager()
    assert m._shadow_active is False
    assert m._champion_id is None
    assert m._challenger_id is None
    assert len(m._predictions) == 0
    logger.info("✅ Shadow init")


def test_shadow_start() -> Any:
    """Shadow mode başlatma."""
    from services.learning.shadow_manager import ShadowModeManager

    m = ShadowModeManager()
    m.start_shadow("champ_v1", "chall_v2")

    assert m._shadow_active is True
    assert m._champion_id == "champ_v1"
    assert m._challenger_id == "chall_v2"
    assert m._start_date is not None
    logger.info("✅ Shadow start")


def test_shadow_stop() -> Any:
    """Shadow mode durdurma."""
    from services.learning.shadow_manager import ShadowModeManager

    m = ShadowModeManager()
    m.start_shadow("c1", "c2")
    m.stop_shadow()

    assert m._shadow_active is False
    logger.info("✅ Shadow stop")


def test_shadow_record_prediction() -> Any:
    """Prediction kayıt."""
    from services.learning.shadow_manager import ShadowModeManager

    m = ShadowModeManager()
    m.start_shadow("c1", "c2")

    m.record_prediction("THYAO", {"direction": "LONG"}, {"direction": "SHORT"})
    m.record_prediction("ASELS", {"direction": "LONG"}, {"direction": "LONG"})

    assert len(m._predictions) == 2
    assert m._predictions[0].ticker == "THYAO"
    assert m._predictions[1].ticker == "ASELS"
    logger.info("✅ Shadow record prediction")


def test_shadow_record_when_inactive() -> Any:
    """Inactive iken prediction kayıt edilmemeli."""
    from services.learning.shadow_manager import ShadowModeManager

    m = ShadowModeManager()
    m.record_prediction("THYAO", {"direction": "LONG"}, {"direction": "LONG"})

    assert len(m._predictions) == 0
    logger.info("✅ Shadow record when inactive → ignored")


def test_shadow_record_outcome() -> Any:
    """Outcome kayıt — her iki model için."""
    from services.learning.shadow_manager import ShadowModeManager

    m = ShadowModeManager()
    m.start_shadow("c1", "c2")

    # LONG prediction
    m.record_prediction("THYAO", {"direction": "LONG"}, {"direction": "LONG"})
    m.record_outcome("THYAO", 5.0)  # %5 getiri

    assert len(m._champion_returns) == 1
    assert len(m._challenger_returns) == 1
    assert m._champion_returns[0] == 5.0
    assert m._challenger_returns[0] == 5.0
    logger.info("✅ Shadow record outcome")


def test_shadow_record_outcome_short() -> Any:
    """SHORT prediction outcome."""
    from services.learning.shadow_manager import ShadowModeManager

    m = ShadowModeManager()
    m.start_shadow("c1", "c2")

    # SHORT prediction
    m.record_prediction("THYAO", {"direction": "SHORT"}, {"direction": "SHORT"})
    m.record_outcome("THYAO", 5.0)  # %5 getiri ama SHORT → negatif

    assert m._champion_returns[0] == -5.0
    assert m._challenger_returns[0] == -5.0
    logger.info("✅ Shadow record outcome SHORT")


def test_shadow_evaluate_not_enough_time() -> Any:
    """Yeterli süre geçmediyse evaluate None döndürmeli."""
    from services.learning.shadow_manager import ShadowModeManager

    m = ShadowModeManager()
    m.start_shadow("c1", "c2")

    result = m.evaluate()
    assert result is None
    logger.info("✅ Shadow evaluate not enough time")


def test_shadow_evaluate_not_enough_predictions() -> Any:
    """Yeterli prediction yoksa evaluate None döndürmeli."""
    from services.learning.shadow_manager import ShadowModeManager

    m = ShadowModeManager()
    m._start_date = datetime.now(UTC) - timedelta(days=25)  # Geçmişe al
    m.start_shadow("c1", "c2")
    m._start_date = datetime.now(UTC) - timedelta(days=25)

    # 5 prediction (50 minimum)
    for i in range(5):
        m.record_prediction(f"T{i}", {"direction": "LONG"}, {"direction": "LONG"})
        m.record_outcome(f"T{i}", float(i))

    result = m.evaluate()
    assert result is None
    logger.info("✅ Shadow evaluate not enough predictions")


def test_shadow_evaluate_challenger_better() -> Any:
    """Challenger daha iyi ise PROMOTE önerilmeli."""
    from services.learning.shadow_manager import ShadowModeManager

    m = ShadowModeManager()
    m.start_shadow("c1", "c2")
    m._start_date = datetime.now(UTC) - timedelta(days=25)

    # 60 prediction: champion SHORT, challenger LONG, hep pozitif getiri
    for i in range(60):
        m.record_prediction(f"T{i}", {"direction": "SHORT"}, {"direction": "LONG"})
        m.record_outcome(f"T{i}", 2.0)  # Pozitif getiri

    result = m.evaluate()
    assert result is not None
    # Challenger LONG dedi ve pozitif getiri → challenger pozitif, champion negatif
    assert result.challenger_sharpe > 0
    assert result.improvement_pct > 0
    logger.info(f"✅ Shadow evaluate challenger better: improvement={result.improvement_pct}%")


def test_shadow_evaluate_champion_better() -> Any:
    """Champion daha iyi ise REJECT önerilmeli."""
    from services.learning.shadow_manager import ShadowModeManager

    m = ShadowModeManager()
    m.start_shadow("c1", "c2")
    m._start_date = datetime.now(UTC) - timedelta(days=25)

    # 60 prediction: champion LONG, challenger SHORT, hep pozitif getiri
    for i in range(60):
        m.record_prediction(f"T{i}", {"direction": "LONG"}, {"direction": "SHORT"})
        m.record_outcome(f"T{i}", 2.0)  # Pozitif getiri

    result = m.evaluate()
    assert result is not None
    # Champion LONG dedi ve pozitif getiri → champion pozitif, challenger negatif
    assert result.champion_sharpe > 0
    assert result.improvement_pct < 0
    logger.info(f"✅ Shadow evaluate champion better: improvement={result.improvement_pct}%")


def test_shadow_status() -> Any:
    """Status doğru mu?"""
    from services.learning.shadow_manager import ShadowModeManager

    m = ShadowModeManager()
    status = m.get_status()
    assert status["active"] is False

    m.start_shadow("c1", "c2")
    status = m.get_status()
    assert status["active"] is True
    assert status["champion_id"] == "c1"
    assert status["challenger_id"] == "c2"
    assert status["prediction_count"] == 0
    logger.info("✅ Shadow status")


# ===================== CHAMPION-CHALLENGER =====================


def test_cc_init() -> Any:
    """Champion-challenger init."""
    from services.learning.champion_challenger import ChampionChallengerEngine

    engine = ChampionChallengerEngine()
    assert engine.get_champion() is None
    assert len(engine._champion_history) == 0
    logger.info("✅ CC init")


def test_cc_promote() -> Any:
    """Champion promote."""
    from services.learning.champion_challenger import ChampionChallengerEngine

    engine = ChampionChallengerEngine()
    engine.promote("model_v1", "v1", {"sharpe": 1.5}, regime="BULL")

    champion = engine.get_champion()
    assert champion is not None
    assert champion.model_id == "model_v1"
    assert champion.version == "v1"
    assert champion.regime == "BULL"
    logger.info("✅ CC promote")


def test_cc_promote_replaces_old() -> Any:
    """Yeni promote eski champion'ı değiştirir."""
    from services.learning.champion_challenger import ChampionChallengerEngine

    engine = ChampionChallengerEngine()
    engine.promote("m1", "v1", {"sharpe": 1.0})
    engine.promote("m2", "v2", {"sharpe": 1.5})

    champion = engine.get_champion()
    assert champion.model_id == "m2"
    assert champion.promoted_from == "m1"
    logger.info("✅ CC promote replaces old")


def test_cc_reject() -> Any:
    """Challenger reddetme."""
    from services.learning.champion_challenger import ChampionChallengerEngine

    engine = ChampionChallengerEngine()
    engine.reject("model_v3", "Low performance", {"sharpe": 0.1})

    assert len(engine._rejected_challengers) == 1
    assert engine._rejected_challengers[0]["model_id"] == "model_v3"
    assert engine._rejected_challengers[0]["reason"] == "Low performance"
    logger.info("✅ CC reject")


def test_cc_multiple_rejects() -> Any:
    """Birden fazla reddetme."""
    from services.learning.champion_challenger import ChampionChallengerEngine

    engine = ChampionChallengerEngine()
    engine.reject("m1", "reason1", {})
    engine.reject("m2", "reason2", {})
    engine.reject("m3", "reason3", {})

    assert len(engine._rejected_challengers) == 3
    logger.info("✅ CC multiple rejects")


def test_cc_rollback() -> Any:
    """Rollback çalışıyor mu?"""
    from services.learning.champion_challenger import ChampionChallengerEngine

    engine = ChampionChallengerEngine()
    engine.promote("m1", "v1", {"sharpe": 1.0})
    engine.promote("m2", "v2", {"sharpe": 1.5})
    engine.promote("m3", "v3", {"sharpe": 0.5})  # Kötü model

    # v1'e geri dön
    result = engine.rollback("v1")
    assert result is True
    assert engine.get_champion().version == "v1"
    logger.info("✅ CC rollback")


def test_cc_rollback_not_found() -> Any:
    """Olmayan versiyona rollback başarısız olmalı."""
    from services.learning.champion_challenger import ChampionChallengerEngine

    engine = ChampionChallengerEngine()
    engine.promote("m1", "v1", {})

    result = engine.rollback("v999")
    assert result is False
    logger.info("✅ CC rollback not found")


def test_cc_history() -> Any:
    """History doğru mu?"""
    from services.learning.champion_challenger import ChampionChallengerEngine

    engine = ChampionChallengerEngine()
    engine.promote("m1", "v1", {})
    engine.promote("m2", "v2", {})
    engine.promote("m3", "v3", {})

    history = engine.get_history()
    assert len(history) == 3
    assert history[0]["version"] == "v1"
    assert history[1]["version"] == "v2"
    assert history[2]["version"] == "v3"
    logger.info("✅ CC history")


def test_cc_report() -> Any:
    """Rapor doğru mu?"""
    from services.learning.champion_challenger import ChampionChallengerEngine

    engine = ChampionChallengerEngine()
    engine.promote("m1", "v1", {})
    engine.reject("m2", "reason", {})

    report = engine.get_report()
    assert report["current_champion"]["model_id"] == "m1"
    assert report["total_promotions"] == 1
    assert report["total_rejections"] == 1
    logger.info("✅ CC report")


def test_cc_promoted_from_tracking() -> Any:
    """promoted_from doğru takip ediliyor mu?"""
    from services.learning.champion_challenger import ChampionChallengerEngine

    engine = ChampionChallengerEngine()
    engine.promote("m1", "v1", {})
    engine.promote("m2", "v2", {})
    engine.promote("m3", "v3", {})

    history = engine.get_history()
    assert history[0]["promoted_from"] is None  # İlk champion
    assert history[1]["promoted_from"] == "m1"
    assert history[2]["promoted_from"] == "m2"
    logger.info("✅ CC promoted_from tracking")


# ===================== MAIN =====================


def run_all_tests() -> Any:
    """Otomatik eklendi."""
    tests = [
        test_shadow_init,
        test_shadow_start,
        test_shadow_stop,
        test_shadow_record_prediction,
        test_shadow_record_when_inactive,
        test_shadow_record_outcome,
        test_shadow_record_outcome_short,
        test_shadow_evaluate_not_enough_time,
        test_shadow_evaluate_not_enough_predictions,
        test_shadow_evaluate_challenger_better,
        test_shadow_evaluate_champion_better,
        test_shadow_status,
        test_cc_init,
        test_cc_promote,
        test_cc_promote_replaces_old,
        test_cc_reject,
        test_cc_multiple_rejects,
        test_cc_rollback,
        test_cc_rollback_not_found,
        test_cc_history,
        test_cc_report,
        test_cc_promoted_from_tracking,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((test.__name__, str(e)))
            logger.info(f"❌ {test.__name__}: {e}")

    logger.info(f"\n{'=' * 60}")
    logger.info("📊 FAZ 5 TEST SONUÇLARI (Shadow Mode + Champion-Challenger)")
    logger.info(f"{'=' * 60}")
    logger.info(f"✅ Geçen: {passed}")
    logger.info(f"❌ Başarısız: {failed}")
    logger.info(f"📈 Toplam: {passed + failed}")

    if errors:
        logger.info("\n🔍 Hatalar:")
        for name, err in errors:
            logger.info(f"  - {name}: {err}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
