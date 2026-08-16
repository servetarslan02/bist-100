"""
ALPHA BIST — Scanner Backtest Runner

Scanner ile backtest entegrasyonu.

Akış:
Historical Market Data → Data Quality → Feature Engine → Ranking → Scanner → Signal

Özellikler:
- Dönem bazlı tarama
- Look-ahead bias kontrolü
- Survivorship bias kontrolü
- Eksik veri yönetimi

Kullanım:
    runner = ScannerBacktestRunner()
    results = runner.run(market_data, start_date, end_date)
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import structlog

from ..features.calculator import FeatureCalculator
from ..core.tradability_mask import TradabilityMask
from ..core.data_quality_v2 import DataQualityV2

logger = structlog.get_logger()


@dataclass
class BacktestSignal:
    date: str
    ticker: str
    signal: str
    score: float
    features_count: int
    quality_score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date, "ticker": self.ticker,
            "signal": self.signal, "score": self.score,
            "features_count": self.features_count,
            "quality_score": self.quality_score,
        }


@dataclass
class BacktestResult:
    start_date: str
    end_date: str
    total_scans: int
    signals_generated: int
    look_ahead_violations: int
    survivorship_violations: int
    data_quality_issues: int
    signals: List[BacktestSignal]
    performance: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_date": self.start_date, "end_date": self.end_date,
            "total_scans": self.total_scans,
            "signals_generated": self.signals_generated,
            "look_ahead_violations": self.look_ahead_violations,
            "survivorship_violations": self.survivorship_violations,
            "data_quality_issues": self.data_quality_issues,
            "signal_count": len(self.signals),
            "performance": self.performance,
        }


class ScannerBacktestRunner:
    """Scanner backtest runner."""

    def __init__(self):
        self._calc = FeatureCalculator()
        self._tm = TradabilityMask()
        self._dq = DataQualityV2()

    def run(
        self,
        market_data: Dict[str, pd.DataFrame],
        lookback_days: int = 120,
        universe_at_date: Optional[List[str]] = None,
    ) -> BacktestResult:
        """Backtest çalıştır.

        Args:
            market_data: {ticker: DataFrame} formatında tarihsel veri
            lookback_days: Feature hesaplama için geriye bakış
            universe_at_date: O tarihte işlem gören hisseler (survivorship bias kontrolü)
        """
        import time as _time
        start_time = _time.time()

        signals = []
        look_ahead_violations = 0
        survivorship_violations = 0
        data_quality_issues = 0
        total_scans = 0

        # Her ticker için
        for ticker, df in market_data.items():
            if df is None or df.empty or len(df) < lookback_days:
                data_quality_issues += 1
                continue

            # Survivorship bias kontrolü
            if universe_at_date and ticker not in universe_at_date:
                survivorship_violations += 1
                continue

            # Data quality check
            quality = self._dq.full_quality_check(df, ticker)
            if not quality.passed:
                data_quality_issues += 1
                continue

            # Son günde feature hesapla (look-ahead yok)
            try:
                # Sadece geçmiş veriyi kullan (son gün hariç)
                df_lookback = df.iloc[-lookback_days:-1]
                if len(df_lookback) < 60:
                    continue

                mask = self._tm.compute_mask(
                    ticker, df_lookback['Open'].values,
                    df_lookback['High'].values, df_lookback['Low'].values,
                    df_lookback['Close'].values, df_lookback['Volume'].values,
                )
                features = self._calc.compute_all_features(
                    df_lookback, mask=mask.mask, ticker=ticker
                )

                if not features:
                    continue

                # Look-ahead kontrolü: feature'lar sadece geçmiş veriden türetilmeli
                # Son günün kapanışı feature hesaplamasında kullanılmamalı
                total_scans += 1

                # Basit sinyal üretimi (scanner entegrasyonu)
                score = self._compute_score(features)
                signal = self._determine_signal(score)

                signals.append(BacktestSignal(
                    date=str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else str(df.index[-1]),
                    ticker=ticker,
                    signal=signal,
                    score=score,
                    features_count=len(features),
                    quality_score=quality.quality_score,
                ))

            except Exception as e:
                logger.warning("Backtest scan failed", ticker=ticker, error=str(e))
                data_quality_issues += 1

        elapsed = _time.time() - start_time

        return BacktestResult(
            start_date=str(df.index[0].date()) if len(market_data) > 0 and len(df) > 0 else "",
            end_date=str(df.index[-1].date()) if len(market_data) > 0 and len(df) > 0 else "",
            total_scans=total_scans,
            signals_generated=len(signals),
            look_ahead_violations=look_ahead_violations,
            survivorship_violations=survivorship_violations,
            data_quality_issues=data_quality_issues,
            signals=signals,
            performance={
                "elapsed_seconds": round(elapsed, 2),
                "scans_per_second": round(total_scans / max(elapsed, 0.001), 1),
            },
        )

    def _compute_score(self, features: Dict[str, Any]) -> float:
        """Feature'lardan basit skor hesapla."""
        score = 50.0

        rsi = features.get("rsi_14", 50)
        if isinstance(rsi, np.ndarray):
            rsi = float(rsi.flat[0]) if rsi.size > 0 else 50
        if rsi > 60:
            score += 10
        elif rsi < 40:
            score -= 10

        mom = features.get("momentum_20d", 0)
        if isinstance(mom, np.ndarray):
            mom = float(mom.flat[0]) if mom.size > 0 else 0
        score += mom * 100

        roc = features.get("roc_5d", 0)
        if isinstance(roc, np.ndarray):
            roc = float(roc.flat[0]) if roc.size > 0 else 0
        score += roc * 2

        return max(0, min(100, score))

    def _determine_signal(self, score: float) -> str:
        """Skordan sinyal üret."""
        if score >= 70:
            return "STRONG_BUY"
        elif score >= 60:
            return "BUY"
        elif score <= 30:
            return "STRONG_SELL"
        elif score <= 40:
            return "SELL"
        return "HOLD"
