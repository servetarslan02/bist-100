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
            train_start = fold["train_start"]
            train_end = fold["train_end"]

            # ====== POINT-IN-TIME KESİT (gelecek veri fiziksel olarak yok) ======
            pit_data = self._truncate(market_data, test_end)

            # ====== ML MODEL EĞİTİMİ (TRAIN window ile) ======
            fold_config = self._config
            if self._config.use_canonical_scoring:
                ml_model = self._train_fold_model(
                    pit_data, train_start, train_end, benchmark_data
                )
                if ml_model is not None:
                    # Config'in kopyasını oluştur (model sadece bu fold için)
                    import copy
                    fold_config = copy.deepcopy(self._config)
                    fold_config.ml_model = ml_model

            # ====== ENGINE RUN (trade penceresi = test aralığı) ======
            engine = BacktestEngineV4(fold_config, use_panel_features=self._use_panel)
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
    # ML MODEL TRAINING
    # ------------------------------------------------------------------

    # Minimum sample sayısı — bundan azsa ML kullanma, rule-based fallback'a geç
    MIN_TRAINING_SAMPLES = 50
    # Forward return penceresi (işlem günü)
    FORWARD_DAYS = 5
    # Feature hesaplaması için minimum bar sayısı
    MIN_BARS_FOR_FEATURES = 60

    def _train_fold_model(
        self,
        pit_data: Dict[str, pd.DataFrame],
        train_start: str,
        train_end: str,
        benchmark_data=None,
    ):
        """TRAIN window için LightGBM modeli eğit — FAZ 4.4.

        Değişiklikler:
        - purge_gap date-space'de çalışır (sample-space değil)
        - CrossSectionalNormalizer PIT-safe entegrasyon
        - Feature contract CS feature'larını içerir
        - Multi-horizon target (1d/5d/20d/60d) altyapısı
        - Model metadata kalıcı field'larda saklanır

        Returns:
            TrainedModel veya None
        """
        try:
            from ..ml.lightgbm_trainer import LightGBMTrainer, MLModelConfig, DEFAULT_TARGETS
            from ..features.calculator import feature_calculator
            from ..ml.training_validator import training_validator, cross_sectional_normalizer
        except ImportError:
            return None

        # 1) Train window verisini kes
        train_data: Dict[str, pd.DataFrame] = {}
        ts_start = pd.Timestamp(train_start)
        ts_end = pd.Timestamp(train_end)
        for ticker, df in pit_data.items():
            mask = (df.index >= ts_start) & (df.index <= ts_end)
            df_train = df.loc[mask]
            if len(df_train) >= self.MIN_BARS_FOR_FEATURES:
                train_data[ticker] = df_train

        if len(train_data) < 5:
            return None

        # 2) Her ticker × her uygun gün için sample oluştur
        calc = feature_calculator
        features_map: Dict[str, Dict] = {}
        returns: Dict[str, float] = {}
        date_groups: Dict[str, str] = {}

        # En büyük horizon kadar son günleri atla (horizon-aware)
        max_horizon = self.FORWARD_DAYS  # Varsayılan 5d

        for ticker, df in train_data.items():
            n = len(df)
            first_feature_idx = self.MIN_BARS_FOR_FEATURES - 1
            last_feature_idx = n - max_horizon - 1

            if last_feature_idx < first_feature_idx:
                continue

            close_all = df['Close'].values

            for idx in range(first_feature_idx, last_feature_idx + 1):
                df_slice = df.iloc[:idx + 1]
                feats = calc.compute_all_features(df_slice, ticker=ticker)
                if not feats:
                    continue

                c_t = close_all[idx]
                c_t_fwd = close_all[idx + self.FORWARD_DAYS]
                if c_t <= 0 or np.isnan(c_t) or np.isnan(c_t_fwd):
                    continue
                forward_ret = (c_t_fwd / c_t - 1.0) * 100.0

                feature_date = df.index[idx]
                date_str = str(feature_date.date()) if hasattr(feature_date, 'date') else str(feature_date)
                sample_key = f"{ticker}::{date_str}"

                if sample_key in features_map:
                    continue

                features_map[sample_key] = feats
                returns[sample_key] = forward_ret
                date_groups[sample_key] = date_str

        n_samples = len(features_map)
        if n_samples < self.MIN_TRAINING_SAMPLES:
            logger.warning("Insufficient training samples for ML, falling back to rule-based",
                          samples=n_samples, min_required=self.MIN_TRAINING_SAMPLES)
            return None

        # 3) Feature names (canonical scoring ile uyumlu)
        feature_names = self._get_canonical_feature_names()
        if not feature_names:
            return None

        # 4) Deterministik sıralama
        sorted_keys = sorted(features_map.keys(), key=lambda k: (date_groups[k], k))
        features_map = {k: features_map[k] for k in sorted_keys}
        returns = {k: returns[k] for k in sorted_keys}
        date_groups = {k: date_groups[k] for k in sorted_keys}

        # 5) Veri kalite kontrolü ve temizlik
        features_map, clean_stats = training_validator.clean_features(
            features_map, feature_names
        )
        if clean_stats["inf_replaced"] > 0 or clean_stats["outliers_clamped"] > 0:
            logger.info("Feature cleaning applied",
                       inf_replaced=clean_stats["inf_replaced"],
                       outliers_clamped=clean_stats["outliers_clamped"])

        quality_report = training_validator.validate_dataset(
            features_map, returns, date_groups, feature_names
        )
        logger.info("Training data quality",
                   quality_score=round(quality_report.quality_score, 2),
                   valid_samples=quality_report.valid_samples,
                   unique_tickers=quality_report.unique_tickers,
                   unique_dates=quality_report.unique_dates)

        # 6) Cross-Sectional Normalization (PIT-safe: sadece aynı tarih snapshot'ı)
        #    CS feature'ları feature contract'a eklenir
        cs_feature_names = []
        try:
            # Sadece temel feature'ları normalize et (CS suffix'li olanları değil)
            base_features = [f for f in feature_names if not f.endswith('_cs_zscore') and not f.endswith('_cs_rank')]
            features_map = cross_sectional_normalizer.normalize_zscore_by_date(
                features_map, date_groups, base_features
            )
            # CS feature isimlerini topla
            sample_feats = list(features_map.values())[0] if features_map else {}
            cs_feature_names = sorted([k for k in sample_feats.keys() if k.endswith('_cs_zscore')])
            # Feature listesini güncelle (orijinal + CS)
            all_feature_names = feature_names + cs_feature_names
            all_feature_names = list(dict.fromkeys(all_feature_names))  # Unique, order preserved
            logger.info("Cross-sectional normalization applied",
                       cs_features=len(cs_feature_names),
                       total_features=len(all_feature_names))
        except Exception as e:
            logger.warning("CS normalization failed, using base features", error=str(e))
            all_feature_names = feature_names

        # 7) Multi-horizon eğitim (1d, 5d, 20d, 60d)
        from ..ml.lightgbm_trainer import MultiHorizonModel, DEFAULT_TARGETS

        multi_model = MultiHorizonModel(
            primary_horizon=self.FORWARD_DAYS,
            cs_features=cs_feature_names,
        )

        for target_spec in DEFAULT_TARGETS:
            horizon = target_spec.horizon

            # Horizon-aware purge: purge = max(default_purge, horizon)
            effective_purge = max(self.FORWARD_DAYS, horizon)

            # Bu horizon için yeterli tarih var mı?
            unique_dates_sorted = sorted(set(date_groups.values()))
            n_dates = len(unique_dates_sorted)
            val_date_count = max(2, int(n_dates * 0.2))
            train_date_end_idx = n_dates - val_date_count - effective_purge

            if train_date_end_idx < 10:
                logger.info("Skipping horizon (insufficient dates)",
                           horizon=horizon, n_dates=n_dates, purge=effective_purge)
                continue

            # Bu horizon için target hesapla (sadece features_map'teki sample'lar için)
            horizon_returns: Dict[str, float] = {}
            for ticker, df in train_data.items():
                close_all = df['Close'].values
                n = len(df)
                first_idx = self.MIN_BARS_FOR_FEATURES - 1
                last_idx = n - horizon - 1
                for idx in range(first_idx, last_idx + 1):
                    c_t = close_all[idx]
                    c_fwd = close_all[idx + horizon]
                    if c_t <= 0 or not np.isfinite(c_t) or not np.isfinite(c_fwd):
                        continue
                    feature_date = df.index[idx]
                    date_str = str(feature_date.date()) if hasattr(feature_date, 'date') else str(feature_date)
                    sample_key = f"{ticker}::{date_str}"
                    if sample_key in features_map and sample_key not in horizon_returns:
                        horizon_returns[sample_key] = (c_fwd / c_t - 1.0) * 100.0

            # Sadece bu horizon için target'ı olan sample'ları kullan
            horizon_features = {k: v for k, v in features_map.items() if k in horizon_returns}
            horizon_date_groups = {k: v for k, v in date_groups.items() if k in horizon_returns}

            if len(horizon_features) < self.MIN_TRAINING_SAMPLES:
                logger.info("Skipping horizon (insufficient samples)",
                           horizon=horizon, samples=len(horizon_features))
                continue

            config = MLModelConfig(
                num_boost_round=50,
                early_stopping_rounds=5,
                purge_gap_days=effective_purge,
                target_horizon=horizon,
            )
            trainer = LightGBMTrainer(config)
            h_model = trainer.train(
                horizon_features, horizon_returns, horizon_date_groups,
                feature_names=all_feature_names, regime="UNKNOWN"
            )

            if h_model is not None:
                h_model.cs_features = cs_feature_names
                multi_model.horizon_models[horizon] = h_model
                vm = h_model.validation_metrics
                logger.info("Horizon model trained",
                           horizon=horizon,
                           samples=h_model.train_samples,
                           ic=round(vm.get('ic', 0), 4),
                           confidence=h_model.confidence_score)

        if not multi_model.horizon_models:
            logger.warning("No horizon models trained, falling back to rule-based")
            return None

        logger.info("Multi-horizon training complete",
                   horizons=multi_model.available_horizons,
                   primary=multi_model.primary_horizon,
                   total_samples=multi_model.total_train_samples)

        # Model metadata'yı DB'ye kaydet (best-effort, crash etmez)
        try:
            from ..core.model_persistence import model_persistence
            import threading
            version = f"fold_{train_start}_{train_end}_h{'_'.join(str(h) for h in multi_model.available_horizons)}"

            def _save():
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(model_persistence.save_model_metadata(
                        model_name="alpha_bist_multi_horizon",
                        version=version,
                        model_obj=multi_model,
                        artifact_path="in_memory",
                        training_data_start=train_start,
                        training_data_end=train_end,
                    ))
                except Exception as e:
                    logger.debug("Handled exception", error=str(e), context="walk_forward_runner.py:471")
                    pass
                finally:
                    loop.close()

            t = threading.Thread(target=_save, daemon=True)
            t.start()
        except Exception as e:
            pass  # Best-effort, DB yoksa devam et

        return multi_model

    def _get_canonical_feature_names(self) -> List[str]:
        """Canonical feature registry'den feature isimlerini al (regex yok)."""
        if hasattr(self, '_feature_names_cache') and self._feature_names_cache:
            return self._feature_names_cache
        try:
            from ..core.canonical_scoring import get_canonical_features
            self._feature_names_cache = get_canonical_features()
        except Exception as e:
            self._feature_names_cache = []
        return self._feature_names_cache


    # ------------------------------------------------------------------
    # GUARDS
    # ------------------------------------------------------------------

    @staticmethod    # ------------------------------------------------------------------
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
