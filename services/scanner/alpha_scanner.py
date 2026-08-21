"""
ALPHA BIST — Alpha Scanner v1.0

Tek merkezi pipeline:
800 hisse → data → canonical bars → incremental features →
market regime → quant scan → opportunity score → rank → signals

Bu, ALPHA'nın kalbidir.
"""

import time
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

from .scanner_interface import ScannerInterface, ScanResult

logger = structlog.get_logger()


# =====================================================
# Signal Types
# =====================================================

class SignalType:
    MOMENTUM = "MOMENTUM"          # Güçlü yükseliş devamı
    BREAKOUT = "BREAKOUT"          # Sıkışma → kırılım
    VOLUME_ANOMALY = "VOLUME_ANOMALY"  # Olağandışı hacim
    ACCUMULATION = "ACCUMULATION"  # Fiyat sakin ama hacim/flow değişiyor
    EVENT = "EVENT"                # KAP/haber kaynaklı
    MACRO_IMPACT = "MACRO_IMPACT"  # Dünya/makro etkisi
    REGIME = "REGIME"              # Rejim avantajı
    SPEC = "SPEC"                  # Normal modellerin yakalayamadığı anomali
    REVERSAL = "REVERSAL"          # Aşırı hareket sonrası dönüş


# =====================================================
# Scanner Result
# =====================================================

@dataclass
class ScannerResult:
    """Tek hisse için scanner sonucu."""
    ticker: str
    timestamp: datetime

    # Tier 0 — State
    price: float = 0.0
    change_1d_pct: float = 0.0
    volume: int = 0
    volume_ratio: float = 0.0

    # Tier 1 — Quant features
    rsi: float = 50.0
    macd: float = 0.0
    roc_5d: float = 0.0
    roc_20d: float = 0.0
    trend_slope: float = 0.0
    relative_strength: float = 0.0
    volume_zscore: float = 0.0
    volume_acceleration: float = 0.0
    volatility: float = 0.0
    atr_pct: float = 0.0
    bb_position: float = 0.5
    breakout_score: float = 0.0
    sector_strength: float = 0.0
    market_regime_fit: float = 0.0

    # Opportunity score
    opportunity_score: float = 0.0
    opportunity_rank: int = 0

    # Signal
    signal_type: str = ""
    signal_score: float = 0.0
    signal_direction: str = ""
    signal_confidence: float = 0.0

    # Evidence
    evidence: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)


# =====================================================
# Alpha Scanner
# =====================================================

