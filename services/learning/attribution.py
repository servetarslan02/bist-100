from typing import Any

"""
ALPHA BIST — Attribution Engine v1.0

Bir işlem kazandı/kaybetti → NEDEN?

Bu feedback olmadan model sadece "kazandım/kaybettim" öğrenir.
Bizim istediğimiz: "Neden kazandım/kaybettim?"

Attribution:
  - Macro contribution
  - Flow contribution
  - Momentum contribution
  - KAP/Event contribution
  - Regime contribution
  - Technical contribution
"""

from dataclasses import dataclass, field
from datetime import datetime

import structlog

logger = structlog.get_logger()


@dataclass
class TradeAttribution:
    """İşlem atfedilmesi."""

    ticker: str
    entry_date: datetime
    exit_date: datetime
    entry_price: float
    exit_price: float
    actual_return_pct: float

    # Beklenen vs Gerçek
    expected_return_pct: float
    prediction_error: float

    # Attribution bileşenleri
    macro_contribution: float = 0.0
    flow_contribution: float = 0.0
    momentum_contribution: float = 0.0
    event_contribution: float = 0.0
    regime_contribution: float = 0.0
    technical_contribution: float = 0.0
    residual: float = 0.0

    # Dersler
    what_worked: list[str] = field(default_factory=list)
    what_failed: list[str] = field(default_factory=list)
    lessons: list[str] = field(default_factory=list)


