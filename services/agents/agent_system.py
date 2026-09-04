"""
ALPHA BIST — AI Agent System v2.0

Refactored:
- LLM client abstraction (Ollama, OpenAI, Anthropic, DeepSeek, Qwen)
- Structured JSON output (Pydantic schemas)
- Prompt templates (BIST-specific)
- Hallucination protection (6 katmanlı)
- Rule-based fallback (LLM yoksa)

FAZ 0: Temel altyapı refactor
"""

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import orjson
import logging

from .llm_client import (
    BaseLLMClient,
    parse_llm_json,
)
from .prompts import PROMPT_VERSION, PromptFactory
from .schemas import (
    DebateArgumentSchema,
    Direction,
    FundamentalOutputSchema,
    MacroOutputSchema,
    NewsOutputSchema,
    RiskAssessmentSchema,
    RiskLevel,
    SynthesisResultSchema,
    TechnicalOutputSchema,
    validate_agent_output,
)

logger = logging.getLogger(__name__)


class AgentRole(StrEnum):
    """Agent rolleri — her rolün farklı yetkileri ve sorumlulukları var."""

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
    """Agent görevi — bir agent'ın çalıştırması için gerekli tüm bilgileri içerir."""

    task_id: str
    agent_role: AgentRole
    ticker: str
    prompt: str
    context: dict[str, Any]
    max_steps: int = 10
    timeout_seconds: int = 120
    template_name: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"AgentTask(id={self.task_id!r}, role={self.agent_role.value!r}, "
            f"ticker={self.ticker!r}, template={self.template_name!r})"
        )


@dataclass
class AgentResult:
    """Agent sonucu — bir görevin çıktısını ve meta-bilgileri içerir."""

    task_id: str
    agent_role: AgentRole
    ticker: str
    success: bool
    output: dict[str, Any]
    confidence: float
    evidence: list[str]
    reasoning: str
    model_version: str
    prompt_version: str
    input_hash: str
    duration_ms: float
    error: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0

    @property
    def direction(self) -> str:
        """Nihai yön kararı (LONG/SHORT/NEUTRAL/NO_TRADE)."""
        return self.output.get("direction", "NEUTRAL")

    def __repr__(self) -> str:
        return (
            f"AgentResult(role={self.agent_role.value!r}, ticker={self.ticker!r}, "
            f"direction={self.direction!r}, conf={self.confidence:.2f}, "
            f"success={self.success}, duration={self.duration_ms:.0f}ms)"
        )


class AgentToolRegistry:
    """Agent tool erişim kontrolü — her rolün kullanabileceği tool'ları tanımlar."""

    ALLOWED_TOOLS = {
        AgentRole.RESEARCH: [
            "read_market_data",
            "read_news",
            "read_fundamentals",
            "run_technical_analysis",
            "run_valuation",
        ],
        AgentRole.NEWS: [
            "read_news",
            "read_kap",
            "read_social",
        ],
        AgentRole.MACRO: [
            "read_macro_data",
            "read_world_state",
        ],
        AgentRole.FUNDAMENTAL: [
            "read_fundamentals",
            "read_financials",
            "run_valuation",
        ],
        AgentRole.TECHNICAL: [
            "read_market_data",
            "run_technical_analysis",
        ],
        AgentRole.RISK: [
            "read_portfolio",
            "calculate_risk",
            "approve_decision",
            "reject_decision",
        ],
        AgentRole.PORTFOLIO: [
            "read_portfolio",
            "calculate_position_size",
        ],
        AgentRole.SCENARIO: [
            "run_scenario",
            "run_stress_test",
        ],
        AgentRole.BACKTEST: [
            "run_backtest",
            "read_historical_data",
        ],
        AgentRole.SYNTHESIS: [
            "read_all_results",
            "generate_report",
        ],
        AgentRole.BULL: [
            "read_market_data",
            "read_fundamentals",
            "run_technical_analysis",
        ],
        AgentRole.BEAR: [
            "read_market_data",
            "read_fundamentals",
            "run_technical_analysis",
        ],
    }

    @classmethod
    def can_access(cls, role: AgentRole, tool: str) -> bool:
        """Bu rol bu tool'a erişebilir mi?"""
        return tool in cls.ALLOWED_TOOLS.get(role, [])


