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

import json
import os
import time
import structlog
from typing import Dict, Any, List, Optional

logger = structlog.get_logger()

# Gemini API import — yoksa mock mode
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning(
        "google-generativeai not installed. Running in mock mode. "
        "Install with: pip install google-generativeai>=0.7.0"
    )


class LLMClient:
    """
    Gemini API istemcisi — Function Calling destekli.
    API anahtarı olmadan mock modda çalışır.
    """

    def __init__(self, model_name: str = "gemini-1.5-pro-latest"):
        self.model_name = model_name
        self.api_key = self._load_api_key()
        self._model = None
        self._initialized = False

        if self.api_key and GEMINI_AVAILABLE:
            self._initialize_gemini()

    def _load_api_key(self) -> Optional[str]:
        """API anahtarını config'den veya env'den yükle."""
        # 1. Önce environment variable
        key = os.environ.get("GEMINI_API_KEY", "")
        if key:
            return key

        # 2. Config'den
        try:
            from services.core.config import settings
            key = getattr(settings, "GEMINI_API_KEY", "") or ""
            if key:
                return key
        except ImportError:
            pass

        logger.info("GEMINI_API_KEY bulunamadı — mock modda çalışılıyor.")
        return None

    def _initialize_gemini(self):
        """Gemini API'yi başlat."""
        try:
            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel(self.model_name)
            self._initialized = True
            logger.info("Gemini API initialized", model=self.model_name)
        except Exception as exc:
            logger.error("Gemini initialization failed", error=str(exc))
            self._initialized = False

    @property
    def is_live(self) -> bool:
        """Gerçek API bağlantısı aktif mi?"""
        return self._initialized and GEMINI_AVAILABLE

    def call_with_tools(
        self,
        prompt: str,
        tool_schemas: List[Dict],
        context: Optional[Dict] = None,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
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

        # Gemini Function Calling formatına dönüştür
        tools = [
            genai.protos.Tool(
                function_declarations=[
                    genai.protos.FunctionDeclaration(
                        name=schema["name"],
                        description=schema["description"],
                        parameters=genai.protos.Schema(
                            type=genai.protos.Type.OBJECT,
                            properties={
                                k: genai.protos.Schema(
                                    type=genai.protos.Type.STRING
                                    if v.get("type") == "string"
                                    else genai.protos.Type.NUMBER
                                    if v.get("type") in ("number", "integer")
                                    else genai.protos.Type.BOOLEAN
                                    if v.get("type") == "boolean"
                                    else genai.protos.Type.STRING,
                                    description=v.get("description", ""),
                                )
                                for k, v in schema.get("parameters", {})
                                .get("properties", {})
                                .items()
                            },
                            required=schema.get("parameters", {}).get("required", []),
                        ),
                    )
                ]
            )
            for schema in tool_schemas
        ]

        for attempt in range(max_retries + 1):
            try:
                response = self._model.generate_content(
                    full_prompt,
                    tools=tools,
                    generation_config=genai.GenerationConfig(
                        temperature=0.1,  # Finansal analiz için düşük sıcaklık
                        max_output_tokens=2048,
                    ),
                )
                return self._parse_response(response)

            except Exception as exc:
                logger.warning(
                    "Gemini API call failed",
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt < max_retries:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    logger.error("All retries exhausted, falling back to mock")
                    return self._mock_tool_response(prompt, context)

        return self._mock_tool_response(prompt, context)

    def generate_text(
        self,
        prompt: str,
        context: Optional[Dict] = None,
        max_tokens: int = 1024,
    ) -> str:
        """
        Düz metin üretimi (araç yok).
        Türkçe açıklama ve narratif üretmek için kullanılır.
        """
        if not self.is_live:
            return self._mock_text_response(prompt, context)

        full_prompt = self._build_prompt(prompt, context)

        try:
            response = self._model.generate_content(
                full_prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.2,
                    max_output_tokens=max_tokens,
                ),
            )
            return response.text if hasattr(response, "text") else str(response)
        except Exception as exc:
            logger.error("Text generation failed", error=str(exc))
            return self._mock_text_response(prompt, context)

    def analyze_financial_text(
        self,
        text: str,
        context_type: str = "news",
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Finansal metin analizi — JSON yapılandırılmış çıktı.
        Geriye dönük uyumluluk için korunuyor.
        """
        context_block = ""
        if context:
            try:
                context_block = f"\n\nBAĞLAM:\n{json.dumps(context, ensure_ascii=False, indent=2, default=str)}"
            except Exception:
                context_block = f"\n\nBAĞLAM: {str(context)}"

        prompt = f"""Sen BIST-100 uzmanı bir finansal analistsın.
Aşağıdaki {context_type} içeriğini analiz et ve JSON formatında yanıt ver.{context_block}

METİN:
{text}

ÇIKTI FORMAT (sadece JSON, başka hiçbir şey yok):
{{
  "entities": [{{"type": "COMPANY|MACRO", "name": "TICKER", "confidence": 0.9}}],
  "event_type": "MACRO|COMPANY|SECTOR|GEOPOLITICAL|OTHER",
  "sentiment": -1.0_ile_1.0_arası_float,
  "importance": 0.0_ile_1.0_arası_float,
  "affected_tickers": ["THYAO", ...],
  "affected_sectors": ["AVIATION", "BANK", ...],
  "surprise_score": 0.0_ile_1.0_arası_float,
  "uncertainty_score": 0.0_ile_1.0_arası_float,
  "key_insight": "Kısa Türkçe özet (max 100 karakter)"
}}"""

        if not self.is_live:
            return self._mock_structured_response()

        try:
            response = self._model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.05,
                    max_output_tokens=512,
                    response_mime_type="application/json",
                ),
            )
            text_resp = response.text if hasattr(response, "text") else "{}"
            return json.loads(text_resp)
        except Exception as exc:
            logger.error("Structured analysis failed", error=str(exc))
            return self._mock_structured_response()

    # ── Yardımcı Metodlar ────────────────────────────────────────────────────

    def _build_prompt(self, prompt: str, context: Optional[Dict]) -> str:
        """Prompt'a bağlam ekle."""
        if not context:
            return prompt
        try:
            ctx_text = json.dumps(context, ensure_ascii=False, indent=2, default=str)
            return f"BAĞLAM VERİSİ:\n{ctx_text}\n\n---\n\nGÖREV:\n{prompt}"
        except Exception:
            return prompt

    def _parse_response(self, response: Any) -> Dict[str, Any]:
        """Gemini response'unu ayrıştır."""
        result = {"text": None, "tool_calls": []}

        if not hasattr(response, "candidates"):
            return result

        for candidate in response.candidates:
            if not hasattr(candidate, "content"):
                continue
            for part in candidate.content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    result["tool_calls"].append({
                        "name": part.function_call.name,
                        "arguments": dict(part.function_call.args),
                    })
                elif hasattr(part, "text") and part.text:
                    result["text"] = part.text

        return result

    def _mock_tool_response(self, prompt: str, context: Optional[Dict]) -> Dict[str, Any]:
        """Mock araç yanıtı."""
        logger.debug("LLM mock tool response", prompt_length=len(prompt))
        return {
            "text": None,
            "tool_calls": [
                {"name": "get_world_state", "arguments": {}},
                {"name": "get_regime", "arguments": {}},
            ],
        }

    def _mock_text_response(self, prompt: str, context: Optional[Dict]) -> str:
        """Mock metin yanıtı."""
        return (
            "[LLM Mock] Analiz tamamlandı. "
            "Gemini API anahtarı eklendiğinde gerçek analiz üretilecek."
        )

    def _mock_structured_response(self) -> Dict[str, Any]:
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
