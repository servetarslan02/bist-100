"""
ALPHA BIST — AI Agent System v2.0

Refactored:
- LLM client abstraction (Ollama, OpenAI, Anthropic, DeepSeek, Qwen)
- Structured JSON output (Pydantic schemas)
- Prompt templates (BIST-specific)
- Hallucination protection (5 katmanlı)
- Rule-based fallback (LLM yoksa)

FAZ 0: Temel altyapı refactor
"""

import asyncio
import json
import hashlib
import re
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import structlog

from .llm_client import (
    BaseLLMClient, LLMClientFactory, LLMConfig, LLMResponse,
    parse_llm_json,
)
from .schemas import (
    AgentOutputSchema, Direction, RiskLevel,
    SynthesisResultSchema, DebateArgumentSchema,
    RiskAssessmentSchema, validate_agent_output,
    TechnicalOutputSchema, FundamentalOutputSchema,
    NewsOutputSchema, MacroOutputSchema,
)
from .prompts import PromptFactory, PROMPT_VERSION

logger = structlog.get_logger()


class AgentRole(str, Enum):
    RESEARCH = "RESEARCH"
    NEWS = "NEWS"
    MACRO = "MACRO"
    FUNDAMENTAL = "FUNDAMENTAL"
    TECHNICAL = "TECHNICAL"
    RISK = "RISK"
    PORTFOLIO = "PORTFOLIO"
    SCENARIO = "SCENARIO"
    BACKTEST = "BACKTEST"
    SYNTHESIS = "SYNTHESIS"
    BULL = "BULL"
    BEAR = "BEAR"


@dataclass
class AgentTask:
    """Agent görevi."""
    task_id: str
    agent_role: AgentRole
    ticker: str
    prompt: str
    context: Dict[str, Any]
    max_steps: int = 10
    timeout_seconds: int = 120
    template_name: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AgentResult:
    """Agent sonucu."""
    task_id: str
    agent_role: AgentRole
    ticker: str
    success: bool
    output: Dict[str, Any]
    confidence: float
    evidence: List[str]
    reasoning: str
    model_version: str
    prompt_version: str
    input_hash: str
    duration_ms: float
    error: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0


class AgentToolRegistry:
    """Agent tool erişim kontrolü."""

    ALLOWED_TOOLS = {
        AgentRole.RESEARCH: [
            "read_market_data", "read_news", "read_fundamentals",
            "run_technical_analysis", "run_valuation",
        ],
        AgentRole.NEWS: [
            "read_news", "read_kap", "read_social",
        ],
        AgentRole.MACRO: [
            "read_macro_data", "read_world_state",
        ],
        AgentRole.FUNDAMENTAL: [
            "read_fundamentals", "read_financials", "run_valuation",
        ],
        AgentRole.TECHNICAL: [
            "read_market_data", "run_technical_analysis",
        ],
        AgentRole.RISK: [
            "read_portfolio", "calculate_risk", "approve_decision", "reject_decision",
        ],
        AgentRole.PORTFOLIO: [
            "read_portfolio", "calculate_position_size",
        ],
        AgentRole.SCENARIO: [
            "run_scenario", "run_stress_test",
        ],
        AgentRole.BACKTEST: [
            "run_backtest", "read_historical_data",
        ],
        AgentRole.SYNTHESIS: [
            "read_all_results", "generate_report",
        ],
        AgentRole.BULL: [
            "read_market_data", "read_fundamentals", "run_technical_analysis",
        ],
        AgentRole.BEAR: [
            "read_market_data", "read_fundamentals", "run_technical_analysis",
        ],
    }

    @classmethod
    def can_access(cls, role: AgentRole, tool: str) -> bool:
        return tool in cls.ALLOWED_TOOLS.get(role, [])


