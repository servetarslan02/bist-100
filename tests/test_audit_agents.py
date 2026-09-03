"""
services/agents/ — Audit Düzeltmeleri Test Suite

Yapılan tüm düzeltmelerin doğru çalıştığını doğrular.
"""

import sys

import pytest

sys.path.insert(0, ".")


# =====================================================
# 1. __init__.py — __version__ ve Docstring
# =====================================================


class TestAgentsInit:
    """__init__.py düzeltmeleri."""

    def test_version_exists(self):
        from services.agents import __version__

        assert __version__ == "2.0.0"

    def test_all_imports_work(self):
        """Tüm eager import'lar başarılı olmalı."""
        from services.agents import (
            AgentMemory,
            AgentPipelineOrchestrator,
            AgentResult,
            AgentRole,
            AgentSelfEvaluator,
            AgentTask,
            BaseAgent,
            CircuitBreaker,
            CircuitBreakerLLMClient,
            CircuitState,
            ConflictDetector,
            DebateEngine,
            MultiAgentEvaluator,
            ParallelAgentRunner,
            RiskAssessor,
            SynthesisEngine,
            TraceContext,
            __version__,
        )
        assert AgentRole is not None
        assert __version__ == "2.0.0"


# =====================================================
# 2. agent_memory.py — Düzeltmeler
# =====================================================


class TestAgentMemory:
    """agent_memory.py düzeltmeleri."""

    def test_no_typo_in_docstring(self):
        """retry_delay satırında fazla n harfi olmamalı."""
        import inspect
        from services.agents.agent_memory import MemoryWriteBuffer

        source = inspect.getsource(MemoryWriteBuffer.__init__)
        assert "n            retry_delay" not in source
        assert "retry_delay: Denemeler arası bekleme" in source

    def test_write_buffer_metrics_to_dict_has_docstring(self):
        import inspect
        from services.agents.agent_memory import WriteBufferMetrics

        source = inspect.getsource(WriteBufferMetrics.to_dict)
        tree = inspect.getsource(WriteBufferMetrics.to_dict)
        # Docstring var mı?
        assert '"""' in source or "'''" in source

    def test_should_save_fallback_has_docstring(self):
        import inspect
        from services.agents import agent_memory

        source = inspect.getsource(agent_memory)
        # Fallback should_save fonksiyonu docstring'e sahip olmalı
        assert "Fallback: her zaman kaydet" in source

    def test_write_buffer_create(self):
        from services.agents.agent_memory import MemoryWriteBuffer

        buf = MemoryWriteBuffer(batch_window_ms=100, max_batch_size=10)
        assert buf is not None
        r = repr(buf)
        assert "MemoryWriteBuffer" in r

    def test_write_buffer_enqueue_and_flush(self):
        from services.agents.agent_memory import MemoryWriteBuffer

        buf = MemoryWriteBuffer(batch_window_ms=100, max_batch_size=10)
        buf.start()
        buf.enqueue("/tmp/test_audit.json", b'{"test": 1}')
        metrics = buf.get_metrics()
        assert metrics["total_writes"] == 1
        assert metrics["queue_depth"] == 1
        buf.flush()
        metrics = buf.get_metrics()
        assert metrics["queue_depth"] == 0
        buf.shutdown()

        import os
        for f in ["/tmp/test_audit.json", "/tmp/test_audit.json.gz"]:
            if os.path.exists(f):
                os.remove(f)

    def test_memory_entry_repr(self):
        from services.agents.agent_memory import MemoryEntry

        entry = MemoryEntry(
            task_id="t1", agent_role="TECHNICAL", ticker="THYAO",
            direction="LONG", confidence=0.8, reasoning="test",
            timestamp="2026-09-04T00:00:00Z",
        )
        r = repr(entry)
        assert "MemoryEntry" in r
        assert "THYAO" in r

    def test_working_memory_add_and_get(self):
        from services.agents.agent_memory import MemoryEntry, WorkingMemory

        wm = WorkingMemory(max_items=5)
        entry = MemoryEntry(
            task_id="t1", agent_role="TECHNICAL", ticker="THYAO",
            direction="LONG", confidence=0.8, reasoning="test",
            timestamp="2026-09-04T00:00:00Z",
        )
        wm.add(entry)
        assert len(wm.items) == 1
        recent = wm.get_recent(ticker="THYAO")
        assert len(recent) == 1

    def test_episodic_memory_outcome(self):
        from services.agents.agent_memory import EpisodicMemory, MemoryEntry

        em = EpisodicMemory()
        entry = MemoryEntry(
            task_id="t1", agent_role="TECHNICAL", ticker="THYAO",
            direction="LONG", confidence=0.8, reasoning="test",
            timestamp="2026-09-04T00:00:00Z",
        )
        em.add(entry)
        em.record_outcome("t1", actual_return=5.0, regime="RISK_ON")
        assert len(em.outcomes) == 1
        assert em.outcomes["t1"]["correct"] is True

    def test_semantic_memory_pattern(self):
        from services.agents.agent_memory import SemanticMemory

        sm = SemanticMemory()
        sm.add_pattern("THYAO", "RISK_ON", {"pattern": "breakout", "confidence": 0.8})
        patterns = sm.get_patterns(ticker="THYAO")
        assert len(patterns) == 1

    def test_agent_memory_save_load(self):
        import os
        import time

        from services.agents.agent_memory import AgentMemory

        path = "/tmp/test_agent_memory_audit.json"
        mem = AgentMemory(agent_role="TEST", persistence_path=path)
        mem.record_task("t1", "THYAO", "LONG", 0.8, "test")
        mem.record_outcome("t1", 5.0, "RISK_ON")
        mem.save(critical=True)
        time.sleep(0.5)

        mem2 = AgentMemory(agent_role="TEST", persistence_path=path)
        mem2.load()
        assert len(mem2.working.items) == 1
        assert len(mem2.episodic.outcomes) == 1

        for f in [path, path + ".gz"]:
            if os.path.exists(f):
                os.remove(f)


