"""ALPHA BIST — Market Breadth Engine v2.0

Piyasa genişliğini 7 göstergeyle hesaplar:
1. Advance-Decline Line (cumulative)
2. AD Ratio (advancing / declining)
3. McClellan Oscillator (EMA19 - EMA39 of net advances)
4. McClellan Summation Index (cumulative McClellan)
5. TRIN / Arms Index (AD ratio / volume ratio)
6. New Highs - New Lows (52-week)
7. Breadth Thrust (advancing / total)

Kaynaklar:
- StockCharts: McClellan Oscillator & Summation Index
- Blueberry Markets: Top Market Breadth Indicators
- Gupta et al. (2025): Ensemble-HMM voting framework

BIST-specific:
- Düşük likiditeli hisseler hariç tutulur (volume eşiği)
- Sektörel breadth ayrı hesaplanır
- Döviz etkisini breadth'den izole etmek için normalize
"""

import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class BreadthResult:
    """Market breadth sonucu — 7 gösterge + state."""
    timestamp: datetime

    # Temel breadth
    advancing: int = 0
    declining: int = 0
    unchanged: int = 0
    total: int = 0

    # Göstergeler
    ad_line: int = 0                        # Advance-Decline Line (cumulative)
    ad_ratio: float = 1.0                   # Advancing / Declining
    pct_advancing: float = 50.0             # % Advancing
    mcclellan_osc: float = 0.0             # McClellan Oscillator
    mcclellan_summation: float = 0.0       # McClellan Summation Index
    trin: float = 1.0                       # TRIN / Arms Index
    new_highs: int = 0                      # 52-week new highs
    new_lows: int = 0                       # 52-week new lows
    breadth_thrust: float = 0.5            # Breadth Thrust

    # State
    breadth_state: str = "NEUTRAL"          # BROAD / NEUTRAL / NARROW
    alert_level: str = "NORMAL"             # NORMAL / WARNING / ALERT / CRITICAL

    # Sektörel breadth (opsiyonel)
    sector_breadth: Dict[str, float] = field(default_factory=dict)

    # Döviz izolasyonu
    fx_adjustment: float = 0.0  # Breadth'e uygulanan döviz düzeltmesi

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "advancing": self.advancing,
            "declining": self.declining,
            "unchanged": self.unchanged,
            "total": self.total,
            "ad_line": self.ad_line,
            "ad_ratio": round(self.ad_ratio, 4),
            "pct_advancing": round(self.pct_advancing, 2),
            "mcclellan_osc": round(self.mcclellan_osc, 2),
            "mcclellan_summation": round(self.mcclellan_summation, 2),
            "trin": round(self.trin, 4),
            "new_highs": self.new_highs,
            "new_lows": self.new_lows,
            "breadth_thrust": round(self.breadth_thrust, 4),
            "breadth_state": self.breadth_state,
            "alert_level": self.alert_level,
            "sector_breadth": self.sector_breadth,
            "fx_adjustment": self.fx_adjustment,
        }


