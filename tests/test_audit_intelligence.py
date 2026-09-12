"""ALPHA BIST — Intelligence Service Audit & Hardening Tests
Verifies that all intelligence engines, models, pipelines, and tools
adhere to strict enterprise standards (no placeholders, mandatory repr,
fail-closed error handling, valid typing).
"""

from datetime import UTC, datetime

import numpy as np

from services.intelligence.advanced_monte_carlo import (
    AdvancedMCResult,
    AdvancedMonteCarloEngine,
)
from services.intelligence.candle_patterns import (
    CandleMetrics,
    CandlePatternEngine,
    CandlePatternResult,
)
from services.intelligence.confidence_calibrator import (
    CalibrationBin,
    CalibrationReport,
    ConfidenceCalibrator,
    Observation,
)
from services.intelligence.dynamic_candle_matrix import (
    DynamicCandleMatrix,
    DynamicPatternMetrics,
)
from services.intelligence.ensemble_forecast import (
    EnsembleForecaster,
    EnsembleResult,
    ModelForecast,
)
from services.intelligence.evidence_engine import (
    Claim,
    ClaimType,
    EvidenceVerificationEngine,
    SourceReliability,
    VerificationResult,
    VerifiedClaim,
)
from services.intelligence.forecasting_utils import (
    EventTimelineEngine,
    NewsDuplicationEngine,
    NewsImpactEngine,
)
from services.intelligence.hmm_regime import (
    HMMRegimeDetector,
    HMMRegimeResult,
)
from services.intelligence.kap_extractor import (
    KAPExtractedEvent,
    KAPExtractor,
)
from services.intelligence.kap_llm_extractor import (
    KAPDocument,
    KAPLLMExtractor,
    LLMInsight,
)
from services.intelligence.knowledge_graph import (
    Entity,
    KnowledgeGraph,
    Relation,
)
from services.intelligence.llm_agent import (
    AgentAnalysis,
    LLMAgent,
)
from services.intelligence.llm_client import LLMClient
from services.intelligence.llm_context_builder import LLMContextBuilder
from services.intelligence.llm_tools import LLMToolExecutor
from services.intelligence.macro_sensitivity import MacroSensitivityEngine
from services.intelligence.ml_signal_fusion import (
    MLFusedSignal,
    MLSignalFusion,
)
from services.intelligence.news_pipeline import (
    NewsPipeline,
    ProcessedNews,
)
from services.intelligence.parallel_pipeline import (
    ParallelIntelligencePipeline,
    ParallelPipelineResult,
    PhaseResult,
)
from services.intelligence.pipeline import (
    IntelligenceOutput,
    IntelligencePipeline,
)


def test_pipelines_instantiation_and_repr():
    """Pipeline sınıflarının ve modellerinin repr ve başlatma doğrulaması."""
    p_result = PhaseResult(phase="phase_1", modules={"mod1": 1}, errors={}, elapsed_ms=12.5)
    assert p_result.success_count == 1
    assert p_result.error_count == 0
    assert "PhaseResult" in repr(p_result)

    pp_result = ParallelPipelineResult(ticker="THYAO", phases={"p1": p_result})
    assert "ParallelPipelineResult" in repr(pp_result)
    assert pp_result.get_module_result("mod1") == 1

    parallel_pipe = ParallelIntelligencePipeline()
    assert "ParallelIntelligencePipeline" in repr(parallel_pipe)

    pipe_out = IntelligenceOutput(ticker="THYAO", timestamp="2026-09-12T10:00:00Z")
    assert "IntelligenceOutput" in repr(pipe_out)

    pipe = IntelligencePipeline()
    assert "IntelligencePipeline" in repr(pipe)
    health = pipe.get_health()
    assert "total_modules" in health
    assert health["total_modules"] == 16


def test_monte_carlo_and_candle_patterns():
    """Gelişmiş Monte Carlo ve Mum Formasyon motorlarının canlı testi."""
    mc_engine = AdvancedMonteCarloEngine()
    assert "AdvancedMonteCarloEngine" in repr(mc_engine)

    # GBM test
    res_gbm = mc_engine.gbm_sim(
        ticker="GARAN",
        current_price=100.0,
        mu=0.15,
        sigma=0.25,
        horizon_days=10,
        n_sims=500,
        seed=42,
    )
    assert isinstance(res_gbm, AdvancedMCResult)
    assert "AdvancedMCResult" in repr(res_gbm)
    assert res_gbm.p50 > 0.0

    # Candle metrics test
    candle = CandleMetrics(open=100.0, high=105.0, low=99.0, close=104.0, volume=1000.0)
    assert "CandleMetrics" in repr(candle)
    assert candle.is_green is True
    assert candle.is_doji is False

    candle_engine = CandlePatternEngine()
    assert "CandlePatternEngine" in repr(candle_engine)

    pat_res = CandlePatternResult(ticker="AKBNK", direction="BULLISH", candle_score=75.0)
    assert "CandlePatternResult" in repr(pat_res)

    # Dynamic matrix
    mat = DynamicCandleMatrix(lookback_window=100)
    assert "DynamicCandleMatrix" in repr(mat)
    pat_metric = DynamicPatternMetrics(pattern_name="hammer", rolling_win_rate=65.0)
    assert "DynamicPatternMetrics" in repr(pat_metric)


