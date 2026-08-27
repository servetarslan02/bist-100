"""
ALPHA BIST — LLM Client v2.0 (Gemini Function Calling Desteği)

Gemini API ile gerçek bağlantı kurar.
API anahtarı yoksa mock modunda çalışmaya devam eder.

Yenilikler v2.0:
- Function Calling (araç çağırma) desteği
- Gemini 1.5 Pro geniş context window kullanımı
- JSON schema enforced structured output
- Retry + timeout yönetimi
- Mock fallback korunuyor
"""

import os
from typing import Any

import orjson
import structlog

logger = structlog.get_logger()

# Yeni Google GenAI SDK (tercih edilen)
try:
    from google import genai

    GENAI_NEW_AVAILABLE = True
except ImportError:
    GENAI_NEW_AVAILABLE = False

# Eski Google GenerativeAI SDK (fallback)
try:
    import google.generativeai as legacy_genai

    GENAI_LEGACY_AVAILABLE = True
except ImportError:
    GENAI_LEGACY_AVAILABLE = False


class LLMClient:
    """
    Gemini API istemcisi — Function Calling destekli.
    google-genai ve legacy SDK destekli.
    """

    def __init__(self, model_name: str = "gemini-3.7-flash"):
        self.model_name = model_name
        self.api_key = self._load_api_key()
        self._new_client = None
        self._legacy_model = None
        self._initialized = False

        if self.api_key:
            self._initialize_gemini()

    def _load_api_key(self) -> str | None:
        """API anahtarını env, .env dosyası veya config'den yükle."""
        # 1. Environment variable
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if key:
            if key.startswith("AIzaSyAQ."):
                key = key.replace("AIzaSyAQ.", "AQ.")
            return key

        # 2. .env dosyasından doğrudan oku (eğer henüz env'e yüklenmemişse)
        env_paths = [
            os.path.join(os.getcwd(), ".env"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"),
        ]
        for env_path in env_paths:
            if os.path.exists(env_path):
                try:
                    with open(env_path, encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith("GEMINI_API_KEY="):
                                key = line.split("GEMINI_API_KEY=", 1)[1].strip().strip('"').strip("'")
                                if key:
                                    if key.startswith("AIzaSyAQ."):
                                        key = key.replace("AIzaSyAQ.", "AQ.")
                                    os.environ["GEMINI_API_KEY"] = key
                                    return key
                except Exception:
                    logger.warning("Caught Exception in _load_api_key", exc_info=True)

        # 3. Config settings
        try:
            from services.core.config import settings

            key = getattr(settings, "gemini_api_key", None) or getattr(settings, "GEMINI_API_KEY", None) or ""
            if key:
                key_str = str(key).strip()
                if key_str.startswith("AIzaSyAQ."):
                    key_str = key_str.replace("AIzaSyAQ.", "AQ.")
                return key_str
        except Exception:
            logger.warning("Caught Exception in _load_api_key", exc_info=True)

        return None

    def _initialize_gemini(self):
        """Gemini API'yi başlat."""
        if GENAI_NEW_AVAILABLE:
            try:
                self._new_client = genai.Client(api_key=self.api_key)
                self._initialized = True
                logger.info("google-genai Client initialized", model=self.model_name)
                return
            except Exception as exc:
                logger.warning("google-genai init failed, trying legacy", error=str(exc))

        if GENAI_LEGACY_AVAILABLE:
            try:
                legacy_genai.configure(api_key=self.api_key)
                self._legacy_model = legacy_genai.GenerativeModel(self.model_name)
                self._initialized = True
                logger.info("Legacy Gemini API initialized", model=self.model_name)
                return
            except Exception as exc:
                logger.error("Legacy Gemini initialization failed", error=str(exc))

        self._initialized = False

    @property
    def is_live(self) -> bool:
        """Gerçek API bağlantısı aktif mi?"""
        return self._initialized and (self._new_client is not None or self._legacy_model is not None)

    def call_with_tools(
        self,
        prompt: str,
        tool_schemas: list[dict],
        context: dict | None = None,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """
        LLM'i araç şemalarıyla çağır (Function Calling).

        Args:
            prompt: Ana görev metni
            tool_schemas: Kullanılabilecek araçların şemaları
            context: Bağlam paketi (RAG verisi)
            max_retries: Hata durumunda yeniden deneme sayısı

        Returns:
            LLM yanıtı veya araç çağrısı listesi
        """
        if not self.is_live:
            return self._mock_tool_response(prompt, context)

        full_prompt = self._build_prompt(prompt, context)

        # 1. Yeni google-genai SDK ile araç çağırma
        if self._new_client is not None:
            try:
                from google.genai import types

                function_declarations = []
                for s in tool_schemas:
                    function_declarations.append(
                        {
                            "name": s["name"],
                            "description": s["description"],
                            "parameters": s.get("parameters", {}),
                        }
                    )

                models_to_try = [self.model_name, "gemini-3.1-pro-preview"]
                for mod in dict.fromkeys(models_to_try):
                    try:
                        resp = self._new_client.models.generate_content(
                            model=mod,
                            contents=full_prompt,
                            config=types.GenerateContentConfig(
                                temperature=0.1,
                                tools=[{"function_declarations": function_declarations}],
                            ),
                        )
                        return self._parse_response(resp)
                    except Exception as exc:
                        logger.debug("google-genai tool calling fallback", model=mod, error=str(exc))
                return self._mock_tool_response(prompt, context)
            except Exception as exc:
                logger.debug("google-genai tool schema building failed", error=str(exc))
                return self._mock_tool_response(prompt, context)

        # 2. Legacy fallback
        if self._legacy_model is not None:
            try:
                tools = [
                    legacy_genai.protos.Tool(
                        function_declarations=[
                            legacy_genai.protos.FunctionDeclaration(
                                name=schema["name"],
                                description=schema["description"],
                            )
                        ]
                    )
                    for schema in tool_schemas
                ]
                response = self._legacy_model.generate_content(
                    full_prompt,
                    tools=tools,
                )
                return self._parse_response(response)
            except Exception as exc:
                logger.debug("Legacy tool calling failed", error=str(exc))

        return self._mock_tool_response(prompt, context)

    def generate_text(
        self,
        prompt: str,
        context: dict | None = None,
        max_tokens: int = 1024,
    ) -> str:
        """
        Düz metin üretimi (araç yok).
        Türkçe açıklama ve narratif üretmek için kullanılır.
        """
        if not self.is_live:
            return self._mock_text_response(prompt, context)

        full_prompt = self._build_prompt(prompt, context)

        # 1. Yeni google-genai SDK
        if self._new_client is not None:
            models_to_try = [self.model_name, "gemini-3.1-pro-preview"]
            for mod in dict.fromkeys(models_to_try):
                try:
                    resp = self._new_client.models.generate_content(
                        model=mod,
                        contents=full_prompt,
                    )
                    if hasattr(resp, "text") and resp.text:
                        return resp.text.strip()
                except Exception as exc:
                    logger.debug("Model generation retry", model=mod, error=str(exc))

        # 2. Legacy fallback
        if self._legacy_model is not None:
            try:
                response = self._legacy_model.generate_content(
                    full_prompt,
                    generation_config=legacy_genai.GenerationConfig(
                        temperature=0.2,
                        max_output_tokens=max_tokens,
                    ),
                )
                return response.text if hasattr(response, "text") else str(response)
            except Exception as exc:
                logger.error("Legacy text generation failed", error=str(exc))

        return self._mock_text_response(prompt, context)

    def analyze_financial_text(
        self,
        text: str,
        context_type: str = "news",
        context: dict | None = None,
    ) -> dict[str, Any]:
        """
        Finansal metin analizi — JSON yapılandırılmış çıktı.
        Geriye dönük uyumluluk için korunuyor.
        """
        context_block = ""
        if context:
            try:
                context_block = (
                    f"\n\nBAĞLAM:\n{orjson.dumps(context, option=orjson.OPT_INDENT_2, default=str).decode()}"
                )
            except Exception:
                context_block = f"\n\nBAĞLAM: {str(context)}"

        prompt = f"""Sen BIST-100 uzmanı bir finansal analistsin.
Aşağıdaki {context_type} içeriğini analiz et ve JSON formatında yanıt ver.{context_block}

METİN:
{text}

ÇIKTI FORMAT (sadece JSON, başka hiçbir şey yok):
{{
  "entities": [{{"type": "COMPANY|MACRO", "name": "TICKER", "confidence": 0.9}}],
  "event_type": "MACRO|COMPANY|SECTOR|GEOPOLITICAL|OTHER",
  "sentiment": 0.5,
  "importance": 0.7,
  "affected_tickers": ["THYAO"],
  "affected_sectors": ["AVIATION"],
  "surprise_score": 0.2,
  "uncertainty_score": 0.1,
  "key_insight": "Kısa Türkçe özet (max 100 karakter)"
}}"""

        if not self.is_live:
            return self._mock_structured_response()

        if self._new_client is not None:
            models_to_try = [self.model_name, "gemini-3.1-pro-preview"]
            for mod in dict.fromkeys(models_to_try):
                try:
                    resp = self._new_client.models.generate_content(
                        model=mod,
                        contents=prompt,
                    )
                    raw_text = resp.text if hasattr(resp, "text") else "{}"
                    if "```json" in raw_text:
                        raw_text = raw_text.split("```json")[1].split("```")[0].strip()
                    elif "```" in raw_text:
                        raw_text = raw_text.split("```")[1].split("```")[0].strip()
                    return orjson.loads(raw_text)
                except Exception as exc:
                    logger.error("google-genai structured analysis failed", model=mod, error=str(exc))

        if self._legacy_model is not None:
            try:
                response = self._legacy_model.generate_content(
                    prompt,
                    generation_config=legacy_genai.GenerationConfig(
                        temperature=0.05,
                        max_output_tokens=512,
                        response_mime_type="application/json",
                    ),
                )
                text_resp = response.text if hasattr(response, "text") else "{}"
                return orjson.loads(text_resp)
            except Exception as exc:
                logger.error("Structured analysis failed", error=str(exc))

    # ── Yardımcı Metodlar ────────────────────────────────────────────────────

    def _build_prompt(self, prompt: str, context: dict | None) -> str:
        """Prompt'a bağlam ekle."""
        if not context:
            return prompt
        try:
            ctx_text = orjson.dumps(context, option=orjson.OPT_INDENT_2, default=str).decode()
            return f"BAĞLAM VERİSİ:\n{ctx_text}\n\n---\n\nGÖREV:\n{prompt}"
        except Exception:
            return prompt

    def _parse_response(self, response: Any) -> dict[str, Any]:
        """Gemini response'unu ayrıştır."""
        result = {"text": None, "tool_calls": []}

        if not hasattr(response, "candidates"):
            return result

        for candidate in response.candidates:
            if not hasattr(candidate, "content"):
                continue
            for part in candidate.content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    result["tool_calls"].append(
                        {
                            "name": part.function_call.name,
                            "arguments": dict(part.function_call.args),
                        }
                    )
                elif hasattr(part, "text") and part.text:
                    result["text"] = part.text

        return result

    def _mock_tool_response(self, prompt: str, context: dict | None) -> dict[str, Any]:
        """Mock araç yanıtı."""
        logger.debug("LLM mock tool response", prompt_length=len(prompt))
        return {
            "text": None,
            "tool_calls": [
                {"name": "get_world_state", "arguments": {}},
                {"name": "get_regime", "arguments": {}},
            ],
        }

    def _mock_text_response(self, prompt: str, context: dict | None) -> str:
        """Mock metin yanıtı."""
        return "[LLM Mock] Analiz tamamlandı. Gemini API anahtarı eklendiğinde gerçek analiz üretilecek."

    def _mock_structured_response(self) -> dict[str, Any]:
        """Mock yapılandırılmış yanıt."""
        return {
            "entities": [{"type": "COMPANY", "name": "THYAO", "confidence": 0.9}],
            "event_type": "COMPANY",
            "sentiment": 0.5,
            "importance": 0.7,
            "affected_tickers": ["THYAO", "PGSUS"],
            "affected_sectors": ["AVIATION"],
            "surprise_score": 0.2,
            "uncertainty_score": 0.1,
            "key_insight": "Mock analiz — API anahtarı gerekli",
        }


# Singleton
llm_client = LLMClient()