class MarketBreadthEngine:
    """Market Breadth Engine — 7 gösterge + BIST-specific normalize.

    Kullanım:
        engine = MarketBreadthEngine()
        result = engine.compute(instrument_states, ad_history)
    """

    # BIST-specific: düşük likiditeli hisseler hariç tutulur
    DEFAULT_VOLUME_MIN = 10000  # Günlük minimum hacim

    def __init__(
        self,
        mcclellan_short_ema: int = 19,
        mcclellan_long_ema: int = 39,
        thrust_threshold: float = 0.615,
        volume_min: float = None,
    ):
        self._mcclellan_short = mcclellan_short_ema
        self._mcclellan_long = mcclellan_long_ema
        self._thrust_threshold = thrust_threshold
        self._volume_min = volume_min or self.DEFAULT_VOLUME_MIN

        # Cumulative state
        self._ad_line_cumulative = 0
        self._mcclellan_summation = 0.0
        self._net_advances_history: List[int] = []

    def compute(
        self,
        instrument_states: List[Dict],
        ad_history: Optional[List[int]] = None,
        new_highs: int = 0,
        new_lows: int = 0,
        sector_map: Optional[Dict[str, str]] = None,
        fx_momentum: float = 0.0,
    ) -> BreadthResult:
        """Tüm breadth göstergelerini hesapla.

        Args:
            instrument_states: Her hisse için state dict
                [{ticker, change_pct, volume, volume_avg, ...}]
            ad_history: Geçmiş net advances değerleri (McClellan için)
            new_highs: 52-week high yapan hisse sayısı
            new_lows: 52-week low yapan hisse sayısı
            sector_map: {ticker: sector_name} eşleştirmesi
            fx_momentum: Döviz momentum (USD/TRY) — breadth'den izole etmek için

        Returns:
            BreadthResult
        """
        # Düşük likiditeli hisseleri filtrele
        valid_states = [
            s for s in instrument_states
            if s.get("volume", 0) >= self._volume_min
        ]

        if not valid_states:
            logger.warning("No valid instruments for breadth calculation")
            return BreadthResult(timestamp=datetime.now(timezone.utc))

        # 1. Temel breadth
        advancing = sum(1 for s in valid_states if s.get("change_pct", 0) > 0)
        declining = sum(1 for s in valid_states if s.get("change_pct", 0) < 0)
        unchanged = len(valid_states) - advancing - declining
        total = len(valid_states)

        # 2. AD Line (cumulative)
        net_advances = advancing - declining
        self._ad_line_cumulative += net_advances
        ad_line = self._ad_line_cumulative

        # 3. AD Ratio
        ad_ratio = advancing / max(declining, 1)

        # 4. % Advancing
        pct_advancing = (advancing / total * 100) if total > 0 else 50.0

        # 5. McClellan Oscillator
        self._net_advances_history.append(net_advances)
        if len(self._net_advances_history) > 1000:
            self._net_advances_history = self._net_advances_history[-1000:]
        mcclellan_osc = self._compute_mcclellan()

        # 6. McClellan Summation Index
        self._mcclellan_summation += mcclellan_osc
        mcclellan_summation = self._mcclellan_summation

        # 7. TRIN / Arms Index
        trin = self._compute_trin(valid_states, advancing, declining)

        # 8. Breadth Thrust
        breadth_thrust = advancing / total if total > 0 else 0.5

        # 9. Breadth State
        breadth_state = self._determine_breadth_state(
            pct_advancing, mcclellan_osc, trin, breadth_thrust
        )

        # 10. Alert Level
        alert_level = self._determine_alert_level(
            pct_advancing, mcclellan_osc, trin, ad_ratio, breadth_thrust
        )

        # 11. Döviz izolasyonu — BIST-specific
        #     USD/TRY yükseldiğinde hisseler düşer ama bu gerçek bearishlik değil.
        #     Breadth'i döviz etkisine göre ayarla.
        fx_adjustment = 0.0
        if fx_momentum > 2.0:  # Döviz sert yükseliyor
            # Breadth'i %5-15 yukarı çek (döviz kaynaklı düşüşü filtrele)
            fx_adjustment = min(fx_momentum * 2.0, 15.0)
            pct_advancing = min(100.0, pct_advancing + fx_adjustment)
        elif fx_momentum < -2.0:  # Döviz sert düşüyor
            # Breadth'i %5-15 aşağı çek (döviz kaynaklı yükselişi filtrele)
            fx_adjustment = max(fx_momentum * 2.0, -15.0)
            pct_advancing = max(0.0, pct_advancing + fx_adjustment)

        # 12. Sektörel breadth
        sector_breadth = {}
        if sector_map:
            sector_breadth = self._compute_sector_breadth(valid_states, sector_map)

        result = BreadthResult(
            timestamp=datetime.now(timezone.utc),
            advancing=advancing,
            declining=declining,
            unchanged=unchanged,
            total=total,
            ad_line=ad_line,
            ad_ratio=round(ad_ratio, 4),
            pct_advancing=round(pct_advancing, 2),
            mcclellan_osc=round(mcclellan_osc, 2),
            mcclellan_summation=round(mcclellan_summation, 2),
            trin=round(trin, 4),
            new_highs=new_highs,
            new_lows=new_lows,
            breadth_thrust=round(breadth_thrust, 4),
            breadth_state=breadth_state,
            alert_level=alert_level,
            sector_breadth=sector_breadth,
            fx_adjustment=round(fx_adjustment, 2),
        )

        logger.info(
            "Breadth computed",
            advancing=advancing,
            declining=declining,
            pct_advancing=round(pct_advancing, 1),
            mcclellan=round(mcclellan_osc, 1),
            state=breadth_state,
            alert=alert_level,
        )

        return result

    def _compute_mcclellan(self) -> float:
        """McClellan Oscillator = EMA(19) of net advances - EMA(39) of net advances.

        EMA smoothing factor: 2 / (period + 1)
        """
        history = self._net_advances_history
        if len(history) < self._mcclellan_long:
            # Yeterli veri yoksa basit ortalama
            if len(history) == 0:
                return 0.0
            return float(np.mean(history[-min(len(history), self._mcclellan_short):]))

        # EMA hesapla
        short_ema = self._ema(history, self._mcclellan_short)
        long_ema = self._ema(history, self._mcclellan_long)

        return short_ema - long_ema

    def _ema(self, data: List[int], period: int) -> float:
        """Exponential Moving Average."""
        if len(data) < period:
            return float(np.mean(data))

        multiplier = 2.0 / (period + 1)
        ema = float(np.mean(data[:period]))  # İlk EMA = SMA

        for val in data[period:]:
            ema = (val - ema) * multiplier + ema

        return ema

    def _compute_trin(
        self,
        states: List[Dict],
        advancing: int,
        declining: int,
    ) -> float:
        """TRIN / Arms Index = (AD Ratio) / (Volume Ratio).

        TRIN < 1 → bullish (yükselen hacim güçlü)
        TRIN > 1 → bearish (düşen hacim güçlü)
        TRIN = 1 → nötr
        """
        advancing_vol = sum(
            s.get("volume", 0) for s in states if s.get("change_pct", 0) > 0
        )
        declining_vol = sum(
            s.get("volume", 0) for s in states if s.get("change_pct", 0) < 0
        )

        ad_ratio = advancing / max(declining, 1)
        vol_ratio = advancing_vol / max(declining_vol, 1)

        # TRIN = AD Ratio / Volume Ratio
        trin = ad_ratio / max(vol_ratio, 0.01)

        return trin

    def _determine_breadth_state(
        self,
        pct_advancing: float,
        mcclellan: float,
        trin: float,
        thrust: float,
    ) -> str:
        """Breadth state belirle — çoklu gösterge kombinasyonu.

        BROAD: Piyasa geniş katılımlı yükseliyor
        NEUTRAL: Normal
        NARROW: Az hisse yükseliyor (dar ralli)
        """
        # Strong breadth
        if pct_advancing > 65 and mcclellan > 30:
            return "BROAD"

        # Thrust signal
        if thrust > self._thrust_threshold:
            return "BROAD"

        # Weak breadth (en az 2 gösterge)
        narrow_signals = 0
        if pct_advancing < 35:
            narrow_signals += 1
        if mcclellan < -30:
            narrow_signals += 1
        if trin > 1.2:
            narrow_signals += 1

        if narrow_signals >= 2:
            return "NARROW"

        return "NEUTRAL"

    def _determine_alert_level(
        self,
        pct_advancing: float,
        mcclellan: float,
        trin: float,
        ad_ratio: float,
        thrust: float,
    ) -> str:
        """Alert level belirle — aşırı seviyeler için uyarı.

        CRITICAL: Aşırı seviye (crash/rally)
        ALERT: Belirgin sapma
        WARNING: Dikkat çekici seviye
        NORMAL: Normal
        """
        # Crash sinyali (en az 2 gösterge)
        crash_signals = 0
        if pct_advancing < 15:
            crash_signals += 1
        if trin > 2.0:
            crash_signals += 1
        if mcclellan < -60:
            crash_signals += 1
        if ad_ratio < 0.2:
            crash_signals += 1

        if crash_signals >= 2:
            return "CRITICAL"

        # Rally sinyali
        if pct_advancing > 85 and thrust > 0.75:
            return "CRITICAL"

        # Bearish alert
        if pct_advancing < 25 and mcclellan < -50:
            return "ALERT"

        # Bullish alert
        if pct_advancing > 75 and mcclellan > 50:
            return "ALERT"

        # Warning
        if pct_advancing < 30 or pct_advancing > 70:
            return "WARNING"

        if abs(mcclellan) > 40:
            return "WARNING"

        return "NORMAL"

    def _compute_sector_breadth(
        self,
        states: List[Dict],
        sector_map: Dict[str, str],
    ) -> Dict[str, float]:
        """Sektörel breadth hesapla — her sektör için % advancing."""
        sector_data: Dict[str, Dict] = {}

        for s in states:
            ticker = s.get("ticker", "")
            sector = sector_map.get(ticker, "UNKNOWN")
            if sector not in sector_data:
                sector_data[sector] = {"advancing": 0, "total": 0}
            sector_data[sector]["total"] += 1
            if s.get("change_pct", 0) > 0:
                sector_data[sector]["advancing"] += 1

        return {
            sector: round(d["advancing"] / max(d["total"], 1) * 100, 2)
            for sector, d in sector_data.items()
            if d["total"] > 0
        }

    def reset(self):
        """Cumulative state sıfırla (backtest için)."""
        self._ad_line_cumulative = 0
        self._mcclellan_summation = 0.0
        self._net_advances_history = []
