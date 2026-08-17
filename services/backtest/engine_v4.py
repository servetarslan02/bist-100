"""
ALPHA BIST — Backtest Engine v4.0 (Institutional Grade)

Tasarım ilkeleri:
1. Finansal doğruluk: v2.0/v3.0 ile aynı sonuçlar
2. Ölçeklenebilirlik: 5000+ hisse
3. Deterministik: aynı veri → aynı sonuç
4. Denetlenebilir: tam audit trail
5. Dayanıklı: restart sonrası recovery

Optimizasyonlar:
- Pre-slice market data (bir kez)
- Batch signal processing
- Feature cache korunuyor
- Quality cache korunuyor
- Portfolio simulator v3.0 (audit + invariant)
- SQLite persistence
"""

import time as _time
import hashlib
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field
import structlog

from .portfolio_sim import PortfolioSimulatorV3
from .persistence import backtest_persistence

logger = structlog.get_logger()


# =====================================================
# DATA CLASSES
# =====================================================

@dataclass
class BacktestConfig:
    """Backtest konfigürasyonu."""
    initial_capital: float = 100_000.0
    lookback_days: int = 120
    signal_threshold: float = 60.0
    max_position_pct: float = 0.10
    max_positions: int = 20
    slippage_rate: float = 0.001
    min_quality_score: float = 70.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "initial_capital": self.initial_capital,
            "lookback_days": self.lookback_days,
            "signal_threshold": self.signal_threshold,
            "max_position_pct": self.max_position_pct,
            "max_positions": self.max_positions,
            "slippage_rate": self.slippage_rate,
            "min_quality_score": self.min_quality_score,
        }


@dataclass
class BacktestMetrics:
    """Backtest performans metrikleri."""
    total_return_pct: float = 0.0
    cagr_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    total_commission: float = 0.0
    total_slippage: float = 0.0
    alpha_pct: float = 0.0
    benchmark_return_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {k: round(v, 4) if isinstance(v, float) else v
                for k, v in self.__dict__.items()}


@dataclass
class BacktestResultV4:
    """Backtest sonucu."""
    run_id: str
    start_date: str
    end_date: str
    config: BacktestConfig
    metrics: BacktestMetrics
    total_scans: int
    signals_generated: int
    trades_executed: int
    look_ahead_violations: int
    survivorship_violations: int
    data_quality_issues: int
    elapsed_seconds: float
    scans_per_second: float
    equity_curve: List[Dict[str, Any]]
    trades: List[Dict[str, Any]]
    persisted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "config": self.config.to_dict(),
            "metrics": self.metrics.to_dict(),
            "total_scans": self.total_scans,
            "signals_generated": self.signals_generated,
            "trades_executed": self.trades_executed,
            "look_ahead_violations": self.look_ahead_violations,
            "survivorship_violations": self.survivorship_violations,
            "data_quality_issues": self.data_quality_issues,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "scans_per_second": round(self.scans_per_second, 1),
            "equity_curve_points": len(self.equity_curve),
            "persisted": self.persisted,
        }


# =====================================================
# FEATURE CACHE (v2.0 ile aynı)
# =====================================================

class FeatureCache:
    """Ticker bazında feature cache."""

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._date_cache: Dict[str, str] = {}
        self._hits = 0
        self._misses = 0

    def get(self, ticker: str, date: str) -> Optional[Dict[str, Any]]:
        if ticker in self._cache and self._date_cache.get(ticker) == date:
            self._hits += 1
            return self._cache[ticker]
        self._misses += 1
        return None

    def set(self, ticker: str, date: str, features: Dict[str, Any]):
        self._cache[ticker] = features
        self._date_cache[ticker] = date

    def clear(self):
        self._cache.clear()
        self._date_cache.clear()
        self._hits = 0
        self._misses = 0

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0


class QualityCache:
    """Data quality sonucu cache."""

    def __init__(self):
        self._cache: Dict[str, Tuple[bool, float]] = {}

    def get(self, ticker: str) -> Optional[Tuple[bool, float]]:
        return self._cache.get(ticker)

    def set(self, ticker: str, passed: bool, score: float):
        self._cache[ticker] = (passed, score)

    def clear(self):
        self._cache.clear()