class AIOutputValidator:
    """AI çıktısını doğrula — 6 katmanlı hallucination koruması.

    Katmanlar:
    1. JSON parse — geçerli JSON mı?
    2. Schema validation — Pydantic ile alan doğrulama
    3. Range validation — confidence 0-1, score 0-100
    4. Domain validation — makul fiyat, tarih, risk seviyesi
    5. Source validation — URL formatı kontrolü
    6. Price/Date hallucination validation — mantıksız fiyat ve tarih kontrolü
    """

    @staticmethod
    def validate(llm_output: str, expected_schema: str | None = None) -> dict[str, Any]:
        """AI çıktısını doğrula.

        Args:
            llm_output: LLM'den gelen ham çıktı (JSON string)
            expected_schema: Beklenen şema adı (technical, fundamental, vb.)

        Returns:
            {"valid": bool, "parsed": dict, "errors": list[str]}
        """
        errors: list[str] = []

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
                if conf < 0:
                    errors.append(f"Confidence out of range: {conf}")
                elif conf > 1:
                    # 0-100 formatından 0-1 formatına normalize et
                    if conf > 100:
                        errors.append(f"Confidence out of range: {conf}")
                    parsed["confidence"] = conf / 100

        if "score" in parsed:
            score = parsed["score"]
            if isinstance(score, (int, float)) and (score < 0 or score > 100):
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
            if isinstance(source, str) and source.startswith("http") and not re.match(r"https?://", source):
                errors.append(f"Suspicious source URL: {source}")

        # 6. Price/Date hallucination validation
        if "price" in parsed:
            price = parsed["price"]
            if isinstance(price, (int, float)):
                if price <= 0:
                    errors.append(f"Invalid price (<=0): {price}")
                elif price > 1_000_000:  # 1M TL üzeri mantıksız
                    errors.append(f"Suspiciously high price: {price}")

        if "target_price" in parsed:
            tp = parsed["target_price"]
            if isinstance(tp, (int, float)) and tp <= 0:
                errors.append(f"Invalid target_price (<=0): {tp}")

        if "stop_loss" in parsed:
            sl = parsed["stop_loss"]
            if isinstance(sl, (int, float)) and sl <= 0:
                errors.append(f"Invalid stop_loss (<=0): {sl}")

        if "date" in parsed:
            date_str = str(parsed["date"])
            try:
                from datetime import datetime as dt_module

                dt = dt_module.fromisoformat(date_str.replace("Z", "+00:00"))
                if dt.year > datetime.now(UTC).year + 1:
                    errors.append(f"Future date too far: {date_str}")
            except (ValueError, TypeError) as e:
                errors.append(f"Invalid date format: {date_str} ({e})")

        valid = len(errors) == 0
        return {"valid": valid, "parsed": parsed, "errors": errors}


