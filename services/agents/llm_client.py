"""ALPHA BIST — LLM İstemci Soyutlama Modülü v3.0.

Bu modül, Alpha BIST multi-agent mimarisinde yerel ve bulut tabanlı büyük dil modelleri
(Ollama, OpenAI GPT-4/GPT-5, Anthropic Claude, DeepSeek, Qwen, Groq) için birleşik ve
tip-güvenli bir istemci arayüzü sunar.

Özellikler:
- Birleşik chat ve generate arayüzü.
- Üstel geri çekilmeli (exponential backoff) otomatik yeniden deneme mekanizması.
- Bağlantı havuzu yönetimi (aiohttp.ClientSession yeniden kullanımı ile socket tükenmesini önleme).
- Halüsinasyon ve sözdizimi bozukluklarına (trailing comma, markdown vb.) dayanıklı JSON ayrıştırıcı (parse_llm_json).
- Thread-safe dinamik sağlayıcı fabrikası (LLMClientFactory).
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Final

import aiohttp
import orjson
import structlog

logger = structlog.get_logger(__name__)

__all__: Final[list[str]] = [
    "LLMConfig",
    "LLMResponse",
    "BaseLLMClient",
    "OllamaLLMClient",
    "OpenAILLMClient",
    "AnthropicLLMClient",
    "LLMClientFactory",
    "parse_llm_json",
]


@dataclass
class LLMResponse:
    """Standartlaştırılmış LLM yanıt veri yapısı."""

    content: str
    model: str
    provider: str
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: float = 0.0
    success: bool = True
    error: str | None = None
    raw_response: dict[str, Any] | None = None

    def __repr__(self) -> str:
        status = "ok" if self.success else f"err={self.error!r}"
        return (
            f"LLMResponse(model={self.model!r}, provider={self.provider!r}, "
            f"tokens={self.tokens_in}→{self.tokens_out}, "
            f"duration={self.duration_ms:.1f}ms, {status})"
        )


@dataclass
class LLMConfig:
    """LLM istemcisi yapılandırma parametreleri."""

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

    def __repr__(self) -> str:
        """Gizli bilgileri (API Key) maskeleyerek temsil metni üretir."""
        masked_key = "***" if self.api_key else None
        return (
            f"LLMConfig(provider={self.provider!r}, model={self.model!r}, "
            f"base_url={self.base_url!r}, api_key={masked_key!r}, "
            f"temperature={self.temperature}, max_tokens={self.max_tokens})"
        )


class BaseLLMClient(ABC):
    """Tüm LLM sağlayıcıları için temel soyut istemci sınıfı."""

    def __init__(self, config: LLMConfig) -> None:
        """BaseLLMClient başlatıcı.

        Args:
            config: LLM yapılandırma nesnesi.
        """
        self.config: LLMConfig = config
        self._session: aiohttp.ClientSession | None = None
        self._session_lock: asyncio.Lock = asyncio.Lock()

    async def get_session(self) -> aiohttp.ClientSession:
        """Yeniden kullanılabilir aiohttp istemci oturumu döner (Bağlantı havuzlama).

        Returns:
            aiohttp.ClientSession: Aktif HTTP oturumu.
        """
        if self._session is None or self._session.closed:
            async with self._session_lock:
                if self._session is None or self._session.closed:
                    timeout = aiohttp.ClientTimeout(total=self.config.timeout)
                    connector = aiohttp.TCPConnector(limit=50, keepalive_timeout=30)
                    self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        return self._session

    async def close(self) -> None:
        """Oturum ve soket bağlantılarını serbest bırakır."""
        async with self._session_lock:
            if self._session is not None and not self._session.closed:
                await self._session.close()
                self._session = None

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Sağlayıcıya özgü sohbet tamamlama (chat completion) çağrısı.

        Args:
            messages: Mesaj listesi [{'role': 'user', 'content': '...'}]
            temperature: İsteğe bağlı sıcaklık parametresi.
            max_tokens: İsteğe bağlı maksimum token sınırı.

        Returns:
            LLMResponse: Standartlaştırılmış LLM yanıtı.
        """

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Tek seferlik sistem ve kullanıcı istemiyle üretim çağrısı.

        Args:
            prompt: Kullanıcı istemi metni.
            system_prompt: Sistem talimat metni.
            temperature: Sıcaklık değeri.
            max_tokens: Maksimum token.

        Returns:
            LLMResponse: Model yanıtı.
        """
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return await self.chat(messages, temperature=temperature, max_tokens=max_tokens)

    async def generate_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Üstel geri çekilme (exponential backoff) ile yeniden denemeli üretim çağrısı.

        Args:
            system_prompt: Sistem talimat metni.
            user_prompt: Kullanıcı istemi.
            temperature: Sıcaklık.
            max_tokens: Maksimum token.

        Returns:
            LLMResponse: Başarılı veya son hata yanıtı.
        """
        last_error: str | None = None
        max_retries = max(1, self.config.max_retries)

        for attempt in range(max_retries):
            try:
                response = await self.generate(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if response.success:
                    return response
                last_error = response.error
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {str(exc)}"
                logger.warning(
                    "LLM çağrısı başarısız oldu, yeniden deneniyor",
                    deneme=attempt + 1,
                    maks_deneme=max_retries,
                    hata=last_error,
                )

            if attempt < max_retries - 1:
                delay = self.config.retry_delay * (2 ** attempt)
                await asyncio.sleep(delay)

        return LLMResponse(
            content="",
            model=self.config.model,
            provider=self.config.provider,
            success=False,
            error=f"Tüm {max_retries} deneme başarısız oldu: {last_error}",
        )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(provider={self.config.provider!r}, model={self.config.model!r})"


class OllamaLLMClient(BaseLLMClient):
    """Yerel Ollama REST API istemcisi."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Ollama API ile sohbet tamamlama."""
        start = time.monotonic()
        temp = temperature if temperature is not None else self.config.temperature

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temp,
                "num_ctx": self.config.context_size,
            },
        }
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens

        try:
            session = await self.get_session()
            async with session.post(
                f"{self.config.base_url.rstrip('/')}/api/chat",
                json=payload,
            ) as resp:
                elapsed_ms = (time.monotonic() - start) * 1000.0
                if resp.status != 200:
                    err_txt = await resp.text()
                    return LLMResponse(
                        content="",
                        model=self.config.model,
                        provider="ollama",
                        success=False,
                        error=f"HTTP {resp.status}: {err_txt[:200]}",
                        duration_ms=elapsed_ms,
                    )

                body_bytes = await resp.read()
                data = orjson.loads(body_bytes)
                content = data.get("message", {}).get("content", "")

                return LLMResponse(
                    content=content,
                    model=self.config.model,
                    provider="ollama",
                    tokens_in=data.get("prompt_eval_count", 0),
                    tokens_out=data.get("eval_count", 0),
                    duration_ms=elapsed_ms,
                    success=True,
                    raw_response=data,
                )

        except TimeoutError:
            return LLMResponse(
                content="",
                model=self.config.model,
                provider="ollama",
                success=False,
                error="İstek zaman aşımına uğradı (Timeout)",
                duration_ms=(time.monotonic() - start) * 1000.0,
            )
        except Exception as exc:
            return LLMResponse(
                content="",
                model=self.config.model,
                provider="ollama",
                success=False,
                error=f"{type(exc).__name__}: {str(exc)}",
                duration_ms=(time.monotonic() - start) * 1000.0,
            )


