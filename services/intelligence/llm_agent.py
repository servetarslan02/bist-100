"""
ALPHA BIST — LLM Agent v1.0 (ReAct Döngüsü)

Sistemin yapay zeka beyni. ReAct (Reason + Act) deseniyle çalışır:
  1. DÜŞÜN  → Bağlamı al, ne bilmem gerekiyor?
  2. ARAÇ   → Eksik veriyi araçlarla çek
  3. GÖZLE  → Araç sonucunu değerlendir
  4. KARAR  → Yeterli veri varsa kararı ver

Yetenekler:
  - Haber analizi (RAG destekli, WorldState bağlamlı)
  - KAP bildirimi analizi (şirket geçmişiyle karşılaştırmalı)
  - Signal Fusion meta-skoru (çelişen sinyalleri hakemlik)
  - Rejim override (Kara Kuğu koruması)
  - Türkçe karar açıklaması üretimi
  - Hafızaya yazma (gelecek RAG için)
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()

# Bağımlılıklar — kendi modüllerimiz
from services.intelligence.llm_client import llm_client
from services.intelligence.llm_tools import llm_tool_executor, TOOL_SCHEMAS
from services.intelligence.llm_context_builder import llm_context_builder


@dataclass
class AgentAnalysis:
    """LLM Ajan analiz çıktısı."""
    ticker: Optional[str]
    analysis_type: str                   # news | kap | signal_fusion | narrative

    # Ana çıktılar
    entities: List[Dict] = field(default_factory=list)
    event_type: str = "OTHER"
    sentiment: float = 0.0               # -1.0 ile +1.0
    importance: float = 0.1
    affected_tickers: List[str] = field(default_factory=list)
    affected_sectors: List[str] = field(default_factory=list)
    surprise_score: float = 0.5
    uncertainty_score: float = 0.3

    # Signal Fusion meta-skor
    ai_direction: str = "NEUTRAL"        # LONG | SHORT | NEUTRAL
    ai_score: float = 50.0               # 0-100
    ai_confidence: float = 0.5

    # Rejim override (varsa)
    regime_override: Optional[str] = None
    regime_override_reason: str = ""

    # Türkçe açıklama
    narrative: str = ""
    key_insight: str = ""
    key_risks: List[str] = field(default_factory=list)

    # Meta
    tool_calls_made: List[str] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    is_mock: bool = False


class LLMAgent:
    """
    ALPHA BIST Ana LLM Ajanı — ReAct döngüsü ile çalışır.
    Tüm LLM analizleri bu sınıf üzerinden geçer.
    """

    MAX_TOOL_ROUNDS = 3  # Sonsuz araç döngüsünü önle

    def analyze_news(
        self,
        text: str,
        ticker: Optional[str] = None,
        sector: Optional[str] = None,
    ) -> AgentAnalysis:
        """
        Haber analizi — RAG ve WorldState bağlamlı.

        Adımlar:
        1. Bağlamı hazırla (WorldState + KnowledgeGraph + ResearchMemory)
        2. LLM'e gönder (araçlarla)
        3. Araç çağrılarını yürüt
        4. Sonucu yapılandır
        5. Hafızaya yaz
        """
        logger.info("LLM Agent: news analysis", ticker=ticker, text_length=len(text))

        # 1. Bağlam paketi
        context = llm_context_builder.build_news_context(ticker=ticker, sector=sector)

        # 2. Görev promptu
        prompt = self._build_news_prompt(text, ticker)

        # 3. ReAct döngüsü
        result, tool_calls = self._react_loop(prompt, context, analysis_type="news")

        # 4. Çıktıyı AgentAnalysis'e dönüştür
        analysis = AgentAnalysis(
            ticker=ticker,
            analysis_type="news",
            entities=result.get("entities", []),
            event_type=result.get("event_type", "OTHER"),
            sentiment=float(result.get("sentiment", 0.0)),
            importance=float(result.get("importance", 0.1)),
            affected_tickers=result.get("affected_tickers", []),
            affected_sectors=result.get("affected_sectors", []),
            surprise_score=float(result.get("surprise_score", 0.5)),
            uncertainty_score=float(result.get("uncertainty_score", 0.3)),
            key_insight=result.get("key_insight", ""),
            tool_calls_made=tool_calls,
            is_mock=not llm_client.is_live,
        )

        # 5. Eğer önemli bir habersa → rejim override değerlendir
        if analysis.importance >= 0.85 and analysis.event_type in ("GEOPOLITICAL", "MACRO"):
            self._evaluate_regime_override(analysis, text)

        # 6. Hafızaya yaz (ticker biliniyorsa)
        if ticker and analysis.importance >= 0.5:
            self._store_to_memory(analysis)

        return analysis

    def analyze_kap(
        self,
        ticker: str,
        title: str,
        summary: str = "",
        kap_history: Optional[List[Dict]] = None,
    ) -> AgentAnalysis:
        """
        KAP bildirimi analizi — şirket geçmişiyle karşılaştırmalı.
        """
        text = f"{title} {summary}".strip()
        logger.info("LLM Agent: KAP analysis", ticker=ticker, text_length=len(text))

        # 1. KAP bağlamı (geçmiş + WorldState)
        context = llm_context_builder.build_kap_context(
            ticker=ticker, kap_history=kap_history
        )

        # 2. Görev promptu
        prompt = self._build_kap_prompt(ticker, text, kap_history)

        # 3. ReAct döngüsü
        result, tool_calls = self._react_loop(prompt, context, analysis_type="kap")

        analysis = AgentAnalysis(
            ticker=ticker,
            analysis_type="kap",
            entities=result.get("entities", []),
            event_type=result.get("event_type", "COMPANY"),
            sentiment=float(result.get("sentiment", 0.0)),
            importance=float(result.get("importance", 0.1)),
            affected_tickers=result.get("affected_tickers", [ticker]),
            affected_sectors=result.get("affected_sectors", []),
            surprise_score=float(result.get("surprise_score", 0.5)),
            uncertainty_score=float(result.get("uncertainty_score", 0.3)),
            key_insight=result.get("key_insight", ""),
            key_risks=result.get("key_risks", []),
            tool_calls_made=tool_calls,
            is_mock=not llm_client.is_live,
        )

        # Hafızaya yaz
        if analysis.importance >= 0.4:
            self._store_to_memory(analysis)

        return analysis

    def compute_signal_meta_score(
        self,
        ticker: str,
        signals: Dict[str, Any],
        conflict_details: List[str],
        features: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Signal Fusion meta-skoru.
        LLM tüm çelişen sinyalleri okuyup kendi hakem kararını üretir.

        Returns:
            {"direction": "LONG|SHORT|NEUTRAL", "score": 0-100, "confidence": 0-1,
             "reasoning": "Türkçe gerekçe"}
        """
        logger.info("LLM Agent: signal meta-score", ticker=ticker)

        context = llm_context_builder.build_signal_fusion_context(
            ticker=ticker,
            signals=signals,
            conflict_details=conflict_details,
            features=features,
        )

        prompt = self._build_signal_prompt(ticker, signals, conflict_details)

        # Signal meta-skoru için araç döngüsü gerekmez; direkt structured output
        result = llm_client.analyze_financial_text(
            text=prompt,
            context_type="signal_fusion",
            context=context,
        )

        # Sonucu signal fusion formatına çevir
        sentiment = float(result.get("sentiment", 0.0))
        if sentiment > 0.2:
            direction = "LONG"
            score = 50 + sentiment * 30
        elif sentiment < -0.2:
            direction = "SHORT"
            score = 50 + sentiment * 30
        else:
            direction = "NEUTRAL"
            score = 50.0

        return {
            "direction": direction,
            "score": round(max(0, min(100, score)), 1),
            "confidence": float(result.get("importance", 0.5)),
            "reasoning": result.get("key_insight", ""),
            "is_mock": not llm_client.is_live,
        }

    def generate_decision_narrative(
        self,
        ticker: str,
        decision: Dict[str, Any],
        features: Dict[str, Any],
        price: float,
    ) -> str:
        """
        Nihai karar için Türkçe açıklama üret.
        """
        context = llm_context_builder.build_decision_narrative_context(
            ticker=ticker,
            decision=decision,
            features=features,
            price=price,
        )

        prompt = f"""
Sen BIST-100 uzmanı bir analistsın. Aşağıdaki karar verilerini kullanarak
{ticker} hissesi için kısa, net, Türkçe bir yatırım özeti yaz.

Maksimum 3 cümle. Formatı:
"{ticker} için [KARAR] kararı üretildi. [Ana gerekçe]. Stop: [stop] TL, Hedef: [hedef] TL"
"""

        return llm_client.generate_text(prompt=prompt, context=context, max_tokens=256)

    # ── ReAct Döngüsü ────────────────────────────────────────────────────────

    def _react_loop(
        self,
        prompt: str,
        context: Dict[str, Any],
        analysis_type: str,
    ) -> tuple:
        """
        ReAct (Reason + Act) döngüsü.
        LLM araç çağırırsa → çalıştır → sonuçları bağlama ekle → tekrar sor.
        """
        tool_calls_made = []
        enriched_context = dict(context)

        for round_num in range(self.MAX_TOOL_ROUNDS):
            response = llm_client.call_with_tools(
                prompt=prompt,
                tool_schemas=TOOL_SCHEMAS,
                context=enriched_context,
            )

            # Araç çağrısı yok → doğrudan metin veya structured output
            if not response.get("tool_calls"):
                # Structured analiz talep et
                final_result = llm_client.analyze_financial_text(
                    text=prompt,
                    context_type=analysis_type,
                    context=enriched_context,
                )
                return final_result, tool_calls_made

            # Araç çağrılarını yürüt ve bağlama ekle
            tool_results = {}
            for call in response["tool_calls"]:
                tool_name = call["name"]
                args = call.get("arguments", {})
                logger.info("Executing tool", tool=tool_name)

                tool_result = llm_tool_executor.execute(tool_name, args)
                tool_results[tool_name] = tool_result
                tool_calls_made.append(tool_name)

            # Araç sonuçlarını bağlama ekle
            enriched_context[f"tool_results_round_{round_num + 1}"] = tool_results

        # MAX_TOOL_ROUNDS tükendi → son structured output
        final_result = llm_client.analyze_financial_text(
            text=prompt,
            context_type=analysis_type,
            context=enriched_context,
        )
        return final_result, tool_calls_made

    # ── Prompt Üreticiler ────────────────────────────────────────────────────

    def _build_news_prompt(self, text: str, ticker: Optional[str]) -> str:
        ticker_context = f"İlgili hisse: {ticker}." if ticker else ""
        return f"""Sen BIST-100 uzmanı bir finansal analistsın. {ticker_context}
Aşağıdaki haberi analiz et. Gerekirse araçları kullanarak:
- Anlık piyasa durumunu (world state) kontrol et
- İlgili sektörlerin etki ağını (knowledge graph) sorgula
- Bu şirket için geçmiş analizleri (research memory) incele

HABER:
{text}

Analizini tamamla ve yapılandırılmış JSON çıktı ver."""

    def _build_kap_prompt(
        self, ticker: str, text: str, history: Optional[List[Dict]]
    ) -> str:
        history_note = ""
        if history:
            history_note = f"\nŞirketin son {len(history)} KAP bildirimi bağlamda mevcut."
        return f"""Sen BIST-100 uzmanı bir finansal analistsın.
{ticker} için yeni bir KAP bildirimi geldi.{history_note}

Gerekirse araçları kullanarak:
- Şirketin geçmiş analizlerini (research memory) sorgula
- Anlık piyasa durumunu (world state) kontrol et

KAP BİLDİRİMİ:
{text}

Önceki KAP'larla karşılaştırmalı analiz yap. Surprise score'u
geçmiş bildirimleri göz önünde bulundurarak belirle."""

    def _build_signal_prompt(
        self,
        ticker: str,
        signals: Dict[str, Any],
        conflicts: List[str],
    ) -> str:
        signal_summary = ", ".join(
            f"{k}: {v.get('direction', 'N')} ({v.get('score', 50):.0f})"
            for k, v in signals.items()
        )
        conflict_text = "; ".join(conflicts) if conflicts else "Çatışma yok"
        return f"""{ticker} için sinyal analizi:
Sinyaller: {signal_summary}
Çatışmalar: {conflict_text}

Bu çelişen sinyalleri değerlendir. Hangi yönde ve ne kadar güvenle pozisyon alınmalı?
Geçmiş piyasa koşulları ve mevcut makro bağlamı göz önünde bulundur."""

    # ── Yardımcı Metodlar ────────────────────────────────────────────────────

    def _evaluate_regime_override(self, analysis: AgentAnalysis, text: str):
        """Önemli makro/jeopolitik haberlerde rejim override değerlendir."""
        if analysis.importance < 0.85:
            return

        negative_sentiment = analysis.sentiment < -0.6
        is_macro_shock = analysis.event_type in ("GEOPOLITICAL", "MACRO")

        if negative_sentiment and is_macro_shock:
            result = llm_tool_executor.execute("override_regime", {
                "new_regime": "RISK_OFF",
                "reason": f"LLM: Yüksek önemli negatif haber (sentiment={analysis.sentiment:.2f}). "
                          f"Insight: {analysis.key_insight}",
                "confidence": analysis.importance,
            })
            if result.get("status") == "ok":
                analysis.regime_override = "RISK_OFF"
                analysis.regime_override_reason = result.get("reason", "")
                logger.warning(
                    "Regime overridden by LLM agent",
                    regime="RISK_OFF",
                    importance=analysis.importance,
                )

    def _store_to_memory(self, analysis: AgentAnalysis):
        """Analiz sonucunu research memory'e yaz."""
        if not analysis.ticker:
            return

        direction = "NEUTRAL"
        if analysis.sentiment > 0.2:
            direction = "LONG"
        elif analysis.sentiment < -0.2:
            direction = "SHORT"

        llm_tool_executor.execute("store_analysis", {
            "ticker": analysis.ticker,
            "thesis": analysis.key_insight or f"{analysis.event_type} haberi analiz edildi.",
            "direction": direction,
            "confidence": float(analysis.importance),
            "key_risks": analysis.key_risks,
        })


# Singleton
llm_agent = LLMAgent()