# =====================================================
# 3. circuit_breaker.py — Düzeltmeler
# =====================================================


class TestCircuitBreaker:
    """circuit_breaker.py düzeltmeleri."""

    def test_stats_to_dict_has_docstring(self):
        import inspect
        from services.agents.circuit_breaker import CircuitBreakerStats

        source = inspect.getsource(CircuitBreakerStats.to_dict)
        assert '"""' in source or "'''" in source

    def test_circuit_breaker_state_machine(self):
        from services.agents.circuit_breaker import CircuitBreaker, CircuitState

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=5.0)
        assert cb.state == CircuitState.CLOSED

        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert not cb.can_execute()

        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_circuit_breaker_repr(self):
        from services.agents.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=5)
        r = repr(cb)
        assert "CircuitBreaker" in r
        assert "CLOSED" in r

    def test_circuit_breaker_stats_repr(self):
        from services.agents.circuit_breaker import CircuitBreakerStats

        stats = CircuitBreakerStats(total_calls=10, successful_calls=8, failed_calls=2)
        r = repr(stats)
        assert "CircuitBreakerStats" in r


# =====================================================
# 4. agent_system.py — Düzeltmeler (yok ama doğrulama)
# =====================================================


class TestAgentSystem:
    """agent_system.py doğrulama testleri."""

    def test_no_placeholder_docstring(self):
        import inspect
        from services.agents.agent_system import BaseAgent

        source = inspect.getsource(BaseAgent)
        assert "Otomatik eklendi" not in source

    def test_agent_roles_complete(self):
        from services.agents.agent_system import AgentRole

        expected = [
            "RESEARCH", "NEWS", "MACRO", "FUNDAMENTAL", "TECHNICAL",
            "RISK", "PORTFOLIO", "SCENARIO", "BACKTEST", "SYNTHESIS",
            "BULL", "BEAR",
        ]
        for role in expected:
            assert hasattr(AgentRole, role)

    def test_fallback_analysis(self):
        from services.agents.agent_system import AIFallback

        features = {
            "roc_5d": 5.0, "volume_zscore": 2.0, "rsi_14": 65,
            "trend_slope_20d": 0.5, "macd_histogram": 0.3, "bb_position": 0.6,
        }
        result = AIFallback.rule_based_analysis(features, "THYAO")
        assert result["direction"] in ["LONG", "SHORT", "NEUTRAL"]
        assert 0 <= result["confidence"] <= 1
        assert result["source"] == "rule_based_fallback"

    def test_output_validator(self):
        from services.agents.agent_system import AIOutputValidator

        # Geçerli
        result = AIOutputValidator.validate('{"direction": "LONG", "confidence": 0.8}')
        assert result["valid"]

        # Geçersiz yön
        result = AIOutputValidator.validate('{"direction": "INVALID"}')
        assert not result["valid"]

        # Negatif fiyat
        result = AIOutputValidator.validate('{"price": -100}')
        assert not result["valid"]


