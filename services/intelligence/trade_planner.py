"""
ALPHA BIST - Trade Planner v1.0

Bulunan hisseler için:
- Al/Sat/Karar
- Giriş noktası
- Hedef fiyat
- Stop loss
- Kar/zarar beklentisi
- Risk/getiri oranı
- Senaryo planları (Bull/Base/Bear)
- Pozisyon büyüklüğü
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class TradePlan:
    """Tek bir işlem planı."""

    ticker: str
    timestamp: datetime

    # Karar
    action: str  # BUY | SELL | HOLD | WATCH
    conviction: str  # HIGH | MEDIUM | LOW
    direction: str  # LONG | SHORT

    # Giriş
    entry_price: float
    entry_type: str  # MARKET | LIMIT | STOP_LIMIT

    # Hedef
    target_price_1: float  # Kısa vade hedef
    target_price_2: float  # Orta vade hedef
    target_price_3: float  # Uzun vade hedef

    # Stop
    stop_loss: float
    stop_type: str  # FIXED | TRAILING | ATR

    # Beklenti
    expected_return_pct: float
    expected_loss_pct: float
    risk_reward_ratio: float

    # Senaryolar
    scenario_bull: dict[str, Any] = field(default_factory=dict)
    scenario_base: dict[str, Any] = field(default_factory=dict)
    scenario_bear: dict[str, Any] = field(default_factory=dict)

    # Pozisyon
    suggested_position_pct: float = 0.0  # Portföyün yüzdesi
    max_loss_pct: float = 0.0  # Maksimum zarar

    # Gerekçe
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    # SPEC
    spec_score: float = 0.0
    spec_category: str = ""

    # Zaman
    horizon: str = ""  # 1-5D | 1-4W | 1-6M
    entry_window: str = ""  # "Bugün", "Bu hafta", vb.


class TradePlanner:
    """İşlem planı oluşturucu."""

    def create_plan(
        self,
        ticker: str,
        price: float,
        features: dict[str, float],
        spec_score: float,
        spec_category: str,
        market_regime: str = "RANGE",
        portfolio_value: float = 100000,
        max_position_pct: float = 10.0,
        max_risk_per_trade_pct: float = 2.0,
    ) -> TradePlan:
        """Bir hisse için kapsamlı işlem planı oluştur."""

        # Karar belirle
        action, conviction, direction = self._determine_action(spec_score, spec_category, features, market_regime)

        # Giriş fiyatı
        entry_price, entry_type = self._determine_entry(price, features)

        # Hedef fiyatlar
        target1, target2, target3 = self._determine_targets(price, features, spec_score)

        # Stop loss
        stop_loss, stop_type = self._determine_stop_loss(price, features, action)

        # Beklenti
        expected_return, expected_loss, risk_reward = self._calculate_expectations(
            entry_price, target1, stop_loss, action
        )

        # Dinamik Senaryo Olasılıkları
        p_bull, p_base, p_bear = self._calculate_scenario_probabilities(spec_score, features, market_regime)
        scenario_bull = self._scenario_bull(price, features, target2, prob=p_bull)
        scenario_base = self._scenario_base(price, features, target1, prob=p_base)
        scenario_bear = self._scenario_bear(price, features, stop_loss, prob=p_bear)

        # Pozisyon büyüklüğü
        position_pct, max_loss = self._calculate_position_size(
            portfolio_value, entry_price, stop_loss, max_position_pct, max_risk_per_trade_pct
        )

        # Gerekçe ve riskler
        reasons = self._generate_reasons(features, spec_score, market_regime)
        risks = self._generate_risks(features, market_regime)

        # Zaman ufku
        horizon, entry_window = self._determine_horizon(spec_score, features)

        return TradePlan(
            ticker=ticker,
            timestamp=datetime.now(UTC),
            action=action,
            conviction=conviction,
            direction=direction,
            entry_price=entry_price,
            entry_type=entry_type,
            target_price_1=target1,
            target_price_2=target2,
            target_price_3=target3,
            stop_loss=stop_loss,
            stop_type=stop_type,
            expected_return_pct=expected_return,
            expected_loss_pct=expected_loss,
            risk_reward_ratio=risk_reward,
            scenario_bull=scenario_bull,
            scenario_base=scenario_base,
            scenario_bear=scenario_bear,
            suggested_position_pct=position_pct,
            max_loss_pct=max_loss,
            reasons=reasons,
            risks=risks,
            spec_score=spec_score,
            spec_category=spec_category,
            horizon=horizon,
            entry_window=entry_window,
        )

    def _calculate_scenario_probabilities(
        self, spec_score: float, features: dict, regime: str
    ) -> tuple[float, float, float]:
        """Piyasa rejimi, model güveni (spec_score) ve volatiliteye göre dinamik senaryo olasılıkları hesaplar."""
        regime_upper = (regime or "SIDEWAYS").upper()
        if regime_upper in ["BULL", "STRONG_BULL"]:
            p_bull, p_base, p_bear = 45.0, 40.0, 15.0
        elif regime_upper in ["BEAR", "CRISIS", "PANIC"]:
            p_bull, p_base, p_bear = 15.0, 40.0, 45.0
        elif regime_upper in ["HIGH_VOL"]:
            p_bull, p_base, p_bear = 30.0, 30.0, 40.0
        else:
            p_bull, p_base, p_bear = 30.0, 50.0, 20.0

        score_shift = (spec_score - 50.0) * 0.4
        p_bull += score_shift
        p_bear -= score_shift

        mom = features.get("momentum_20d", 0.0)
        if mom > 10:
            p_bull += 5.0
            p_bear -= 5.0
        elif mom < -10:
            p_bear += 5.0
            p_bull -= 5.0

        p_bull = max(5.0, min(80.0, p_bull))
        p_base = max(10.0, min(70.0, p_base))
        p_bear = max(5.0, min(80.0, p_bear))

        total = p_bull + p_base + p_bear
        p_bull = round((p_bull / total) * 100.0, 1)
        p_base = round((p_base / total) * 100.0, 1)
        p_bear = round(100.0 - p_bull - p_base, 1)

        return p_bull, p_base, p_bear

    def _determine_action(
        self, spec_score: float, spec_category: str, features: dict, regime: str
    ) -> tuple[str, str, str]:
        """Al/Sat/Karar belirle."""

        mom20 = features.get("momentum_20d", 0)
        rsi = features.get("rsi_14", 50)
        vol_z = features.get("volume_zscore", 0)
        features.get("bb_position", 0.5)

        # HIGH CONVICTION BUY
        if spec_category == "HIGH_CONVICTION" and mom20 > 0:
            return "BUY", "HIGH", "LONG"

        # CANDIDATE BUY
        if spec_category == "CANDIDATE" and mom20 > 0 and rsi < 70:
            return "BUY", "MEDIUM", "LONG"

        # WATCH BUY (dikkatli)
        if spec_category == "WATCH" and vol_z > 2.0 and mom20 > 5:
            return "BUY", "LOW", "LONG"

        # Momentum bazlı alım
        if mom20 > 10 and rsi < 65 and vol_z > 1.5:
            return "BUY", "MEDIUM", "LONG"

        # Aşırı alım — sat
        if rsi > 80 and mom20 > 15:
            return "SELL", "MEDIUM", "LONG"

        # Düşüş trendi — sat
        if mom20 < -10 and rsi > 60:
            return "SELL", "LOW", "LONG"

        # Bekle
        return "HOLD", "LOW", "LONG"

    def _determine_entry(self, price: float, features: dict) -> tuple[float, str]:
        """Giriş noktası belirle."""

        bb_lower = features.get("bb_lower", price * 0.95)
        sma_20 = features.get("sma_20", price)
        atr_raw = features.get("atr_14")
        atr_pct_raw = features.get("atr_pct")
        if atr_raw is not None and atr_raw > 0:
            atr = atr_raw
        elif atr_pct_raw is not None and atr_pct_raw > 0:
            atr = price * atr_pct_raw / 100.0
        else:
            bb_width = features.get("bb_upper", price * 1.05) - bb_lower
            atr = min(bb_width * 0.5, price * 0.02) if bb_width > 0 else price * 0.015

        # Bollinger alt bandına yakın → limit emir
        if price < bb_lower * 1.02:
            return round(bb_lower, 2), "LIMIT"

        # SMA20'ye yakın → limit emir
        if abs(price - sma_20) / price < 0.01:
            return round(sma_20, 2), "LIMIT"

        # ATR bazlı giriş
        entry = price - atr * 0.5
        return round(entry, 2), "LIMIT"

    def _determine_targets(self, price: float, features: dict, spec_score: float) -> tuple[float, float, float]:
        """Hedef fiyatlar belirle."""

        atr_raw = features.get("atr_14")
        atr_pct_raw = features.get("atr_pct")
        if atr_raw is not None and atr_raw > 0:
            atr = atr_raw
        elif atr_pct_raw is not None and atr_pct_raw > 0:
            atr = price * atr_pct_raw / 100.0
        else:
            atr = price * 0.015
        bb_upper = features.get("bb_upper", price * 1.05)
        features.get("sma_20", price)
        mom20 = features.get("momentum_20d", 0)

        # ATR bazlı hedefler
        target1 = price + atr * 1.5  # Kısa vade: 1.5x ATR
        target2 = price + atr * 3.0  # Orta vade: 3x ATR
        target3 = price + atr * 5.0  # Uzun vade: 5x ATR

        # BB üst bandı referans
        if target1 < bb_upper:
            target1 = bb_upper

        # Momentum bazlı ayarlama
        if mom20 > 10:
            # Scale the projected move, not the entire price.  Multiplying
            # target2 directly makes a 6% target on a 100 TL share become
            # 127.2 TL instead of 107.2 TL.
            target2 = price + (target2 - price) * 1.2
            target3 = price + (target3 - price) * 1.3

        # SPEC skoru yüksekse hedefleri artır
        if spec_score > 80:
            target1 = price + (target1 - price) * 1.1
            target2 = price + (target2 - price) * 1.2

        return round(target1, 2), round(target2, 2), round(target3, 2)

    def _determine_stop_loss(self, price: float, features: dict, action: str) -> tuple[float, str]:
        """Stop loss belirle."""

        atr_raw = features.get("atr_14")
        atr_pct_raw = features.get("atr_pct")
        if atr_raw is not None and atr_raw > 0:
            atr = atr_raw
        elif atr_pct_raw is not None and atr_pct_raw > 0:
            atr = price * atr_pct_raw / 100.0
        else:
            atr = price * 0.015
        bb_lower = features.get("bb_lower", price * 0.95)
        features.get("near_20d_low", 0)

        # ATR bazlı stop
        stop_atr = price - atr * 2.0

        # BB alt bandı stop
        stop_bb = bb_lower * 0.98

        # Destek seviyesi stop
        stop_support = price * 0.95  # %5 altı

        # En yakın olanı seç
        stop = max(stop_atr, stop_bb, stop_support)

        # Maksimum %7 zarar
        max_stop = price * 0.93
        stop = max(stop, max_stop)

        return round(stop, 2), "ATR"

    def _calculate_expectations(
        self, entry: float, target: float, stop: float, action: str
    ) -> tuple[float, float, float]:
        """Beklenti hesapla."""

        if action == "BUY":
            expected_return = (target / entry - 1) * 100
            expected_loss = (stop / entry - 1) * 100
        else:
            expected_return = (entry / target - 1) * 100
            expected_loss = (entry / stop - 1) * 100

        risk_reward = abs(expected_return / expected_loss) if expected_loss != 0 else 0

        return round(expected_return, 2), round(expected_loss, 2), round(risk_reward, 2)

    def _scenario_bull(self, price: float, features: dict, target: float, prob: float = 30.0) -> dict:
        """Boğa senaryosu."""
        return {
            "name": "BULL",
            "probability": prob,
            "price_target": round(target, 2),
            "return_pct": round((target / price - 1) * 100, 2),
            "description": "Piyasa pozitif, momentum devam ediyor",
            "triggers": ["Sektör güçlenmesi", "KAP pozitif", "Hacim artışı"],
        }

    def _scenario_base(self, price: float, features: dict, target: float, prob: float = 50.0) -> dict:
        """Baz senaryo."""
        return {
            "name": "BASE",
            "probability": prob,
            "price_target": round(price * 1.02, 2),
            "return_pct": 2.0,
            "description": "Piyasa yatay, sınırlı hareket",
            "triggers": ["Normal hacim", "Sektör nötr"],
        }

    def _scenario_bear(self, price: float, features: dict, stop: float, prob: float = 20.0) -> dict:
        """Ayı senaryosu."""
        return {
            "name": "BEAR",
            "probability": prob,
            "price_target": round(stop, 2),
            "return_pct": round((stop / price - 1) * 100, 2),
            "description": "Piyasa negatif, stop loss tetiklenir",
            "triggers": ["Sektör zayıflığı", "KAP negatif", "Hacim düşüşü"],
        }

    def _calculate_position_size(
        self, portfolio: float, entry: float, stop: float, max_position: float, max_risk: float
    ) -> tuple[float, float]:
        """Pozisyon büyüklüğü hesapla (Kelly Criterion basitleştirilmiş)."""

        risk_per_share = abs(entry - stop)
        risk_amount = portfolio * (max_risk / 100)

        if risk_per_share > 0:
            shares = int(risk_amount / risk_per_share)
            position_value = shares * entry
            position_pct = (position_value / portfolio) * 100

            # Maksimum pozisyon limiti
            if position_pct > max_position:
                position_pct = max_position
                position_value = portfolio * (max_position / 100)
                shares = int(position_value / entry)

            max_loss = shares * risk_per_share
            max_loss_pct = (max_loss / portfolio) * 100
        else:
            position_pct = 0
            max_loss_pct = 0

        return round(position_pct, 2), round(max_loss_pct, 2)

    def _generate_reasons(self, features: dict, spec_score: float, regime: str) -> list[str]:
        """Alım gerekçeleri."""
        reasons = []

        if features.get("volume_zscore", 0) > 2.0:
            reasons.append(f"Hacim anomalisi: {features['volume_zscore']:.1f}σ")

        if features.get("momentum_20d", 0) > 5:
            reasons.append(f"Güçlü momentum: +{features['momentum_20d']:.1f}%")

        if features.get("rsi_14", 50) < 40:
            reasons.append(f"Aşırı satım bölgesi: RSI={features['rsi_14']:.0f}")

        if features.get("bb_position", 0.5) < 0.2:
            reasons.append("Bollinger alt bandına yakın")

        if spec_score > 70:
            reasons.append(f"Yüksek SPEC skoru: {spec_score:.0f}")

        if features.get("trend_slope_20d", 0) > 0:
            reasons.append("Yükselen trend")

        return reasons

    def _generate_risks(self, features: dict, regime: str) -> list[str]:
        """Risk faktörleri."""
        risks = []

        if features.get("realized_vol_20d", 20) > 30:
            risks.append(f"Yüksek volatilite: %{features['realized_vol_20d']:.0f}")

        if features.get("rsi_14", 50) > 70:
            risks.append(f"Aşırı alım riski: RSI={features['rsi_14']:.0f}")

        if features.get("correlation_to_index", 0.5) > 0.85:
            risks.append("Endeksle yüksek korelasyon")

        if regime in ["RISK-OFF", "PANIC"]:
            risks.append(f"Olumsuz piyasa rejimi: {regime}")

        if features.get("amihud_illiquidity", 0) > 0.005:
            risks.append("Düşük likidite")

        return risks

    def _determine_horizon(self, spec_score: float, features: dict) -> tuple[str, str]:
        """Zaman ufku belirle."""

        mom5 = abs(features.get("roc_5d", 0))
        mom20 = abs(features.get("momentum_20d", 0))

        if mom5 > 5 and spec_score > 70:
            return "1-5D", "Bugün"
        elif mom20 > 10 or spec_score > 60:
            return "1-4W", "Bu hafta"
        else:
            return "1-6M", "Uygun zamanda"


def format_trade_plan(plan: TradePlan) -> str:
    """İşlem planını okunabilir formata çevir."""

    lines = []
    lines.append(f"{'=' * 60}")
    lines.append(f"🎯 {plan.ticker} — İŞLEM PLANI")
    lines.append(f"{'=' * 60}")
    lines.append("")
    lines.append(f"📌 KARAR: {plan.action} ({plan.conviction})")
    lines.append(f"📌 YÖN: {plan.direction}")
    lines.append(f"📌 ZAMAN: {plan.horizon} — Giriş: {plan.entry_window}")
    lines.append("")
    lines.append("💰 GİRİŞ")
    lines.append(f"   Fiyat: ₺{plan.entry_price:.2f}")
    lines.append(f"   Tip: {plan.entry_type}")
    lines.append("")
    lines.append("🎯 HEDEFLER")
    lines.append(
        f"   Kısa vade: ₺{plan.target_price_1:.2f} (+{(plan.target_price_1 / plan.entry_price - 1) * 100:.1f}%)"
    )
    lines.append(
        f"   Orta vade: ₺{plan.target_price_2:.2f} (+{(plan.target_price_2 / plan.entry_price - 1) * 100:.1f}%)"
    )
    lines.append(
        f"   Uzun vade: ₺{plan.target_price_3:.2f} (+{(plan.target_price_3 / plan.entry_price - 1) * 100:.1f}%)"
    )
    lines.append("")
    lines.append("🛑 STOP LOSS")
    lines.append(f"   Fiyat: ₺{plan.stop_loss:.2f} ({(plan.stop_loss / plan.entry_price - 1) * 100:.1f}%)")
    lines.append(f"   Tip: {plan.stop_type}")
    lines.append("")
    lines.append("📊 BEKLENTİ")
    lines.append(f"   Getiri: %{plan.expected_return_pct}")
    lines.append(f"   Zarar: %{plan.expected_loss_pct}")
    lines.append(f"   Risk/Getiri: {plan.risk_reward_ratio:.2f}")
    lines.append("")
    lines.append("💼 POZİSYON")
    lines.append(f"   Önerilen: %{plan.suggested_position_pct}")
    lines.append(f"   Maks zarar: %{plan.max_loss_pct}")
    lines.append("")
    lines.append("📈 SENARYOLAR")
    lines.append(
        f"   🟢 Boğa (%{plan.scenario_bull['probability']}): ₺{plan.scenario_bull['price_target']:.2f} ({plan.scenario_bull['return_pct']:+.1f}%)"
    )
    lines.append(
        f"   ⚪ Baz (%{plan.scenario_base['probability']}): ₺{plan.scenario_base['price_target']:.2f} ({plan.scenario_base['return_pct']:+.1f}%)"
    )
    lines.append(
        f"   🔴 Ayı (%{plan.scenario_bear['probability']}): ₺{plan.scenario_bear['price_target']:.2f} ({plan.scenario_bear['return_pct']:+.1f}%)"
    )
    lines.append("")
    lines.append("✅ GEREKÇELER")
    for r in plan.reasons:
        lines.append(f"   • {r}")
    lines.append("")
    lines.append("⚠️ RİSKLER")
    for r in plan.risks:
        lines.append(f"   • {r}")
    lines.append(f"{'=' * 60}")

    return "\n".join(lines)


# Singleton
trade_planner = TradePlanner()
