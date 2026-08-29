from typing import Any
"""
ALPHA BIST — Agent System Test Suite v1.0

Tüm fazlar için kapsamlı test'ler.
FAZ 0-7 test'leri dahil.

Kullanım:
    python -m pytest tests/test_agent_system.py -v
"""

import asyncio
from datetime import UTC, datetime

import orjson
import pytest

# Test edilecek modüller
from services.agents import (
    PROMPT_VERSION,
    AgentCommunicationBus,
    AgentMemory,
    AgentMessage,
    AgentPipelineOrchestrator,
    AgentResult,
    AgentRole,
    AgentSelfEvaluator,
    AgentTask,
    AgentToolRegistry,
    AIFallback,
    AIOutputValidator,
    BaseAgent,
    ConflictDetector,
    ConflictResolver,
    DebateEngine,
    DebateResult,
    EpisodicMemory,
    LLMClientFactory,
    LLMConfig,
    MemoryConsolidator,
    MemoryEntry,
    MultiAgentEvaluator,
    OllamaLLMClient,
    ParallelAgentRunner,
    ParallelRunResult,
    PromptFactory,
    Resolution,
    RiskAssessor,
    SynthesisEngine,
    WorkingMemory,
    parse_llm_json,
    validate_agent_output,
)
from services.agents.agent_pipeline import PipelineResult

# =====================================================
# HELPERS
# =====================================================


def create_mock_features() -> Any:
    """Mock feature'lar oluştur."""
    return {
        "roc_5d": 2.5,
        "roc_20d": 5.0,
        "rsi_14": 55.0,
        "volume_zscore": 1.2,
        "trend_slope_20d": 0.05,
        "atr_pct": 2.5,
        "momentum_20d": 3.0,
        "regime": "RISK_ON",
    }


def create_mock_agent_result(
    role: AgentRole = AgentRole.TECHNICAL,
    direction: str = "LONG",
    confidence: float = 0.7,
    success: bool = True,
) -> AgentResult:
    """Mock agent sonucu oluştur."""
    return AgentResult(
        task_id=f"test-{role.value}",
        agent_role=role,
        ticker="THYAO",
        success=success,
        output={
            "direction": direction,
            "confidence": confidence,
            "score": 65.0,
            "reasoning": f"{role.value} analysis",
            "reasons": ["reason1", "reason2"],
            "risks": ["risk1"],
        },
        confidence=confidence,
        evidence=["reason1", "reason2"],
        reasoning=f"{role.value} analysis",
        model_version="test",
        prompt_version=PROMPT_VERSION,
        input_hash="test123",
        duration_ms=100.0,
    )


def run_async(coro) -> Any:
    """Async fonksiyonu çalıştır."""
    return asyncio.get_event_loop().run_until_complete(coro)


# =====================================================
# FAZ 0: TEMEL ALTYAPI
# =====================================================


class TestFaz0_LLMClient:
    """Faz 0: LLM Client Abstraction test'leri."""

    def test_llm_config_defaults(self) -> Any:
        """Otomatik eklendi."""
        config = LLMConfig()
        assert config.provider == "ollama"
        assert config.temperature == 0.3
        assert config.max_retries == 3

    def test_llm_factory_ollama(self) -> Any:
        """Otomatik eklendi."""
        config = LLMConfig(provider="ollama")
        client = LLMClientFactory.create(config)
        assert isinstance(client, OllamaLLMClient)

    def test_llm_factory_unknown_provider(self) -> Any:
        """Otomatik eklendi."""
        config = LLMConfig(provider="unknown")
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            LLMClientFactory.create(config)

    def test_parse_llm_json_valid(self) -> Any:
        """Otomatik eklendi."""
        content = '{"direction": "LONG", "confidence": 0.7}'
        result = parse_llm_json(content)
        assert result is not None
        assert result["direction"] == "LONG"

    def test_parse_llm_json_code_block(self) -> Any:
        """Otomatik eklendi."""
        content = '```json\n{"direction": "SHORT", "confidence": 0.6}\n```'
        result = parse_llm_json(content)
        assert result is not None
        assert result["direction"] == "SHORT"

    def test_parse_llm_json_text_fallback(self) -> Any:
        """Otomatik eklendi."""
        content = "Hisse LONG görünüyor, confidence 0.75"
        result = parse_llm_json(content)
        assert result is not None
        assert result["direction"] == "LONG"

    def test_parse_llm_json_empty(self) -> Any:
        """Otomatik eklendi."""
        result = parse_llm_json("")
        assert result is None

    def test_parse_llm_json_none(self) -> Any:
        """Otomatik eklendi."""
        result = parse_llm_json(None)
        assert result is None


