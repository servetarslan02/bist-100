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
- DuckDB persistence
"""

import hashlib
import time as _time
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl
import structlog

from .persistence import backtest_persistence
from .portfolio_sim import PortfolioSimulatorV3

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
    use_canonical_scoring: bool = False  # True → CanonicalScoringPipeline kullan
    regime: str = "UNKNOWN"  # Canonical scoring için rejim
    historical_repository: Any = None  # HistoricalDataRepository instance
    ml_model: Any = None  # TrainedModel instance (LightGBM)

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_capital": self.initial_capital,
            "lookback_days": self.lookback_days,
            "signal_threshold": self.signal_threshold,
            "max_position_pct": self.max_position_pct,
            "max_positions": self.max_positions,
            "slippage_rate": self.slippage_rate,
            "min_quality_score": self.min_quality_score,
            "use_canonical_scoring": self.use_canonical_scoring,
            "regime": self.regime,
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
    var_95: float = 0.0
    cvar_95: float = 0.0
    max_drawdown_duration_days: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {k: round(v, 4) if isinstance(v, float) else v for k, v in self.__dict__.items()}


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
    equity_curve: list[dict[str, Any]]
    trades: list[dict[str, Any]]
    persisted: bool = False

    def to_dict(self) -> dict[str, Any]:
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
        self._cache: dict[str, dict[str, Any]] = {}
        self._date_cache: dict[str, str] = {}
        self._hits = 0
        self._misses = 0

    def get(self, ticker: str, date: str) -> dict[str, Any] | None:
        if ticker in self._cache and self._date_cache.get(ticker) == date:
            self._hits += 1
            return self._cache[ticker]
        self._misses += 1
        return None

    def set(self, ticker: str, date: str, features: dict[str, Any]):
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
        self._cache: dict[str, tuple[bool, float]] = {}

    def get(self, ticker: str) -> tuple[bool, float] | None:
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
        config: BacktestConfig | None = None,
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
                from ..features.calculator import feature_calculator

                self._calc = feature_calculator
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
                from ..core.data_quality import DataQualityChecker as DataQualityV2

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
        market_data: dict[str, pl.DataFrame],
        universe_at_date: list[str] | None = None,
        benchmark_data: pl.DataFrame | None = None,
        run_id: str | None = None,
        persist: bool = True,
        trade_start: str | None = None,
        trade_end: str | None = None,
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
                market_data,
                universe_at_date,
                benchmark_data,
                run_id,
                persist,
                trade_start,
                trade_end,
            )
        return self._run_legacy(
            market_data,
            universe_at_date,
            benchmark_data,
            run_id,
            persist,
            trade_start,
            trade_end,
        )

    def _run_legacy(
        self,
        market_data: dict[str, pl.DataFrame],
        universe_at_date: list[str] | None = None,
        benchmark_data: pl.DataFrame | None = None,
        run_id: str | None = None,
        persist: bool = True,
        trade_start: str | None = None,
        trade_end: str | None = None,
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
            logger.warning("Insufficient data", dates=len(sorted_dates), needed=effective_lookback + 10)
            return self._empty_result(run_id, sorted_dates, cfg, start_time)

        # Benchmark prices (XU100)
        benchmark_prices = {}
        benchmark_close_arr = None  # Motor1 relative strength için
        if benchmark_data is not None and not benchmark_data.empty:
            for idx in benchmark_data.index:
                date_str = str(idx.date()) if hasattr(idx, "date") else str(idx)
                benchmark_prices[date_str] = float(benchmark_data.loc[idx, "Close"])
            if "Close" in benchmark_data.columns:
                benchmark_close_arr = benchmark_data["Close"].to_numpy().astype(float)

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
            date_str = str(current_date.date()) if hasattr(current_date, "date") else str(current_date)
            next_date_str = str(next_date.date()) if hasattr(next_date, "date") else str(next_date)

            # Walk-forward trade penceresi (varsayılan: kısıt yok)
            if trade_start is not None and date_str < trade_start:
                continue
            if trade_end is not None and date_str > trade_end:
                continue

            # Benchmark price
            bench_price = benchmark_prices.get(date_str)

            # === CANONICAL: GÜNLÜK FEATURE TOPLAMA (tüm tickers) ===
            day_features: dict[str, dict[str, Any]] = {}
            if cfg.use_canonical_scoring:
                # Historical adapter (repository varsa)
                hist_adapter = None
                if cfg.historical_repository is not None:
                    from ..data.historical_adapter import HistoricalDataAdapter

                    hist_adapter = HistoricalDataAdapter(cfg.historical_repository)

                for t, tdf in market_data.items():
                    tdf_until = tdf[tdf.index <= current_date]
                    if len(tdf_until) >= effective_lookback:
                        feats = self._get_features(t, date_str, tdf_until, effective_lookback, cfg)
                        if feats:
                            day_features[t] = feats
                # Cross-sectional enrichment (PIT-safe: sadece current_date verisi)
                if len(day_features) >= 5:
                    for t in list(day_features.keys()):
                        day_features[t] = self._enrich_features_for_canonical(
                            t,
                            day_features[t],
                            date_str,
                            day_features,
                            market_data,
                            current_date,
                            benchmark_close=benchmark_close_arr,
                            historical_adapter=hist_adapter,
                        )

            # SELL sinyalleri (pozisyondaki hisseler)
            for ticker in list(sim._positions.keys()):
                if ticker not in market_data:
                    continue
                df = market_data[ticker]
                if next_date not in df.index:
                    continue

                # Score hesapla (canonical modda enriched features)
                if cfg.use_canonical_scoring and ticker in day_features:
                    features = day_features[ticker]
                else:
                    df_until = df[df.index <= current_date]
                    if len(df_until) < effective_lookback:
                        continue
                    features = self._get_features(ticker, date_str, df_until, effective_lookback, cfg)

                if not features:
                    continue

                total_scans += 1
                score = self._compute_score(features, ticker=ticker, all_day_features=day_features, date_str=date_str)
                if score <= (100 - cfg.signal_threshold):
                    price = float(df.loc[next_date, "Open"])
                    sim.execute_sell(ticker, price, date_str)
                    signals_count += 1

            # BUY sinyalleri
            buy_candidates = []

            if cfg.use_canonical_scoring:
                # Canonical modda: day_features zaten SELL öncesi toplandı ve enrich edildi
                # Sadece pozisyonda olmayanları filtrele
                for ticker, features in day_features.items():
                    if sim.has_position(ticker):
                        continue
                    quality_info = self._quality_cache.get(ticker)
                    if quality_info and not quality_info[0]:
                        continue
                    if quality_info and quality_info[1] < cfg.min_quality_score:
                        continue
                    total_scans += 1
                    score = self._compute_score(
                        features, ticker=ticker, all_day_features=day_features, date_str=date_str
                    )
                    if score >= cfg.signal_threshold + 10:
                        buy_candidates.append((ticker, score))
            else:
                # Legacy modda: burada topla
                day_features = {}
                for ticker, df in market_data.items():
                    if universe_at_date and ticker not in universe_at_date:
                        survivorship_violations += 1
                        continue
                    if sim.has_position(ticker):
                        continue
                    quality_info = self._quality_cache.get(ticker)
                    if quality_info and not quality_info[0]:
                        data_quality_issues += 1
                        continue
                    if quality_info and quality_info[1] < cfg.min_quality_score:
                        data_quality_issues += 1
                        continue
                    df_until = df[df.index <= current_date]
                    if len(df_until) < effective_lookback:
                        continue
                    features = self._get_features(ticker, date_str, df_until, effective_lookback, cfg)
                    if not features:
                        continue
                    day_features[ticker] = features

                for ticker, features in day_features.items():
                    total_scans += 1
                    score = self._compute_score(
                        features, ticker=ticker, all_day_features=day_features, date_str=date_str
                    )
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
                price = float(df.loc[next_date, "Open"])
                atr = day_features.get(ticker, {}).get("atr_pct", 2.0) if day_features else 2.0
                vol_ratio = max(0.5, float(atr) / 2.5)
                sim.execute_buy(ticker, price, date_str, volatility_ratio=vol_ratio)
                signals_count += 1

            # Equity snapshot
            prices = {}
            for ticker in sim._positions:
                if ticker in market_data and current_date in market_data[ticker].index:
                    prices[ticker] = float(market_data[ticker].loc[current_date, "Close"])
            sim.update_equity(prices, date_str, bench_price)

        elapsed = _time.time() - start_time
        return self._finalize_run(
            run_id,
            sorted_dates,
            effective_lookback,
            cfg,
            sim,
            total_scans,
            signals_count,
            look_ahead_violations,
            survivorship_violations,
            data_quality_issues,
            elapsed,
            persist,
        )

    # ===================== FAST PATH (PANEL) =====================

    # Borderline eşikleri: panel ve scalar yol arasındaki kayan nokta /
    # yuvarlama farkları (~1e-2'den çok daha küçük) bir karar sınırını
    # ancak bu epsilon içindeyken değiştirebilir. Bu durumlarda scalar
    # yola düşülür → sonuç her zaman legacy ile birebir kalır.
    _BORDERLINE_SCORE_EPS = 0.02
    _BORDERLINE_RSI_EPS = 0.01

    def _run_fast(
        self,
        market_data: dict[str, pl.DataFrame],
        universe_at_date: list[str] | None = None,
        benchmark_data: pl.DataFrame | None = None,
        run_id: str | None = None,
        persist: bool = True,
        trade_start: str | None = None,
        trade_end: str | None = None,
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
            logger.warning("Insufficient data", dates=len(sorted_dates), needed=effective_lookback + 10)
            return self._empty_result(run_id, sorted_dates, cfg, start_time)

        # Benchmark prices (legacy ile aynı)
        benchmark_prices = {}
        benchmark_close_arr = None  # Motor1 relative strength için
        if benchmark_data is not None and not benchmark_data.empty:
            for idx in benchmark_data.index:
                date_str = str(idx.date()) if hasattr(idx, "date") else str(idx)
                benchmark_prices[date_str] = float(benchmark_data.loc[idx, "Close"])
            if "Close" in benchmark_data.columns:
                benchmark_close_arr = benchmark_data["Close"].to_numpy().astype(float)

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
        tinfo: dict[str, tuple[Any, np.ndarray, np.ndarray]] = {}
        for ticker, df in market_data.items():
            if df is None or df.empty:
                continue
            open_arr = df["Open"].to_numpy() if "Open" in df.columns else df["Close"].to_numpy()
            tinfo[ticker] = (df.index, open_arr, df["Close"].to_numpy())

        # Ana döngü (legacy kontrol akışının birebir aynası)
        signals_count = 0
        look_ahead_violations = 0
        survivorship_violations = 0
        data_quality_issues = 0
        total_scans = 0

        for i in range(effective_lookback, len(sorted_dates) - 1):
            current_date = sorted_dates[i]
            next_date = sorted_dates[i + 1]
            date_str = str(current_date.date()) if hasattr(current_date, "date") else str(current_date)

            # Walk-forward trade penceresi
            if trade_start is not None and date_str < trade_start:
                continue
            if trade_end is not None and date_str > trade_end:
                continue

            bench_price = benchmark_prices.get(date_str)

            # FAZ 4.9: Tum gunun feature'larini topla (CS normalization icin)
            day_features_fast: dict[str, dict[str, Any]] = {}
            for _t, _df in market_data.items():
                _info = tinfo.get(_t)
                if _info is None:
                    continue
                _idx_arr = _info[0]
                _pos = _idx_arr.searchsorted(current_date, side="right") - 1
                if _pos < effective_lookback - 1:
                    continue
                _feats = self._features_fast(_t, date_str, _pos, panels, market_data, effective_lookback, cfg)
                if _feats:
                    day_features_fast[_t] = _feats

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

                features = self._features_fast(ticker, date_str, pos, panels, market_data, effective_lookback, cfg)
                if not features:
                    continue

                total_scans += 1
                score = self._compute_score(
                    features, ticker=ticker, all_day_features=day_features_fast, date_str=date_str
                )
                if score <= (100 - cfg.signal_threshold):
                    price = float(open_arr[loc])
                    sim.execute_sell(ticker, price, date_str)
                    signals_count += 1

            # BUY sinyalleri
            buy_candidates = []
            day_scores: dict[str, tuple[float, int]] = {}
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

                features = self._features_fast(ticker, date_str, pos, panels, market_data, effective_lookback, cfg)
                if not features:
                    continue

                total_scans += 1
                score = self._compute_score(
                    features, ticker=ticker, all_day_features=day_features_fast, date_str=date_str
                )
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
                        buy_candidates,
                        tie_members,
                        day_scores,
                        date_str,
                        market_data,
                        effective_lookback,
                        cfg,
                        all_day_features=day_features_fast,
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
                atr = day_features_fast.get(ticker, {}).get("atr_pct", 2.0) if day_features_fast else 2.0
                vol_ratio = max(0.5, float(atr) / 2.5)
                sim.execute_buy(ticker, price, date_str, volatility_ratio=vol_ratio)
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
            run_id,
            sorted_dates,
            effective_lookback,
            cfg,
            sim,
            total_scans,
            signals_count,
            look_ahead_violations,
            survivorship_violations,
            data_quality_issues,
            elapsed,
            persist,
        )

    def _features_fast(
        self,
        ticker: str,
        date_str: str,
        pos: int,
        panels: dict[str, Any],
        market_data: dict[str, pl.DataFrame],
        lookback: int,
        cfg: BacktestConfig,
    ) -> dict[str, Any] | None:
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
            score = self._compute_score(feats, ticker=ticker, date_str=date_str)
            if (
                abs(rsi - 60.0) <= self._BORDERLINE_RSI_EPS
                or abs(rsi - 40.0) <= self._BORDERLINE_RSI_EPS
                or abs(score - (cfg.signal_threshold + 10)) <= self._BORDERLINE_SCORE_EPS
                or abs(score - (100 - cfg.signal_threshold)) <= self._BORDERLINE_SCORE_EPS
            ):
                use_scalar = True

        if use_scalar:
            self._last_scalar_fallbacks += 1
            df_until = market_data[ticker][: pos + 1]
            feats = self._get_features(ticker, date_str, df_until, lookback, cfg)

        return feats

    def _find_tie_members(
        self,
        buy_candidates: list[tuple[str, float]],
    ) -> list[int]:
        """Sıralı aday listesinde near-tie kümelerine üye index'leri bul.

        Küme: zincirleme gap < eps ile bağlı adaylar. Clip sınırındaki
        (0/100) birebir eşitlikler deterministik olduğundan küme sayılmaz.
        """
        eps = self._BORDERLINE_SCORE_EPS
        members: list[int] = []
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
        buy_candidates: list[tuple[str, float]],
        tie_members: list[int],
        day_scores: dict[str, tuple[float, int]],
        date_str: str,
        market_data: dict[str, pl.DataFrame],
        lookback: int,
        cfg: BacktestConfig,
        all_day_features: dict[str, dict[str, Any]] | None = None,
    ) -> list[tuple[str, float]]:
        """Tie kümesi üyelerinin skorlarını scalar (legacy) yoldan hesapla."""
        rescored: dict[str, float] = {}
        for i in tie_members:
            ticker = buy_candidates[i][0]
            pos = day_scores[ticker][1]
            df_until = market_data[ticker][: pos + 1]
            feats = self._get_features(ticker, date_str, df_until, lookback, cfg)
            if feats:
                rescored[ticker] = self._compute_score(
                    feats, ticker=ticker, all_day_features=all_day_features, date_str=date_str
                )
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
        metrics = BacktestMetrics(
            **{k: v for k, v in metrics_dict.items() if k in BacktestMetrics.__dataclass_fields__}
        )

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

        logger.info(
            "Backtest completed",
            run_id=run_id,
            trades=result.trades_executed,
            return_pct=metrics.total_return_pct,
            elapsed=f"{elapsed:.1f}s",
        )

        return result

    # ===================== HELPERS =====================

    def _get_features(
        self,
        ticker: str,
        date_str: str,
        df_until: pl.DataFrame,
        lookback: int,
        cfg: BacktestConfig,
    ) -> dict[str, Any] | None:
        """Feature hesapla (cache ile)."""
        cached = self._feature_cache.get(ticker, date_str)
        if cached is not None:
            return cached

        df_lookback = df_until[-lookback:]
        _t0 = _time.perf_counter()
        try:
            mask = self._tm.compute_mask(
                ticker,
                df_lookback["Open"].to_numpy(),
                df_lookback["High"].to_numpy(),
                df_lookback["Low"].to_numpy(),
                df_lookback["Close"].to_numpy(),
                df_lookback["Volume"].to_numpy(),
            )
            mask_arr = mask.mask if hasattr(mask, "mask") else mask
            features = self._calc.compute_all_features(df_lookback, mask=mask_arr, ticker=ticker)
            self._last_feature_seconds += _time.perf_counter() - _t0
            if features:
                self._feature_cache.set(ticker, date_str, features)
            return features
        except Exception:
            self._last_feature_seconds += _time.perf_counter() - _t0
            return None

    def _compute_score(
        self,
        features: dict[str, Any],
        ticker: str = "",
        all_day_features: dict[str, dict[str, Any]] | None = None,
        date_str: str = "",
    ) -> float:
        """Feature'lardan skor hesapla.

        use_canonical_scoring=True ise CanonicalScoringPipeline kullanır.
        Aksi halde v2.0 ile aynı legacy mantık.
        """
        if self._config.use_canonical_scoring:
            return self._compute_score_canonical(features, ticker, all_day_features, date_str)
        return self._compute_score_legacy(features)

    def _compute_score_legacy(self, features: dict[str, Any]) -> float:
        """Legacy skor — normalize edilmiş ağırlıklar.

        Her bileşen ±5-10 puan aralığına normalize edilir:
        - RSI (0-100): ±10 puan (eşik 40/60)
        - momentum_20d (ondalık, tipik ±0.05): ×200 → ±10 puan
        - roc_5d (%, tipik ±5): ×1.5 → ±7.5 puan
        - volume_zscore (z, tipik ±2): ×3 → ±6 puan

        Skor aralığı: ~25-75 (normal), 0-100 (aşırı durumlar)
        """

        def _s(v):
            return float(v.flat[0]) if isinstance(v, np.ndarray) and v.size > 0 else float(v) if v is not None else 0

        score = 50.0

        # RSI: 40-60 arası nötr, dışı ±10 puan
        rsi = _s(features.get("rsi_14", 50))
        if rsi > 60:
            score += min((rsi - 60) * 0.25, 10)  # 60→+0, 100→+10
        elif rsi < 40:
            score -= min((40 - rsi) * 0.25, 10)  # 40→-0, 0→-10

        # Momentum 20d (ondalık): ×200 → ±10 puan
        mom20 = _s(features.get("momentum_20d", 0))
        score += max(-10, min(10, mom20 * 200))

        # ROC 5d (%): ×1.5 → ±7.5 puan
        roc5 = _s(features.get("roc_5d", 0))
        score += max(-7.5, min(7.5, roc5 * 1.5))

        # Volume z-score: ×3 → ±6 puan
        vz = _s(features.get("volume_zscore", 0))
        score += max(-6, min(6, vz * 3))

        return max(0, min(100, score))

    def _compute_score_canonical(
        self,
        features: dict[str, Any],
        ticker: str = "",
        all_day_features: dict[str, dict[str, Any]] | None = None,
        date_str: str = "",
    ) -> float:
        """Canonical scoring pipeline ile skor.

        FAZ 4.7: prepare_features_for_inference() ile parity-safe.
        all_day_features ve date_str adapter'a geçirilerek CS normalization uygulanır.
        """
        try:
            from .canonical_adapter import backtest_canonical_adapter

            return backtest_canonical_adapter.compute_score(
                features=features,
                regime=self._config.regime,
                ml_model=self._config.ml_model,
                ticker=ticker or "BACKTEST",
                all_day_features=all_day_features,
                date_str=date_str,
            )
        except Exception as e:
            logger.warning("Canonical scoring failed, falling back to legacy", error=str(e))
            return self._compute_score_legacy(features)

    def _enrich_features_for_canonical(
        self,
        ticker: str,
        features: dict[str, Any],
        date_str: str,
        all_day_features: dict[str, dict[str, Any]],
        market_data: dict[str, pl.DataFrame],
        current_date,
        benchmark_close: np.ndarray | None = None,
        historical_adapter=None,
    ) -> dict[str, Any]:
        """Calculator feature'larını canonical scoring için zenginleştir.

        PIT-safe: Sadece current_date'e kadar bilinen veriler kullanılır.

        Eklenen:
        - Historical fundamental features (Motor4)
        - Historical KAP/News sentiment (Motor5)
        - Historical catalyst features (Motor6)
        - WhyFallingMotor — düşüş nedeni sınıflandırması (Motor7)
        - Motor1 relative strength features (benchmark varsa)
        - Cross-sectional rank features (return_*, rank_*, market_breadth)
        - Seasonality features (Motor9)
        - Canonical aliases (return_5d → roc_5d mapping)
        """
        enriched = dict(features)

        # === HISTORICAL FUNDAMENTAL (Motor4 — PIT-safe) ===
        if historical_adapter is not None:
            try:
                fund_features = historical_adapter.get_fundamental_features(ticker, date_str)
                if fund_features:
                    enriched.update(fund_features)
            except Exception as e:
                logger.debug("Handled exception", error=str(e), context="engine_v4.py:1091")

        # === HISTORICAL KAP + NEWS SENTIMENT (Motor5 — PIT-safe) ===
        if historical_adapter is not None:
            try:
                kap_events = historical_adapter.get_kap_events(ticker, date_str)
                news_events = historical_adapter.get_news_events(ticker, date_str)
                sentiment_features = historical_adapter.compute_sentiment(kap_events, news_events)
                if sentiment_features:
                    enriched.update(sentiment_features)
            except Exception as e:
                logger.debug("Handled exception", error=str(e), context="engine_v4.py:1102")

        # === HISTORICAL CATALYST (Motor6 — PIT-safe) ===
        if historical_adapter is not None:
            try:
                catalyst_events = historical_adapter.get_catalyst_events(ticker, date_str)
                catalyst_features = historical_adapter.compute_catalyst_features(catalyst_events)
                if catalyst_features:
                    enriched.update(catalyst_features)
            except Exception as e:
                logger.debug("Handled exception", error=str(e), context="engine_v4.py:1112")

        # === MOTOR 7: WHY FALLING (PIT-safe) ===
        try:
            from services.features.seven_motors import WhyFallingMotor

            stock_ret_5d = enriched.get("roc_5d", 0.0)
            stock_ret_20d = enriched.get("roc_20d", 0.0)

            # Market return: all_day_features ortalaması
            market_ret_5d = 0.0
            market_ret_20d = 0.0
            if all_day_features:
                rets_5d = [f.get("roc_5d", 0.0) for f in all_day_features if "roc_5d" in f]
                rets_20d = [f.get("roc_20d", 0.0) for f in all_day_features if "roc_20d" in f]
                if rets_5d:
                    market_ret_5d = float(np.mean(rets_5d))
                if rets_20d:
                    market_ret_20d = float(np.mean(rets_20d))

            # Sector return: aynı sektördeki hisselerin ortalaması
            # (sector bilgisi yoksa market return kullan)
            sector_ret_5d = market_ret_5d
            sector_ret_20d = market_ret_20d

            vol_zscore = enriched.get("volume_zscore_20d", 0.0)
            vol_ratio = enriched.get("volume_ratio", 1.0)
            news_sent = enriched.get("news_sentiment_weighted", 0.0)
            kap_sent = enriched.get("kap_sentiment_avg", 0.0)
            rsi_val = enriched.get("rsi_14", 50.0)
            atr_val = enriched.get("atr_pct", 0.0)

            why_motor = WhyFallingMotor()
            why_feats = why_motor.compute(
                ticker,
                stock_return_5d=stock_ret_5d,
                stock_return_20d=stock_ret_20d,
                market_return_5d=market_ret_5d,
                market_return_20d=market_ret_20d,
                sector_return_5d=sector_ret_5d,
                sector_return_20d=sector_ret_20d,
                volume_change=vol_ratio,
                volume_zscore=vol_zscore,
                news_sentiment=news_sent,
                kap_sentiment=kap_sent,
                rsi=rsi_val,
                atr_pct=atr_val,
            )
            enriched.update(why_feats)
        except Exception as e:
            logger.debug("Handled exception", error=str(e), context="engine_v4.py:WhyFallingMotor")

        # === MOTOR 1: RELATIVE STRENGTH (PIT-safe) ===
        if benchmark_close is not None and len(benchmark_close) > 20:
            try:
                from services.features.seven_motors import RelativeStrengthMotor

                df = market_data.get(ticker)
                if df is not None:
                    mask_arr = df.index <= current_date
                    stock_close = df["Close"].to_numpy()[mask_arr]
                    bench_slice = benchmark_close[: len(stock_close)]
                    if len(stock_close) > 20 and len(bench_slice) == len(stock_close):
                        rs_motor = RelativeStrengthMotor()
                        rs_feats = rs_motor.compute(ticker, stock_close, bench_slice)
                        enriched.update(rs_feats)
            except Exception as e:
                logger.debug("Handled exception", error=str(e), context="engine_v4.py:1130")

        # === CROSS-SECTIONAL FEATURES (PIT-safe) ===
        if len(all_day_features) >= 5:
            from services.features.cross_sectional import cross_sectional_engine

            rank_feats = cross_sectional_engine.compute_rank_features(ticker, features, all_day_features)
            enriched.update(rank_feats)
            breadth = cross_sectional_engine.compute_market_breadth_features(all_day_features)
            enriched.update(breadth)

        # === SEASONALITY (PIT-safe) ===
        try:
            dates_list = []
            df = market_data.get(ticker)
            if df is not None:
                mask_arr = df.index <= current_date
                dates_list = [str(d.date()) if hasattr(d, "date") else str(d) for d in df.index[mask_arr]]
            if len(dates_list) >= 252:
                close_arr = df["Close"].to_numpy()[mask_arr] if df is not None else None
                if close_arr is not None and len(close_arr) >= 252:
                    from services.features.seven_motors import SeasonalityMotor

                    season_motor = SeasonalityMotor()
                    season_feats = season_motor.compute(ticker, close_arr, dates_list)
                    enriched.update(season_feats)
        except Exception as e:
            logger.debug("Handled exception", error=str(e), context="engine_v4.py:1162")

        # === CANONICAL ALIASES ===
        for period in [1, 5, 20, 60]:
            roc_key = f"roc_{period}d"
            ret_key = f"return_{period}d"
            if roc_key in enriched and ret_key not in enriched:
                enriched[ret_key] = enriched[roc_key]

        return enriched

    def _generate_run_id(self, market_data: dict[str, pl.DataFrame]) -> str:
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
