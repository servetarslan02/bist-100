"""ALPHA BIST — Component States Engine v2.0

Piyasa bileşenlerinin ayrı ayrı state hesaplaması:
1. Momentum State: POSITIVE / NEGATIVE / NEUTRAL
2. Volatility State: LOW / NORMAL / HIGH / EXTREME
3. Volume State: BELOW_AVERAGE / AVERAGE / ABOVE_AVERAGE / SURGE
4. RSI State: OVERSOLD / NEUTRAL / OVERBOUGHT
5. Liquidity State: TIGHT / NORMAL / LOOSE
6. Sentiment State: NEGATIVE / NEUTRAL / POSITIVE / EUPHORIA
7. Macro State: EXPANSION / CONTRACTION / STAGFLATION / REFLATION
8. Anomaly State: count, severity, sector clustering
"""

import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class ComponentStates:
    """Tüm bileşen state'lerinin birleşimi."""
    timestamp: datetime
    momentum_state: str = "NEUTRAL"
    volatility_state: str = "NORMAL"
    volume_state: str = "AVERAGE"
    rsi_state: str = "NEUTRAL"
    liquidity_state: str = "NORMAL"
    sentiment_state: str = "NEUTRAL"
    macro_state: str = "NEUTRAL"
    anomaly_count: int = 0
    anomaly_severity: str = "NONE"

    # Detay değerler
    avg_momentum: float = 0.0
    avg_volatility: float = 0.0
    avg_volume_zscore: float = 0.0
    avg_rsi: float = 50.0
    avg_spread: float = 0.0
    sentiment_score: float = 0.0
    macro_score: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "momentum_state": self.momentum_state,
            "volatility_state": self.volatility_state,
            "volume_state": self.volume_state,
            "rsi_state": self.rsi_state,
            "liquidity_state": self.liquidity_state,
            "sentiment_state": self.sentiment_state,
            "macro_state": self.macro_state,
            "anomaly_count": self.anomaly_count,
            "anomaly_severity": self.anomaly_severity,
            "avg_momentum": round(self.avg_momentum, 4),
            "avg_volatility": round(self.avg_volatility, 4),
            "avg_volume_zscore": round(self.avg_volume_zscore, 4),
            "avg_rsi": round(self.avg_rsi, 2),
            "avg_spread": round(self.avg_spread, 4),
            "sentiment_score": round(self.sentiment_score, 4),
            "macro_score": round(self.macro_score, 4),
        }


