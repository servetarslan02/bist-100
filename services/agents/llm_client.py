"""
ALPHA BIST — LLM Client Abstraction v1.0

Çoklu LLM provider desteği:
- Ollama (yerel)
- OpenAI (GPT-4, GPT-5)
- Anthropic (Claude)
- OpenAI-compatible (DeepSeek, Qwen, Groq)

Her provider aynı interface'i kullanır.
Retry, timeout, token counting dahil.
"""

import asyncio
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import aiohttp
import orjson
import structlog

logger = structlog.get_logger()


@dataclass
class LLMResponse:
    """LLM yanıt standardı."""

    content: str
    model: str
    provider: str
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: float = 0
    success: bool = True
    error: str | None = None
    raw_response: dict | None = None


@dataclass
class LLMConfig:
    """LLM yapılandırması."""

    provider: str = "ollama"
    model: str = "gemma4:12b-q4_0"
    base_url: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    api_key: str | None = None
    temperature: float = 0.3
    max_tokens: int = 2048
    context_size: int = 8192
    timeout: int = 60
    max_retries: int = 3
    retry_delay: float = 1.0

    def __repr__(self):
        """API key'i gizle."""
        masked_key = "***" if self.api_key else None
        return (
            f"LLMConfig(provider={self.provider!r}, model={self.model!r}, "
            f"base_url={self.base_url!r}, api_key={masked_key!r}, "
            f"temperature={self.temperature}, max_tokens={self.max_tokens})"
        )


class BaseLLMClient(ABC):
    """Abstract LLM client interface."""

    def __init__(self, config: LLMConfig):
        self.config = config

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Chat completion."""

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Tek seferlik generate (system + user)."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return await self.chat(messages, temperature, max_tokens)

    async def generate_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Retry mekanizmalı generate."""
        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                response = await self.generate(system_prompt, user_prompt, temperature, max_tokens)
                if response.success:
                    return response
                last_error = response.error
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "LLM call failed, retrying",
                    attempt=attempt + 1,
                    max_retries=self.config.max_retries,
                    error=str(e),
                )

            if attempt < self.config.max_retries - 1:
                delay = self.config.retry_delay * (2**attempt)  # exponential backoff
                await asyncio.sleep(delay)

        # Tüm denemeler başarısız
        return LLMResponse(
            content="",
            model=self.config.model,
            provider=self.config.provider,
            success=False,
            error=f"All {self.config.max_retries} attempts failed: {last_error}",
        )