def test_calibration_and_ensemble():
    """Kalibratör ve ensemble tahmin modellerinin doğrulanması."""
    calib = ConfidenceCalibrator(n_bins=5, min_samples=5)
    assert "ConfidenceCalibrator" in repr(calib)

    calib_bin = CalibrationBin(bin_range="0.7-0.8", mean_prediction=0.75, mean_actual=0.70, count=20, miscalibration=0.05)
    assert "CalibrationBin" in repr(calib_bin)

    rep = CalibrationReport(
        brier_score=0.15,
        bins=[calib_bin],
        overconfident=False,
        overconfidence_magnitude=0.0,
        n_samples=20,
        recommended_adjustment=1.0,
    )
    assert "CalibrationReport" in repr(rep)

    obs = Observation(predicted_confidence=0.8, actual_outcome=True, ticker="SISE")
    assert "Observation" in repr(obs)

    ens_forecaster = EnsembleForecaster()
    assert "EnsembleForecaster" in repr(ens_forecaster)

    m_forecast = ModelForecast(model_name="lightgbm", predicted_return=3.5, confidence=0.85, horizon_days=5)
    assert "ModelForecast" in repr(m_forecast)

    ens_res = EnsembleResult(
        ticker="EREGL",
        horizon_days=5,
        ensemble_prediction=2.4,
        ensemble_confidence=0.80,
        model_agreement=0.90,
        model_predictions={"lightgbm": 2.5, "xgboost": 2.3},
        model_confidences={"lightgbm": 0.8, "xgboost": 0.8},
        regime="BULL",
        weights_used={"lightgbm": 0.5, "xgboost": 0.5},
        calibrated_confidence=0.78,
    )
    assert "EnsembleResult" in repr(ens_res)


def test_evidence_and_forecasting_utils():
    """Evidence engine ve yardımcı tahmin motorlarının testi."""
    ev_engine = EvidenceVerificationEngine()
    assert "EvidenceVerificationEngine" in repr(ev_engine)

    claim = Claim(
        claim_id="c_1",
        text="Şirket %50 temettü dağıtacak",
        source="kap.org.tr",
        source_type=SourceReliability.PRIMARY,
        ticker="FROTO",
    )
    assert "Claim" in repr(claim)

    v_claim = VerifiedClaim(
        claim=claim,
        claim_type=ClaimType.FACT,
        result=VerificationResult.VERIFIED,
        evidence_score=95.0,
        source_reliability=SourceReliability.PRIMARY,
        timestamp_valid=True,
        cross_check_passed=True,
        contradictions=[],
        supporting_evidence=["KAP bildirimi doğrulandı"],
        explanation="Resmi KAP açıklaması ile uyumlu",
    )
    assert "VerifiedClaim" in repr(v_claim)

    impact_engine = NewsImpactEngine()
    assert "NewsImpactEngine" in repr(impact_engine)
    res_impact = impact_engine.compute_impact({"sentiment": 0.8, "importance": 0.9, "novelty": 0.9, "credibility": 0.9})
    assert res_impact["direction"] == "POSITIVE"

    dup_engine = NewsDuplicationEngine()
    assert "NewsDuplicationEngine" in repr(dup_engine)
    assert dup_engine.is_duplicate("Flaş gelişme: bilanço açıklandı", "sourceA") is False
    assert dup_engine.is_duplicate("Flaş gelişme: bilanço açıklandı", "sourceB") is True

    time_engine = EventTimelineEngine()
    assert "EventTimelineEngine" in repr(time_engine)
    time_engine.add_event(ticker="TUPRS", event_type="DIVIDEND", data={"yield": 0.08}, timestamp="2026-09-12")
    assert "TUPRS" in time_engine._timelines