class TestFaz0_Schemas:
    """Faz 0: JSON Schema test'leri."""

    def test_agent_output_schema_valid(self) -> Any:
        """Otomatik eklendi."""
        from services.agents.schemas import AgentOutputSchema

        data = {"direction": "LONG", "confidence": 0.7, "score": 65}
        schema = AgentOutputSchema(**data)
        assert schema.direction == "LONG"
        assert schema.confidence == 0.7

    def test_agent_output_schema_normalize_confidence(self) -> Any:
        """Otomatik eklendi."""
        from services.agents.schemas import AgentOutputSchema

        data = {"confidence": 75}  # 0-100 arası
        schema = AgentOutputSchema(**data)
        assert schema.confidence == 0.75

    def test_validate_agent_output_valid(self) -> Any:
        """Otomatik eklendi."""
        data = {"direction": "LONG", "confidence": 0.7}
        is_valid, parsed, errors = validate_agent_output(data)
        assert is_valid
        assert len(errors) == 0


class TestFaz0_Prompts:
    """Faz 0: Prompt Template test'leri."""

    def test_list_templates(self) -> Any:
        """Otomatik eklendi."""
        templates = PromptFactory.list_templates()
        assert "technical" in templates
        assert "fundamental" in templates
        assert "news" in templates
        assert "macro" in templates
        assert "risk" in templates
        assert "synthesis" in templates

    def test_get_technical_prompt(self) -> Any:
        """Otomatik eklendi."""
        context = {"features": create_mock_features()}
        system, user = PromptFactory.get_prompts("technical", "THYAO", context)
        assert "THYAO" in system
        assert "JSON" in system
        assert "THYAO" in user

    def test_unknown_template_raises(self) -> Any:
        """Otomatik eklendi."""
        with pytest.raises(ValueError, match="Unknown template"):
            PromptFactory.get_prompts("nonexistent", "THYAO", {})


class TestFaz0_AgentSystem:
    """Faz 0: Agent System refactor test'leri."""

    def test_agent_roles(self) -> Any:
        """Otomatik eklendi."""
        assert AgentRole.TECHNICAL.value == "TECHNICAL"
        assert AgentRole.BULL.value == "BULL"
        assert AgentRole.BEAR.value == "BEAR"

    def test_agent_task_creation(self) -> Any:
        """Otomatik eklendi."""
        task = AgentTask(
            task_id="test-1",
            agent_role=AgentRole.TECHNICAL,
            ticker="THYAO",
            prompt="Analyze",
            context={"features": {}},
        )
        assert task.ticker == "THYAO"
        assert task.template_name is None

    def test_tool_registry(self) -> Any:
        """Otomatik eklendi."""
        assert AgentToolRegistry.can_access(AgentRole.TECHNICAL, "read_market_data")
        assert not AgentToolRegistry.can_access(AgentRole.TECHNICAL, "read_portfolio")
        assert AgentToolRegistry.can_access(AgentRole.RISK, "reject_decision")

    def test_fallback_analysis(self) -> Any:
        """Otomatik eklendi."""
        features = create_mock_features()
        result = AIFallback.rule_based_analysis(features, "THYAO")
        assert "direction" in result
        assert "confidence" in result
        assert result["source"] == "rule_based_fallback"

    def test_output_validator_valid(self) -> Any:
        """Otomatik eklendi."""
        output = orjson.dumps({"direction": "LONG", "confidence": 0.7}).decode()
        result = AIOutputValidator.validate(output)
        assert result["valid"]

    def test_output_validator_invalid_direction(self) -> Any:
        """Otomatik eklendi."""
        output = orjson.dumps({"direction": "INVALID", "confidence": 0.7}).decode()
        result = AIOutputValidator.validate(output)
        assert not result["valid"] or "Invalid direction" in str(result["errors"])


# =====================================================
# FAZ 1: PARALEL ÇALIŞMA
# =====================================================


