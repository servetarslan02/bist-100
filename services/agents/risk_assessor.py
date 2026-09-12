"""ALPHA BIST — Risk Assessor (Risk Değerlendirme) Modülü v3.0.

Bu modül, Alpha BIST multi-agent mimarisinde üretilen yatırım ve işlem sinyallerini
(Teknik, Temel, Haber, Makro vb.) kurumsal risk yönetimi ilkeleri doğrultusunda denetler.
Volatilite (ATR), likidite derinliği, model çelişkileri, rejim şokları ve portföy konsantrasyonunu
analiz eder. Baş Risk Yöneticisi (CRO) yetkisiyle 'Fail-Closed' çalışır ve kritik risk
tespitinde işlemi doğrudan veto eder (approved=False).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import orjson
import structlog

from .prompts import PromptFactory

if TYPE_CHECKING:
    from .agent_system import AgentResult, AgentRole
    from .llm_client import BaseLLMClient

logger = structlog.get_logger(__name__)

__all__: Final[list[str]] = [
    "RiskAssessment",
    "RiskAssessor",
]


@dataclass
class RiskAssessment:
    """Risk değerlendirme neticesi, onay durumu ve pozisyon sınırları veri yapısı."""

    approved: bool
    risk_level: str  # 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
    risk_score: float  # 0.0 - 100.0
    max_position_pct: float  # Maksimum önerilen portföy ağırlığı (%)
    stop_loss_pct: float  # Dinamik koruyucu stop-loss yüzdesi (%)
    risk_factors: list[str]
    veto_reason: str | None = None
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Risk değerlendirmesini Python sözlüğüne çevirir.

        Returns:
            dict[str, Any]: Yapılandırılmış değerlendirme verisi.
        """
        return {
            "approved": self.approved,
            "risk_level": self.risk_level,
            "risk_score": round(self.risk_score, 2),
            "max_position_pct": round(self.max_position_pct, 2),
            "stop_loss_pct": round(self.stop_loss_pct, 2),
            "risk_factors": list(self.risk_factors),
            "veto_reason": self.veto_reason,
            "reasoning": self.reasoning[:500],
        }

    def to_json(self) -> str:
        """Risk değerlendirmesini orjson kullanarak JSON metnine dönüştürür.

        Returns:
            str: JSON formatında risk değerlendirme özeti.
        """
        return orjson.dumps(self.to_dict()).decode("utf-8")

    def __repr__(self) -> str:
        return (
            f"RiskAssessment(level={self.risk_level!r}, score={self.risk_score:.1f}, "
            f"approved={self.approved}, max_pos={self.max_position_pct:.1f}%, "
            f"stop_loss={self.stop_loss_pct:.1f}%)"
        )


