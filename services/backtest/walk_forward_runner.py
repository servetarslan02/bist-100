"""
ALPHA BIST — Walk-Forward Backtest Runner v1.0

BacktestEngineV4 + WalkForwardEngine (purge + embargo) gerçek entegrasyonu.

Güvenceler:
1. POINT-IN-TIME: Her fold için piyasa verisi test_end'e kadar KESİLİR.
   Engine gelecek veriyi fiziksel olarak göremez.
2. PURGE: train_end → test_start arası gap korunur (WalkForwardEngine.create_folds).
3. EMBARGO: test_end → sonraki train arası gap fold metadata'sında korunur.
4. LEAKAGE GUARD: Fold sınırları, trade tarihleri ve equity tarihleri
   çalışma zamanında doğrulanır; ihlal varsa fold FAIL sayılır.
5. REPRODUCIBLE: Fold run_id'leri deterministiktir; her fold'un sonucu
   (run + trades + equity curve) ayrıca persist edilir.

KURAL: Tahmin modeli / skor formülü DEĞİŞTİRİLMEZ — engine ne üretiyorsa o.
"""

import hashlib
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import structlog

from .engine_v4 import BacktestEngineV4, BacktestConfig, BacktestResultV4
from .walk_forward import WalkForwardEngine

logger = structlog.get_logger()


@dataclass
class FoldBacktestResult:
    """Tek fold'un engine tabanlı backtest sonucu."""
    fold_id: int
    train_start: str
    train_end: str
    purge_start: str
    purge_end: str
    test_start: str
    test_end: str
    embargo_start: str
    embargo_end: str
    run_id: str
    total_return_pct: float = 0.0
    cagr_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate_pct: float = 0.0
    total_trades: int = 0
    signals_generated: int = 0
    total_scans: int = 0
    final_equity: float = 0.0
    elapsed_seconds: float = 0.0
    persisted: bool = False
    leakage_ok: bool = True
    leakage_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class WalkForwardBacktestResult:
    """Walk-forward backtest toplu sonucu."""
    run_id: str
    total_folds: int
    avg_test_return_pct: float
    avg_test_sharpe: float
    avg_test_sortino: float
    avg_test_max_drawdown_pct: float
    avg_win_rate_pct: float
    stability_score: float
    worst_fold_return_pct: float
    best_fold_return_pct: float
    deflated_sharpe: float
    total_trades: int
    all_leakage_ok: bool
    folds: List[FoldBacktestResult]
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "folds"}
        d["folds"] = [f.to_dict() for f in self.folds]
        return d