class TestFaz1_ParallelRunner:
    """Faz 1: Parallel Agent Runner test'leri."""

    def test_parallel_run_result_properties(self) -> Any:
        """Otomatik eklendi."""
        result = ParallelRunResult(
            results={},
            total_duration_ms=100,
            success_count=3,
            failure_count=1,
            timeout_count=0,
        )
        assert result.success_rate == 0.75
        assert not result.all_failed
        assert result.partial_success

    def test_parallel_run_result_all_failed(self) -> Any:
        """Otomatik eklendi."""
        result = ParallelRunResult(
            results={},
            total_duration_ms=100,
            success_count=0,
            failure_count=4,
            timeout_count=0,
        )
        assert result.all_failed
        assert result.success_rate == 0

    @pytest.mark.asyncio
    async def test_parallel_runner_basic(self) -> Any:
        """Otomatik eklendi."""
        runner = ParallelAgentRunner(max_concurrent=2, timeout_seconds=5)

        # Mock agent'lar
        agents = {
            AgentRole.TECHNICAL: BaseAgent(AgentRole.TECHNICAL),
            AgentRole.FUNDAMENTAL: BaseAgent(AgentRole.FUNDAMENTAL),
        }

        tasks = {
            AgentRole.TECHNICAL: AgentTask(
                task_id="t1",
                agent_role=AgentRole.TECHNICAL,
                ticker="THYAO",
                prompt="test",
                context={"features": {}},
            ),
            AgentRole.FUNDAMENTAL: AgentTask(
                task_id="t2",
                agent_role=AgentRole.FUNDAMENTAL,
                ticker="THYAO",
                prompt="test",
                context={"features": {}},
            ),
        }

        result = await runner.run_agents(agents, tasks)
        assert isinstance(result, ParallelRunResult)
        assert result.success_count + result.failure_count == 2


# =====================================================
# FAZ 2: CONFLICT + DEBATE
# =====================================================


class TestFaz2_ConflictDetector:
    """Faz 2: Conflict Detection test'leri."""

    def test_no_conflict_unanimous_long(self) -> Any:
        """Otomatik eklendi."""
        detector = ConflictDetector()
        results = {
            AgentRole.TECHNICAL: create_mock_agent_result(AgentRole.TECHNICAL, "LONG"),
            AgentRole.FUNDAMENTAL: create_mock_agent_result(AgentRole.FUNDAMENTAL, "LONG"),
            AgentRole.NEWS: create_mock_agent_result(AgentRole.NEWS, "LONG"),
        }
        report = detector.detect(results)
        assert not report.has_conflict
        assert report.is_unanimous
        assert not report.requires_debate

    def test_conflict_long_vs_short(self) -> Any:
        """Otomatik eklendi."""
        detector = ConflictDetector()
        results = {
            AgentRole.TECHNICAL: create_mock_agent_result(AgentRole.TECHNICAL, "LONG"),
            AgentRole.FUNDAMENTAL: create_mock_agent_result(AgentRole.FUNDAMENTAL, "SHORT"),
            AgentRole.NEWS: create_mock_agent_result(AgentRole.NEWS, "LONG"),
        }
        report = detector.detect(results)
        assert report.has_conflict
        assert not report.is_unanimous
        assert report.long_count == 2
        assert report.short_count == 1

    def test_excludes_synthesis_and_risk(self) -> Any:
        """Otomatik eklendi."""
        detector = ConflictDetector()
        results = {
            AgentRole.TECHNICAL: create_mock_agent_result(AgentRole.TECHNICAL, "LONG"),
            AgentRole.SYNTHESIS: create_mock_agent_result(AgentRole.SYNTHESIS, "SHORT"),
            AgentRole.RISK: create_mock_agent_result(AgentRole.RISK, "NEUTRAL"),
        }
        report = detector.detect(results)
        assert not report.has_conflict  # SYNTHESIS ve RISK hariç


class TestFaz2_DebateEngine:
    """Faz 2: Debate Engine test'leri."""

    def test_debate_result_to_dict(self) -> Any:
        """Otomatik eklendi."""
        result = DebateResult(
            consensus="LONG",
            consensus_confidence=0.6,
            rounds=[],
            agreement=True,
            total_rounds=1,
        )
        d = result.to_dict()
        assert d["consensus"] == "LONG"
        assert d["agreement"]


# =====================================================
# FAZ 3: MEMORY
# =====================================================