class OllamaLLMClient(BaseLLMClient):
    """Ollama LLM client."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:

        start = time.monotonic()
        temp = temperature if temperature is not None else self.config.temperature

        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "model": self.config.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": temp,
                        "num_ctx": self.config.context_size,
                    },
                }

                timeout = aiohttp.ClientTimeout(total=self.config.timeout)
                async with session.post(
                    f"{self.config.base_url}/api/chat",
                    json=payload,
                    timeout=timeout,
                ) as resp:
                    if resp.status != 200:
                        return LLMResponse(
                            content="",
                            model=self.config.model,
                            provider="ollama",
                            success=False,
                            error=f"HTTP {resp.status}",
                            duration_ms=(time.monotonic() - start) * 1000,
                        )

                    data = await resp.json()
                    content = data.get("message", {}).get("content", "")

                    return LLMResponse(
                        content=content,
                        model=self.config.model,
                        provider="ollama",
                        tokens_in=data.get("prompt_eval_count", 0),
                        tokens_out=data.get("eval_count", 0),
                        duration_ms=(time.monotonic() - start) * 1000,
                        success=True,
                        raw_response=data,
                    )

        except TimeoutError:
            return LLMResponse(
                content="",
                model=self.config.model,
                provider="ollama",
                success=False,
                error="Timeout",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            return LLMResponse(
                content="",
                model=self.config.model,
                provider="ollama",
                success=False,
                error=str(e),
                duration_ms=(time.monotonic() - start) * 1000,
            )


class OpenAILLMClient(BaseLLMClient):
    """OpenAI-compatible LLM client (OpenAI, DeepSeek, Qwen, Groq)."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:

        start = time.monotonic()
        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens if max_tokens is not None else self.config.max_tokens

        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "model": self.config.model,
                    "messages": messages,
                    "temperature": temp,
                    "max_tokens": tokens,
                    "stream": False,
                }

                headers = {
                    "Content-Type": "application/json",
                }
                if self.config.api_key:
                    headers["Authorization"] = f"Bearer {self.config.api_key}"

                timeout = aiohttp.ClientTimeout(total=self.config.timeout)
                async with session.post(
                    f"{self.config.base_url}/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        return LLMResponse(
                            content="",
                            model=self.config.model,
                            provider="openai-compatible",
                            success=False,
                            error=f"HTTP {resp.status}: {error_text[:200]}",
                            duration_ms=(time.monotonic() - start) * 1000,
                        )

                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})

                    return LLMResponse(
                        content=content,
                        model=self.config.model,
                        provider="openai-compatible",
                        tokens_in=usage.get("prompt_tokens", 0),
                        tokens_out=usage.get("completion_tokens", 0),
                        duration_ms=(time.monotonic() - start) * 1000,
                        success=True,
                        raw_response=data,
                    )

        except TimeoutError:
            return LLMResponse(
                content="",
                model=self.config.model,
                provider="openai-compatible",
                success=False,
                error="Timeout",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            return LLMResponse(
                content="",
                model=self.config.model,
                provider="openai-compatible",
                success=False,
                error=str(e),
                duration_ms=(time.monotonic() - start) * 1000,
            )


class AnthropicLLMClient(BaseLLMClient):
    """Anthropic Claude LLM client."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:

        start = time.monotonic()
        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens if max_tokens is not None else self.config.max_tokens

        # Anthropic system message'ı ayrı alır
        system_msg = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                chat_messages.append(msg)

        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "model": self.config.model,
                    "messages": chat_messages,
                    "max_tokens": tokens,
                    "temperature": temp,
                }
                if system_msg:
                    payload["system"] = system_msg

                headers = {
                    "Content-Type": "application/json",
                    "x-api-key": self.config.api_key or "",
                    "anthropic-version": "2023-06-01",
                }

                timeout = aiohttp.ClientTimeout(total=self.config.timeout)
                async with session.post(
                    "https://api.anthropic.com/v1/messages",
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        return LLMResponse(
                            content="",
                            model=self.config.model,
                            provider="anthropic",
                            success=False,
                            error=f"HTTP {resp.status}: {error_text[:200]}",
                            duration_ms=(time.monotonic() - start) * 1000,
                        )

                    data = await resp.json()
                    content = data["content"][0]["text"]
                    usage = data.get("usage", {})

                    return LLMResponse(
                        content=content,
                        model=self.config.model,
                        provider="anthropic",
                        tokens_in=usage.get("input_tokens", 0),
                        tokens_out=usage.get("output_tokens", 0),
                        duration_ms=(time.monotonic() - start) * 1000,
                        success=True,
                        raw_response=data,
                    )

        except TimeoutError:
            return LLMResponse(
                content="",
                model=self.config.model,
                provider="anthropic",
                success=False,
                error="Timeout",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            return LLMResponse(
                content="",
                model=self.config.model,
                provider="anthropic",
                success=False,
                error=str(e),
                duration_ms=(time.monotonic() - start) * 1000,
            )


class LLMClientFactory:
    """LLM client factory — config'den provider seçimi."""

    _providers = {
        "ollama": OllamaLLMClient,
        "openai": OpenAILLMClient,
        "openai-compatible": OpenAILLMClient,
        "deepseek": OpenAILLMClient,
        "qwen": OpenAILLMClient,
        "groq": OpenAILLMClient,
        "anthropic": AnthropicLLMClient,
    }

    @classmethod
    def create(cls, config: LLMConfig) -> BaseLLMClient:
        """Config'den LLM client oluştur."""
        provider = config.provider.lower()
        client_class = cls._providers.get(provider)
        if not client_class:
            raise ValueError(f"Unknown LLM provider: {provider}. Available: {list(cls._providers.keys())}")
        return client_class(config)

    @classmethod
    def from_settings(cls, settings) -> BaseLLMClient:
        """Settings objesinden LLM client oluştur."""
        config = LLMConfig(
            provider=getattr(settings, "agent_llm_provider", "ollama"),
            model=getattr(settings, "agent_llm_model", settings.ollama_model),
            base_url=getattr(settings, "agent_llm_base_url", settings.ollama_base_url),
            api_key=getattr(settings, "agent_llm_api_key", None),
            temperature=getattr(settings, "agent_llm_temperature", 0.3),
            max_tokens=getattr(settings, "agent_llm_max_tokens", 2048),
            context_size=getattr(settings, "llm_context_size", 8192),
            timeout=getattr(settings, "agent_llm_timeout", 60),
            max_retries=getattr(settings, "agent_llm_max_retries", 3),
        )
        return cls.create(config)

    @classmethod
    def register_provider(cls, name: str, client_class):
        """Yeni provider kaydet."""
        cls._providers[name.lower()] = client_class


def parse_llm_json(content: str) -> dict[str, Any] | None:
    """LLM yanıtından JSON çıkar.

    Birden fazla strateji dener:
    1. Doğrudan JSON parse
    2. ```json ... ``` bloğu
    3. İlk { ... } bul
    4. Metinden direction/confidence çıkar
    """
    if not content:
        return None

    content = content.strip()

    # 1. Doğrudan JSON
    try:
        return orjson.loads(content)
    except orjson.JSONDecodeError:
        pass  # Normal durum — LLM her zaman düzgün JSON üretmez

    # 2. ```json ... ``` bloğu
    json_block = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
    if json_block:
        try:
            return orjson.loads(json_block.group(1))
        except orjson.JSONDecodeError:
            pass

    # 3. İlk { ... }
    json_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", content, re.DOTALL)
    if json_match:
        try:
            return orjson.loads(json_match.group())
        except orjson.JSONDecodeError:
            pass

    # 4. Metinden fallback extraction
    return _extract_from_text(content)


def _extract_from_text(content: str) -> dict[str, Any]:
    """Metinden structured veri çıkar (son çare)."""
    result = {
        "direction": "NEUTRAL",
        "confidence": 0.5,
        "score": 50,
        "reasoning": content[:500],
        "reasons": [],
        "risks": [],
        "source": "text_extraction",
    }

    content_upper = content.upper()

    # Direction tespiti
    if any(w in content_upper for w in ["LONG", "AL ", "YUKSEL", "YÜKSEL", "BULLISH"]):
        result["direction"] = "LONG"
    elif any(w in content_upper for w in ["SHORT", "SAT ", "DUS", "DÜŞ", "BEARISH"]):
        result["direction"] = "SHORT"

    # Confidence tespiti
    conf_match = re.search(r"(?:confidence|güven)[\s:]*(\d+(?:\.\d+)?)", content, re.IGNORECASE)
    if conf_match:
        conf = float(conf_match.group(1))
        if conf > 1:
            conf = conf / 100
        result["confidence"] = min(max(conf, 0), 1)

    return result