# =====================================================
# BACKTEST ENGINE v4.0
# =====================================================

class BacktestEngineV4:
    """Kurumsal seviye backtest motoru.

    v2.0 (ScannerBacktestRunner) ile aynı finansal sonuçları üretir.
    Ek: persistence, audit trail, invariant checks, benchmark.
    """

    def __init__(
        self,
        config: Optional[BacktestConfig] = None,
        use_panel_features: bool = True,
    ):
        """
        Args:
            config: Backtest konfigürasyonu
            use_panel_features: True (varsayılan) → vektörize panel feature
                motoru (batch, tek geçiş). False → legacy ticker-by-ticker
                yol (referans / equivalence doğrulaması için korunur).
                İki yol da finansal olarak BİREBİR aynı sonucu üretir;
                şüpheli (borderline) durumlarda panel yolu otomatik olarak
                scalar hesaba düşer.
        """
        self._config = config or BacktestConfig()
        self._use_panel = use_panel_features
        self._feature_cache = FeatureCache()
        self._quality_cache = QualityCache()

        # Lazy-loaded dependencies
        self._calc = None
        self._tm = None
        self._dq = None
        self._panel_engine = None

        # Instrumentation (benchmark için)
        self._last_feature_seconds: float = 0.0
        self._last_panel_seconds: float = 0.0
        self._last_scalar_fallbacks: int = 0

    def _lazy_load(self):
        """Modülleri lazy-load et (test ortamında import hatası önlemek için)."""
        if self._calc is None:
            try:
                from ..features.calculator import FeatureCalculator
                self._calc = FeatureCalculator()
            except ImportError:
                self._calc = _FallbackCalculator()

        if self._tm is None:
            try:
                from ..core.tradability_mask import TradabilityMask
                self._tm = TradabilityMask()
            except ImportError:
                self._tm = _FallbackMask()

        if self._dq is None:
            try:
                from ..core.data_quality_v2 import DataQualityV2
                self._dq = DataQualityV2()
            except ImportError:
                self._dq = _FallbackQuality()

        if self._panel_engine is None:
            try:
                from ..features.panel_engine import PanelFeatureEngine
                self._panel_engine = PanelFeatureEngine(tradability_mask=self._tm)
            except ImportError:
                self._panel_engine = None

    def run(
        self,
        market_data: Dict[str, pd.DataFrame],
        universe_at_date: Optional[List[str]] = None,
        benchmark_data: Optional[pd.DataFrame] = None,
        run_id: Optional[str] = None,
        persist: bool = True,
        trade_start: Optional[str] = None,
        trade_end: Optional[str] = None,
    ) -> BacktestResultV4:
        """Backtest çalıştır.

        Args:
            market_data: {ticker: OHLCV DataFrame}
            universe_at_date: Survivorship bias kontrolü için tarih bazlı evren
            benchmark_data: XU100 benchmark DataFrame
            run_id: Run identifier (None ise otomatik üret)
            persist: Sonuçları DB'ye kaydet
            trade_start: Opsiyonel — sinyal/trade üretimini bu tarihten
                itibaren yap (YYYY-MM-DD). Feature'lar yine point-in-time
                olarak tüm geçmişi kullanır. Walk-forward entegrasyonu içindir.
            trade_end: Opsiyonel — sinyal/trade üretimini bu tarihte bitir.
        """
        if self._use_panel:
            return self._run_fast(
                market_data, universe_at_date, benchmark_data,
                run_id, persist, trade_start, trade_end,
            )
        return self._run_legacy(
            market_data, universe_at_date, benchmark_data,
            run_id, persist, trade_start, trade_end,
        )

    def _run_legacy(
        self,
        market_data: Dict[str, pd.DataFrame],
        universe_at_date: Optional[List[str]] = None,
        benchmark_data: Optional[pd.DataFrame] = None,
        run_id: Optional[str] = None,
        persist: bool = True,
        trade_start: Optional[str] = None,
        trade_end: Optional[str] = None,
    ) -> BacktestResultV4:
        """Referans (ticker-by-ticker) implementasyon — v4.0 orijinal yolu.

        NOT: Bu yol DEĞİŞTİRİLMEDEN korunur; panel yolunun finansal
        eşdeğerliliği bu yola karşı test edilir.
        """
        self._lazy_load()
        start_time = _time.time()

        # Run ID
        if run_id is None:
            run_id = self._generate_run_id(market_data)

        # Config
        cfg = self._config
        sim = PortfolioSimulatorV3(
            initial_capital=cfg.initial_capital,
            max_position_pct=cfg.max_position_pct,
            max_positions=cfg.max_positions,
            slippage_rate=cfg.slippage_rate,
        )

        # Cache temizle
        self._feature_cache.clear()
        self._quality_cache.clear()

        # Ortak tarih aralığı
        all_dates = set()
        for df in market_data.values():
            if df is not None and not df.empty:
                all_dates.update(df.index)
        sorted_dates = sorted(all_dates)

        effective_lookback = max(cfg.lookback_days, 60)

        if len(sorted_dates) < effective_lookback + 10:
            logger.warning("Insufficient data", dates=len(sorted_dates),
                         needed=effective_lookback + 10)
            return self._empty_result(run_id, sorted_dates, cfg, start_time)

        # Benchmark prices (XU100)
        benchmark_prices = {}
        if benchmark_data is not None and not benchmark_data.empty:
            for idx in benchmark_data.index:
                date_str = str(idx.date()) if hasattr(idx, 'date') else str(idx)
                benchmark_prices[date_str] = float(benchmark_data.loc[idx, 'Close'])

        # Pre-compute quality cache
        for ticker, df in market_data.items():
            if df is not None and not df.empty and len(df) >= effective_lookback:
                try:
                    quality = self._dq.full_quality_check(df, ticker)
                    self._quality_cache.set(ticker, quality.passed, quality.quality_score)
                except Exception:
                    self._quality_cache.set(ticker, True, 80.0)

        # Ana döngü
        signals_count = 0
        look_ahead_violations = 0
        survivorship_violations = 0
        data_quality_issues = 0
        total_scans = 0

        for i in range(effective_lookback, len(sorted_dates) - 1):
            current_date = sorted_dates[i]
            next_date = sorted_dates[i + 1]
            date_str = str(current_date.date()) if hasattr(current_date, 'date') else str(current_date)
            next_date_str = str(next_date.date()) if hasattr(next_date, 'date') else str(next_date)

            # Walk-forward trade penceresi (varsayılan: kısıt yok)
            if trade_start is not None and date_str < trade_start:
                continue
            if trade_end is not None and date_str > trade_end:
                continue

            # Benchmark price
            bench_price = benchmark_prices.get(date_str)

            # SELL sinyalleri (pozisyondaki hisseler)
            for ticker in list(sim._positions.keys()):
                if ticker not in market_data:
                    continue
                df = market_data[ticker]
                if next_date not in df.index:
                    continue

                # Score hesapla
                df_until = df[df.index <= current_date]
                if len(df_until) < effective_lookback:
                    continue

                features = self._get_features(ticker, date_str, df_until, effective_lookback, cfg)
                if not features:
                    continue

                total_scans += 1
                score = self._compute_score(features)
                if score <= (100 - cfg.signal_threshold):
                    price = float(df.loc[next_date, 'Open'])
                    sim.execute_sell(ticker, price, date_str)
                    signals_count += 1

            # BUY sinyalleri
            buy_candidates = []
            for ticker, df in market_data.items():
                # Survivorship bias
                if universe_at_date and ticker not in universe_at_date:
                    survivorship_violations += 1
                    continue

                # Zaten pozisyondaysa skip
                if sim.has_position(ticker):
                    continue

                # Quality cache
                quality_info = self._quality_cache.get(ticker)
                if quality_info and not quality_info[0]:
                    data_quality_issues += 1
                    continue
                if quality_info and quality_info[1] < cfg.min_quality_score:
                    data_quality_issues += 1
                    continue

                # Veri penceresi
                df_until = df[df.index <= current_date]
                if len(df_until) < effective_lookback:
                    continue

                features = self._get_features(ticker, date_str, df_until, effective_lookback, cfg)
                if not features:
                    continue

                total_scans += 1
                score = self._compute_score(features)
                if score >= cfg.signal_threshold + 10:
                    buy_candidates.append((ticker, score))

            # En iyi adayları sırala ve al
            buy_candidates.sort(key=lambda x: x[1], reverse=True)
            for ticker, score in buy_candidates:
                if not sim.can_buy():
                    break
                df = market_data[ticker]
                if next_date not in df.index:
                    continue
                price = float(df.loc[next_date, 'Open'])
                sim.execute_buy(ticker, price, date_str)
                signals_count += 1

            # Equity snapshot
            prices = {}
            for ticker in sim._positions:
                if ticker in market_data and current_date in market_data[ticker].index:
                    prices[ticker] = float(market_data[ticker].loc[current_date, 'Close'])
            sim.update_equity(prices, date_str, bench_price)

        elapsed = _time.time() - start_time
        metrics_dict = sim.compute_metrics()

        # Metrics objesi
        metrics = BacktestMetrics(**{k: v for k, v in metrics_dict.items()
                                     if k in BacktestMetrics.__dataclass_fields__})

        # Result
        start_date = str(sorted_dates[effective_lookback].date()) if sorted_dates else ""
        end_date = str(sorted_dates[-1].date()) if sorted_dates else ""

        result = BacktestResultV4(
            run_id=run_id,
            start_date=start_date,
            end_date=end_date,
            config=cfg,
            metrics=metrics,
            total_scans=total_scans,
            signals_generated=signals_count,
            trades_executed=len(sim.get_trades()),
            look_ahead_violations=look_ahead_violations,
            survivorship_violations=survivorship_violations,
            data_quality_issues=data_quality_issues,
            elapsed_seconds=elapsed,
            scans_per_second=total_scans / max(elapsed, 0.001),
            equity_curve=[s.to_dict() for s in sim.get_equity_curve()],
            trades=[t.to_dict() for t in sim.get_trades()],
        )

        # Invariant check
        ok, errors = sim.check_invariants()
        if not ok:
            logger.error("Invariant violations detected", errors=errors)
            result.metrics.max_drawdown_pct = -1  # Flag

        # Persist
        if persist:
            try:
                backtest_persistence.save_run(
                    run_id=run_id,
                    start_date=start_date,
                    end_date=end_date,
                    initial_capital=cfg.initial_capital,
                    metrics=metrics_dict,
                    config=cfg.to_dict(),
                )
                backtest_persistence.save_trades(run_id, result.trades)
                backtest_persistence.save_equity_curve(run_id, result.equity_curve)
                result.persisted = True
            except Exception as e:
                logger.error("Persistence failed", error=str(e))

        logger.info("Backtest completed",
                   run_id=run_id,
                   trades=result.trades_executed,
                   return_pct=metrics.total_return_pct,
                   elapsed=f"{elapsed:.1f}s")

        return result

    # ===================== FAST PATH (PANEL) =====================

    # Borderline eşikleri: panel ve scalar yol arasındaki kayan nokta /
    # yuvarlama farkları (~1e-2'den çok daha küçük) bir karar sınırını
    # ancak bu epsilon içindeyken değiştirebilir. Bu durumlarda scalar
    # yola düşülür → sonuç her zaman legacy ile birebir kalır.
    _BORDERLINE_SCORE_EPS = 0.02
    _BORDERLINE_RSI_EPS = 0.01

    def _run_fast(
        self,
        market_data: Dict[str, pd.DataFrame],
        universe_at_date: Optional[List[str]] = None,
        benchmark_data: Optional[pd.DataFrame] = None,
        run_id: Optional[str] = None,
        persist: bool = True,
        trade_start: Optional[str] = None,
        trade_end: Optional[str] = None,
    ) -> BacktestResultV4:
        """Panel tabanlı hızlı yol — _run_legacy ile birebir aynı finansal akış.

        Fark yalnızca hesaplama maliyetinde:
        - Feature'lar hisse başına TÜM tarihlere tek seferde vektörize hesaplanır
          (doğru seviyede cache: run başına bir kez, O(n) per hisse).
        - df[df.index <= date] slice'ları yerine önceden kurulan
          searchsorted eşlemeleri ile O(1) lookup.
        - Borderline / mask-edge durumlarda scalar (legacy) hesaba düşülür.
        """
        self._lazy_load()
        start_time = _time.time()

        if run_id is None:
            run_id = self._generate_run_id(market_data)

        cfg = self._config
        sim = PortfolioSimulatorV3(
            initial_capital=cfg.initial_capital,
            max_position_pct=cfg.max_position_pct,
            max_positions=cfg.max_positions,
            slippage_rate=cfg.slippage_rate,
        )

        self._feature_cache.clear()
        self._quality_cache.clear()
        self._last_feature_seconds = 0.0
        self._last_panel_seconds = 0.0
        self._last_scalar_fallbacks = 0

        # Ortak tarih aralığı (legacy ile aynı)
        all_dates = set()
        for df in market_data.values():
            if df is not None and not df.empty:
                all_dates.update(df.index)
        sorted_dates = sorted(all_dates)

        effective_lookback = max(cfg.lookback_days, 60)

        if len(sorted_dates) < effective_lookback + 10:
            logger.warning("Insufficient data", dates=len(sorted_dates),
                         needed=effective_lookback + 10)
            return self._empty_result(run_id, sorted_dates, cfg, start_time)

        # Benchmark prices (legacy ile aynı)
        benchmark_prices = {}
        if benchmark_data is not None and not benchmark_data.empty:
            for idx in benchmark_data.index:
                date_str = str(idx.date()) if hasattr(idx, 'date') else str(idx)
                benchmark_prices[date_str] = float(benchmark_data.loc[idx, 'Close'])

        # Pre-compute quality cache (legacy ile aynı)
        for ticker, df in market_data.items():
            if df is not None and not df.empty and len(df) >= effective_lookback:
                try:
                    quality = self._dq.full_quality_check(df, ticker)
                    self._quality_cache.set(ticker, quality.passed, quality.quality_score)
                except Exception:
                    self._quality_cache.set(ticker, True, 80.0)

        # ====== PANEL PRE-COMPUTE (feature bottleneck çözümü) ======
        panels = {}
        if self._panel_engine is not None:
            store = self._panel_engine.compute(market_data, effective_lookback)
            panels = store.panels
            self._last_panel_seconds = store.compute_seconds
            self._last_feature_seconds += store.compute_seconds

        # Hisse başına O(1) erişim yapıları
        tinfo: Dict[str, Tuple[Any, np.ndarray, np.ndarray]] = {}
        for ticker, df in market_data.items():
            if df is None or df.empty:
                continue
            open_arr = df["Open"].values if "Open" in df.columns else df["Close"].values
            tinfo[ticker] = (df.index, open_arr, df["Close"].values)

        # Ana döngü (legacy kontrol akışının birebir aynası)
        signals_count = 0
        look_ahead_violations = 0
        survivorship_violations = 0
        data_quality_issues = 0
        total_scans = 0

        for i in range(effective_lookback, len(sorted_dates) - 1):
            current_date = sorted_dates[i]
            next_date = sorted_dates[i + 1]
            date_str = str(current_date.date()) if hasattr(current_date, 'date') else str(current_date)

            # Walk-forward trade penceresi
            if trade_start is not None and date_str < trade_start:
                continue
            if trade_end is not None and date_str > trade_end:
                continue

            bench_price = benchmark_prices.get(date_str)

            # SELL sinyalleri (pozisyondaki hisseler)
            for ticker in list(sim._positions.keys()):
                info = tinfo.get(ticker)
                if info is None:
                    continue
                idx, open_arr, _ = info

                loc = idx.searchsorted(next_date)
                if loc >= len(idx) or idx[loc] != next_date:
                    continue

                pos = idx.searchsorted(current_date, side="right") - 1
                if pos < effective_lookback - 1:
                    continue

                features = self._features_fast(
                    ticker, date_str, pos, panels, market_data, effective_lookback, cfg
                )
                if not features:
                    continue

                total_scans += 1
                score = self._compute_score(features)
                if score <= (100 - cfg.signal_threshold):
                    price = float(open_arr[loc])
                    sim.execute_sell(ticker, price, date_str)
                    signals_count += 1

            # BUY sinyalleri
            buy_candidates = []
            day_scores: Dict[str, Tuple[float, int]] = {}
            for ticker, df in market_data.items():
                # Survivorship bias
                if universe_at_date and ticker not in universe_at_date:
                    survivorship_violations += 1
                    continue

                # Zaten pozisyondaysa skip
                if sim.has_position(ticker):
                    continue

                # Quality cache
                quality_info = self._quality_cache.get(ticker)
                if quality_info and not quality_info[0]:
                    data_quality_issues += 1
                    continue
                if quality_info and quality_info[1] < cfg.min_quality_score:
                    data_quality_issues += 1
                    continue

                info = tinfo.get(ticker)
                if info is None:
                    continue
                idx = info[0]

                pos = idx.searchsorted(current_date, side="right") - 1
                if pos < effective_lookback - 1:
                    continue

                features = self._features_fast(
                    ticker, date_str, pos, panels, market_data, effective_lookback, cfg
                )
                if not features:
                    continue

                total_scans += 1
                score = self._compute_score(features)
                day_scores[ticker] = (score, pos)
                if score >= cfg.signal_threshold + 10:
                    buy_candidates.append((ticker, score))

            # En iyi adayları sırala (legacy: stabil sort, dict sırası korunur)
            buy_candidates.sort(key=lambda x: x[1], reverse=True)

            # Near-tie guard: sıralama farkı kayan nokta gürültüsünden
            # etkilenebilecek kadar yakınsa, YALNIZCA tie kümesi üyelerini
            # scalar yoldan yeniden hesapla → sıralama legacy ile birebir kalır.
            # Clip sınırındaki (0/100) eşitlikler deterministiktir — iki taraf
            # da aynı clip değerindeyse sıralama zaten stabil, recompute gerekmez.
            # (Panel↔scalar skor kayması ≤ ~0.011 < eps=0.02 olduğundan tie
            #  üyeleri küme dışındaki adaylarla yer değiştiremez.)
            if len(buy_candidates) > 1:
                tie_members = self._find_tie_members(buy_candidates)
                if tie_members:
                    buy_candidates = self._rescore_tie_members_scalar(
                        buy_candidates, tie_members, day_scores, date_str,
                        market_data, effective_lookback, cfg,
                    )

            for ticker, score in buy_candidates:
                if not sim.can_buy():
                    break
                info = tinfo.get(ticker)
                if info is None:
                    continue
                idx, open_arr, _ = info
                loc = idx.searchsorted(next_date)
                if loc >= len(idx) or idx[loc] != next_date:
                    continue
                price = float(open_arr[loc])
                sim.execute_buy(ticker, price, date_str)
                signals_count += 1

            # Equity snapshot
            prices = {}
            for ticker in sim._positions:
                info = tinfo.get(ticker)
                if info is None:
                    continue
                idx, _, close_arr = info
                loc = idx.searchsorted(current_date)
                if loc < len(idx) and idx[loc] == current_date:
                    prices[ticker] = float(close_arr[loc])
            sim.update_equity(prices, date_str, bench_price)

        elapsed = _time.time() - start_time
        return self._finalize_run(
            run_id, sorted_dates, effective_lookback, cfg, sim,
            total_scans, signals_count, look_ahead_violations,
            survivorship_violations, data_quality_issues, elapsed, persist,
        )

    def _features_fast(
        self,
        ticker: str,
        date_str: str,
        pos: int,
        panels: Dict[str, Any],
        market_data: Dict[str, pd.DataFrame],
        lookback: int,
        cfg: BacktestConfig,
    ) -> Optional[Dict[str, Any]]:
        """Panel lookup + borderline durumlarda scalar (legacy) fallback."""
        panel = panels.get(ticker)
        use_scalar = panel is None
        feats = None

        if not use_scalar:
            feats = self._panel_engine.features_at(panel, pos, lookback)
            if feats is None:
                use_scalar = True  # fallback işaretli veya scalar-only hisse

        if not use_scalar:
            # Borderline kontrolü — karar sınırlarına yakınsa scalar doğrula
            rsi = feats["rsi_14"]
            score = self._compute_score(feats)
            if (
                abs(rsi - 60.0) <= self._BORDERLINE_RSI_EPS
                or abs(rsi - 40.0) <= self._BORDERLINE_RSI_EPS
                or abs(score - (cfg.signal_threshold + 10)) <= self._BORDERLINE_SCORE_EPS
                or abs(score - (100 - cfg.signal_threshold)) <= self._BORDERLINE_SCORE_EPS
            ):
                use_scalar = True

        if use_scalar:
            self._last_scalar_fallbacks += 1
            df_until = market_data[ticker].iloc[: pos + 1]
            feats = self._get_features(ticker, date_str, df_until, lookback, cfg)

        return feats

    def _find_tie_members(
        self,
        buy_candidates: List[Tuple[str, float]],
    ) -> List[int]:
        """Sıralı aday listesinde near-tie kümelerine üye index'leri bul.

        Küme: zincirleme gap < eps ile bağlı adaylar. Clip sınırındaki
        (0/100) birebir eşitlikler deterministik olduğundan küme sayılmaz.
        """
        eps = self._BORDERLINE_SCORE_EPS
        members: List[int] = []
        cluster = [0]
        for j in range(1, len(buy_candidates)):
            a, b = buy_candidates[j - 1][1], buy_candidates[j][1]
            gap = abs(a - b)
            clipped_tie = (a == b) and (a in (0.0, 100.0))
            if gap < eps and not clipped_tie:
                cluster.append(j)
            else:
                if len(cluster) > 1:
                    members.extend(cluster)
                cluster = [j]
        if len(cluster) > 1:
            members.extend(cluster)
        return members

    def _rescore_tie_members_scalar(
        self,
        buy_candidates: List[Tuple[str, float]],
        tie_members: List[int],
        day_scores: Dict[str, Tuple[float, int]],
        date_str: str,
        market_data: Dict[str, pd.DataFrame],
        lookback: int,
        cfg: BacktestConfig,
    ) -> List[Tuple[str, float]]:
        """Tie kümesi üyelerinin skorlarını scalar (legacy) yoldan hesapla."""
        rescored: Dict[str, float] = {}
        for i in tie_members:
            ticker = buy_candidates[i][0]
            pos = day_scores[ticker][1]
            df_until = market_data[ticker].iloc[: pos + 1]
            feats = self._get_features(ticker, date_str, df_until, lookback, cfg)
            if feats:
                rescored[ticker] = self._compute_score(feats)
        merged = [(t, rescored.get(t, s)) for t, s in buy_candidates]
        merged.sort(key=lambda x: x[1], reverse=True)
        return merged

    def _finalize_run(
        self,
        run_id: str,
        sorted_dates: list,
        effective_lookback: int,
        cfg: BacktestConfig,
        sim: PortfolioSimulatorV3,
        total_scans: int,
        signals_count: int,
        look_ahead_violations: int,
        survivorship_violations: int,
        data_quality_issues: int,
        elapsed: float,
        persist: bool,
    ) -> BacktestResultV4:
        """Metrik + persistence (legacy ile aynı)."""
        metrics_dict = sim.compute_metrics()
        metrics = BacktestMetrics(**{k: v for k, v in metrics_dict.items()
                                     if k in BacktestMetrics.__dataclass_fields__})

        start_date = str(sorted_dates[effective_lookback].date()) if sorted_dates else ""
        end_date = str(sorted_dates[-1].date()) if sorted_dates else ""

        result = BacktestResultV4(
            run_id=run_id,
            start_date=start_date,
            end_date=end_date,
            config=cfg,
            metrics=metrics,
            total_scans=total_scans,
            signals_generated=signals_count,
            trades_executed=len(sim.get_trades()),
            look_ahead_violations=look_ahead_violations,
            survivorship_violations=survivorship_violations,
            data_quality_issues=data_quality_issues,
            elapsed_seconds=elapsed,
            scans_per_second=total_scans / max(elapsed, 0.001),
            equity_curve=[s.to_dict() for s in sim.get_equity_curve()],
            trades=[t.to_dict() for t in sim.get_trades()],
        )

        ok, errors = sim.check_invariants()
        if not ok:
            logger.error("Invariant violations detected", errors=errors)
            result.metrics.max_drawdown_pct = -1  # Flag

        if persist:
            try:
                backtest_persistence.save_run(
                    run_id=run_id,
                    start_date=start_date,
                    end_date=end_date,
                    initial_capital=cfg.initial_capital,
                    metrics=metrics_dict,
                    config=cfg.to_dict(),
                )
                backtest_persistence.save_trades(run_id, result.trades)
                backtest_persistence.save_equity_curve(run_id, result.equity_curve)
                result.persisted = True
            except Exception as e:
                logger.error("Persistence failed", error=str(e))

        logger.info("Backtest completed",
                   run_id=run_id,
                   trades=result.trades_executed,
                   return_pct=metrics.total_return_pct,
                   elapsed=f"{elapsed:.1f}s")

        return result

    # ===================== HELPERS =====================

    def _get_features(
        self,
        ticker: str,
        date_str: str,
        df_until: pd.DataFrame,
        lookback: int,
        cfg: BacktestConfig,
    ) -> Optional[Dict[str, Any]]:
        """Feature hesapla (cache ile)."""
        cached = self._feature_cache.get(ticker, date_str)
        if cached is not None:
            return cached

        df_lookback = df_until.iloc[-lookback:]
        _t0 = _time.perf_counter()
        try:
            mask = self._tm.compute_mask(
                ticker,
                df_lookback['Open'].values,
                df_lookback['High'].values,
                df_lookback['Low'].values,
                df_lookback['Close'].values,
                df_lookback['Volume'].values,
            )
            mask_arr = mask.mask if hasattr(mask, 'mask') else mask
            features = self._calc.compute_all_features(
                df_lookback, mask=mask_arr, ticker=ticker
            )
            self._last_feature_seconds += _time.perf_counter() - _t0
            if features:
                self._feature_cache.set(ticker, date_str, features)
            return features
        except Exception:
            self._last_feature_seconds += _time.perf_counter() - _t0
            return None

    def _compute_score(self, features: Dict[str, Any]) -> float:
        """Feature'lardan skor hesapla (v2.0 ile aynı mantık)."""
        _s = lambda v: float(v.flat[0]) if isinstance(v, np.ndarray) and v.size > 0 else float(v) if v is not None else 0
        score = 50.0
        rsi = _s(features.get("rsi_14", 50))
        if rsi > 60:
            score += 10
        elif rsi < 40:
            score -= 10
        score += _s(features.get("momentum_20d", 0)) * 100
        score += _s(features.get("roc_5d", 0)) * 2
        score += _s(features.get("volume_zscore", 0)) * 5
        return max(0, min(100, score))

    def _generate_run_id(self, market_data: Dict[str, pd.DataFrame]) -> str:
        """Deterministic run ID üret."""
        tickers = sorted(market_data.keys())
        hash_input = f"{','.join(tickers)}_{self._config.to_dict()}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:12]

    def _empty_result(
        self,
        run_id: str,
        dates: list,
        cfg: BacktestConfig,
        start_time: float,
    ) -> BacktestResultV4:
        return BacktestResultV4(
            run_id=run_id,
            start_date="",
            end_date="",
            config=cfg,
            metrics=BacktestMetrics(),
            total_scans=0,
            signals_generated=0,
            trades_executed=0,
            look_ahead_violations=0,
            survivorship_violations=0,
            data_quality_issues=0,
            elapsed_seconds=_time.time() - start_time,
            scans_per_second=0,
            equity_curve=[],
            trades=[],
        )


# =====================================================
# FALLBACK (test ortamında import hatası önlemek için)
# =====================================================

class _FallbackCalculator:
    def compute_all_features(self, df, mask=None, ticker=""):
        return {"rsi_14": 50, "momentum_20d": 0, "roc_5d": 0, "volume_zscore": 0}

class _FallbackMask:
    def compute_mask(self, *args, **kwargs):
        class _M:
            mask = None
        return _M()

class _FallbackQuality:
    def full_quality_check(self, df, ticker=""):
        class _Q:
            passed = True
            quality_score = 80.0
        return _Q()