# =====================================================
# 5. agent_pipeline.py — Doğrulama
# =====================================================


class TestAgentPipeline:
    """agent_pipeline.py doğrulama testleri."""

    def test_no_placeholder_docstring(self):
        import inspect
        from services.agents.agent_pipeline import AgentPipelineOrchestrator

        source = inspect.getsource(AgentPipelineOrchestrator)
        assert "Otomatik eklendi" not in source

    def test_pipeline_metrics(self):
        from services.agents.agent_pipeline import PipelineMetrics

        pm = PipelineMetrics()
        pm.record_run(True, 1500.0, "THYAO")
        pm.record_run(False, 2000.0, "GARAN")
        assert pm.total_runs == 2
        assert pm.successful_runs == 1
        assert pm.failed_runs == 1
        assert pm.success_rate == 0.5

    def test_pipeline_metrics_repr(self):
        from services.agents.agent_pipeline import PipelineMetrics

        pm = PipelineMetrics()
        pm.record_run(True, 1000.0, "THYAO")
        r = repr(pm)
        assert "PipelineMetrics" in r


# =====================================================
# 6. communication_bus.py — Doğrulama
# =====================================================


class TestCommunicationBus:
    """communication_bus.py doğrulama testleri."""

    def test_no_placeholder_docstring(self):
        import inspect
        from services.agents.communication_bus import AgentCommunicationBus

        source = inspect.getsource(AgentCommunicationBus)
        assert "Otomatik eklendi" not in source


# =====================================================
# 7. conflict_detector.py — Doğrulama
# =====================================================


class TestConflictDetector:
    """conflict_detector.py doğrulama testleri."""

    def test_no_placeholder_docstring(self):
        import inspect
        from services.agents.conflict_detector import ConflictDetector

        source = inspect.getsource(ConflictDetector)
        assert "Otomatik eklendi" not in source


# =====================================================
# 8. debate_engine.py — Doğrulama
# =====================================================


class TestDebateEngine:
    """debate_engine.py doğrulama testleri."""

    def test_no_placeholder_docstring(self):
        import inspect
        from services.agents.debate_engine import DebateEngine

        source = inspect.getsource(DebateEngine)
        assert "Otomatik eklendi" not in source


# =====================================================
# 9. llm_client.py — Doğrulama
# =====================================================


class TestLLMClient:
    """llm_client.py doğrulama testleri."""

    def test_no_placeholder_docstring(self):
        import inspect
        from services.agents.llm_client import BaseLLMClient

        source = inspect.getsource(BaseLLMClient)
        assert "Otomatik eklendi" not in source


# =====================================================
# 10. parallel_runner.py — Doğrulama
# =====================================================


class TestParallelRunner:
    """parallel_runner.py doğrulama testleri."""

    def test_no_placeholder_docstring(self):
        import inspect
        from services.agents.parallel_runner import ParallelAgentRunner

        source = inspect.getsource(ParallelAgentRunner)
        assert "Otomatik eklendi" not in source


# =====================================================
# 11. risk_assessor.py — Doğrulama
# =====================================================


class TestRiskAssessor:
    """risk_assessor.py doğrulama testleri."""

    def test_no_placeholder_docstring(self):
        import inspect
        from services.agents.risk_assessor import RiskAssessor

        source = inspect.getsource(RiskAssessor)
        assert "Otomatik eklendi" not in source


# =====================================================
# 12. self_evaluator.py — Doğrulama
# =====================================================


class TestSelfEvaluator:
    """self_evaluator.py doğrulama testleri."""

    def test_no_placeholder_docstring(self):
        import inspect
        from services.agents.self_evaluator import AgentSelfEvaluator

        source = inspect.getsource(AgentSelfEvaluator)
        assert "Otomatik eklendi" not in source


# =====================================================
# 13. synthesis_engine.py — Doğrulama
# =====================================================


class TestSynthesisEngine:
    """synthesis_engine.py doğrulama testleri."""

    def test_no_placeholder_docstring(self):
        import inspect
        from services.agents.synthesis_engine import SynthesisEngine

        source = inspect.getsource(SynthesisEngine)
        assert "Otomatik eklendi" not in source


# =====================================================
# 14. trace_context.py — Doğrulama
# =====================================================


class TestTraceContext:
    """trace_context.py doğrulama testleri."""

    def test_no_placeholder_docstring(self):
        import inspect
        from services.agents.trace_context import TraceContext

        source = inspect.getsource(TraceContext)
        assert "Otomatik eklendi" not in source


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