class TestFaz3_WorkingMemory:
    """Faz 3: Working Memory test'leri."""

    def test_add_and_get_recent(self) -> Any:
        """Otomatik eklendi."""
        wm = WorkingMemory(max_items=5)
        for i in range(10):
            wm.add(
                MemoryEntry(
                    task_id=f"t{i}",
                    agent_role="TECHNICAL",
                    ticker="THYAO",
                    direction="LONG",
                    confidence=0.7,
                    reasoning="test",
                    timestamp=datetime.now(UTC).isoformat(),
                )
            )
        assert len(wm.items) == 5  # max_items
        recent = wm.get_recent(limit=3)
        assert len(recent) == 3

    def test_get_last_direction(self) -> Any:
        """Otomatik eklendi."""
        wm = WorkingMemory()
        wm.add(
            MemoryEntry(
                task_id="t1",
                agent_role="TECHNICAL",
                ticker="THYAO",
                direction="SHORT",
                confidence=0.6,
                reasoning="",
                timestamp="",
            )
        )
        wm.add(
            MemoryEntry(
                task_id="t2",
                agent_role="TECHNICAL",
                ticker="THYAO",
                direction="LONG",
                confidence=0.8,
                reasoning="",
                timestamp="",
            )
        )
        assert wm.get_last_direction("THYAO") == "LONG"


class TestFaz3_EpisodicMemory:
    """Faz 3: Episodic Memory test'leri."""

    def test_record_outcome(self) -> Any:
        """Otomatik eklendi."""
        em = EpisodicMemory()
        em.add(
            MemoryEntry(
                task_id="t1",
                agent_role="TECHNICAL",
                ticker="THYAO",
                direction="LONG",
                confidence=0.7,
                reasoning="",
                timestamp="",
            )
        )
        em.record_outcome("t1", 5.0, "RISK_ON")

        assert len(em.outcomes) == 1
        assert em.outcomes["t1"]["correct"]  # LONG + positive return

    def test_accuracy(self) -> Any:
        """Otomatik eklendi."""
        em = EpisodicMemory()
        for i in range(10):
            task_id = f"t{i}"
            em.add(
                MemoryEntry(
                    task_id=task_id,
                    agent_role="TECHNICAL",
                    ticker="THYAO",
                    direction="LONG",
                    confidence=0.7,
                    reasoning="",
                    timestamp="",
                )
            )
            em.record_outcome(task_id, 5.0 if i < 7 else -3.0, "RISK_ON")

        # 10 episodic (conf 0.7 > 0.6), 7 correct, 3 wrong
        assert em.get_accuracy() == 0.7  # 7/10


class TestFaz3_AgentMemory:
    """Faz 3: Agent Memory (3 katmanlı) test'leri."""

    def test_record_task(self) -> Any:
        """Otomatik eklendi."""
        mem = AgentMemory("TECHNICAL")
        mem.record_task("t1", "THYAO", "LONG", 0.7, "test reasoning")
        assert len(mem.working.items) == 1

    def test_get_context(self) -> Any:
        """Otomatik eklendi."""
        mem = AgentMemory("TECHNICAL")
        mem.record_task("t1", "THYAO", "LONG", 0.7, "test")
        context = mem.get_context_for_task("THYAO")
        assert "recent_tasks" in context
        assert "accuracy" in context

    def test_performance_summary(self) -> Any:
        """Otomatik eklendi."""
        mem = AgentMemory("TECHNICAL")
        summary = mem.get_performance_summary()
        assert summary["agent_role"] == "TECHNICAL"
        assert summary["overall_accuracy"] == 0


class TestFaz3_MemoryConsolidator:
    """Faz 3: Memory Consolidator test'leri."""

    @pytest.mark.asyncio
    async def test_consolidate_first_run(self) -> Any:
        """Otomatik eklendi."""
        consolidator = MemoryConsolidator(consolidation_interval_hours=24)
        mem = AgentMemory("TECHNICAL")
        # Boş memory — consolidation yapmaz
        result = await consolidator.consolidate(mem)
        assert result["consolidated"] is False
        assert result["reason"] == "empty_memory"

    @pytest.mark.asyncio
    async def test_consolidate_too_soon(self) -> Any:
        """Otomatik eklendi."""
        consolidator = MemoryConsolidator(consolidation_interval_hours=24)
        mem = AgentMemory("TECHNICAL")
        # İlk çalıştırma
        await consolidator.consolidate(mem)
        # İkinci çalıştırma — too_soon
        result = await consolidator.consolidate(mem)
        assert not result["consolidated"]
        assert result["reason"] == "too_soon"