class AlphaScanner(ScannerInterface):
    """
    ALPHA'nın merkezi tarama motoru.

    800 hisseyi tarar, fırsatları bulur, sinyal üretir.
    ScannerInterface implementasyonu — backtest ile aynı kod yolunu kullanır.
    """

    def __init__(self):
        self._last_scan: Optional[datetime] = None
        self._scan_count: int = 0
        self._regime: str = "RANGE"
        self._regime_confidence: float = 0.5

    def scan(
        self,
        universe: List[str],
        features_map: Dict[str, Dict[str, float]],
        market_regime: str = "RANGE",
        regime_confidence: float = 0.5,
        ml_scores: Optional[Dict[str, float]] = None,
        event_scores: Optional[Dict[str, float]] = None,
    ) -> List[ScannerResult]:
        """
        Tüm BIST'i tara → sonuçları döndür.

        Pipeline:
        1. Tier 0: State (zaten features_map'te var)
        2. Tier 1: Quant scan (her hisse için skor)
        3. Tier 2: Opportunity ranking (sıralama)
        4. Tier 3: Signal generation (tür + skor)
        """
        self._regime = market_regime
        self._regime_confidence = regime_confidence
        start = time.time()

        results = []

        # Tier 1: Her hisse için quant scan
        for ticker in universe:
            features = features_map.get(ticker)
            if not features:
                continue

            ml = (ml_scores or {}).get(ticker, 50.0)
            evt = (event_scores or {}).get(ticker, 50.0)
            result = self._scan_single(ticker, features, ml, evt)
            results.append(result)

        # Tier 2: Opportunity ranking
        results.sort(key=lambda r: r.opportunity_score, reverse=True)
        for i, r in enumerate(results):
            r.opportunity_rank = i + 1

        # Tier 3: Signal generation (sadece top 50)
        for r in results[:50]:
            self._generate_signal(r)

        elapsed = time.time() - start
        self._last_scan = datetime.now(timezone.utc)
        self._scan_count += 1

        logger.info("Alpha scan completed",
                    stocks=len(results),
                    elapsed=f"{elapsed:.1f}s",
                    regime=market_regime,
                    scan_count=self._scan_count)

        return results

    def _scan_single(self, ticker: str, f: Dict[str, float], ml_score: float = 50.0, event_score: float = 50.0) -> ScannerResult:
        """Tek hisse için quant scan."""
        r = ScannerResult(ticker=ticker, timestamp=datetime.now(timezone.utc))

        # State
        r.price = f.get("price", 0) or f.get("close", 0) or f.get("current_price", 0)
        r.change_1d_pct = f.get("return_1d", 0)
        r.volume = int(f.get("volume", 0))
        r.volume_ratio = f.get("volume_ratio_20d", 1.0)

        # Quant features
        r.rsi = f.get("rsi_14", 50)
        r.macd = f.get("macd", 0)
        r.roc_5d = f.get("roc_5d", 0)
        r.roc_20d = f.get("momentum_20d", 0) or f.get("roc_20d", 0)
        r.trend_slope = f.get("trend_slope_20d", 0)
        r.relative_strength = f.get("price_vs_sma20", 0)
        r.volume_zscore = f.get("volume_zscore", 0)
        r.volatility = f.get("realized_vol_20d", 0)
        r.atr_pct = f.get("atr_pct", f.get("atr_14_pct", 0))
        r.bb_position = f.get("bb_position", 0.5)
        r.sector_strength = f.get("sector_momentum", 0) or f.get("relative_strength_vs_sector", 0)

        # Derived scores
        r.breakout_score = self._calc_breakout(f)
        r.volume_acceleration = self._calc_volume_acceleration(f)
        r.market_regime_fit = self._calc_regime_fit(f)

        # Opportunity score (ML ve event skorları dahil)
        r.opportunity_score = self._calc_opportunity_score(r, ml_score, event_score)

        return r

    def _calc_breakout(self, f: Dict) -> float:
        """Kırılım skoru."""
        bb_pos = f.get("bb_position", 0.5)
        near_high = f.get("near_20d_high", 0)
        vol_z = f.get("volume_zscore", 0)

        score = 0
        if bb_pos > 0.95:
            score += 30
        elif bb_pos > 0.85:
            score += 15
        if near_high:
            score += 25
        if vol_z > 1.5:
            score += 20
        if f.get("trend_slope_20d", 0) > 0:
            score += 15

        return min(100, score)

    def _calc_volume_acceleration(self, f: Dict) -> float:
        """Hacim ivmesi."""
        vol_z = f.get("volume_zscore", 0)
        vol_ratio = f.get("volume_ratio_20d", 1)
        return (vol_z * 30 + (vol_ratio - 1) * 20)

    def _calc_regime_fit(self, f: Dict) -> float:
        """Rejim uyumu."""
        regime = self._regime
        mom = f.get("momentum_20d", 0) or f.get("roc_20d", 0)
        vol = f.get("realized_vol_20d", 20)

        if regime in ["TRENDING-UP", "MOMENTUM-EXPANSION"]:
            if mom > 5:
                return 80
            elif mom > 0:
                return 60
            else:
                return 30
        elif regime in ["RISK-OFF", "PANIC"]:
            if vol < 20:
                return 70
            else:
                return 30
        elif regime == "RANGE":
            bb = f.get("bb_position", 0.5)
            if bb < 0.2 or bb > 0.8:
                return 70
            else:
                return 50
        return 50

    def _calc_opportunity_score(self, r: ScannerResult, ml_score: float = 50.0, event_score: float = 50.0) -> float:
        """
        Opportunity Score = ağırlıklı toplam.

        20% momentum
        15% relative_strength
        15% volume_anomaly
        10% breakout
        10% volatility_structure
        10% market_regime_fit
        10% event_impact (ML + haber + KAP etkisi)
        10% ML_probability (model tahmin skoru)
        """
        # Momentum skoru (0-100)
        mom_score = 50
        if r.roc_5d > 3:
            mom_score += min(r.roc_5d * 5, 30)
        elif r.roc_5d < -3:
            mom_score += max(r.roc_5d * 5, -30)
        if r.roc_20d > 5:
            mom_score += min(r.roc_20d * 2, 20)
        mom_score = max(0, min(100, mom_score))

        # Relative strength skoru
        rs_score = 50 + min(r.relative_strength * 5, 50)
        rs_score = max(0, min(100, rs_score))

        # Volume anomaly skoru
        vol_score = 50
        if r.volume_zscore > 2:
            vol_score += min(r.volume_zscore * 15, 40)
        elif r.volume_zscore < -1:
            vol_score += max(r.volume_zscore * 10, -30)
        vol_score = max(0, min(100, vol_score))

        # Breakout skoru
        brk_score = r.breakout_score

        # Volatility structure
        vol_struct = 50
        if r.volatility > 0:
            if r.atr_pct < 2:
                vol_struct = 70
            elif r.atr_pct > 5:
                vol_struct = 40

        # Regime fit
        regime_score = r.market_regime_fit

        # Ağırlıklı toplam (ML ve event artık gerçek skor)
        score = (
            mom_score * 0.20
            + rs_score * 0.15
            + vol_score * 0.15
            + brk_score * 0.10
            + vol_struct * 0.10
            + regime_score * 0.10
            + event_score * 0.10
            + ml_score * 0.10
        )

        return round(float(max(0, min(100, score))), 1)

    def _generate_signal(self, r: ScannerResult):
        """Sinyal üret."""
        score = r.opportunity_score

        if score < 50:
            return

        # Sinyal türü belirle
        if r.volume_zscore > 3 and r.roc_5d > 3:
            r.signal_type = SignalType.MOMENTUM
            r.signal_score = score
        elif r.breakout_score > 70 and r.volume_zscore > 2:
            r.signal_type = SignalType.BREAKOUT
            r.signal_score = score
        elif r.volume_zscore > 3 and abs(r.roc_5d) < 2:
            r.signal_type = SignalType.ACCUMULATION
            r.signal_score = score
        elif r.volume_zscore > 4:
            r.signal_type = SignalType.VOLUME_ANOMALY
            r.signal_score = score
        elif r.rsi < 25 and r.roc_20d < -10:
            r.signal_type = SignalType.REVERSAL
            r.signal_score = score
            r.signal_direction = "LONG"  # Dip dönüş → LONG
        elif r.market_regime_fit > 70:
            r.signal_type = SignalType.REGIME
            r.signal_score = score
        else:
            # SPEC = residual anomaly (diğer modellerin açıklayamadığı)
            # Kriterler: volume anomaly + fiyat sapması + cross-sectional deviation
            if (r.volume_zscore > 2.0
                and abs(r.roc_5d) > 2.0
                and r.breakout_score < 50  # Breakout değil
                and r.market_regime_fit < 60):  # Regime uyumu düşük
                r.signal_type = SignalType.SPEC
                r.signal_score = score
            else:
                # SPEC kriterleri karşılanmadı — sinyal üretme
                return

        # Yön — sinyal türüne göre akıllı belirleme
        if r.signal_type == SignalType.REVERSAL:
            # Reversal: düşüş sonrası LONG (dip dönüş) — trigger ile aynı eşik
            r.signal_direction = "LONG" if r.rsi < 25 else "SHORT"
        elif r.signal_type == SignalType.ACCUMULATION:
            # Accumulation: genellikle LONG
            r.signal_direction = "LONG"
        elif r.signal_type == SignalType.EVENT:
            # Event: sentiment'e göre
            r.signal_direction = "LONG"  # Varsayılan, event analizi belirler
        else:
            # Diğer: momentum'a göre
            r.signal_direction = "LONG" if r.roc_20d > 0 else "SHORT"

        # Confidence
        r.signal_confidence = min(score / 100, 0.95)

        # Evidence
        if r.volume_zscore > 2:
            r.evidence.append(f"Hacim anomalisi: {r.volume_zscore:.1f}σ")
        if r.roc_5d > 3:
            r.evidence.append(f"Güçlü momentum: +{r.roc_5d:.1f}%")
        if r.breakout_score > 60:
            r.evidence.append(f"Kırılım skoru: {r.breakout_score:.0f}")
        if r.market_regime_fit > 60:
            r.evidence.append(f"Rejim uyumu: {r.market_regime_fit:.0f}")

        # Risks
        if r.volatility > 30:
            r.risks.append(f"Yüksek volatilite: %{r.volatility:.0f}")
        if r.rsi > 75:
            r.risks.append(f"Aşırı alım: RSI={r.rsi:.0f}")

    # =====================================================
    # ScannerInterface Implementation
    # =====================================================

    def get_opportunities(
        self,
        results: List[ScannerResult],
        top_n: int = 50,
        min_score: float = 50.0,
    ) -> List[ScannerResult]:
        """En iyi fırsatları seç."""
        filtered = [r for r in results if r.opportunity_score >= min_score]
        filtered.sort(key=lambda r: r.opportunity_score, reverse=True)
        return filtered[:top_n]

    def generate_signals(
        self,
        results: List[ScannerResult],
    ) -> List[ScannerResult]:
        """Sinyal üret — ScannerInterface implementasyonu."""
        for r in results:
            self._generate_signal(r)
        return [r for r in results if r.signal_type]

    def to_scan_results(self, results: List[ScannerResult]) -> List[ScanResult]:
        """ScannerResult'ları standart ScanResult formatına çevir."""
        scan_results = []
        for r in results:
            sr = ScanResult(
                ticker=r.ticker,
                timestamp=r.timestamp,
                price=r.price,
                change_1d_pct=r.change_1d_pct,
                volume=r.volume,
                opportunity_score=r.opportunity_score,
                risk_adjusted_score=r.opportunity_score,  # AlphaScanner'da aynı
                opportunity_rank=r.opportunity_rank,
                signal_type=r.signal_type,
                signal_direction=r.signal_direction,
                signal_score=r.signal_score,
                signal_confidence=r.signal_confidence,
                momentum_score=r.roc_5d * 10 + 50,  # Normalize
                volume_anomaly_score=r.volume_zscore * 15 + 50,
                breakout_score=r.breakout_score,
                volatility_score=r.volatility,
                relative_strength_score=r.relative_strength * 10 + 50,
                technical_score=r.rsi,
                regime_fit_score=r.market_regime_fit,
                ml_score=0,
                event_score=0,
                evidence=r.evidence,
                risks=r.risks,
            )
            scan_results.append(sr)
        return scan_results

    def get_summary(self, results: List[ScannerResult]) -> Dict:
        """Tarama özeti."""
        signals = [r for r in results if r.signal_score > 0]
        anomalies = [r for r in results if r.volume_zscore > 2.5]
        oversold = [r for r in results if r.rsi < 30]
        overbought = [r for r in results if r.rsi > 70]

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "regime": self._regime,
            "total_scanned": len(results),
            "signals_generated": len(signals),
            "anomalies": len(anomalies),
            "oversold": len(oversold),
            "overbought": len(overbought),
            "top_opportunities": [
                {
                    "ticker": r.ticker,
                    "score": r.opportunity_score,
                    "signal": r.signal_type,
                    "direction": r.signal_direction,
                    "confidence": r.signal_confidence,
                    "price": r.price,
                    "rsi": r.rsi,
                    "momentum_5d": r.roc_5d,
                    "volume_zscore": r.volume_zscore,
                }
                for r in results[:20]
            ],
            "top_signals": [
                {
                    "ticker": r.ticker,
                    "type": r.signal_type,
                    "score": r.signal_score,
                    "direction": r.signal_direction,
                    "confidence": r.signal_confidence,
                    "evidence": r.evidence,
                    "risks": r.risks,
                }
                for r in sorted(signals, key=lambda x: x.signal_score, reverse=True)[:10]
            ],
        }


# Singleton
alpha_scanner = AlphaScanner()
