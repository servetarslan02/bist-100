"""ALPHA BIST — Debate Engine (Boğa/Ayı Münazara Motoru) v3.0.

Bu modül, Alpha BIST multi-agent mimarisinde karar ayrılığı veya yüksek çelişki
tespit edildiğinde Boğa (Bull) ve Ayı (Bear) analistlerini CGX (Constrained Generation
& Cross-Examination) protokolü çerçevesinde kontrollü bir münazaraya sokar.

Münazara Kuralları:
- Maksimum 3 tur (sonsuz döngü ve token israfı kesinlikle engellenir).
- Yapılandırılmış JSON çıktı ve karşı tezin kanıtlarını çürütme odaklı çapraz sorgu.
- Güven Sönümlemesi (Confidence Damping): Her turda güven katsayısı sönümlenir (örn: 0.9^tur).
- Konsensüs Kapısı (Consensus Gate): Erken uzlaşı kontrolü ve anlaşma sağlanamazsa fail-closed NO_TRADE.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

import orjson
import structlog

from .agent_system import AgentResult, AgentRole, AgentTask, BaseAgent

if TYPE_CHECKING:
    from .llm_client import BaseLLMClient

logger = structlog.get_logger(__name__)

__all__: Final[list[str]] = [
    "DebateRound",
    "DebateResult",
    "DebateEngine",
]


def _truncate_at_sentence(text: str, max_len: int) -> str:
    """Metni kelime veya cümle ortasında bölmeden anlamlı sınırda keser.

    Args:
        text: Giriş metni.
        max_len: İzin verilen tavan karakter uzunluğu.

    Returns:
        str: Cümle sınırında sonlandırılmış metin.
    """
    if not text or len(text) <= max_len:
        return text or ""

    truncated = text[:max_len]
    for sep in (".", "!", "?", "\n"):
        last_sep = truncated.rfind(sep)
        if last_sep > max_len * 0.5:
            return truncated[: last_sep + 1]

    return truncated + "..."


@dataclass
class DebateRound:
    """Tek bir münazara turunun Boğa ve Ayı savları özeti."""

    round_num: int
    bull_direction: str = "NEUTRAL"
    bull_confidence: float = 0.0
    bull_reasoning: str = ""
    bull_evidence: list[str] = field(default_factory=list)
    bear_direction: str = "NEUTRAL"
    bear_confidence: float = 0.0
    bear_reasoning: str = ""
    bear_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Tur sonucunu sözlüğe çevirir.

        Returns:
            dict[str, Any]: Yapılandırılmış tur verisi.
        """
        return {
            "round": self.round_num,
            "bull": {
                "direction": self.bull_direction,
                "confidence": round(self.bull_confidence, 4),
                "reasoning": _truncate_at_sentence(self.bull_reasoning, 300),
                "evidence": list(self.bull_evidence),
            },
            "bear": {
                "direction": self.bear_direction,
                "confidence": round(self.bear_confidence, 4),
                "reasoning": _truncate_at_sentence(self.bear_reasoning, 300),
                "evidence": list(self.bear_evidence),
            },
        }

    def to_json(self) -> str:
        """Tur sonucunu orjson ile JSON dizgisine dönüştürür.

        Returns:
            str: JSON metni.
        """
        return orjson.dumps(self.to_dict()).decode("utf-8")

    def __repr__(self) -> str:
        return (
            f"DebateRound(r={self.round_num}, "
            f"bull={self.bull_direction!r}({self.bull_confidence:.2f}), "
            f"bear={self.bear_direction!r}({self.bear_confidence:.2f}))"
        )


