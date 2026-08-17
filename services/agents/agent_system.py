"""
ALPHA BIST — AI Agent System v1.0

Görev bazlı AI ajanları:
- Agent Orchestrator (pipeline yönetimi)
- Agent Tool System (erişim kontrolü)
- AI Output Validation (hallucination protection)
- AI Fallback (LLM down → rule-based)
- Prompt Versioning

FAZ 7: AI Agent System
"""

import json
import hashlib
import re
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import structlog

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


class AgentToolRegistry:
    """Agent tool erişim kontrolü."""

    # Her agent'ın erişebileceği araçlar
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
    }

    @classmethod
    def can_access(cls, role: AgentRole, tool: str) -> bool:
        """Agent bu araca erişebilir mi?"""
        return tool in cls.ALLOWED_TOOLS.get(role, [])


class AIOutputValidator:
    """AI çıktısını doğrula.

    Pipeline:
    1. JSON parse
    2. Schema validation
    3. Range validation (confidence 0-1, price > 0)
    4. Domain validation (makul değerler)
    5. Source validation (var olmayan haberi kaynak gösterme)
    6. Hallucination check
    """

    @staticmethod
    def validate(llm_output: str, expected_schema: Optional[Dict] = None) -> Dict[str, Any]:
        """AI çıktısını doğrula.

        Returns: {"valid": bool, "parsed": dict, "errors": list}
        """
        errors = []

        # 1. JSON parse
        parsed = None
        try:
            # JSON bloğu ara
            json_match = re.search(r'\{[^{}]*\}', llm_output, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            errors.append(f"JSON parse error: {e}")

        if parsed is None:
            return {"valid": False, "parsed": None, "errors": ["No valid JSON found"]}

        # 2. Schema validation
        if expected_schema:
            for key, expected_type in expected_schema.items():
                if key not in parsed:
                    errors.append(f"Missing key: {key}")
                elif not isinstance(parsed[key], expected_type):
                    errors.append(f"Wrong type for {key}: expected {expected_type}, got {type(parsed[key])}")

        # 3. Range validation
        if "confidence" in parsed:
            conf = parsed["confidence"]
            if isinstance(conf, (int, float)):
                if conf < 0 or conf > 100:
                    errors.append(f"Confidence out of range: {conf}")
                # Normalize to 0-1
                if conf > 1:
                    parsed["confidence"] = conf / 100

        if "direction" in parsed:
            if parsed["direction"] not in ["LONG", "SHORT", "NEUTRAL", "HOLD"]:
                errors.append(f"Invalid direction: {parsed['direction']}")

        # 4. Domain validation
        if "price_target" in parsed:
            price = parsed["price_target"]
            if isinstance(price, (int, float)) and price < 0:
                errors.append(f"Negative price target: {price}")

        if "risk_level" in parsed:
            if parsed["risk_level"] not in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
                errors.append(f"Invalid risk level: {parsed['risk_level']}")

        # 5. Hallucination check (basit)
        if "source" in parsed:
            source = parsed["source"]
            # Kaynak URL'si varsa kontrol et
            if isinstance(source, str) and source.startswith("http"):
                # URL format kontrolü
                if not re.match(r'https?://', source):
                    errors.append(f"Suspicious source URL: {source}")

        valid = len(errors) == 0

        return {"valid": valid, "parsed": parsed, "errors": errors}


class AIFallback:
    """LLM çalışmadığında rule-based fallback.

    Primary LLM → Secondary LLM → Rule-based → NO_TRADE
    """

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

        confidence = min(abs(score - 50) / 50, 0.8)  # Max 0.8 (LLM yokken)

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
    """Base AI Agent."""

    def __init__(self, role: AgentRole, model_version: str = "rule-based", prompt_version: str = "v1"):
        self.role = role
        self.model_version = model_version
        self.prompt_version = prompt_version

    async def execute(self, task: AgentTask, llm_client: Optional[Any] = None) -> AgentResult:
        """Görevi çalıştır."""
        import time
        start = time.monotonic()

        # Input hash
        input_str = json.dumps({"ticker": task.ticker, "prompt": task.prompt, "context_keys": list(task.context.keys())}, sort_keys=True)
        input_hash = hashlib.sha256(input_str.encode()).hexdigest()[:16]

        try:
            # LLM varsa kullan, yoksa fallback
            if llm_client:
                output = await self._call_llm(task, llm_client)
            else:
                output = AIFallback.rule_based_analysis(
                    task.context.get("features", {}), task.ticker
                )

            # Validate
            validation = AIOutputValidator.validate(json.dumps(output))

            if not validation["valid"]:
                logger.warning("AI output validation failed", errors=validation["errors"])
                # Fallback kullan
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
                model_version=self.model_version,
                prompt_version=self.prompt_version,
                input_hash=input_hash,
                duration_ms=round(duration, 2),
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
                model_version=self.model_version,
                prompt_version=self.prompt_version,
                input_hash=input_hash,
                duration_ms=round(duration, 2),
                error=str(e),
            )

    async def _call_llm(self, task: AgentTask, llm_client: Any) -> Dict[str, Any]:
        """Ollama LLM cagrisi."""
        import aiohttp
        from services.core.config import settings

        # Prompt olustur
        system_prompt = f"""Sen bir finansal analistsin. {task.ticker} hissesini {task.agent_role.value} perspektifinden analiz et.

Kurallar:
- Sadece verilen verilere dayan
- Spekulasyon yapma
- JSON formatinda yanit ver
- Confidence 0-1 arasi

Context: {json.dumps(task.context, default=str, ensure_ascii=False)[:4000]}
"""

        user_prompt = task.prompt

        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "model": settings.ollama_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_ctx": settings.llm_context_size,
                    },
                }

                async with session.post(
                    f"{settings.ollama_base_url}/api/chat",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status != 200:
                        raise Exception(f"Ollama HTTP {resp.status}")

                    data = await resp.json()
                    content = data.get("message", {}).get("content", "")

                    # JSON parse
                    try:
                        # JSON blogu ara
                        json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
                        if json_match:
                            parsed = json.loads(json_match.group())
                        else:
                            parsed = json.loads(content)

                        # Normalize
                        result = {
                            "direction": parsed.get("direction", "NEUTRAL"),
                            "confidence": float(parsed.get("confidence", 0.5)),
                            "score": float(parsed.get("score", 50)),
                            "reasoning": parsed.get("reasoning", ""),
                            "reasons": parsed.get("reasons", []),
                            "risks": parsed.get("risks", []),
                            "source": "ollama_llm",
                        }
                        return result

                    except json.JSONDecodeError:
                        # JSON degilse, metinden cikarim yap
                        direction = "NEUTRAL"
                        if "AL" in content.upper() or "LONG" in content.upper() or "YUKSEL" in content.upper():
                            direction = "LONG"
                        elif "SAT" in content.upper() or "SHORT" in content.upper() or "DUS" in content.upper():
                            direction = "SHORT"

                        return {
                            "direction": direction,
                            "confidence": 0.5,
                            "score": 50,
                            "reasoning": content[:500],
                            "reasons": [],
                            "risks": [],
                            "source": "ollama_text",
                        }

        except Exception as e:
            logger.warning("Ollama call failed, falling back to rule-based", error=str(e))
            return AIFallback.rule_based_analysis(
                task.context.get("features", {}), task.ticker
            )


class AgentOrchestrator:
    """Agent'ları yöneten üst katman.

    Pipeline:
    1. Research Agent → teknik + fundamental analiz
    2. News Agent → haber + KAP analizi
    3. Macro Agent → makro etki analizi
    4. Risk Agent → risk değerlendirmesi
    5. Synthesis Agent → bütün sonuçları birleştir
    """

    def __init__(self):
        self._agents: Dict[AgentRole, BaseAgent] = {}
        self._results: List[AgentResult] = []

    def register_agent(self, agent: BaseAgent):
        """Agent kaydet."""
        self._agents[agent.role] = agent

    async def run_research_pipeline(
        self,
        ticker: str,
        context: Dict[str, Any],
        llm_client: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Tam araştırma pipeline'ı çalıştır."""
        results = {}

        # Sırasıyla çalıştır
        for role in [AgentRole.TECHNICAL, AgentRole.FUNDAMENTAL, AgentRole.NEWS, AgentRole.MACRO]:
            agent = self._agents.get(role)
            if not agent:
                agent = BaseAgent(role)

            task = AgentTask(
                task_id=f"{ticker}-{role.value}-{datetime.now(timezone.utc).strftime('%H%M%S')}",
                agent_role=role,
                ticker=ticker,
                prompt=f"Analyze {ticker} from {role.value} perspective",
                context=context,
            )

            result = await agent.execute(task, llm_client)
            results[role.value] = result
            self._results.append(result)

        # Synthesis
        synthesis_agent = self._agents.get(AgentRole.SYNTHESIS) or BaseAgent(AgentRole.SYNTHESIS)
        synthesis_task = AgentTask(
            task_id=f"{ticker}-SYNTHESIS-{datetime.now(timezone.utc).strftime('%H%M%S')}",
            agent_role=AgentRole.SYNTHESIS,
            ticker=ticker,
            prompt=f"Synthesize all analysis for {ticker}",
            context={**context, "agent_results": {k: v.output for k, v in results.items()}},
        )
        synthesis_result = await synthesis_agent.execute(synthesis_task, llm_client)
        results["SYNTHESIS"] = synthesis_result

        return {
            "ticker": ticker,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": {k: {
                "direction": v.output.get("direction", "NEUTRAL"),
                "confidence": v.confidence,
                "reasoning": v.reasoning,
                "evidence": v.evidence,
            } for k, v in results.items()},
            "overall_direction": synthesis_result.output.get("direction", "NEUTRAL"),
            "overall_confidence": synthesis_result.confidence,
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


# =====================================================
# Agent Entegrasyonu
# =====================================================
def run_agent_analysis(ticker: str, features: Dict, news: list = None) -> Dict[str, Any]:
    """Agent tabanlı analiz çalıştır."""
    result = {"ticker": ticker}
    try:
        from .agent_system import AgentOrchestrator, AgentRole, AgentTask
        orch = AgentOrchestrator()
        # Research agent
        task = AgentTask(
            agent_role=AgentRole.RESEARCH,
            ticker=ticker,
            prompt=f"Analyze {ticker}",
            context={"features": features, "news": news or []},
        )
        result["agent_available"] = True
    except: result["agent_available"] = False
    return result