class WalkForwardBacktestRunner:
    """Engine v4.0 üzerinde purge + embargo korumalı walk-forward backtest."""

    def __init__(
        self,
        backtest_config: Optional[BacktestConfig] = None,
        purge_days: int = 5,
        embargo_days: int = 5,
        train_days: int = 252,
        test_days: int = 63,
        step_days: int = 21,
        use_panel_features: bool = True,
    ):
        self._config = backtest_config or BacktestConfig()
        self._use_panel = use_panel_features
        self._wf = WalkForwardEngine(
            purge_days=purge_days,
            embargo_days=embargo_days,
            train_days=train_days,
            test_days=test_days,
            step_days=step_days,
        )

    def run(
        self,
        market_data: Dict[str, pd.DataFrame],
        universe_at_date: Optional[List[str]] = None,
        benchmark_data: Optional[pd.DataFrame] = None,
        run_id: Optional[str] = None,
        persist: bool = True,
    ) -> WalkForwardBacktestResult:
        """Walk-forward backtest çalıştır.

        Args:
            market_data: {ticker: OHLCV DataFrame}
            universe_at_date: Survivorship kontrolü için evren
            benchmark_data: XU100 benchmark
            run_id: Base run id (None ise deterministik üretilir)
            persist: Her fold'un sonucunu ayrı run olarak kaydet
        """
        # Global tarih listesi (engine ile aynı semantik, date-string)
        all_dates = set()
        for df in market_data.values():
            if df is not None and not df.empty:
                for ts in df.index:
                    all_dates.add(str(ts.date()) if hasattr(ts, "date") else str(ts))
        dates = sorted(all_dates)

        if run_id is None:
            run_id = self._base_run_id(market_data)

        folds = self._wf.create_folds(dates)
        if not folds:
            logger.warning("No walk-forward folds", dates=len(dates))
            return self._empty_result(run_id)

        fold_results: List[FoldBacktestResult] = []

        for fold_id, fold in enumerate(folds, 1):
            fold_run_id = f"{run_id}_fold{fold_id:03d}"
            test_start = fold["test_start"]
            test_end = fold["test_end"]

            # ====== POINT-IN-TIME KESİT (gelecek veri fiziksel olarak yok) ======
            pit_data = self._truncate(market_data, test_end)

            # ====== ENGINE RUN (trade penceresi = test aralığı) ======
            engine = BacktestEngineV4(self._config, use_panel_features=self._use_panel)
            r = engine.run(
                pit_data,
                universe_at_date=universe_at_date,
                benchmark_data=benchmark_data,
                run_id=fold_run_id,
                persist=persist,
                trade_start=test_start,
                trade_end=test_end,
            )

            # ====== LEAKAGE GUARDS ======
            leakage_ok, leakage_errors = self._verify_fold(fold, r, pit_data, test_end)

            m = r.metrics
            fold_results.append(FoldBacktestResult(
                fold_id=fold_id,
                train_start=fold["train_start"],
                train_end=fold["train_end"],
                purge_start=fold["purge_start"],
                purge_end=fold["purge_end"],
                test_start=test_start,
                test_end=test_end,
                embargo_start=fold["embargo_start"],
                embargo_end=fold["embargo_end"],
                run_id=fold_run_id,
                total_return_pct=m.total_return_pct,
                cagr_pct=m.cagr_pct,
                sharpe_ratio=m.sharpe_ratio,
                sortino_ratio=m.sortino_ratio,
                max_drawdown_pct=m.max_drawdown_pct,
                win_rate_pct=m.win_rate_pct,
                total_trades=r.trades_executed,
                signals_generated=r.signals_generated,
                total_scans=r.total_scans,
                final_equity=round(r.equity_curve[-1]["equity"], 2) if r.equity_curve else self._config.initial_capital,
                elapsed_seconds=round(r.elapsed_seconds, 3),
                persisted=r.persisted,
                leakage_ok=leakage_ok,
                leakage_errors=leakage_errors,
            ))

            logger.info("Walk-forward fold completed",
                       fold=fold_id, run_id=fold_run_id,
                       trades=r.trades_executed,
                       return_pct=m.total_return_pct,
                       leakage_ok=leakage_ok)

        return self._aggregate(run_id, fold_results)

    # ------------------------------------------------------------------
    # GUARDS
    # ------------------------------------------------------------------

    @staticmethod
    def _truncate(
        market_data: Dict[str, pd.DataFrame],
        test_end: str,
    ) -> Dict[str, pd.DataFrame]:
        """Veriyi test_end'e kadar kes (point-in-time)."""
        end_ts = pd.Timestamp(test_end)
        pit = {}
        for ticker, df in market_data.items():
            if df is None or df.empty:
                continue
            # Tarih bileşeni test_end'i aşmayan satırlar (timestamp time-of-day
            # içerse bile test_end günü dahil, sonrası KESİNLİKLE yok)
            mask = df.index <= end_ts
            if df.index.has_duplicates is False and df.index.is_monotonic_increasing:
                cut = df.index.searchsorted(end_ts, side="right")
                sliced = df.iloc[:cut]
            else:
                sliced = df[mask]
            # date-string seviyesinde de garanti
            if not sliced.empty:
                last = sliced.index[-1]
                last_str = str(last.date()) if hasattr(last, "date") else str(last)
                if last_str > test_end:
                    sliced = sliced.iloc[:-1]
            if not sliced.empty:
                pit[ticker] = sliced
        return pit

    @staticmethod
    def _verify_fold(
        fold: Dict[str, Any],
        result: BacktestResultV4,
        pit_data: Dict[str, pd.DataFrame],
        test_end: str,
    ) -> tuple:
        """Fold leakage doğrulaması.

        Kontroller:
        1. Purge: train_end < purge_start <= purge_end < test_start
        2. Embargo metadata: test_end < embargo_start (varsa)
        3. PIT: hiçbir hissenin verisi test_end'i aşmıyor
        4. Trade'ler test penceresi içinde
        5. Equity tarihleri test penceresi içinde
        """
        errors = []

        # 1-2. Fold sınır bütünlüğü
        if not (fold["train_end"] < fold["purge_start"] <= fold["purge_end"] < fold["test_start"]):
            errors.append(
                f"Purge ihlali: train_end={fold['train_end']} "
                f"purge=[{fold['purge_start']},{fold['purge_end']}] "
                f"test_start={fold['test_start']}"
            )
        if fold["embargo_start"] < fold["test_end"] and fold["embargo_start"] != fold["test_end"]:
            errors.append(
                f"Embargo ihlali: test_end={fold['test_end']} embargo_start={fold['embargo_start']}"
            )

        # 3. Point-in-time veri kontrolü
        for ticker, df in pit_data.items():
            last = df.index[-1]
            last_str = str(last.date()) if hasattr(last, "date") else str(last)
            if last_str > test_end:
                errors.append(f"PIT ihlali: {ticker} verisi {last_str} > {test_end}")
                break

        # 4-5. Trade / equity pencere kontrolü
        for t in result.trades:
            if not (fold["test_start"] <= t["date"] <= fold["test_end"]):
                errors.append(f"Trade pencere dışı: {t['ticker']} @ {t['date']}")
                break
        for s in result.equity_curve:
            if not (fold["test_start"] <= s["date"] <= fold["test_end"]):
                errors.append(f"Equity pencere dışı: {s['date']}")
                break

        return len(errors) == 0, errors

    # ------------------------------------------------------------------
    # AGGREGATION
    # ------------------------------------------------------------------

    def _aggregate(
        self,
        run_id: str,
        folds: List[FoldBacktestResult],
    ) -> WalkForwardBacktestResult:
        returns = [f.total_return_pct for f in folds]
        sharpes = [f.sharpe_ratio for f in folds]
        sortinos = [f.sortino_ratio for f in folds]
        dds = [f.max_drawdown_pct for f in folds]
        wins = [f.win_rate_pct for f in folds]

        mean_ret = float(np.mean(returns))
        std_ret = float(np.std(returns))
        stability = max(0.0, 1.0 - std_ret / (abs(mean_ret) + 0.01))

        # Deflated Sharpe (WalkForwardEngine ile aynı formül)
        deflated = self._wf._deflated_sharpe(
            float(np.mean(sharpes)),
            max(sum(f.total_scans for f in folds), 1),
            len(folds),
        )

        return WalkForwardBacktestResult(
            run_id=run_id,
            total_folds=len(folds),
            avg_test_return_pct=round(mean_ret, 4),
            avg_test_sharpe=round(float(np.mean(sharpes)), 4),
            avg_test_sortino=round(float(np.mean(sortinos)), 4),
            avg_test_max_drawdown_pct=round(float(np.mean(dds)), 4),
            avg_win_rate_pct=round(float(np.mean(wins)), 4),
            stability_score=round(stability, 4),
            worst_fold_return_pct=round(float(min(returns)), 4),
            best_fold_return_pct=round(float(max(returns)), 4),
            deflated_sharpe=round(float(deflated), 4),
            total_trades=sum(f.total_trades for f in folds),
            all_leakage_ok=all(f.leakage_ok for f in folds),
            folds=folds,
            summary={
                "purge_days": self._wf.purge_days,
                "embargo_days": self._wf.embargo_days,
                "train_days": self._wf.train_days,
                "test_days": self._wf.test_days,
                "step_days": self._wf.step_days,
                "use_panel_features": self._use_panel,
                "engine": "BacktestEngineV4",
            },
        )

    def _base_run_id(self, market_data: Dict[str, pd.DataFrame]) -> str:
        tickers = sorted(market_data.keys())
        wf_cfg = (self._wf.purge_days, self._wf.embargo_days, self._wf.train_days,
                  self._wf.test_days, self._wf.step_days)
        hash_input = f"wf_{','.join(tickers)}_{self._config.to_dict()}_{wf_cfg}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:12]

    def _empty_result(self, run_id: str) -> WalkForwardBacktestResult:
        return WalkForwardBacktestResult(
            run_id=run_id, total_folds=0,
            avg_test_return_pct=0, avg_test_sharpe=0, avg_test_sortino=0,
            avg_test_max_drawdown_pct=0, avg_win_rate_pct=0,
            stability_score=0, worst_fold_return_pct=0, best_fold_return_pct=0,
            deflated_sharpe=0, total_trades=0, all_leakage_ok=True,
            folds=[], summary={},
        )
