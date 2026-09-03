"""
ALPHA BIST — Agent System Package v2.0

Tüm agent modülleri.
"""

# === Core ===
# === Phase 3: Memory ===
from .agent_memory import (
    AgentMemory,
    EpisodicMemory,
    MemoryConsolidator,
    MemoryEntry,
    SemanticMemory,
    WorkingMemory,
)
from .agent_pipeline import AgentPipelineOrchestrator, PipelineMetrics, PipelineResult
from .circuit_breaker import CircuitBreaker, CircuitBreakerLLMClient, CircuitState
from .agent_system import (
    AgentOrchestrator,
    AgentResult,
    AgentRole,
    AgentTask,
    AgentToolRegistry,
    AIFallback,
    AIOutputValidator,
    BaseAgent,
    agent_orchestrator,
    run_agent_analysis,
)

# === Phase 4: Communication + Synthesis ===
from .communication_bus import (
    AgentCommunicationBus,
    AgentMessage,
    ConflictResolver,
    Resolution,
)

# === Phase 2: Conflict + Debate ===
from .conflict_detector import ConflictDetector, ConflictReport
from .debate_engine import DebateEngine, DebateResult, DebateRound

# === LLM ===
from .llm_client import (
    AnthropicLLMClient,
    BaseLLMClient,
    LLMClientFactory,
    LLMConfig,
    LLMResponse,
    OllamaLLMClient,
    OpenAILLMClient,
    parse_llm_json,
)

# === Phase 1: Parallel ===
from .parallel_runner import AgentPipelineBuilder, ParallelAgentRunner, ParallelRunResult

# === Prompts ===
from .prompts import PROMPT_VERSION, PromptFactory

# === Phase 6: Risk + Pipeline ===
from .risk_assessor import RiskAssessment, RiskAssessor

# === Schemas ===
from .schemas import (
    AgentOutputSchema,
    DebateArgumentSchema,
    Direction,
    RiskAssessmentSchema,
    RiskLevel,
    SynthesisResultSchema,
    validate_agent_output,
)

# === Phase 5: Self-Evaluation ===
from .self_evaluator import AgentSelfEvaluator, EvalReport, MultiAgentEvaluator
from .synthesis_engine import SynthesisEngine, SynthesisResult
from .trace_context import TraceContext, get_trace_id, trace_processor

__all__ = [
    # Core
    "AgentRole",
    "AgentTask",
    "AgentResult",
    "AgentToolRegistry",
    "AIOutputValidator",
    "AIFallback",
    "BaseAgent",
    "AgentOrchestrator",
    "agent_orchestrator",
    "run_agent_analysis",
    # LLM
    "BaseLLMClient",
    "OllamaLLMClient",
    "OpenAILLMClient",
    "AnthropicLLMClient",
    "LLMClientFactory",
    "LLMConfig",
    "LLMResponse",
    "parse_llm_json",
    # Schemas
    "AgentOutputSchema",
    "Direction",
    "RiskLevel",
    "SynthesisResultSchema",
    "DebateArgumentSchema",
    "RiskAssessmentSchema",
    "validate_agent_output",
    # Prompts
    "PromptFactory",
    "PROMPT_VERSION",
    # Parallel
    "ParallelAgentRunner",
    "ParallelRunResult",
    "AgentPipelineBuilder",
    # Conflict + Debate
    "ConflictDetector",
    "ConflictReport",
    "DebateEngine",
    "DebateResult",
    "DebateRound",
    # Memory
    "AgentMemory",
    "WorkingMemory",
    "EpisodicMemory",
    "SemanticMemory",
    "MemoryConsolidator",
    "MemoryEntry",
    # Communication + Synthesis
    "AgentCommunicationBus",
    "AgentMessage",
    "ConflictResolver",
    "Resolution",
    "SynthesisEngine",
    "SynthesisResult",
    # Self-Evaluation
    "AgentSelfEvaluator",
    "MultiAgentEvaluator",
    "EvalReport",
    # Risk + Pipeline
    "RiskAssessor",
    "RiskAssessment",
    "AgentPipelineOrchestrator",
    "PipelineResult",
    "PipelineMetrics",
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitBreakerLLMClient",
    "CircuitState",
    # Trace
    "TraceContext",
    "get_trace_id",
    "trace_processor",
]