class AIOutputValidator:
    """AI çıktısını doğrula — 5 katmanlı hallucination koruması."""

    @staticmethod
    def validate(llm_output: str, expected_schema: Optional[str] = None) -> Dict[str, Any]:
        """AI çıktısını doğrula.

        Pipeline:
        1. JSON parse (llm_client.parse_llm_json)
        2. Schema validation (Pydantic)
        3. Range validation (confidence 0-1, score 0-100)
        4. Domain validation (makul değerler)
        5. Source validation
        """
        errors = []

        # 1. JSON parse
        parsed = parse_llm_json(llm_output)
        if parsed is None:
            return {"valid": False, "parsed": None, "errors": ["No valid JSON found"]}

        # 2. Schema validation (Pydantic)
        schema_map = {
            "technical": TechnicalOutputSchema,
            "fundamental": FundamentalOutputSchema,
            "news": NewsOutputSchema,
            "macro": MacroOutputSchema,
            "debate": DebateArgumentSchema,
            "risk": RiskAssessmentSchema,
            "synthesis": SynthesisResultSchema,
        }

        if expected_schema and expected_schema in schema_map:
            is_valid, validated, schema_errors = validate_agent_output(
                parsed, schema_class=schema_map[expected_schema]
            )
            if not is_valid:
                errors.extend(schema_errors)
            else:
                parsed = validated

        # 3. Range validation
        if "confidence" in parsed:
            conf = parsed["confidence"]
            if isinstance(conf, (int, float)):
                if conf < 0 or conf > 100:
                    errors.append(f"Confidence out of range: {conf}")
                if conf > 1:
                    parsed["confidence"] = conf / 100

        if "score" in parsed:
            score = parsed["score"]
            if isinstance(score, (int, float)):
                if score < 0 or score > 100:
                    errors.append(f"Score out of range: {score}")

        if "direction" in parsed:
            valid_directions = [d.value for d in Direction]
            if parsed["direction"] not in valid_directions:
                errors.append(f"Invalid direction: {parsed['direction']}")

        # 4. Domain validation
        if "risk_level" in parsed:
            valid_levels = [r.value for r in RiskLevel]
            if parsed["risk_level"] not in valid_levels:
                errors.append(f"Invalid risk level: {parsed['risk_level']}")

        # 5. Source validation
        if "source" in parsed:
            source = parsed["source"]
            if isinstance(source, str) and source.startswith("http"):
                if not re.match(r'https?://', source):
                    errors.append(f"Suspicious source URL: {source}")

        # 6. F-030: Price/Date hallucination validation
        if "price" in parsed:
            price = parsed["price"]
            if isinstance(price, (int, float)):
                if price <= 0:
                    errors.append(f"Invalid price (<=0): {price}")
                elif price > 1000000:  # 1M TL üzeri mantıksız
                    errors.append(f"Suspiciously high price: {price}")

        if "target_price" in parsed:
            tp = parsed["target_price"]
            if isinstance(tp, (int, float)):
                if tp <= 0:
                    errors.append(f"Invalid target_price (<=0): {tp}")

        if "stop_loss" in parsed:
            sl = parsed["stop_loss"]
            if isinstance(sl, (int, float)):
                if sl <= 0:
                    errors.append(f"Invalid stop_loss (<=0): {sl}")

        if "date" in parsed:
            date_str = str(parsed["date"])
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                # Gelecek tarih kontrolü (1 yıldan fazla ileri)
                if dt.year > datetime.now().year + 1:
                    errors.append(f"Future date too far: {date_str}")
            except (ValueError, TypeError):
                pass  # Tarih parse edilemiyorsa diğer validasyonlar yakalar

        valid = len(errors) == 0
        return {"valid": valid, "parsed": parsed, "errors": errors}


class AIFallback:
    """LLM çalışmadığında rule-based fallback."""

    @staticmethod
    def rule_based_analysis(features: Dict[str, float], ticker: str) -> Dict[str, Any]:
        """LLM yokken kural tabanlı analiz."""
        score = 50.0
        reasons = []
        risks = []

        # Momentum
        roc_5d = features.get("roc_5d", 0)
        if roc_5d > 3:
            score += 10
            reasons.append(f"Güçlü kısa vadeli momentum: +{roc_5d:.1f}%")
        elif roc_5d < -3:
            score -= 10
            risks.append(f"Zayıf momentum: {roc_5d:.1f}%")

        # Volume
        vol_z = features.get("volume_zscore", 0)
        if vol_z > 2:
            score += 8
            reasons.append(f"Hacim anomalisi: {vol_z:.1f}σ")

        # RSI
        rsi = features.get("rsi_14", 50)
        if rsi > 70:
            score -= 5
            risks.append(f"Aşırı alım: RSI={rsi:.0f}")
        elif rsi < 30:
            score += 5
            reasons.append(f"Aşırı satım: RSI={rsi:.0f}")

        # Trend
        trend = features.get("trend_slope_20d", 0)
        if trend > 0:
            score += 5
            reasons.append("Yükselen trend")
        elif trend < 0:
            score -= 5
            risks.append("Düşen trend")

        # Direction
        if score >= 60:
            direction = "LONG"
        elif score <= 40:
            direction = "SHORT"
        else:
            direction = "NEUTRAL"

        confidence = min(abs(score - 50) / 50, 0.8)

        return {
            "direction": direction,
            "confidence": round(confidence, 4),
            "score": round(score, 2),
            "reasoning": "Rule-based analysis (LLM unavailable)",
            "reasons": reasons,
            "risks": risks,
            "source": "rule_based_fallback",
        }