@dataclass
class DebateResult:
    """Tamamlanan tüm münazara turlarının nihai uzlaşı raporu."""

    consensus: str  # 'LONG', 'SHORT', 'NEUTRAL', 'NO_TRADE'
    consensus_confidence: float
    rounds: list[DebateRound]
    agreement: bool
    total_rounds: int
    total_duration_ms: float = 0.0
    bull_final_confidence: float = 0.0
    bear_final_confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Münazara sonucunu sözlük formatına çevirir.

        Returns:
            dict[str, Any]: Yapısal münazara çıktısı.
        """
        return {
            "consensus": self.consensus,
            "consensus_confidence": round(self.consensus_confidence, 4),
            "agreement": self.agreement,
            "total_rounds": self.total_rounds,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "bull_final_confidence": round(self.bull_final_confidence, 4),
            "bear_final_confidence": round(self.bear_final_confidence, 4),
            "rounds": [r.to_dict() for r in self.rounds],
        }

    def to_json(self) -> str:
        """Münazara sonucunu orjson kullanarak JSON metnine çevirir.

        Returns:
            str: JSON formatında sonuç.
        """
        return orjson.dumps(self.to_dict()).decode("utf-8")

    def __repr__(self) -> str:
        return (
            f"DebateResult(consensus={self.consensus!r}, conf={self.consensus_confidence:.2f}, "
            f"rounds={self.total_rounds}, agreement={self.agreement})"
        )


class DebateEngine:
    """Çelişkili durumlarda Boğa ve Ayı tezlerini çapraz sorgulayan münazara motoru."""

    def __init__(
        self,
        max_rounds: int = 3,
        confidence_damping: float = 0.90,
    ) -> None:
        """DebateEngine başlatıcı.

        Args:
            max_rounds: İzin verilen maksimum münazara tur sayısı (varsayılan: 3).
            confidence_damping: Her turda uygulanan güven sönümleme çarpanı (varsayılan: 0.90).
        """
        self.max_rounds: int = max(1, min(5, max_rounds))
        self.confidence_damping: float = max(0.5, min(1.0, confidence_damping))

    async def run_debate(
        self,
        ticker: str,
        context: dict[str, Any],
        bull_agent: BaseAgent | None = None,
        bear_agent: BaseAgent | None = None,
        llm_client: BaseLLMClient | None = None,
    ) -> DebateResult:
        """Boğa ve Ayı analistleri arasında çok turlu münazarayı yürütür.

        Args:
            ticker: Hisse sembolü (örn: 'THYAO').
            context: Piyasa ve öznitelik bağlam sözlüğü.
            bull_agent: İsteğe bağlı özel Boğa analisti örneği.
            bear_agent: İsteğe bağlı özel Ayı analisti örneği.
            llm_client: İstemci bağlantısı.

        Returns:
            DebateResult: Münazara neticesi, uzlaşı yönü ve güven skoru.
        """
        start = time.monotonic()
        clean_ticker = str(ticker).strip().upper() if ticker else "UNKNOWN"

        # Ajan nesnelerini sağla
        if bull_agent is None:
            bull_agent = BaseAgent(AgentRole.BULL, llm_client=llm_client)
        if bear_agent is None:
            bear_agent = BaseAgent(AgentRole.BEAR, llm_client=llm_client)

        history: list[DebateRound] = []
        last_round: DebateRound | None = None

        for round_num in range(self.max_rounds):
            try:
                round_result = await self._run_round(
                    round_num=round_num,
                    ticker=clean_ticker,
                    context=context,
                    bull_agent=bull_agent,
                    bear_agent=bear_agent,
                    llm_client=llm_client,
                    last_round=last_round,
                    history=history,
                )
            except Exception as exc:
                logger.error(
                    "Münazara turu sırasında hata oluştu, mevcut turlarla sonlandırılıyor",
                    tur=round_num + 1,
                    ticker=clean_ticker,
                    hata=str(exc),
                )
                break

            history.append(round_result)
            last_round = round_result

            # Erken Uzlaşı (Early Consensus): İki taraf da aynı yöne evrildiyse
            if (
                round_result.bull_direction == round_result.bear_direction
                and round_result.bull_direction in ("LONG", "SHORT")
            ):
                logger.info(
                    "Münazarada erken uzlaşı sağlandı",
                    tur=round_num + 1,
                    yon=round_result.bull_direction,
                )
                break

        # Hiçbir tur tamamlanamadıysa fail-closed NO_TRADE
        if not history:
            total_duration = (time.monotonic() - start) * 1000.0
            return DebateResult(
                consensus="NO_TRADE",
                consensus_confidence=0.0,
                rounds=[],
                agreement=False,
                total_rounds=0,
                total_duration_ms=round(total_duration, 2),
            )

        final_round = history[-1]
        final_bull = final_round.bull_direction
        final_bear = final_round.bear_direction
        final_bull_conf = max(0.0, min(1.0, final_round.bull_confidence))
        final_bear_conf = max(0.0, min(1.0, final_round.bear_confidence))

        # Nihai Konsensüs Değerlendirmesi
        if final_bull == final_bear and final_bull in ("LONG", "SHORT", "NEUTRAL"):
            consensus = final_bull
            consensus_confidence = (final_bull_conf + final_bear_conf) / 2.0
            agreement = True
        else:
            # Açık bir baskınlık var mı kontrol et
            if final_bull_conf >= 0.60 and final_bear_conf < 0.35:
                consensus = final_bull
                consensus_confidence = final_bull_conf * 0.70
                agreement = False
            elif final_bear_conf >= 0.60 and final_bull_conf < 0.35:
                consensus = final_bear
                consensus_confidence = final_bear_conf * 0.70
                agreement = False
            else:
                # Kutuplaşma çözülemedi → Fail-closed NO_TRADE
                consensus = "NO_TRADE"
                consensus_confidence = 0.0
                agreement = False

        if math.isnan(consensus_confidence) or math.isinf(consensus_confidence):
            consensus_confidence = 0.0
        consensus_confidence = max(0.0, min(1.0, consensus_confidence))

        total_duration = (time.monotonic() - start) * 1000.0

        result = DebateResult(
            consensus=consensus,
            consensus_confidence=round(consensus_confidence, 4),
            rounds=history,
            agreement=agreement,
            total_rounds=len(history),
            total_duration_ms=round(total_duration, 2),
            bull_final_confidence=round(final_bull_conf, 4),
            bear_final_confidence=round(final_bear_conf, 4),
        )

        logger.info(
            "Münazara oturumu tamamlandı",
            ticker=clean_ticker,
            konsensus=consensus,
            uzlasi=agreement,
            toplam_tur=len(history),
            sure_ms=round(total_duration, 2),
        )

        return result

    async def _run_round(
        self,
        round_num: int,
        ticker: str,
        context: dict[str, Any],
        bull_agent: BaseAgent,
        bear_agent: BaseAgent,
        llm_client: BaseLLMClient | None,
        last_round: DebateRound | None,
        history: list[DebateRound],
    ) -> DebateRound:
        """Tek bir münazara turunu Boğa savı ve Ayı karşı-savı ile işletir."""
        damping = self.confidence_damping ** round_num

        # 1. Boğa Argümanı
        bull_prompt_vars = self._create_bull_prompt_vars(round_num, ticker, context, last_round, history)
        bull_template = f"bull_tur{round_num + 1}" if round_num < 3 else "bull_tur3"
        bull_task = AgentTask(
            task_id=f"bull-{ticker}-r{round_num}-{int(time.time())}",
            agent_role=AgentRole.BULL,
            ticker=ticker,
            prompt=f"[Tur {round_num + 1}] {ticker} için Boğa yükseliş tezi",
            context={**context, "prompt_vars": bull_prompt_vars},
            template_name=bull_template,
        )
        bull_result = await bull_agent.execute(bull_task, llm_client)

        raw_b_conf = float(bull_result.confidence) if not math.isnan(float(bull_result.confidence)) else 0.5
        bull_confidence = round(max(0.0, min(1.0, raw_b_conf * damping)), 4)

        # 2. Ayı Karşı Savı (Boğa'nın bu turdaki argümanını değerlendirir)
        bear_prompt_vars = self._create_bear_prompt_vars(round_num, ticker, context, bull_result, history)
        bear_template = f"bear_tur{round_num + 1}" if round_num < 3 else "bear_tur3"
        bear_task = AgentTask(
            task_id=f"bear-{ticker}-r{round_num}-{int(time.time())}",
            agent_role=AgentRole.BEAR,
            ticker=ticker,
            prompt=f"[Tur {round_num + 1}] {ticker} için Ayı düşüş tezi",
            context={**context, "prompt_vars": bear_prompt_vars},
            template_name=bear_template,
        )
        bear_result = await bear_agent.execute(bear_task, llm_client)

        raw_bear_conf = float(bear_result.confidence) if not math.isnan(float(bear_result.confidence)) else 0.5
        bear_confidence = round(max(0.0, min(1.0, raw_bear_conf * damping)), 4)

        bull_dir = str(bull_result.output.get("direction") or bull_result.output.get("position", "NEUTRAL")).upper()
        bear_dir = str(bear_result.output.get("direction") or bear_result.output.get("position", "NEUTRAL")).upper()

        return DebateRound(
            round_num=round_num,
            bull_direction=bull_dir,
            bull_confidence=bull_confidence,
            bull_reasoning=str(bull_result.reasoning or ""),
            bull_evidence=list(getattr(bull_result, "evidence", []) or []),
            bear_direction=bear_dir,
            bear_confidence=bear_confidence,
            bear_reasoning=str(bear_result.reasoning or ""),
            bear_evidence=list(getattr(bear_result, "evidence", []) or []),
        )

    def _create_bull_prompt_vars(
        self,
        round_num: int,
        ticker: str,
        context: dict[str, Any],
        last_round: DebateRound | None,
        history: list[DebateRound],
    ) -> dict[str, str]:
        """Boğa istemi için dinamik geçmiş ve karşı argüman değişkenlerini üretir."""
        if round_num == 0:
            return {}
        elif round_num == 1 and last_round:
            return {"bear_argument": last_round.bear_reasoning}
        else:
            return {"debate_summary": self._summarize_history(history)}

    def _create_bear_prompt_vars(
        self,
        round_num: int,
        ticker: str,
        context: dict[str, Any],
        bull_result: AgentResult,
        history: list[DebateRound],
    ) -> dict[str, str]:
        """Ayı istemi için Boğa argümanı ve geçmiş değişkenlerini üretir."""
        if round_num <= 1:
            bull_reasoning = str(getattr(bull_result, "reasoning", "") or "")
            return {"bull_argument": bull_reasoning}
        else:
            return {"debate_summary": self._summarize_history(history)}

    def _summarize_history(self, history: list[DebateRound]) -> str:
        """Önceki turların savlarını özetleyen metin bloğu oluşturur."""
        lines: list[str] = []
        for r in history:
            lines.append(f"Tur {r.round_num + 1}:")
            lines.append(f"  Boğa (Bull): {r.bull_direction} (güven: {r.bull_confidence:.2f})")
            lines.append(f"    {_truncate_at_sentence(r.bull_reasoning, 150)}")
            lines.append(f"  Ayı (Bear): {r.bear_direction} (güven: {r.bear_confidence:.2f})")
            lines.append(f"    {_truncate_at_sentence(r.bear_reasoning, 150)}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"DebateEngine(max_rounds={self.max_rounds}, damping={self.confidence_damping})"
