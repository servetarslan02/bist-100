"""
ALPHA BIST — Agent System Package v2.0

Tüm agent modülleri.
"""

# === Core ===
from .agent_system import (
    AgentRole, AgentTask, AgentResult,
    AgentToolRegistry, AIOutputValidator, AIFallback,
    BaseAgent, AgentOrchestrator, agent_orchestrator,
    run_agent_analysis,
)

# === LLM ===
from .llm_client import (
    BaseLLMClient, OllamaLLMClient, OpenAILLMClient, AnthropicLLMClient,
    LLMClientFactory, LLMConfig, LLMResponse, parse_llm_json,
)

# === Schemas ===
from .schemas import (
    AgentOutputSchema, Direction, RiskLevel,
    SynthesisResultSchema, DebateArgumentSchema, RiskAssessmentSchema,
    validate_agent_output,
)

# === Prompts ===
from .prompts import PromptFactory, PROMPT_VERSION

# === Phase 1: Parallel ===
from .parallel_runner import ParallelAgentRunner, ParallelRunResult, AgentPipelineBuilder

# === Phase 2: Conflict + Debate ===
from .conflict_detector import ConflictDetector, ConflictReport
from .debate_engine import DebateEngine, DebateResult, DebateRound

# === Phase 3: Memory ===
from .agent_memory import (
    AgentMemory, WorkingMemory, EpisodicMemory, SemanticMemory,
    MemoryConsolidator, MemoryEntry,
)

# === Phase 4: Communication + Synthesis ===
from .communication_bus import (
    AgentCommunicationBus, AgentMessage, ConflictResolver, Resolution,
)
from .synthesis_engine import SynthesisEngine, SynthesisResult

# === Phase 5: Self-Evaluation ===
from .self_evaluator import AgentSelfEvaluator, MultiAgentEvaluator, EvalReport

# === Phase 6: Risk + Pipeline ===
from .risk_assessor import RiskAssessor, RiskAssessment
from .agent_pipeline import AgentPipelineOrchestrator, PipelineResult

__all__ = [
    # Core
    "AgentRole", "AgentTask", "AgentResult",
    "AgentToolRegistry", "AIOutputValidator", "AIFallback",
    "BaseAgent", "AgentOrchestrator", "agent_orchestrator",
    "run_agent_analysis",
    # LLM
    "BaseLLMClient", "OllamaLLMClient", "OpenAILLMClient", "AnthropicLLMClient",
    "LLMClientFactory", "LLMConfig", "LLMResponse", "parse_llm_json",
    # Schemas
    "AgentOutputSchema", "Direction", "RiskLevel",
    "SynthesisResultSchema", "DebateArgumentSchema", "RiskAssessmentSchema",
    "validate_agent_output",
    # Prompts
    "PromptFactory", "PROMPT_VERSION",
    # Parallel
    "ParallelAgentRunner", "ParallelRunResult", "AgentPipelineBuilder",
    # Conflict + Debate
    "ConflictDetector", "ConflictReport",
    "DebateEngine", "DebateResult", "DebateRound",
    # Memory
    "AgentMemory", "WorkingMemory", "EpisodicMemory", "SemanticMemory",
    "MemoryConsolidator", "MemoryEntry",
    # Communication + Synthesis
    "AgentCommunicationBus", "AgentMessage", "ConflictResolver", "Resolution",
    "SynthesisEngine", "SynthesisResult",
    # Self-Evaluation
    "AgentSelfEvaluator", "MultiAgentEvaluator", "EvalReport",
    # Risk + Pipeline
    "RiskAssessor", "RiskAssessment",
    "AgentPipelineOrchestrator", "PipelineResult",
]