class AttributionEngine:
    """İşlem atfedilmesi motoru."""

    def attribute(
        self,
        ticker: str,
        entry_date: datetime,
        exit_date: datetime,
        entry_price: float,
        exit_price: float,
        expected_return: float,
        market_state_at_entry: dict,
        market_state_at_exit: dict,
        events_during_trade: list[dict],
        features_at_entry: dict,
        features_at_exit: dict,
    ) -> TradeAttribution:
        """İşlemi atfet."""

        actual_return = (exit_price / entry_price - 1) * 100
        prediction_error = actual_return - expected_return

        # 1. Macro contribution
        macro = self._calc_macro_contribution(market_state_at_entry, market_state_at_exit)

        # 2. Flow contribution
        flow = self._calc_flow_contribution(features_at_entry, features_at_exit)

        # 3. Momentum contribution
        momentum = self._calc_momentum_contribution(features_at_entry, features_at_exit)

        # 4. Event contribution
        event = self._calc_event_contribution(events_during_trade, actual_return)

        # 5. Regime contribution
        regime = self._calc_regime_contribution(market_state_at_entry, market_state_at_exit)

        # 6. Technical contribution
        technical = self._calc_technical_contribution(features_at_entry, features_at_exit)

        # 7. Residual
        attributed = macro + flow + momentum + event + regime + technical
        residual = actual_return - attributed

        # 8. Dersler
        what_worked, what_failed, lessons = self._extract_lessons(
            actual_return, expected_return, macro, flow, momentum, event, regime, technical
        )

        return TradeAttribution(
            ticker=ticker,
            entry_date=entry_date,
            exit_date=exit_date,
            entry_price=entry_price,
            exit_price=exit_price,
            actual_return_pct=round(actual_return, 2),
            expected_return_pct=round(expected_return, 2),
            prediction_error=round(prediction_error, 2),
            macro_contribution=round(macro, 2),
            flow_contribution=round(flow, 2),
            momentum_contribution=round(momentum, 2),
            event_contribution=round(event, 2),
            regime_contribution=round(regime, 2),
            technical_contribution=round(technical, 2),
            residual=round(residual, 2),
            what_worked=what_worked,
            what_failed=what_failed,
            lessons=lessons,
        )

    def _calc_macro_contribution(self, entry: dict, exit: dict) -> float:
        """Makro katkısı."""
        # USD değişimi
        usd_entry = entry.get("usd_strength", 0.5)
        usd_exit = exit.get("usd_strength", 0.5)
        usd_change = usd_exit - usd_entry

        # VIX değişimi
        vix_entry = entry.get("vix_level", 20)
        vix_exit = exit.get("vix_level", 20)
        vix_change = (vix_exit - vix_entry) / vix_entry

        # Basitleştirilmiş katkı
        contribution = -usd_change * 5 + vix_change * -3
        return contribution

    def _calc_flow_contribution(self, entry: dict, exit: dict) -> float:
        """Akış katkısı."""
        vol_entry = entry.get("volume_zscore", 0)
        vol_exit = exit.get("volume_zscore", 0)
        vol_change = vol_exit - vol_entry
        return vol_change * 0.5

    def _calc_momentum_contribution(self, entry: dict, exit: dict) -> float:
        """Momentum katkısı."""
        mom_entry = entry.get("momentum_20d", 0)
        mom_exit = exit.get("momentum_20d", 0)
        return (mom_exit - mom_entry) * 0.3

    def _calc_event_contribution(self, events: list[dict], actual_return: float) -> float:
        """Olay katkısı."""
        if not events:
            return 0

        # Pozitif/negatif olay sayısını say
        positive = sum(1 for e in events if e.get("sentiment", 0) > 0.3)
        negative = sum(1 for e in events if e.get("sentiment", 0) < -0.3)

        return (positive - negative) * 0.5

    def _calc_regime_contribution(self, entry: dict, exit: dict) -> float:
        """Rejim katkısı."""
        regime_entry = entry.get("regime", "UNKNOWN")
        regime_exit = exit.get("regime", "UNKNOWN")

        if regime_entry != regime_exit:
            # Rejim değişimi
            if regime_exit in ["RISK-OFF", "PANIC"]:
                return -2.0
            elif regime_exit in ["TRENDING-UP", "MOMENTUM-EXPANSION"]:
                return 2.0
        return 0

    def _calc_technical_contribution(self, entry: dict, exit: dict) -> float:
        """Teknik katkısı."""
        rsi_entry = entry.get("rsi_14", 50)
        rsi_exit = exit.get("rsi_14", 50)

        # Aşırı alımdan çıkış = pozitif
        if rsi_entry > 70 and rsi_exit < 70 or rsi_entry < 30 and rsi_exit > 30:
            return 1.0
        return 0

    def _extract_lessons(self, actual, expected, macro, flow, momentum, event, regime, technical) -> Any:
        """Dersler çıkar."""
        what_worked = []
        what_failed = []
        lessons = []

        if actual > 0:
            if macro > 0:
                what_worked.append("Makro ortam destekleyici")
            if momentum > 0:
                what_worked.append("Momentum desteği")
            if event > 0:
                what_worked.append("Olaylar pozitif")
        else:
            if macro < 0:
                what_failed.append("Makro ortam olumsuz")
            if regime < -1:
                what_failed.append("Rejim değişimi (risk-off)")
            if event < 0:
                what_failed.append("Olumsuz olaylar")

        # Prediction error analizi
        error = actual - expected
        if abs(error) > 5:
            if actual > expected:
                lessons.append("Model beklenenden daha iyi performans — faktörler kaçırılmış olabilir")
            else:
                lessons.append("Model beklenenden kötü performans — risk faktörleri eksik")

        return what_worked, what_failed, lessons

    def generate_report(self, attribution: TradeAttribution) -> str:
        """Attribution raporu üret."""
        lines = []
        lines.append(f"{'=' * 50}")
        lines.append(f"📊 {attribution.ticker} — İŞLEM ATFEDİLMESİ")
        lines.append(f"{'=' * 50}")
        lines.append("")
        lines.append(f"Giriş: ₺{attribution.entry_price:.2f} ({attribution.entry_date.strftime('%Y-%m-%d')})")
        lines.append(f"Çıkış: ₺{attribution.exit_price:.2f} ({attribution.exit_date.strftime('%Y-%m-%d')})")
        lines.append(f"Getiri: {attribution.actual_return_pct:+.2f}%")
        lines.append(f"Beklenen: {attribution.expected_return_pct:+.2f}%")
        lines.append(f"Hata: {attribution.prediction_error:+.2f}%")
        lines.append("")
        lines.append("ATRİBÜSYON:")
        lines.append(f"  Macro:     {attribution.macro_contribution:+.2f}%")
        lines.append(f"  Flow:      {attribution.flow_contribution:+.2f}%")
        lines.append(f"  Momentum:  {attribution.momentum_contribution:+.2f}%")
        lines.append(f"  Event:     {attribution.event_contribution:+.2f}%")
        lines.append(f"  Regime:    {attribution.regime_contribution:+.2f}%")
        lines.append(f"  Technical: {attribution.technical_contribution:+.2f}%")
        lines.append(f"  Residual:  {attribution.residual:+.2f}%")
        lines.append("")

        if attribution.what_worked:
            lines.append("✅ İŞE YARAYAN:")
            for w in attribution.what_worked:
                lines.append(f"   • {w}")

        if attribution.what_failed:
            lines.append("❌ BAŞARISIZ OLAN:")
            for w in attribution.what_failed:
                lines.append(f"   • {w}")

        if attribution.lessons:
            lines.append("📚 DERSLER:")
            for l in attribution.lessons:
                lines.append(f"   • {l}")

        return "\n".join(lines)


# Singleton
attribution_engine = AttributionEngine()