class OpenAILLMClient(BaseLLMClient):
    """OpenAI uyumlu REST API istemcisi (OpenAI, DeepSeek, Qwen, Groq)."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """OpenAI v1/chat/completions API ile sohbet tamamlama."""
        start = time.monotonic()
        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens if max_tokens is not None else self.config.max_tokens

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": tokens,
            "stream": False,
        }

        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        try:
            session = await self.get_session()
            async with session.post(
                f"{self.config.base_url.rstrip('/')}/v1/chat/completions",
                json=payload,
                headers=headers,
            ) as resp:
                elapsed_ms = (time.monotonic() - start) * 1000.0
                if resp.status != 200:
                    err_txt = await resp.text()
                    return LLMResponse(
                        content="",
                        model=self.config.model,
                        provider="openai-compatible",
                        success=False,
                        error=f"HTTP {resp.status}: {err_txt[:200]}",
                        duration_ms=elapsed_ms,
                    )

                body_bytes = await resp.read()
                data = orjson.loads(body_bytes)
                choices = data.get("choices", [])
                if not choices:
                    return LLMResponse(
                        content="",
                        model=self.config.model,
                        provider="openai-compatible",
                        success=False,
                        error="Boş model yanıtı (Choices listesi boş)",
                        duration_ms=elapsed_ms,
                        raw_response=data,
                    )

                content = choices[0].get("message", {}).get("content", "")
                usage = data.get("usage", {})

                return LLMResponse(
                    content=content,
                    model=self.config.model,
                    provider="openai-compatible",
                    tokens_in=usage.get("prompt_tokens", 0),
                    tokens_out=usage.get("completion_tokens", 0),
                    duration_ms=elapsed_ms,
                    success=True,
                    raw_response=data,
                )

        except TimeoutError:
            return LLMResponse(
                content="",
                model=self.config.model,
                provider="openai-compatible",
                success=False,
                error="İstek zaman aşımına uğradı (Timeout)",
                duration_ms=(time.monotonic() - start) * 1000.0,
            )
        except Exception as exc:
            return LLMResponse(
                content="",
                model=self.config.model,
                provider="openai-compatible",
                success=False,
                error=f"{type(exc).__name__}: {str(exc)}",
                duration_ms=(time.monotonic() - start) * 1000.0,
            )


class AnthropicLLMClient(BaseLLMClient):
    """Anthropic Claude Messages API istemcisi."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Anthropic v1/messages API ile sohbet tamamlama."""
        start = time.monotonic()
        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens if max_tokens is not None else self.config.max_tokens

        system_msg = ""
        chat_messages: list[dict[str, str]] = []
        for msg in messages:
            if msg.get("role") == "system":
                system_msg = msg.get("content", "")
            else:
                chat_messages.append(msg)

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": chat_messages,
            "max_tokens": tokens,
            "temperature": temp,
        }
        if system_msg:
            payload["system"] = system_msg

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "x-api-key": self.config.api_key or "",
            "anthropic-version": "2023-06-01",
        }

        try:
            session = await self.get_session()
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
            ) as resp:
                elapsed_ms = (time.monotonic() - start) * 1000.0
                if resp.status != 200:
                    err_txt = await resp.text()
                    return LLMResponse(
                        content="",
                        model=self.config.model,
                        provider="anthropic",
                        success=False,
                        error=f"HTTP {resp.status}: {err_txt[:200]}",
                        duration_ms=elapsed_ms,
                    )

                body_bytes = await resp.read()
                data = orjson.loads(body_bytes)
                content_blocks = data.get("content", [])
                if not content_blocks:
                    return LLMResponse(
                        content="",
                        model=self.config.model,
                        provider="anthropic",
                        success=False,
                        error="Boş model yanıtı (Content bloğu eksik)",
                        duration_ms=elapsed_ms,
                        raw_response=data,
                    )

                content = content_blocks[0].get("text", "")
                usage = data.get("usage", {})

                return LLMResponse(
                    content=content,
                    model=self.config.model,
                    provider="anthropic",
                    tokens_in=usage.get("input_tokens", 0),
                    tokens_out=usage.get("output_tokens", 0),
                    duration_ms=elapsed_ms,
                    success=True,
                    raw_response=data,
                )

        except TimeoutError:
            return LLMResponse(
                content="",
                model=self.config.model,
                provider="anthropic",
                success=False,
                error="İstek zaman aşımına uğradı (Timeout)",
                duration_ms=(time.monotonic() - start) * 1000.0,
            )
        except Exception as exc:
            return LLMResponse(
                content="",
                model=self.config.model,
                provider="anthropic",
                success=False,
                error=f"{type(exc).__name__}: {str(exc)}",
                duration_ms=(time.monotonic() - start) * 1000.0,
            )