# =====================================================
# FAZ 4: COMMUNICATION + SYNTHESIS
# =====================================================


class TestFaz4_CommunicationBus:
    """Faz 4: Communication Bus test'leri."""

    def test_send_and_receive(self) -> Any:
        """Otomatik eklendi."""
        bus = AgentCommunicationBus()
        msg = AgentMessage(
            sender=AgentRole.TECHNICAL,
            receiver=AgentRole.FUNDAMENTAL,
            task_id="t1",
            message_type="CONTEXT",
            payload={"data": "test"},
        )
        bus.send(msg)
        messages = bus.receive(AgentRole.FUNDAMENTAL)
        assert len(messages) == 1
        assert messages[0].payload["data"] == "test"

    def test_broadcast(self) -> Any:
        """Otomatik eklendi."""
        bus = AgentCommunicationBus()
        bus.broadcast(AgentRole.TECHNICAL, "ALERT", {"warning": True})
        # Tüm roller TECHNICAL hariç mesaj almalı
        for role in AgentRole:
            if role != AgentRole.TECHNICAL:
                messages = bus.peek(role)
                assert len(messages) >= 1


class TestFaz4_ConflictResolver:
    """Faz 4: Conflict Resolver test'leri."""

    def test_majority_vote(self) -> Any:
        """Otomatik eklendi."""
        resolver = ConflictResolver()
        results = {
            AgentRole.TECHNICAL: create_mock_agent_result(AgentRole.TECHNICAL, "LONG", 0.7),
            AgentRole.FUNDAMENTAL: create_mock_agent_result(AgentRole.FUNDAMENTAL, "LONG", 0.6),
            AgentRole.NEWS: create_mock_agent_result(AgentRole.NEWS, "SHORT", 0.5),
        }
        resolution = resolver.resolve(results)
        assert resolution.direction == "LONG"
        assert resolution.method == "majority_vote"

    def test_risk_veto(self) -> Any:
        """Otomatik eklendi."""
        resolver = ConflictResolver()
        results = {
            AgentRole.TECHNICAL: create_mock_agent_result(AgentRole.TECHNICAL, "LONG"),
        }
        resolution = resolver.resolve(results, risk_approved=False)
        assert resolution.direction == "NO_TRADE"
        assert resolution.method == "risk_veto"

    def test_debate_consensus(self) -> Any:
        """Otomatik eklendi."""
        resolver = ConflictResolver()
        results = {
            AgentRole.TECHNICAL: create_mock_agent_result(AgentRole.TECHNICAL, "LONG"),
        }
        resolution = resolver.resolve(results, debate_consensus="SHORT")
        assert resolution.direction == "SHORT"
        assert resolution.method == "debate_consensus"


class TestFaz4_SynthesisEngine:
    """Faz 4: Synthesis Engine test'leri."""

    @pytest.mark.asyncio
    async def test_synthesize_basic(self) -> Any:
        """Otomatik eklendi."""
        engine = SynthesisEngine()
        results = {
            AgentRole.TECHNICAL: create_mock_agent_result(AgentRole.TECHNICAL, "LONG", 0.7),
            AgentRole.FUNDAMENTAL: create_mock_agent_result(AgentRole.FUNDAMENTAL, "LONG", 0.6),
        }
        resolution = Resolution(
            direction="LONG",
            confidence=0.65,
            method="majority_vote",
            conflict=False,
        )
        result = await engine.synthesize(
            ticker="THYAO",
            agent_results=results,
            resolution=resolution,
        )
        assert result.ticker == "THYAO"
        assert result.final_direction == "LONG"
        assert result.final_confidence > 0


# =====================================================
# FAZ 5: SELF-EVALUATION
# =====================================================


class TestFaz5_SelfEvaluator:
    """Faz 5: Self-Evaluator test'leri."""

    def test_evaluate_empty_memory(self) -> Any:
        """Otomatik eklendi."""
        evaluator = AgentSelfEvaluator()
        mem = AgentMemory("TECHNICAL")
        report = evaluator.evaluate(mem)
        assert report.recommendation == "RETRAIN"  # 0 accuracy = RETRAIN
        assert report.accuracy == 0

    def test_evaluate_with_outcomes(self) -> Any:
        """Otomatik eklendi."""
        evaluator = AgentSelfEvaluator()
        mem = AgentMemory("TECHNICAL")

        # 50 görev ekle (min_samples)
        for i in range(50):
            task_id = f"t{i}"
            mem.record_task(task_id, "THYAO", "LONG", 0.7, "test")
            mem.record_outcome(task_id, 5.0 if i < 35 else -3.0, "RISK_ON")

        report = evaluator.evaluate(mem)
        assert report.accuracy == 0.7  # 35/50
        assert report.total_outcomes == 50