class AIFallback:
    """LLM çalışmadığında rule-based fallback.

    7 temel gösterge kullanarak kural tabanlı analiz yapar:
    1. Momentum (ROC 5d)
    2. Volume (z-score)
    3. RSI (14)
    4. Trend (20d slope)
    5. Volatilite (ATR %)
    6. MACD sinyali
    7. Bollinger Band pozisyonu
    """

    @staticmethod
    def rule_based_analysis(features: dict[str, float], ticker: str) -> dict[str, Any]:
        """LLM yokken kural tabanlı analiz.

        Her gösterge için skor eklenir/çıkarılır.
        Son skor → direction ve confidence belirler.
        """
        score = 50.0
        reasons: list[str] = []
        risks: list[str] = []

        # 1. Momentum — ROC 5d
        roc_5d = features.get("roc_5d", 0)
        if roc_5d > 3:
            score += 10
            reasons.append(f"Güçlü kısa vadeli momentum: +{roc_5d:.1f}%")
        elif roc_5d < -3:
            score -= 10
            risks.append(f"Zayıf momentum: {roc_5d:.1f}%")

        # 2. Volume — z-score
        vol_z = features.get("volume_zscore", 0)
        if vol_z > 2:
            score += 8
            reasons.append(f"Hacim anomalisi: {vol_z:.1f}σ")
        elif vol_z < -2:
            score -= 5
            risks.append(f"Düşük hacim: {vol_z:.1f}σ")

        # 3. RSI — 14 periyot
        rsi = features.get("rsi_14", 50)
        if rsi > 70:
            score -= 5
            risks.append(f"Aşırı alım: RSI={rsi:.0f}")
        elif rsi < 30:
            score += 5
            reasons.append(f"Aşırı satım: RSI={rsi:.0f}")

        # 4. Trend — 20d slope
        trend = features.get("trend_slope_20d", 0)
        if trend > 0:
            score += 5
            reasons.append("Yükselen trend")
        elif trend < 0:
            score -= 5
            risks.append("Düşen trend")

        # 5. Volatilite — ATR %
        atr_pct = features.get("atr_pct", 0)
        if atr_pct > 5:
            score -= 5
            risks.append(f"Yüksek volatilite: ATR %{atr_pct:.1f}")

        # 6. MACD sinyali
        macd_hist = features.get("macd_histogram", 0)
        if macd_hist > 0:
            score += 5
            reasons.append("MACD pozitif")
        elif macd_hist < 0:
            score -= 5
            risks.append("MACD negatif")

        # 7. Bollinger Band pozisyonu
        bb_position = features.get("bb_position", 0.5)
        if bb_position > 0.9:
            score -= 3
            risks.append("Bollinger üst bandına yakın")
        elif bb_position < 0.1:
            score += 3
            reasons.append("Bollinger alt bandına yakın")

        # Skor sınırla
        score = max(0, min(100, score))

        # Direction
        if score >= 60:
            direction = "LONG"
        elif score <= 40:
            direction = "SHORT"
        else:
            direction = "NEUTRAL"

        # Confidence — skorun 50'den uzaklığına göre
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
    """Base AI Agent v2.0 — LLM client + structured output.

    Her agent bir role'e sahiptir ve o rolün izin verdiği tool'ları kullanabilir.
    LLM yoksa otomatik olarak rule-based fallback kullanır.

    Kullanım:
        agent = BaseAgent(AgentRole.TECHNICAL, llm_client=client)
        result = await agent.execute(task)
    """

    def __init__(
        self,
        role: AgentRole,
        llm_client: BaseLLMClient | None = None,
        model_version: str = "auto",
        prompt_version: str = PROMPT_VERSION,
    ):
        """Base agent oluştur.

        Args:
            role: Agent rolü (TECHNICAL, FUNDAMENTAL, vb.)
            llm_client: LLM client (opsiyonel, yoksa rule-based fallback)
            model_version: Model versiyonu
            prompt_version: Prompt versiyonu
        """
        self.role = role
        self.llm_client = llm_client
        self.model_version = model_version
        self.prompt_version = prompt_version
        # Metrics
        self._execution_count = 0
        self._total_duration_ms = 0.0
        self._success_count = 0
        self._failure_count = 0

    async def execute(
        self,
        task: AgentTask,
        llm_client: BaseLLMClient | None = None,
    ) -> AgentResult:
        """Görevi çalıştır.

        Args:
            task: Çalıştırılacak görev
            llm_client: LLM client (opsiyonel, instance'daki kullanılır)

        Returns:
            AgentResult — çıktı, confidence, evidence, reasoning
        """
        start = time.monotonic()
        self._execution_count += 1

        # LLM client önceliği: parametre > instance > fallback
        client = llm_client or self.llm_client

        # Input hash — aynı input aynı sonuç üretmeli (deterministic check)
        input_str = orjson.dumps(
            {
                "ticker": task.ticker,
                "prompt": task.prompt[:200],
                "context_keys": sorted(task.context.keys()),
            },
            option=orjson.OPT_SORT_KEYS,
        )
        input_hash = hashlib.sha256(input_str).hexdigest()[:16]

        try:
            if client:
                output = await self._call_llm(task, client)
            else:
                output = AIFallback.rule_based_analysis(task.context.get("features", {}), task.ticker)

            # Validate — rol -> şema eşlemesi ile
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
                orjson.dumps(output).decode(), expected_schema=_role_schema_map.get(self.role)
            )
            if not validation["valid"]:
                logger.warning(
                    "AI output validation failed, using fallback",
                    errors=validation["errors"],
                )
                output = AIFallback.rule_based_analysis(task.context.get("features", {}), task.ticker)

            duration = (time.monotonic() - start) * 1000
            self._total_duration_ms += duration
            self._success_count += 1

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
            self._total_duration_ms += duration
            self._failure_count += 1
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
    ) -> dict[str, Any]:
        """LLM çağrısı — prompt template ile.

        Args:
            task: Agent görevi
            client: LLM client

        Returns:
            LLM çıktısı (parsed JSON dict)
        """
        # Prompt template kullan (varsa)
        if task.template_name:
            system_prompt, user_prompt = PromptFactory.get_prompts(
                template_name=task.template_name,
                ticker=task.ticker,
                context=task.context,
                **task.context.get("prompt_vars", {}),
            )
        else:
            system_prompt = (
                f"Sen bir finansal analistsin. {task.ticker} hissesini "
                f"{task.agent_role.value} perspektifinden analiz et.\n"
                f"Kurallar: Sadece verilen verilere dayan. JSON formatında yanıt ver. "
                f"Confidence 0-1 arası."
            )
            user_prompt = task.prompt

        # LLM çağrısı (retry mekanizmalı — generate_with_retry kendi retry'unu yapar)
        try:
            response = await client.generate_with_retry(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except Exception as e:
            logger.warning(
                "LLM call failed after retries, using rule-based fallback",
                error=str(e),
                ticker=task.ticker,
                agent_role=task.agent_role.value,
            )
            return AIFallback.rule_based_analysis(task.context.get("features", {}), task.ticker)

        if not response.success:
            logger.warning(
                "LLM call failed, using rule-based fallback",
                error=response.error,
                ticker=task.ticker,
                agent_role=task.agent_role.value,
                model=getattr(client, "_model", "unknown"),
            )
            return AIFallback.rule_based_analysis(task.context.get("features", {}), task.ticker)

        # Boş response kontrolü
        if not response.content or not response.content.strip():
            logger.warning(
                "LLM returned empty response, using rule-based fallback",
                ticker=task.ticker,
                agent_role=task.agent_role.value,
            )
            return AIFallback.rule_based_analysis(task.context.get("features", {}), task.ticker)

        # JSON parse
        parsed = parse_llm_json(response.content)
        if parsed is None:
            logger.warning(
                "Failed to parse LLM output, using rule-based fallback",
                ticker=task.ticker,
                agent_role=task.agent_role.value,
                content_preview=response.content[:200] if response.content else "empty",
            )
            return AIFallback.rule_based_analysis(task.context.get("features", {}), task.ticker)

        # Token bilgilerini ekle
        parsed["_tokens_in"] = response.tokens_in
        parsed["_tokens_out"] = response.tokens_out
        parsed["source"] = "llm"

        return parsed

    def get_metrics(self) -> dict[str, Any]:
        """Agent istatistiklerini getir."""
        return {
            "role": self.role.value,
            "execution_count": self._execution_count,
            "success_count": self._success_count,
            "failure_count": self._failure_count,
            "success_rate": self._success_count / self._execution_count if self._execution_count > 0 else 0.0,
            "avg_duration_ms": self._total_duration_ms / self._execution_count if self._execution_count > 0 else 0.0,
        }

    def __repr__(self) -> str:
        return (
            f"BaseAgent(role={self.role.value!r}, "
            f"llm={'set' if self.llm_client else 'none'}, "
            f"executions={self._execution_count})"
        )


def run_agent_analysis(ticker: str, features: dict, news: list | None = None) -> dict[str, Any]:
    """Agent tabanlı analiz çalıştır (sync wrapper).

    AgentPipelineOrchestrator kullanır.
    Not: Zaten bir async loop içindeyken çağrılamaz.

    Args:
        ticker: Hisse kodu
        features: Feature'lar
        news: Haber listesi (opsiyonel)

    Returns:
        Analiz sonuçları
    """
    from .agent_pipeline import AgentPipelineOrchestrator

    result: dict[str, Any] = {"ticker": ticker}
    try:
        context = {"features": features, "news": news or []}

        # Async loop varsa hata ver — nested asyncio.run() crash eder
        try:
            asyncio.get_running_loop()
            result["agent_available"] = False
            result["error"] = (
                "Cannot call sync wrapper inside async context. "
                "Use AgentPipelineOrchestrator.run() directly."
            )
            return result
        except RuntimeError:
            pass  # Loop yok, güvenle devam et

        async def _run() -> dict[str, Any]:
            orch = AgentPipelineOrchestrator()
            pipeline_result = await orch.run(ticker=ticker, features=features)
            return pipeline_result.to_dict()

        report = asyncio.run(_run())
        result.update(report)
        result["agent_available"] = True

    except Exception as e:
        logger.error("run_agent_analysis failed", ticker=ticker, error=str(e))
        result["agent_available"] = False
        result["error"] = str(e)
    return result