class LLMClientFactory:
    """Yapılandırmaya göre doğru LLM istemcisini üreten thread-safe fabrika."""

    _lock: threading.Lock = threading.Lock()
    _providers: dict[str, type[BaseLLMClient]] = {
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
        """Verilen yapılandırmaya uygun LLM istemci nesnesi üretir.

        Args:
            config: LLM yapılandırma nesnesi.

        Returns:
            BaseLLMClient: İstemci örneği.

        Raises:
            ValueError: Bilinmeyen sağlayıcı tanımlandığında.
        """
        provider = str(config.provider).strip().lower()
        with cls._lock:
            client_class = cls._providers.get(provider)

        if not client_class:
            with cls._lock:
                available = sorted(cls._providers.keys())
            raise ValueError(f"Unknown LLM provider / Bilinmeyen LLM sağlayıcısı: {provider}. Desteklenenler: {available}")

        return client_class(config)

    @classmethod
    def from_settings(cls, settings: Any) -> BaseLLMClient:
        """Uygulama ayarlarından (alpha_config/settings) LLM istemcisi oluşturur.

        Args:
            settings: Konfigürasyon ayarları nesnesi.

        Returns:
            BaseLLMClient: Yapılandırılmış istemci örneği.
        """
        config = LLMConfig(
            provider=getattr(settings, "agent_llm_provider", "ollama"),
            model=getattr(settings, "agent_llm_model", getattr(settings, "ollama_model", "gemma4:12b-q4_0")),
            base_url=getattr(settings, "agent_llm_base_url", getattr(settings, "ollama_base_url", "http://localhost:11434")),
            api_key=getattr(settings, "agent_llm_api_key", None),
            temperature=getattr(settings, "agent_llm_temperature", 0.3),
            max_tokens=getattr(settings, "agent_llm_max_tokens", 2048),
            context_size=getattr(settings, "llm_context_size", 8192),
            timeout=getattr(settings, "agent_llm_timeout", 60),
            max_retries=getattr(settings, "agent_llm_max_retries", 3),
        )
        return cls.create(config)

    @classmethod
    def register_provider(cls, name: str, client_class: type[BaseLLMClient]) -> None:
        """Yeni veya özel bir LLM istemci sınıfını fabrikaya kaydeder.

        Args:
            name: Sağlayıcı adı (küçük harfe normalize edilir).
            client_class: BaseLLMClient türevi sınıf.
        """
        with cls._lock:
            cls._providers[name.strip().lower()] = client_class

    @classmethod
    def list_providers(cls) -> list[str]:
        """Kayıtlı tüm sağlayıcı adlarını döner."""
        with cls._lock:
            return sorted(cls._providers.keys())


def parse_llm_json(content: str) -> dict[str, Any] | None:
    """LLM metin çıktısından JSON nesnesini yüksek dayanıklılıkla çıkarır.

    Stratejiler:
    1. Doğrudan orjson parse denemesi.
    2. ```json ... ``` kod bloğu ayıklama.
    3. Parantez sayma (brace counting) ile iç içe geçmiş { ... } bulma.
    4. Trailing comma (sondaki gereksiz virgül) temizliği.
    5. Son çare metin tabanlı yön ve güven çıkarma fallback'i.

    Args:
        content: LLM ham metin yanıtı.

    Returns:
        dict[str, Any] | None: Ayrıştırılmış sözlük veya None.
    """
    if not content or not isinstance(content, str):
        return None

    cleaned = content.strip()

    # 1. Doğrudan orjson dene
    try:
        res = orjson.loads(cleaned)
        if isinstance(res, dict):
            return res
    except Exception:
        logger.debug("JSON parse: doğrudan parse başarısız, alternatifler deneniyor")

    # 2. ```json ... ``` bloğu
    code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if code_block_match:
        block_text = code_block_match.group(1).strip()
        try:
            res = orjson.loads(block_text)
            if isinstance(res, dict):
                return res
        except Exception:
            # Trailing comma temizleyerek tekrar dene
            sanitized = re.sub(r",\s*([\]}])", r"\1", block_text)
            try:
                res = orjson.loads(sanitized)
                if isinstance(res, dict):
                    return res
            except Exception:
                pass

    # 3. İlk geçerli { ... } nesnesini brace-counting ile bul
    extracted_json = _find_json_object(cleaned)
    if extracted_json:
        try:
            res = orjson.loads(extracted_json)
            if isinstance(res, dict):
                return res
        except Exception:
            sanitized = re.sub(r",\s*([\]}])", r"\1", extracted_json)
            try:
                res = orjson.loads(sanitized)
                if isinstance(res, dict):
                    return res
            except Exception:
                pass

    # 4. Metin bazlı kural tabanlı çıkarım (son çare)
    return _extract_from_text(cleaned)


def _find_json_object(text: str) -> str | None:
    """Metin içindeki ilk iç içe JSON nesnesini parantez derinliği ile bulur."""
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]

        if escape:
            escape = False
            continue

        if ch == "\\":
            escape = True
            continue

        if ch == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return None