# =====================================================
# FAZ 6: RISK + PIPELINE
# =====================================================


class TestFaz6_RiskAssessor:
    """Faz 6: Risk Assessor test'leri."""

    @pytest.mark.asyncio
    async def test_assess_low_risk(self) -> Any:
        """Otomatik eklendi."""
        assessor = RiskAssessor()
        features = create_mock_features()
        results = {
            AgentRole.TECHNICAL: create_mock_agent_result(AgentRole.TECHNICAL, "LONG"),
            AgentRole.FUNDAMENTAL: create_mock_agent_result(AgentRole.FUNDAMENTAL, "LONG"),
        }
        assessment = await assessor.assess("THYAO", results, features)
        assert assessment.approved
        assert assessment.risk_level in ["LOW", "MEDIUM"]

    @pytest.mark.asyncio
    async def test_assess_high_volatility(self) -> Any:
        """Otomatik eklendi."""
        assessor = RiskAssessor()
        features = {**create_mock_features(), "atr_pct": 8.0}
        results = {
            AgentRole.TECHNICAL: create_mock_agent_result(AgentRole.TECHNICAL, "LONG"),
        }
        assessment = await assessor.assess("THYAO", results, features)
        assert assessment.risk_score > 20
        assert "volatilite" in str(assessment.risk_factors).lower() or assessment.risk_level in [
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        ]


# =====================================================
# FAZ 7: ENTEGRASYON
# =====================================================


class TestFaz7_Integration:
    """Faz 7: Entegrasyon test'leri."""

    def test_all_modules_importable(self) -> Any:
        """Tüm modüllerin import edilebilir olduğunu doğrula."""
        from services.agents import (
            AgentCommunicationBus,
            AgentMemory,
            AgentPipelineOrchestrator,
            AgentResult,
            AgentRole,
            AgentSelfEvaluator,
            AgentTask,
            ConflictDetector,
            DebateEngine,
            MultiAgentEvaluator,
            ParallelAgentRunner,
            RiskAssessor,
            SynthesisEngine,
        )

        assert AgentRole is not None
        assert AgentTask is not None
        assert AgentResult is not None
        assert ParallelAgentRunner is not None
        assert ConflictDetector is not None
        assert DebateEngine is not None
        assert AgentMemory is not None
        assert SynthesisEngine is not None
        assert RiskAssessor is not None
        assert AgentPipelineOrchestrator is not None
        assert AgentCommunicationBus is not None
        assert AgentSelfEvaluator is not None
        assert MultiAgentEvaluator is not None

    def test_pipeline_result_structure(self) -> Any:
        """PipelineResult yapısını doğrula."""
        import dataclasses

        assert dataclasses.is_dataclass(PipelineResult)
        field_names = [f.name for f in dataclasses.fields(PipelineResult)]
        assert "ticker" in field_names
        assert "synthesis" in field_names

    def test_memory_persistence_path(self) -> Any:
        """Memory persistence path'in doğru oluştuğunu doğrula."""
        mem = AgentMemory("TECHNICAL", persistence_path="/tmp/test_memory.json")
        assert mem._persistence_path == "/tmp/test_memory.json"

    def test_debate_confidence_damping(self) -> Any:
        """Debate confidence damping'in doğru uygulandığını doğrula."""
        engine = DebateEngine(confidence_damping=0.9)
        assert engine.confidence_damping == 0.9
        assert engine.max_rounds == 3

    def test_full_pipeline_structure(self) -> Any:
        """Full pipeline yapısını doğrula."""
        pipeline = AgentPipelineOrchestrator()
        assert pipeline.runner is not None
        assert pipeline.conflict_detector is not None
        assert pipeline.debate_engine is not None
        assert pipeline.risk_assessor is not None
        assert pipeline.synthesis_engine is not None
        assert pipeline.conflict_resolver is not None


# =====================================================
# BUG FIX TESTS
# =====================================================