class BaseAgent:
    """Base AI Agent v2.0 — LLM client + structured output."""

    def __init__(
        self,
        role: AgentRole,
        llm_client: Optional[BaseLLMClient] = None,
        model_version: str = "auto",
        prompt_version: str = PROMPT_VERSION,
    ):
        self.role = role
        self.llm_client = llm_client
        self.model_version = model_version
        self.prompt_version = prompt_version

    async def execute(
        self,
        task: AgentTask,
        llm_client: Optional[BaseLLMClient] = None,
    ) -> AgentResult:
        """Görevi çalıştır."""
        start = time.monotonic()

        # LLM client önceliği: parametre > instance > fallback
        client = llm_client or self.llm_client

        # Input hash
        input_str = json.dumps({
            "ticker": task.ticker,
            "prompt": task.prompt[:200],
            "context_keys": list(task.context.keys()),
        }, sort_keys=True)
        input_hash = hashlib.sha256(input_str.encode()).hexdigest()[:16]

        try:
            if client:
                # LLM ile analiz
                output = await self._call_llm(task, client)
            else:
                # Rule-based fallback
                output = AIFallback.rule_based_analysis(
                    task.context.get("features", {}), task.ticker
                )

            # Validate — rol -> şema eşlemesi ile (önceden expected_schema
            # hiç geçirilmediği için Pydantic doğrulama katmanı hiçbir
            # zaman gerçekten devreye girmiyordu).
            _role_schema_map = {
                AgentRole.TECHNICAL: "technical",
                AgentRole.FUNDAMENTAL: "fundamental",
                AgentRole.NEWS: "news",
                AgentRole.MACRO: "macro",
                AgentRole.BULL: "debate",
                AgentRole.BEAR: "debate",
                AgentRole.RISK: "risk",
                AgentRole.SYNTHESIS: "synthesis",
            }
            validation = AIOutputValidator.validate(
                json.dumps(output), expected_schema=_role_schema_map.get(self.role)
            )
            if not validation["valid"]:
                logger.warning(
                    "AI output validation failed, using fallback",
                    errors=validation["errors"],
                )
                output = AIFallback.rule_based_analysis(
                    task.context.get("features", {}), task.ticker
                )

            duration = (time.monotonic() - start) * 1000

            return AgentResult(
                task_id=task.task_id,
                agent_role=self.role,
                ticker=task.ticker,
                success=True,
                output=output,
                confidence=output.get("confidence", 0.5),
                evidence=output.get("reasons", []),
                reasoning=output.get("reasoning", ""),
                model_version=self.model_version if client else "rule-based",
                prompt_version=self.prompt_version,
                input_hash=input_hash,
                duration_ms=round(duration, 2),
                tokens_in=output.get("_tokens_in", 0),
                tokens_out=output.get("_tokens_out", 0),
            )

        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            logger.error("Agent execution failed", agent=self.role.value, error=str(e))

            return AgentResult(
                task_id=task.task_id,
                agent_role=self.role,
                ticker=task.ticker,
                success=False,
                output={},
                confidence=0.0,
                evidence=[],
                reasoning="",
                model_version="error",
                prompt_version=self.prompt_version,
                input_hash=input_hash,
                duration_ms=round(duration, 2),
                error=str(e),
            )

    async def _call_llm(
        self,
        task: AgentTask,
        client: BaseLLMClient,
    ) -> Dict[str, Any]:
        """LLM çağrısı — prompt template ile."""

        # Prompt template kullan (varsa)
        if task.template_name:
            system_prompt, user_prompt = PromptFactory.get_prompts(
                template_name=task.template_name,
                ticker=task.ticker,
                context=task.context,
                **task.context.get("prompt_vars", {}),
            )
        else:
            # Fallback: generic prompt
            system_prompt = f"""Sen bir finansal analistsin. {task.ticker} hissesini {task.agent_role.value} perspektifinden analiz et.
Kurallar: Sadece verilen verilere dayan. JSON formatında yanıt ver. Confidence 0-1 arası."""
            user_prompt = task.prompt

        # LLM çağrısı (retry mekanizmalı)
        response = await client.generate_with_retry(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        if not response.success:
            # F-029: LLM fallback detaylı logging
            logger.warning("LLM call failed, using rule-based fallback",
                         error=response.error,
                         ticker=task.ticker,
                         agent_role=task.agent_role,
                         model=getattr(client, '_model', 'unknown'),
                         fallback_type="rule_based_analysis")
            return AIFallback.rule_based_analysis(
                task.context.get("features", {}), task.ticker
            )

        # JSON parse
        parsed = parse_llm_json(response.content)
        if parsed is None:
            # F-029: Parse hatası detaylı logging
            logger.warning("Failed to parse LLM output, using rule-based fallback",
                         ticker=task.ticker,
                         agent_role=task.agent_role,
                         content_preview=response.content[:200] if response.content else "empty",
                         fallback_type="rule_based_analysis")
            return AIFallback.rule_based_analysis(
                task.context.get("features", {}), task.ticker
            )

        # Token bilgilerini ekle
        parsed["_tokens_in"] = response.tokens_in
        parsed["_tokens_out"] = response.tokens_out
        parsed["source"] = "llm"

        return parsed


class AgentOrchestrator:
    """Agent'ları yöneten üst katman v2.0."""

    def __init__(self, llm_client: Optional[BaseLLMClient] = None):
        self._agents: Dict[AgentRole, BaseAgent] = {}
        self._results: List[AgentResult] = []
        self.llm_client = llm_client

    def register_agent(self, agent: BaseAgent):
        """Agent kaydet."""
        self._agents[agent.role] = agent

    def set_llm_client(self, client: BaseLLMClient):
        """LLM client ayarla."""
        self.llm_client = client

    async def run_research_pipeline(
        self,
        ticker: str,
        context: Dict[str, Any],
        llm_client: Optional[BaseLLMClient] = None,
    ) -> Dict[str, Any]:
        """Tam araştırma pipeline'ı çalıştır."""
        client = llm_client or self.llm_client
        results = {}

        # Paralel çalıştır (asyncio.gather ile)
        research_roles = [
            AgentRole.TECHNICAL, AgentRole.FUNDAMENTAL,
            AgentRole.NEWS, AgentRole.MACRO,
        ]

        template_map = {
            AgentRole.TECHNICAL: "technical",
            AgentRole.FUNDAMENTAL: "fundamental",
            AgentRole.NEWS: "news",
            AgentRole.MACRO: "macro",
        }

        async def _run_agent(role):
            agent = self._agents.get(role) or BaseAgent(role, llm_client=client)
            task = AgentTask(
                task_id=f"{ticker}-{role.value}-{datetime.now(timezone.utc).strftime('%H%M%S')}",
                agent_role=role,
                ticker=ticker,
                prompt=f"Analyze {ticker} from {role.value} perspective",
                context=context,
                template_name=template_map.get(role),
            )
            return role.value, await agent.execute(task, client)

        gather_results = await asyncio.gather(*[_run_agent(r) for r in research_roles], return_exceptions=True)

        results = {}
        for item in gather_results:
            if isinstance(item, Exception):
                logger.warning("Agent execution failed", error=str(item))
                continue
            role_val, result = item
            results[role_val] = result
            self._results.append(result)

        # Synthesis
        synth_agent = self._agents.get(AgentRole.SYNTHESIS) or BaseAgent(
            AgentRole.SYNTHESIS, llm_client=client
        )
        synth_task = AgentTask(
            task_id=f"{ticker}-SYNTHESIS-{datetime.now(timezone.utc).strftime('%H%M%S')}",
            agent_role=AgentRole.SYNTHESIS,
            ticker=ticker,
            prompt=f"Synthesize all analysis for {ticker}",
            context={
                **context,
                "agent_results": {k: v.output for k, v in results.items()},
            },
            template_name="synthesis",
        )
        synth_result = await synth_agent.execute(synth_task, client)
        results["SYNTHESIS"] = synth_result

        return {
            "ticker": ticker,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": {
                k: {
                    "direction": v.output.get("direction", "NEUTRAL"),
                    "confidence": v.confidence,
                    "reasoning": v.reasoning,
                    "evidence": v.evidence,
                }
                for k, v in results.items()
            },
            "overall_direction": synth_result.output.get("direction", "NEUTRAL"),
            "overall_confidence": synth_result.confidence,
        }

    def get_recent_results(self, limit: int = 10) -> List[Dict]:
        """Son sonuçları getir."""
        return [
            {
                "task_id": r.task_id,
                "agent": r.agent_role.value,
                "ticker": r.ticker,
                "direction": r.output.get("direction", "NEUTRAL"),
                "confidence": r.confidence,
                "duration_ms": r.duration_ms,
            }
            for r in self._results[-limit:]
        ]


# Singleton
agent_orchestrator = AgentOrchestrator()


def run_agent_analysis(ticker: str, features: Dict, news: list = None) -> Dict[str, Any]:
    """Agent tabanlı analiz çalıştır (sync wrapper)."""
    result = {"ticker": ticker}
    try:
        orch = AgentOrchestrator()
        context = {"features": features, "news": news or []}

        # Async loop varsa kullan, yoksa yeni oluştur
        try:
            loop = asyncio.get_running_loop()
            # Zaten bir loop içindeyiz — task oluştur
            result["agent_available"] = True
            result["note"] = "Use async run_research_pipeline instead"
        except RuntimeError:
            # Loop yok — yeni oluştur
            report = asyncio.run(orch.run_research_pipeline(ticker, context))
            result.update(report)
            result["agent_available"] = True

    except Exception as e:
        result["agent_available"] = False
        result["error"] = str(e)
    return result