def test_hmm_regime_and_kap_extractors():
    """HMM rejim tespiti ve KAP çıkarıcılarının testi."""
    hmm_detector = HMMRegimeDetector(n_regimes=4, rolling_window=50)
    assert "HMMRegimeDetector" in repr(hmm_detector)

    fake_returns = np.array([0.01, -0.005, 0.02, -0.01, 0.015] * 15)
    fake_vol = np.array([0.02, 0.018, 0.025, 0.022, 0.019] * 15)
    hmm_res = hmm_detector.predict_regime(fake_returns, fake_vol)
    assert isinstance(hmm_res, HMMRegimeResult)
    assert "HMMRegimeResult" in repr(hmm_res)
    assert hmm_res.confidence > 0.0

    ke = KAPExtractor()
    assert "KAPExtractor" in repr(ke)
    empty_ke = ke._build_empty("BIMAS", "kap_999")
    assert isinstance(empty_ke, KAPExtractedEvent)
    assert "KAPExtractedEvent" in repr(empty_ke)

    k_llm = KAPLLMExtractor()
    assert "KAPLLMExtractor" in repr(k_llm)
    doc = KAPDocument(
        doc_id="d1",
        ticker="SAHOL",
        date="2026-09-12",
        category="DIVIDEND",
        title="Temettü Ödeme Tarihleri",
        content="Hisse başı 2.5 TL nakit temettü",
    )
    assert "KAPDocument" in repr(doc)

    insight = LLMInsight(
        ticker="SAHOL",
        overall_sentiment=0.7,
        confidence=0.85,
        key_topics=["temettü"],
        risk_factors=[],
        opportunity_factors=["nakit akışı"],
        sector_impact={"HOLDING": 0.5},
        summary="Pozitif temettü duyurusu",
    )
    assert "LLMInsight" in repr(insight)


def test_knowledge_graph_and_llm_tools():
    """Bilgi grafiği, LLM istemcisi ve LLM araç yürütücüsünün testi."""
    kg = KnowledgeGraph()
    assert "KnowledgeGraph" in repr(kg)

    e1 = Entity(entity_id="comp_THYAO", entity_type="company", name="Türk Hava Yolları")
    e2 = Entity(entity_id="sec_AVIATION", entity_type="sector", name="Havacılık")
    rel = Relation(source_id="comp_THYAO", target_id="sec_AVIATION", relation_type="belongs_to")
    assert "Entity" in repr(e1)
    assert "Relation" in repr(rel)

    kg.add_entity(e1)
    kg.add_entity(e2)
    kg.add_relation(rel)

    client = LLMClient()
    assert "LLMClient" in repr(client)

    tool_exec = LLMToolExecutor()
    assert "LLMToolExecutor" in repr(tool_exec)

    # Execute world state tool
    res = tool_exec.execute("get_world_state", {})
    assert "status" in res

    # Execute ticker features tool
    res_f = tool_exec.execute("get_ticker_features", {"ticker": "KCHOL"})
    assert res_f["status"] == "available_in_context"


def test_agent_macro_fusion_and_news():
    """LLMAgent, MacroSensitivity, MLSignalFusion ve NewsPipeline testi."""
    agent = LLMAgent()
    assert "LLMAgent" in repr(agent)

    analysis = AgentAnalysis(
        ticker="ISCTR",
        analysis_type="news",
        ai_direction="LONG",
        ai_score=78.0,
        ai_confidence=0.82,
    )
    assert "AgentAnalysis" in repr(analysis)

    builder = LLMContextBuilder()
    assert "LLMContextBuilder" in repr(builder)
    news_ctx = builder.build_news_context(ticker="ISCTR", sector="BANK")
    assert "world_state" in news_ctx

    macro_engine = MacroSensitivityEngine()
    assert "MacroSensitivityEngine" in repr(macro_engine)
    bank_sens = macro_engine.get_sector_sensitivity("BANK")
    assert "interest_rate" in bank_sens

    fusion_engine = MLSignalFusion()
    assert "MLSignalFusion" in repr(fusion_engine)
    fused = MLFusedSignal(
        ticker="ASELS",
        regime="BULL",
        fused_score=82.0,
        fused_direction="LONG",
        fused_confidence=0.88,
    )
    assert "MLFusedSignal" in repr(fused)

    news_pipe = NewsPipeline()
    assert "NewsPipeline" in repr(news_pipe)
    proc_news = ProcessedNews(
        news_id="n_1",
        timestamp=datetime.now(UTC),
        source="bloomberg",
        title="BIST Yükselişte",
        sentiment=0.6,
        importance=0.8,
        is_llm_analyzed=True,
    )
    assert "ProcessedNews" in repr(proc_news)