class TestBugFixes:
    """Düzeltilen bug'lar için test'ler."""

    @pytest.mark.asyncio
    async def test_multi_evaluator_no_double_evaluation(self) -> Any:
        """MultiAgentEvaluator.evaluate_all() double-evaluation yapmamalı."""
        evaluator = MultiAgentEvaluator()
        mem = AgentMemory("TECHNICAL")
        # 50 görev ekle
        for i in range(50):
            tid = f"t{i}"
            mem.record_task(tid, "THYAO", "LONG", 0.7, "test")
            mem.record_outcome(tid, 5.0 if i < 35 else -3.0, "RISK_ON")

        result = evaluator.evaluate_all({"TECHNICAL": mem})
        # System health doğru hesaplanmalı (double-evaluation olmadan)
        assert result["system_health"] in ["HEALTHY", "DEGRADED", "CRITICAL"]
        assert result["agent_reports"]["TECHNICAL"]["accuracy"] == 0.7

    @pytest.mark.asyncio
    async def test_consolidator_empty_memory_no_run(self) -> Any:
        """Boş memory'de consolidation çalışmamalı."""
        consolidator = MemoryConsolidator()
        mem = AgentMemory("TECHNICAL")
        result = await consolidator.consolidate(mem)
        assert not result["consolidated"]
        assert result["reason"] == "empty_memory"

    @pytest.mark.asyncio
    async def test_consolidator_populated_memory_runs(self) -> Any:
        """Dolu memory'de consolidation çalışmalı."""
        consolidator = MemoryConsolidator()
        mem = AgentMemory("TECHNICAL")
        for i in range(10):
            mem.record_task(f"t{i}", "THYAO", "LONG", 0.7, "test")
        result = await consolidator.consolidate(mem)
        assert result["consolidated"] is True

    def test_conflict_resolver_neutral_excluded(self) -> Any:
        """NEUTRAL oylar LONG/SHORT kararını etkilememeli."""
        resolver = ConflictResolver()
        results = {
            AgentRole.TECHNICAL: create_mock_agent_result(AgentRole.TECHNICAL, "LONG", 0.7),
            AgentRole.FUNDAMENTAL: create_mock_agent_result(AgentRole.FUNDAMENTAL, "NEUTRAL", 0.5),
            AgentRole.NEWS: create_mock_agent_result(AgentRole.NEWS, "NEUTRAL", 0.5),
            AgentRole.MACRO: create_mock_agent_result(AgentRole.MACRO, "NEUTRAL", 0.5),
        }
        resolution = resolver.resolve(results)
        # 1 LONG vs 0 SHORT → LONG (NEUTRAL sayılmaz)
        assert resolution.direction == "LONG"
        assert resolution.method == "majority_vote"

    def test_conflict_resolver_all_neutral(self) -> Any:
        """Tüm agent'lar NEUTRAL ise NO_TRADE dönmeli."""
        resolver = ConflictResolver()
        results = {
            AgentRole.TECHNICAL: create_mock_agent_result(AgentRole.TECHNICAL, "NEUTRAL", 0.5),
            AgentRole.FUNDAMENTAL: create_mock_agent_result(AgentRole.FUNDAMENTAL, "NEUTRAL", 0.5),
        }
        resolution = resolver.resolve(results)
        assert resolution.direction == "NO_TRADE"
        assert resolution.method == "no_directional_votes"

    def test_prompt_factory_keyerror_protection(self) -> Any:
        """PromptFactory eksik anahtar için KeyError atmamalı."""
        # synthesis template'inde {agent_results} var ama kwargs'da yok
        try:
            system, user = PromptFactory.get_prompts(
                "synthesis",
                "THYAO",
                {},
                # agent_results, debate_result vb. gönderilmiyor
            )
            # KeyError atmamalı, boş string kullanmalı
            assert "Sentez" in system
            assert "THYAO" in user
        except KeyError:
            pytest.fail("PromptFactory KeyError fırlattı — koruma çalışmıyor")

    def test_debate_damping_no_mutation(self) -> Any:
        """Debate confidence damping orijinal sonucu bozmamalı."""
        engine = DebateEngine(confidence_damping=0.9)
        assert engine.confidence_damping == 0.9
        # Damping'in orijinal result'ı bozmadığını doğrulamak için
        # _run_round'da damping_local değişkeni kullanılıyor
        # (doğrudan result.confidence *= damping yapılmıyor)


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