class ComponentStateEngine:
    """Piyasa bileşenlerinin ayrı ayrı state hesaplaması.

    Her bileşen kendi içinde normalize edilir ve state atanır.
    """

    def compute_all(
        self,
        instrument_states: List[Dict],
        vix_level: float = None,
        news_sentiment: float = None,
        social_sentiment: float = None,
        put_call_ratio: float = None,
        market_depth: float = None,
        macro_data: Dict = None,
        world_state: Dict = None,
    ) -> ComponentStates:
        """Tüm bileşen state'lerini hesapla.

        Args:
            instrument_states: Her hisse için state dict
                [{ticker, momentum, volatility, volume_zscore, rsi, spread, anomaly_score, ...}]
            vix_level: VIX seviyesi (opsiyonel)
            news_sentiment: Haber sentiment skoru [-1, 1] (opsiyonel)
            social_sentiment: Sosyal medya sentiment skoru [-1, 1] (opsiyonel)
            macro_data: Makro veri (opsiyonel)
            world_state: World state dict (opsiyonel)

        Returns:
            ComponentStates
        """
        # Temel istatistikler
        momentums = [s.get("momentum", 0) for s in instrument_states if s.get("momentum") is not None]
        volatilities = [s.get("volatility", 0) for s in instrument_states if s.get("volatility") is not None]
        volume_zscores = [s.get("volume_zscore", 0) for s in instrument_states if s.get("volume_zscore") is not None]
        rsis = [s.get("rsi", 50) for s in instrument_states if s.get("rsi") is not None]
        spreads = [s.get("spread", 0) for s in instrument_states if s.get("spread") is not None]
        anomaly_scores = [s.get("anomaly_score", 0) for s in instrument_states if s.get("anomaly_score") is not None]

        avg_momentum = float(np.mean(momentums)) if momentums else 0.0
        avg_volatility = float(np.mean(volatilities)) if volatilities else 0.0
        avg_volume_zscore = float(np.mean(volume_zscores)) if volume_zscores else 0.0
        avg_rsi = float(np.mean(rsis)) if rsis else 50.0
        avg_spread = float(np.mean(spreads)) if spreads else 0.0

        # Her bileşeni hesapla
        momentum_state = self._compute_momentum_state(momentums, avg_momentum)
        volatility_state = self._compute_volatility_state(volatilities, avg_volatility, vix_level)
        volume_state = self._compute_volume_state(volume_zscores, avg_volume_zscore)
        rsi_state = self._compute_rsi_state(rsis, avg_rsi)
        liquidity_state = self._compute_liquidity_state(spreads, avg_spread, volume_zscores, market_depth)
        sentiment_state = self._compute_sentiment_state(
            news_sentiment, social_sentiment, put_call_ratio, vix_level
        )
        macro_state = self._compute_macro_state(world_state)
        anomaly_count, anomaly_severity = self._compute_anomaly_state(anomaly_scores)

        # Sentiment score (composite — fear/greed)
        sentiment_score = self._compute_fear_greed_score(
            news_sentiment, social_sentiment, put_call_ratio, vix_level
        )

        # Macro score
        macro_score = self._compute_macro_score(world_state)

        return ComponentStates(
            timestamp=datetime.now(timezone.utc),
            momentum_state=momentum_state,
            volatility_state=volatility_state,
            volume_state=volume_state,
            rsi_state=rsi_state,
            liquidity_state=liquidity_state,
            sentiment_state=sentiment_state,
            macro_state=macro_state,
            anomaly_count=anomaly_count,
            anomaly_severity=anomaly_severity,
            avg_momentum=avg_momentum,
            avg_volatility=avg_volatility,
            avg_volume_zscore=avg_volume_zscore,
            avg_rsi=avg_rsi,
            avg_spread=avg_spread,
            sentiment_score=sentiment_score,
            macro_score=macro_score,
        )

    def _compute_momentum_state(self, momentums: List[float], avg: float) -> str:
        """Momentum state belirle.

        POSITIVE: Pozitif momentum yaygın
        NEGATIVE: Negatif momentum yaygın
        NEUTRAL: Karışık
        """
        if not momentums:
            return "NEUTRAL"

        positive_count = sum(1 for m in momentums if m > 0)
        negative_count = sum(1 for m in momentums if m < 0)
        total = len(momentums)

        positive_pct = positive_count / total

        if positive_pct > 0.65:
            return "POSITIVE"
        elif positive_pct < 0.35:
            return "NEGATIVE"
        return "NEUTRAL"

    def _compute_volatility_state(
        self,
        volatilities: List[float],
        avg: float,
        vix_level: float = None,
    ) -> str:
        """Volatility state belirle.

        LOW: Düşük volatilite (<%15 annualized)
        NORMAL: Normal volatilite (%15-25)
        HIGH: Yüksek volatilite (%25-40)
        EXTREME: Aşırı volatilite (>%40)
        """
        # VIX varsa onu da dahil et
        if vix_level is not None:
            # VIX normalize: 20 normal, 30+ yüksek, 40+ aşırı
            if vix_level > 40:
                return "EXTREME"
            elif vix_level > 30:
                return "HIGH"
            elif vix_level < 15:
                return "LOW"

        # Annualized volatility (günlük → yıllık)
        annual_vol = avg * np.sqrt(252) * 100 if avg < 1 else avg

        if annual_vol < 15:
            return "LOW"
        elif annual_vol < 25:
            return "NORMAL"
        elif annual_vol < 40:
            return "HIGH"
        return "EXTREME"

    def _compute_volume_state(self, zscores: List[float], avg_zscore: float) -> str:
        """Volume state belirle.

        BELOW_AVERAGE: Hacim düşük
        AVERAGE: Normal
        ABOVE_AVERAGE: Hacim yüksek
        SURGE: Hacim patlaması
        """
        if not zscores:
            return "AVERAGE"

        if avg_zscore > 2.0:
            return "SURGE"
        elif avg_zscore > 0.5:
            return "ABOVE_AVERAGE"
        elif avg_zscore < -0.5:
            return "BELOW_AVERAGE"
        return "AVERAGE"

    def _compute_rsi_state(self, rsi_values: List[float], avg_rsi: float) -> str:
        """RSI state belirle.

        OVERSOLD: RSI < 30 yaygın
        OVERBOUGHT: RSI > 70 yaygın
        NEUTRAL: Normal
        """
        if not rsi_values:
            return "NEUTRAL"

        oversold_count = sum(1 for r in rsi_values if r < 30)
        overbought_count = sum(1 for r in rsi_values if r > 70)
        total = len(rsi_values)

        oversold_pct = oversold_count / total
        overbought_pct = overbought_count / total

        if oversold_pct > 0.3:
            return "OVERSOLD"
        elif overbought_pct > 0.3:
            return "OVERBOUGHT"
        return "NEUTRAL"

    def _compute_liquidity_state(
        self,
        spreads: List[float],
        avg_spread: float,
        volume_zscores: List[float],
        market_depth: float = None,
    ) -> str:
        """Liquidity state belirle.

        TIGHT: Likidite sıkışık (yüksek spread, düşük hacim, düşük derinlik)
        NORMAL: Normal
        LOOSE: Likidite bol (düşük spread, yüksek hacim, yüksek derinlik)
        """
        # Spread analizi
        avg_vol_zscore = float(np.mean(volume_zscores)) if volume_zscores else 0.0

        # Market depth varsa dahil et
        depth_score = 0.0
        if market_depth is not None:
            # depth 0-1 arası normalize edilmiş
            # 0 = derinlik yok, 1 = tam derinlik
            depth_score = market_depth

        # Yüksek spread + düşük hacim = TIGHT
        if avg_spread > 0.03 and avg_vol_zscore < -0.5:
            return "TIGHT"

        # Düşük spread + yüksek hacim = LOOSE
        if avg_spread < 0.01 and avg_vol_zscore > 0.5:
            return "LOOSE"

        # Market depth'e göre
        if market_depth is not None:
            if depth_score < 0.3:
                return "TIGHT"
            elif depth_score > 0.7:
                return "LOOSE"

        # Sadece spread'e göre
        if avg_spread > 0.05:
            return "TIGHT"
        elif avg_spread < 0.005:
            return "LOOSE"

        return "NORMAL"

    def _compute_sentiment_state(
        self,
        news_sentiment: float = None,
        social_sentiment: float = None,
        put_call_ratio: float = None,
        vix_level: float = None,
    ) -> str:
        """Sentiment state belirle.

        Fear/Greed composite = news + social + put_call + VIX

        NEGATIVE: Piyasa korkusu (fear)
        NEUTRAL: Normal
        POSITIVE: Piyasa iyimser (greed)
        EUPHORIA: Aşırı iyimserlik (dikkat)
        """
        score = self._compute_fear_greed_score(
            news_sentiment, social_sentiment, put_call_ratio, vix_level
        )

        if score < -0.3:
            return "NEGATIVE"
        elif score > 0.5:
            return "EUPHORIA"
        elif score > 0.2:
            return "POSITIVE"
        return "NEUTRAL"

    def _compute_sentiment_score(
        self,
        news_sentiment: float = None,
        social_sentiment: float = None,
    ) -> float:
        """Composite sentiment skoru [-1, 1]."""
        scores = []
        weights = []

        if news_sentiment is not None:
            scores.append(news_sentiment)
            weights.append(0.6)

        if social_sentiment is not None:
            scores.append(social_sentiment)
            weights.append(0.4)

        if not scores:
            return 0.0

        total_weight = sum(weights)
        return sum(s * w for s, w in zip(scores, weights)) / total_weight

    def _compute_fear_greed_score(
        self,
        news_sentiment: float = None,
        social_sentiment: float = None,
        put_call_ratio: float = None,
        vix_level: float = None,
    ) -> float:
        """Fear/Greed composite skoru [-1, 1].

        -1 = extreme fear
         0 = neutral
        +1 = extreme greed

        Bileşenler:
        - News sentiment (ağırlık: 0.35)
        - Social sentiment (ağırlık: 0.25)
        - Put/Call ratio (ağırlık: 0.20) — yüksek = fear, düşük = greed
        - VIX level (ağırlık: 0.20) — yüksek = fear, düşük = greed
        """
        scores = []
        weights = []

        if news_sentiment is not None:
            scores.append(news_sentiment)
            weights.append(0.35)

        if social_sentiment is not None:
            scores.append(social_sentiment)
            weights.append(0.25)

        if put_call_ratio is not None:
            # Put/Call > 1.0 = fear, < 0.7 = greed
            # Normalize: [-1, 1]
            pcr_score = np.clip(1.0 - put_call_ratio, -1, 1)
            scores.append(pcr_score)
            weights.append(0.20)

        if vix_level is not None:
            # VIX > 30 = fear, < 15 = greed
            # Normalize: [0, 50] → [-1, 1]
            vix_score = np.clip(1.0 - (vix_level - 15) / 25.0, -1, 1)
            scores.append(vix_score)
            weights.append(0.20)

        if not scores:
            return 0.0

        total_weight = sum(weights)
        return sum(s * w for s, w in zip(scores, weights)) / total_weight

    def _compute_macro_state(self, world_state: Dict = None) -> str:
        """Macro state belirle (world_state'den).

        EXPANSION: Büyüme, risk-on
        CONTRACTION: Daralma, risk-off
        STAGFLATION: Duraklama + enflasyon
        REFLATION: Toparlanma
        """
        if not world_state:
            return "NEUTRAL"

        risk_appetite = world_state.get("global_risk_appetite", 0.5)
        inflation = world_state.get("inflation_pressure", 0.5)
        turkey_risk = world_state.get("turkey_macro_risk", 0.5)

        # Stagflation: yüksek enflasyon + düşük risk iştahı
        if inflation > 0.7 and risk_appetite < 0.4:
            return "STAGFLATION"

        # Expansion: yüksek risk iştahı + düşük enflasyon
        if risk_appetite > 0.6 and inflation < 0.5:
            return "EXPANSION"

        # Contraction: düşük risk iştahı
        if risk_appetite < 0.35:
            return "CONTRACTION"

        # Reflation: risk iştahı artıyor, enflasyon kontrol altında
        if risk_appetite > 0.5 and inflation < 0.6:
            return "REFLATION"

        return "NEUTRAL"

    def _compute_macro_score(self, world_state: Dict = None) -> float:
        """Macro skoru [0, 1]. 1 = risk-on, 0 = risk-off."""
        if not world_state:
            return 0.5

        risk_appetite = world_state.get("global_risk_appetite", 0.5)
        turkey_risk = world_state.get("turkey_macro_risk", 0.5)
        geopolitical = world_state.get("geopolitical_risk", 0.5)

        # Risk-on: yüksek risk_appetite, düşük turkey_risk, düşük geopolitical
        score = (
            risk_appetite * 0.5 +
            (1 - turkey_risk) * 0.3 +
            (1 - geopolitical) * 0.2
        )

        return float(np.clip(score, 0, 1))

    def _compute_anomaly_state(self, anomaly_scores: List[float]) -> tuple:
        """Anomaly state hesapla.

        Returns:
            (anomaly_count, anomaly_severity)
        """
        if not anomaly_scores:
            return 0, "NONE"

        # Anomaly eşiği: 0.7
        anomalies = [s for s in anomaly_scores if s > 0.7]
        count = len(anomalies)

        if count == 0:
            return 0, "NONE"

        max_severity = max(anomalies)

        if count > 10 or max_severity > 0.95:
            return count, "CRITICAL"
        elif count > 5 or max_severity > 0.85:
            return count, "HIGH"
        elif count > 2:
            return count, "MEDIUM"
        return count, "LOW"