class RiskAssessor:
    """Multi-agent pipeline için risk denetim ve sermaye koruma motoru.

    Değerlendirme Kriterleri:
    1. Volatilite Riski: ATR oranı, aşırı sapmalar.
    2. Likidite Riski: 5 günlük ortalama işlem hacmi ve hacim z-skoru.
    3. Model Ayrışması (Çatışma): Ajanlar arası yön kutuplaşması.
    4. Ortalama Model Güveni: Ajanların düşük güven skoru.
    5. Portföy Riski: Konsantrasyon, mevcut açık pozisyon adedi.
    6. Makro Piyasa Rejimi: RISK_OFF veya aşırı volatilite rejimi.
    7. BIST Seans ve Fiyat Limitleri: Devre kesici ve tavan/taban kuralları.
    """

    # BIST günlük marj tavanı stop-loss üst sınırı (%9.5 — taban kilitlenmeden çıkış payı)
    BIST_MAX_STOP_LOSS_PCT: float = 9.5
    BIST_MIN_STOP_LOSS_PCT: float = 1.5

    # Risk seviyesi sayısal eşik sınırları
    RISK_THRESHOLDS: dict[str, float] = {
        "LOW": 30.0,
        "MEDIUM": 50.0,
        "HIGH": 70.0,
        "CRITICAL": 85.0,
    }

    def __init__(self, veto_threshold: float = 70.0) -> None:
        """RiskAssessor başlatıcı.

        Args:
            veto_threshold: Otomatik veto tetikleyecek taban risk skoru (varsayılan: 70.0).
        """
        self.veto_threshold: float = veto_threshold

    async def assess(
        self,
        ticker: str,
        agent_results: dict[AgentRole, AgentResult],
        features: dict[str, float],
        portfolio_info: dict[str, Any] | None = None,
        llm_client: BaseLLMClient | None = None,
        context: dict[str, Any] | None = None,
    ) -> RiskAssessment:
        """Kapsamlı risk denetimi yürütür.

        Args:
            ticker: Analiz edilen hisse kodu (örn: 'THYAO').
            agent_results: Uzman ajanların ürettiği AgentResult sözlüğü.
            features: Teknik ve piyasa göstergeleri sözlüğü.
            portfolio_info: İsteğe bağlı mevcut portföy durumu.
            llm_client: İsteğe bağlı LLM tabanlı niteliksel risk analisti.
            context: Makro rejim, sektör vb. ek bağlam bilgileri.

        Returns:
            RiskAssessment: Onay, veto gerekçesi, risk skoru ve pozisyon limitleri.
        """
        start = time.monotonic()
        clean_ticker = str(ticker).strip().upper() if ticker else "UNKNOWN"
        features = features or {}

        risk_factors: list[str] = []
        risk_score = 0.0

        # 1. Volatilite Riski (ATR ve oynaklık)
        raw_atr = features.get("atr_pct", features.get("atr", 0.0))
        atr_pct = float(raw_atr) if not (math.isnan(raw_atr) or math.isinf(raw_atr)) else 0.0

        if atr_pct > 6.0:
            risk_score += 30.0
            risk_factors.append(f"Aşırı volatilite: ATR %{atr_pct:.1f}")
        elif atr_pct > 4.5:
            risk_score += 20.0
            risk_factors.append(f"Yüksek volatilite: ATR %{atr_pct:.1f}")
        elif atr_pct > 3.0:
            risk_score += 10.0
            risk_factors.append(f"Orta volatilite: ATR %{atr_pct:.1f}")

        # 2. Likidite Riski
        avg_vol = float(features.get("avg_volume_5d", features.get("volume", 500000.0)))
        vol_zscore = float(features.get("volume_zscore", 0.0))

        if avg_vol < 100000.0:
            risk_score += 20.0
            risk_factors.append(f"Düşük likidite/hacim: {avg_vol:,.0f} lot")
        if vol_zscore < -2.0:
            risk_score += 10.0
            risk_factors.append(f"Hacim kuruluğu anomalisi: {vol_zscore:.1f}σ")

        # 3. Model Karar Çatışması Riski
        valid_results = {r: res for r, res in agent_results.items() if getattr(res, "success", False)}
        directions = [str(res.output.get("direction", "NEUTRAL")).upper() for res in valid_results.values()]
        long_count = directions.count("LONG")
        short_count = directions.count("SHORT")

        if long_count > 0 and short_count > 0:
            risk_score += 15.0
            risk_factors.append(f"Ajanlar arası kutuplaşma: {long_count} LONG vs {short_count} SHORT")

        # 4. Ortalama Model Güveni Yetersizliği
        confs = [
            float(r.confidence)
            for r in valid_results.values()
            if hasattr(r, "confidence") and not math.isnan(float(r.confidence))
        ]
        avg_confidence = sum(confs) / len(confs) if confs else 0.5
        if avg_confidence < 0.45:
            risk_score += 15.0
            risk_factors.append(f"Düşük ortalama model güveni: {avg_confidence:.2f}")

        # 5. Portföy Konsantrasyonu Riski
        if portfolio_info:
            pos_count = int(portfolio_info.get("position_count", 0))
            if pos_count > 12:
                risk_score += 10.0
                risk_factors.append(f"Yüksek açık pozisyon adedi: {pos_count}")

            current_weight = float(portfolio_info.get("current_weight_pct", 0.0))
            if current_weight >= 12.0:
                risk_score += 15.0
                risk_factors.append(f"Mevcut hisse ağırlığı zaten yüksek: %{current_weight:.1f}")

        # 6. Makroekonomik Piyasa Rejimi Riski
        regime = str((context or {}).get("regime", "UNKNOWN")).upper()
        if regime in ("RISK_OFF", "HIGH_VOLATILITY"):
            risk_score += 15.0
            risk_factors.append(f"Olumsuz makro rejim: {regime}")

        # Skoru [0, 100] aralığında sınırla
        risk_score = max(0.0, min(100.0, risk_score))
        risk_level = self._determine_risk_level(risk_score)

        # 7. Veto ve Onay Kararı (Fail-Closed)
        approved = True
        veto_reason: str | None = None

        if risk_score >= self.veto_threshold or risk_level == "CRITICAL":
            approved = False
            veto_reason = f"Kritik risk eşiği aşıldı: Risk Skoru={risk_score:.1f} (Seviye={risk_level})"
            logger.warning(
                "Risk VETO uygulandı — işlem onaylanmadı",
                ticker=clean_ticker,
                risk_score=risk_score,
                risk_factors=risk_factors,
            )

        # Pozisyon büyüklüğü ve stop-loss hesabı
        max_position_pct = self._calculate_max_position(risk_level, risk_score)
        stop_loss_pct = self._calculate_stop_loss(risk_level, atr_pct)

        # 8. Opsiyonel Niteliksel LLM Risk Analizi
        llm_reasoning = ""
        if llm_client:
            llm_result = await self._llm_risk_assessment(
                ticker=clean_ticker,
                agent_results=agent_results,
                features=features,
                portfolio_info=portfolio_info,
                llm_client=llm_client,
            )
            if llm_result:
                llm_reasoning = str(llm_result.get("reasoning", ""))
                # LLM veto override (fail-closed)
                if str(llm_result.get("risk_level", "")).upper() == "CRITICAL" and approved:
                    approved = False
                    veto_reason = f"LLM CRO Veto: {llm_result.get('veto_reason', 'Kritik risk')}"
                    logger.warning(
                        "LLM CRO Risk VETO uyguladı",
                        ticker=clean_ticker,
                        llm_veto_reason=veto_reason,
                    )

        elapsed_ms = (time.monotonic() - start) * 1000.0

        assessment = RiskAssessment(
            approved=approved,
            risk_level=risk_level,
            risk_score=round(risk_score, 2),
            max_position_pct=max_position_pct,
            stop_loss_pct=stop_loss_pct,
            risk_factors=risk_factors,
            veto_reason=veto_reason,
            reasoning=llm_reasoning or f"Kural tabanlı risk analizi tamamlandı: Seviye={risk_level}",
        )

        logger.info(
            "Risk değerlendirmesi tamamlandı",
            ticker=clean_ticker,
            risk_level=risk_level,
            risk_score=assessment.risk_score,
            approved=approved,
            duration_ms=round(elapsed_ms, 2),
        )

        return assessment

    @classmethod
    def _determine_risk_level(cls, risk_score: float) -> str:
        """Risk puanını seviye etiketine dönüştürür."""
        if risk_score >= cls.RISK_THRESHOLDS["HIGH"]:
            return "CRITICAL"
        elif risk_score >= cls.RISK_THRESHOLDS["MEDIUM"]:
            return "HIGH"
        elif risk_score >= cls.RISK_THRESHOLDS["LOW"]:
            return "MEDIUM"
        else:
            return "LOW"

    @classmethod
    def _calculate_max_position(cls, risk_level: str, risk_score: float) -> float:
        """Risk seviyesine göre sermayenin tek hisseye ayrılabilecek maksimum yüzdesini döner."""
        if risk_level == "CRITICAL":
            return 0.0

        # Seviyeye göre (tavan_yüzde, taban_yüzde, min_skor, maks_skor)
        bounds = {
            "LOW": (10.0, 8.0, 0.0, 30.0),
            "MEDIUM": (7.0, 5.0, 30.0, 50.0),
            "HIGH": (4.0, 1.0, 50.0, 70.0),
        }

        tavan, taban, low_s, high_s = bounds.get(risk_level, (5.0, 1.0, 50.0, 70.0))
        t = (risk_score - low_s) / max(1.0, high_s - low_s)
        t = max(0.0, min(1.0, t))

        position = tavan - (tavan - taban) * t
        return round(max(0.5, position), 1)

    @classmethod
    def _calculate_stop_loss(cls, risk_level: str, atr_pct: float) -> float:
        """ATR oynaklığına ve BIST taban limitlerine göre dinamik stop-loss hesaplar."""
        base_stops = {
            "LOW": 3.0,
            "MEDIUM": 5.0,
            "HIGH": 7.0,
            "CRITICAL": 9.5,
        }
        base = base_stops.get(risk_level, 5.0)

        # En az 2× ATR, ancak BIST seans limitlerini (en çok %9.5) aşmayacak şekilde sınırla
        if atr_pct > 0.0:
            target = max(base, atr_pct * 2.0)
        else:
            target = base

        clamped = max(cls.BIST_MIN_STOP_LOSS_PCT, min(cls.BIST_MAX_STOP_LOSS_PCT, target))
        return round(clamped, 1)

    async def _llm_risk_assessment(
        self,
        ticker: str,
        agent_results: dict[AgentRole, AgentResult],
        features: dict[str, float],
        portfolio_info: dict[str, Any] | None,
        llm_client: BaseLLMClient,
    ) -> dict[str, Any] | None:
        """LLM ile derinlemesine niteliksel risk değerlendirmesi yapar."""
        try:
            agent_text: list[str] = []
            for role, result in agent_results.items():
                if getattr(result, "success", False):
                    direction = result.output.get("direction", "NEUTRAL")
                    agent_text.append(f"{role.value}: {direction} (güven: {result.confidence:.2f})")

            system_prompt, user_prompt = PromptFactory.get_prompts(
                template_name="risk",
                ticker=ticker,
                context=features,
                agent_results="\n".join(agent_text) if agent_text else "Ajan verisi yok",
                portfolio_info=str(portfolio_info or {}),
            )

            response = await llm_client.generate_with_retry(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

            if response.success and response.content:
                from .llm_client import parse_llm_json

                return parse_llm_json(response.content)

        except Exception as exc:
            logger.warning("LLM risk analizi sırasında hata oluştu, kural tabanlı devam ediliyor", hata=str(exc))

        return None

    def __repr__(self) -> str:
        return f"RiskAssessor(veto_threshold={self.veto_threshold})"