def _extract_from_text(content: str) -> dict[str, Any]:
    """Yapısal JSON bulunamadığında metinden yön ve gerekçeleri kurtarır."""
    result: dict[str, Any] = {
        "direction": "NEUTRAL",
        "confidence": 0.5,
        "score": 50.0,
        "reasoning": content[:500],
        "reasons": [],
        "risks": [],
        "source": "text_extraction",
    }

    content_upper = content.upper()

    long_patterns = ["LONG", "BULLISH", "YÜKSELİŞ", "YUKSELIS", "ALIM", "AL"]
    short_patterns = ["SHORT", "BEARISH", "DÜŞÜŞ", "DUSUS", "SATIM", "SAT"]

    for pat in long_patterns:
        if re.search(rf"\b{pat}\b", content_upper):
            result["direction"] = "LONG"
            break

    if result["direction"] == "NEUTRAL":
        for pat in short_patterns:
            if re.search(rf"\b{pat}\b", content_upper):
                result["direction"] = "SHORT"
                break

    conf_match = re.search(r"(?:confidence|güven|skor)[\s:]*(\d+(?:\.\d+)?)", content, re.IGNORECASE)
    if conf_match:
        try:
            conf = float(conf_match.group(1))
            if conf > 1.0:
                conf = conf / 100.0
            result["confidence"] = max(0.0, min(1.0, conf))
        except (ValueError, TypeError):
            pass

    return result
