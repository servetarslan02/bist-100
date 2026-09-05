"""
ALPHA BIST — Walk-Forward Backtest Runner v2.0

BacktestEngineV4 + WalkForwardEngineV5 (purge + embargo) gerçek entegrasyonu.
v5.0 canonical engine olarak kullanılır (scipy tabanlı Deflated Sharpe, leakage guard, feature engine entegrasyonu).

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

from __future__ import annotations

import hashlib
import math
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import numpy as np
import structlog

try:
    import polars as pl
except ImportError:
    pl = None

from .engine_v4 import BacktestConfig, BacktestEngineV4, BacktestResultV4
from .walk_forward_engine import WalkForwardEngineV5 as WalkForwardEngine

# ============================================================================
# SABİTLER (MAGIC NUMBER TEMİZLİĞİ & VARSAYILAN DEĞERLER)
# ============================================================================
DEFAULT_PURGE_DAYS: int = 5
DEFAULT_EMBARGO_DAYS: int = 5
DEFAULT_TRAIN_DAYS: int = 252
DEFAULT_TEST_DAYS: int = 63
DEFAULT_STEP_DAYS: int = 21

logger = structlog.get_logger(__name__)


def _filter_polars_by_date(df: pl.DataFrame, end_date: str) -> pl.DataFrame:
    """Polars DataFrame'i end_date tarihine göre (<= end_date) güvenle filtreler.

    Date, Datetime ve String sütun tiplerini destekler; tip uyuşmazlığı hatalarını önler.
    """
    if "Date" not in df.columns:
        return df
    dtype = df["Date"].dtype
    if dtype in (pl.Date, pl.Datetime):
        end_d = date.fromisoformat(end_date[:10])
        if dtype == pl.Date:
            return df.filter(pl.col("Date") <= end_d)
        else:
            end_dt = datetime.combine(end_d, datetime.max.time())
            return df.filter(pl.col("Date") <= end_dt)
    else:
        return df.filter(pl.col("Date").cast(pl.String).str.slice(0, 10) <= end_date[:10])


def _filter_polars_by_range(df: pl.DataFrame, start_date: str, end_date: str) -> pl.DataFrame:
    """Polars DataFrame'i start_date ile end_date aralığına göre güvenle filtreler.

    Date, Datetime ve String sütun tiplerini destekler; tip uyuşmazlığı hatalarını önler.
    """
    if "Date" not in df.columns:
        return df
    dtype = df["Date"].dtype
    if dtype in (pl.Date, pl.Datetime):
        start_d = date.fromisoformat(start_date[:10])
        end_d = date.fromisoformat(end_date[:10])
        if dtype == pl.Date:
            return df.filter((pl.col("Date") >= start_d) & (pl.col("Date") <= end_d))
        else:
            start_dt = datetime.combine(start_d, datetime.min.time())
            end_dt = datetime.combine(end_d, datetime.max.time())
            return df.filter((pl.col("Date") >= start_dt) & (pl.col("Date") <= end_dt))
    else:
        col_str = pl.col("Date").cast(pl.String).str.slice(0, 10)
        return df.filter((col_str >= start_date[:10]) & (col_str <= end_date[:10]))


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
    leakage_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Fold sonucunu sözlük formatında döndürür.

        Returns:
            dict[str, Any]: Fold metrikleri ve pencerelerini içeren sözlük.
        """
        return {k: v for k, v in self.__dict__.items()}

    def __repr__(self) -> str:
        return (
            f"FoldBacktestResult(fold={self.fold_id}, test=[{self.test_start}..{self.test_end}], "
            f"ret={self.total_return_pct:.2f}%, sharpe={self.sharpe_ratio:.2f}, trades={self.total_trades}, "
            f"leakage_ok={self.leakage_ok})"
        )


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
    folds: list[FoldBacktestResult]
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Toplu walk-forward sonucunu sözlük formatında döndürür.

        Returns:
            dict[str, Any]: Özet metrikler ve tüm fold detaylarını içeren sözlük.
        """
        d = {k: v for k, v in self.__dict__.items() if k != "folds"}
        d["folds"] = [f.to_dict() for f in self.folds]
        return d

    def __repr__(self) -> str:
        return (
            f"WalkForwardBacktestResult(run_id='{self.run_id}', folds={len(self.folds)}/{self.total_folds}, "
            f"avg_ret={self.avg_test_return_pct:.2f}%, avg_sharpe={self.avg_test_sharpe:.2f}, "
            f"stability={self.stability_score:.2f}, deflated_sharpe={self.deflated_sharpe:.2f})"
        )


class WalkForwardBacktestRunner:
    """Engine v4.0 üzerinde purge + embargo korumalı walk-forward backtest çalıştırıcı."""

    def __init__(
        self,
        backtest_config: BacktestConfig | None = None,
        purge_days: int = DEFAULT_PURGE_DAYS,
        embargo_days: int = DEFAULT_EMBARGO_DAYS,
        train_days: int = DEFAULT_TRAIN_DAYS,
        test_days: int = DEFAULT_TEST_DAYS,
        step_days: int = DEFAULT_STEP_DAYS,
        use_panel_features: bool = True,
    ):
        """WalkForwardBacktestRunner başlatıcı.

        Args:
            backtest_config: Backtest motoru yapılandırması.
            purge_days: Train ile test arasındaki arınma (purge) gün sayısı.
            embargo_days: Test sonrasındaki ambargo gün sayısı.
            train_days: Eğitim penceresi gün sayısı.
            test_days: Test penceresi gün sayısı.
            step_days: Fold kaydırma adımı (gün).
            use_panel_features: Panel çapraz kesit özelliklerin kullanılıp kullanılmayacağı.

        Raises:
            ValueError: Gün değerleri sınır dışındaysa (train < 1, test < 1, purge < 0 vb.).
        """
        if train_days < 1:
            raise ValueError(f"train_days en az 1 olmalıdır: {train_days}")
        if test_days < 1:
            raise ValueError(f"test_days en az 1 olmalıdır: {test_days}")
        if step_days < 1:
            raise ValueError(f"step_days en az 1 olmalıdır: {step_days}")
        if purge_days < 0:
            raise ValueError(f"purge_days negatif olamaz: {purge_days}")
        if embargo_days < 0:
            raise ValueError(f"embargo_days negatif olamaz: {embargo_days}")

        self._config = backtest_config or BacktestConfig()
        self._use_panel = use_panel_features
        self._lock = threading.Lock()
        self._wf = WalkForwardEngine(
            purge_days=purge_days,
            embargo_days=embargo_days,
            train_days=train_days,
            test_days=test_days,
            step_days=step_days,
        )

    def __repr__(self) -> str:
        return (
            f"WalkForwardBacktestRunner(train={self._wf.train_days}, test={self._wf.test_days}, "
            f"step={self._wf.step_days}, purge={self._wf.purge_days}, embargo={self._wf.embargo_days}, "
            f"use_panel={self._use_panel})"
        )

    def run(
        self,
        market_data: dict[str, Any],
        universe_at_date: list[str] | None = None,
        benchmark_data: Any | None = None,
        run_id: str | None = None,
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
        with self._lock:
            # Global tarih listesi (engine ile aynı semantik, date-string)
            all_dates: set[str] = set()
            for df in market_data.values():
                if df is None:
                    continue
                try:
                    if pl is not None and isinstance(df, pl.DataFrame):
                        if "Date" in df.columns:
                            for d in df["Date"].to_list():
                                all_dates.add(str(d)[:10])
                    elif hasattr(df, "columns") and "Date" in df.columns:
                        for d in df["Date"]:
                            all_dates.add(str(d)[:10])
                    elif hasattr(df, "index"):
                        for ts in df.index:
                            all_dates.add(str(ts.date()) if hasattr(ts, "date") else str(ts)[:10])
                    elif isinstance(df, dict) and "Date" in df:
                        for d in df["Date"]:
                            all_dates.add(str(d)[:10])
                except Exception:
                    continue
            dates = sorted(all_dates)

            if run_id is None:
                run_id = self._base_run_id(market_data)

            folds = self._wf.create_folds(dates)
            if not folds:
                logger.warning("Walk-forward fold oluşturulamadı: mevcut_tarih_sayısı=%d", len(dates))
                return self._empty_result(run_id)

        fold_results: list[FoldBacktestResult] = []

        for fold_id, fold in enumerate(folds, 1):
            fold_run_id = f"{run_id}_fold{fold_id:03d}"
            test_start = fold.test_start
            test_end = fold.test_end
            train_start = fold.train_start
            train_end = fold.train_end

            # ====== POINT-IN-TIME KESİT (gelecek veri fiziksel olarak yok) ======
            pit_data = self._truncate(market_data, test_end)

            # ====== ML MODEL EĞİTİMİ (TRAIN window ile) ======
            fold_config = self._config
            if self._config.use_canonical_scoring:
                ml_model = self._train_fold_model(pit_data, train_start, train_end, benchmark_data)
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
            fold_results.append(
                FoldBacktestResult(
                    fold_id=fold_id,
                    train_start=fold.train_start,
                    train_end=fold.train_end,
                    purge_start=fold.purge_start,
                    purge_end=fold.purge_end,
                    test_start=test_start,
                    test_end=test_end,
                    embargo_start=fold.embargo_start,
                    embargo_end=fold.embargo_end,
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
                    final_equity=round(r.equity_curve[-1]["equity"], 2)
                    if r.equity_curve
                    else self._config.initial_capital,
                    elapsed_seconds=round(r.elapsed_seconds, 3),
                    persisted=r.persisted,
                    leakage_ok=leakage_ok,
                    leakage_errors=leakage_errors,
                )
            )

            logger.info(
                "Walk-forward fold tamamlandı: fold=%d, run_id=%s, trades=%d, getiri=%%%.2f, leakage_ok=%s",
                fold_id,
                fold_run_id,
                r.trades_executed,
                m.total_return_pct,
                leakage_ok,
            )

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
        pit_data: dict[str, pl.DataFrame],
        train_start: str,
        train_end: str,
        benchmark_data=None,
    ) -> Any:
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
            from ..features.calculator import feature_calculator
            from ..ml.lightgbm_trainer import DEFAULT_TARGETS, LightGBMTrainer, MLModelConfig
            from ..ml.training_validator import cross_sectional_normalizer, training_validator
        except ImportError:
            return None

        # 1) Train window verisini kes
        train_data: dict[str, Any] = {}
        for ticker, df in pit_data.items():
            if df is None:
                continue
            try:
                if pl is not None and isinstance(df, pl.DataFrame):
                    if len(df) == 0:
                        continue
                    df_train = _filter_polars_by_range(df, train_start, train_end)
                elif hasattr(df, "index"):
                    if len(df) == 0:
                        continue
                    if "Date" in df.columns:
                        s = df["Date"].astype(str).str.slice(0, 10)
                        df_train = df[(s >= train_start[:10]) & (s <= train_end[:10])]
                    else:
                        idx_s = df.index.astype(str).str.slice(0, 10)
                        df_train = df[(idx_s >= train_start[:10]) & (idx_s <= train_end[:10])]
                else:
                    df_train = df

                if len(df_train) >= self.MIN_BARS_FOR_FEATURES:
                    train_data[ticker] = df_train
            except Exception:
                continue

        if len(train_data) < 5:
            return None

        # 2) Her ticker × her uygun gün için sample oluştur
        calc = feature_calculator
        features_map: dict[str, dict] = {}
        returns: dict[str, float] = {}
        date_groups: dict[str, str] = {}

        # En büyük horizon kadar son günleri atla (horizon-aware)
        max_horizon = self.FORWARD_DAYS  # Varsayılan 5d

        for ticker, df in train_data.items():
            n = len(df)
            first_feature_idx = self.MIN_BARS_FOR_FEATURES - 1
            last_feature_idx = n - max_horizon - 1

            if last_feature_idx < first_feature_idx:
                continue

            if pl is not None and isinstance(df, pl.DataFrame):
                close_all = df["Close"].to_numpy() if "Close" in df.columns else np.array([])
            elif hasattr(df, "columns") and "Close" in df.columns:
                close_all = df["Close"].to_numpy() if hasattr(df["Close"], "to_numpy") else df["Close"].values
            else:
                continue

            for idx in range(first_feature_idx, last_feature_idx + 1):
                df_slice = df[: idx + 1]
                feats = calc.compute_all_features(df_slice, ticker=ticker)
                if not feats:
                    continue

                c_t = close_all[idx]
                c_t_fwd = close_all[idx + self.FORWARD_DAYS]
                if c_t <= 0 or np.isnan(c_t) or np.isnan(c_t_fwd):
                    continue
                forward_ret = (c_t_fwd / c_t - 1.0) * 100.0

                if pl is not None and isinstance(df, pl.DataFrame) and "Date" in df.columns:
                    date_str = str(df["Date"][idx])[:10]
                elif hasattr(df, "columns") and "Date" in df.columns:
                    date_str = str(df["Date"].iloc[idx])[:10]
                elif hasattr(df, "index"):
                    feature_date = df.index[idx]
                    date_str = str(feature_date.date()) if hasattr(feature_date, "date") else str(feature_date)[:10]
                else:
                    date_str = f"bar_{idx}"

                sample_key = f"{ticker}::{date_str}"

                if sample_key in features_map:
                    continue

                features_map[sample_key] = feats
                returns[sample_key] = forward_ret
                date_groups[sample_key] = date_str

        n_samples = len(features_map)
        if n_samples < self.MIN_TRAINING_SAMPLES:
            logger.warning(
                "ML eğitimi için yetersiz örnek, kural tabanlı yönteme geçiliyor: örnek=%d, asgari=%d",
                n_samples,
                self.MIN_TRAINING_SAMPLES,
            )
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
        features_map, clean_stats = training_validator.clean_features(features_map, feature_names)
        if clean_stats["inf_replaced"] > 0 or clean_stats["outliers_clamped"] > 0:
            logger.info(
                "Öznitelik temizleme uygulandı: inf_degistirilen=%d, aykiri_baskilanan=%d",
                clean_stats.get("inf_replaced", 0),
                clean_stats.get("outliers_clamped", 0),
            )

        quality_report = training_validator.validate_dataset(features_map, returns, date_groups, feature_names)
        logger.info(
            "Eğitim veri kalitesi: kalite_skoru=%.2f, gecerli_ornek=%d, hisse_sayisi=%d, tarih_sayisi=%d",
            quality_report.quality_score,
            quality_report.valid_samples,
            quality_report.unique_tickers,
            quality_report.unique_dates,
        )

        # 6) Cross-Sectional Normalization (PIT-safe: sadece aynı tarih snapshot'ı)
        #    CS feature'ları feature contract'a eklenir
        cs_feature_names = []
        try:
            # Sadece temel feature'ları normalize et (CS suffix'li olanları değil)
            base_features = [f for f in feature_names if not f.endswith("_cs_zscore") and not f.endswith("_cs_rank")]
            features_map = cross_sectional_normalizer.normalize_zscore_by_date(features_map, date_groups, base_features)
            # CS feature isimlerini topla
            sample_feats = list(features_map.values())[0] if features_map else {}
            cs_feature_names = sorted([k for k in sample_feats if k.endswith("_cs_zscore")])
            # Feature listesini güncelle (orijinal + CS)
            all_feature_names = feature_names + cs_feature_names
            all_feature_names = list(dict.fromkeys(all_feature_names))  # Unique, order preserved
            logger.info(
                "Yatay kesit normalizasyonu uygulandı: cs_oznitelik=%d, toplam_oznitelik=%d",
                len(cs_feature_names),
                len(all_feature_names),
            )
        except Exception as e:
            logger.warning("Yatay kesit normalizasyonu başarısız, temel öznitelikler kullanılacak: hata=%s", str(e))
            all_feature_names = feature_names

        # 7) Multi-horizon eğitim (1d, 5d, 20d, 60d)
        from ..ml.lightgbm_trainer import DEFAULT_TARGETS, MultiHorizonModel

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
                logger.info(
                    "Ufuk atlandı (yetersiz tarih sayısı): ufuk=%d, tarih_sayisi=%d, purge=%d",
                    horizon,
                    n_dates,
                    effective_purge,
                )
                continue

            # Bu horizon için target hesapla (sadece features_map'teki sample'lar için)
            horizon_returns: dict[str, float] = {}
            for ticker, df in train_data.items():
                if pl is not None and isinstance(df, pl.DataFrame):
                    close_all = df["Close"].to_numpy() if "Close" in df.columns else np.array([])
                elif hasattr(df, "columns") and "Close" in df.columns:
                    close_all = df["Close"].to_numpy() if hasattr(df["Close"], "to_numpy") else df["Close"].values
                else:
                    continue
                n = len(df)
                first_idx = self.MIN_BARS_FOR_FEATURES - 1
                last_idx = n - horizon - 1
                for idx in range(first_idx, last_idx + 1):
                    c_t = close_all[idx]
                    c_fwd = close_all[idx + horizon]
                    if c_t <= 0 or not np.isfinite(c_t) or not np.isfinite(c_fwd):
                        continue
                    if pl is not None and isinstance(df, pl.DataFrame) and "Date" in df.columns:
                        date_str = str(df["Date"][idx])[:10]
                    elif hasattr(df, "columns") and "Date" in df.columns:
                        date_str = str(df["Date"].iloc[idx])[:10]
                    elif hasattr(df, "index"):
                        feature_date = df.index[idx]
                        date_str = str(feature_date.date()) if hasattr(feature_date, "date") else str(feature_date)[:10]
                    else:
                        date_str = f"bar_{idx}"
                    sample_key = f"{ticker}::{date_str}"
                    if sample_key in features_map and sample_key not in horizon_returns:
                        horizon_returns[sample_key] = (c_fwd / c_t - 1.0) * 100.0

            # Sadece bu horizon için target'ı olan sample'ları kullan
            horizon_features = {k: v for k, v in features_map.items() if k in horizon_returns}
            horizon_date_groups = {k: v for k, v in date_groups.items() if k in horizon_returns}

            if len(horizon_features) < self.MIN_TRAINING_SAMPLES:
                logger.info(
                    "Ufuk atlandı (yetersiz örnek sayısı): ufuk=%d, ornek_sayisi=%d",
                    horizon,
                    len(horizon_features),
                )
                continue

            config = MLModelConfig(
                num_boost_round=50,
                early_stopping_rounds=5,
                purge_gap_days=effective_purge,
                target_horizon=horizon,
            )
            trainer = LightGBMTrainer(config)
            h_model = trainer.train(
                horizon_features,
                horizon_returns,
                horizon_date_groups,
                feature_names=all_feature_names,
                regime="UNKNOWN",
            )

            if h_model is not None:
                h_model.cs_features = cs_feature_names
                multi_model.horizon_models[horizon] = h_model
                vm = h_model.validation_metrics
                logger.info(
                    "Ufuk modeli eğitildi: ufuk=%d, ornekler=%d, ic=%.4f, guven=%.2f",
                    horizon,
                    h_model.train_samples,
                    vm.get("ic", 0.0),
                    getattr(h_model, "confidence_score", 0.0),
                )

        if not multi_model.horizon_models:
            logger.warning("Ufuk modelleri eğitilemedi, kural tabanlı yönteme geçiliyor")
            return None

        logger.info(
            "Çoklu ufuk eğitimi tamamlandı: ufuklar=%s, birincil=%d, toplam_ornek=%d",
            multi_model.available_horizons,
            multi_model.primary_horizon,
            multi_model.total_train_samples,
        )

        # Model metadata'yı DB'ye kaydet (best-effort, crash etmez)
        try:
            import threading

            from ..core.model_persistence import model_persistence

            version = f"fold_{train_start}_{train_end}_h{'_'.join(str(h) for h in multi_model.available_horizons)}"

            def _save() -> Any:
                """Eğitilen model metadata'sını asenkron olarak DuckDB havuzuna kaydeder."""
                import asyncio

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(
                        model_persistence.save_model_metadata(
                            model_name="alpha_bist_multi_horizon",
                            version=version,
                            model_obj=multi_model,
                            artifact_path="in_memory",
                            training_data_start=train_start,
                            training_data_end=train_end,
                        )
                    )
                except Exception as e:
                    logger.debug("Model metadata kaydı atlandı: hata=%s", str(e))
                finally:
                    loop.close()

            t = threading.Thread(target=_save, daemon=True)
            t.start()
        except Exception:
            logger.warning("Model metadata asenkron kaydı başlatılamadı", exc_info=True)

        return multi_model

    def _get_canonical_feature_names(self) -> list[str]:
        """Canonical feature registry'den feature isimlerini al (regex yok)."""
        if hasattr(self, "_feature_names_cache") and self._feature_names_cache:
            return self._feature_names_cache
        try:
            from ..core.canonical_scoring import get_canonical_features

            self._feature_names_cache = get_canonical_features()
        except Exception:
            self._feature_names_cache = []
        return self._feature_names_cache

    # ------------------------------------------------------------------
    # GUARDS
    # ------------------------------------------------------------------

    @staticmethod
    def _truncate(
        market_data: dict[str, Any],
        test_end: str,
    ) -> dict[str, Any]:
        """Veriyi test_end'e kadar kes (point-in-time).

        Gelecek veriyi fiziksel olarak yok eder. Polars ve Pandas uyumludur.

        Args:
            market_data: {ticker: DataFrame} sözlüğü.
            test_end: Kesme tarihi ('YYYY-MM-DD').

        Returns:
            dict[str, Any]: test_end tarihine kadar filtrelenmiş piyasa verisi.
        """
        pit = {}
        for ticker, df in market_data.items():
            if df is None:
                continue
            try:
                if pl is not None and isinstance(df, pl.DataFrame):
                    if len(df) == 0:
                        continue
                    cut = _filter_polars_by_date(df, test_end)
                    if len(cut) > 0:
                        pit[ticker] = cut
                elif hasattr(df, "index") and hasattr(df, "loc"):
                    if len(df) == 0:
                        continue
                    if "Date" in df.columns:
                        s = df["Date"].astype(str).str.slice(0, 10)
                        cut = df[s <= test_end[:10]]
                    else:
                        idx_s = df.index.astype(str).str.slice(0, 10)
                        cut = df[idx_s <= test_end[:10]]
                    if len(cut) > 0:
                        pit[ticker] = cut
                elif isinstance(df, dict) and "Date" in df:
                    dates = df["Date"]
                    indices = [i for i, d in enumerate(dates) if str(d)[:10] <= test_end[:10]]
                    if indices:
                        pit[ticker] = {k: [v[i] for i in indices] for k, v in df.items()}
                else:
                    pit[ticker] = df
            except Exception as e:
                logger.debug("Truncate hatası, ticker=%s, error=%s", ticker, str(e))
                continue
        return pit

    @staticmethod
    def _verify_fold(
        fold: Any,
        result: BacktestResultV4,
        pit_data: dict[str, Any],
        test_end: str,
    ) -> tuple[bool, list[str]]:
        """Fold leakage doğrulaması.

        Kontroller:
        1. Purge: train_end < purge_start <= purge_end < test_start
        2. Embargo metadata: test_end < embargo_start (varsa)
        3. PIT: hiçbir hissenin verisi test_end'i aşmıyor
        4. Trade'ler test penceresi içinde
        5. Equity tarihleri test penceresi içinde

        Args:
            fold: Fold yapılandırma nesnesi.
            result: BacktestResultV4 sonucu.
            pit_data: Test sonuna kadar kesilmiş veri kümesi.
            test_end: Test bitiş tarihi.

        Returns:
            tuple[bool, list[str]]: (Doğrulama başarılı mı, hata mesajları listesi).
        """
        errors = []

        # 1-2. Fold sınır bütünlüğü
        if not (fold.train_end < fold.purge_start <= fold.purge_end < fold.test_start):
            errors.append(
                f"Purge ihlali: train_end={fold.train_end} "
                f"purge=[{fold.purge_start},{fold.purge_end}] "
                f"test_start={fold.test_start}"
            )
        if fold.embargo_start < fold.test_end and fold.embargo_start != fold.test_end:
            errors.append(f"Embargo ihlali: test_end={fold.test_end} embargo_start={fold.embargo_start}")

        # 3. Point-in-time veri kontrolü
        for ticker, df in pit_data.items():
            last_str = ""
            if pl is not None and isinstance(df, pl.DataFrame):
                if "Date" in df.columns and len(df) > 0:
                    last_str = str(df["Date"][-1])[:10]
            elif hasattr(df, "index") and len(df) > 0:
                if "Date" in df.columns:
                    last_str = str(df["Date"].iloc[-1])[:10]
                else:
                    last = df.index[-1]
                    last_str = str(last.date()) if hasattr(last, "date") else str(last)[:10]
            elif isinstance(df, dict) and "Date" in df and len(df["Date"]) > 0:
                last_str = str(df["Date"][-1])[:10]

            if last_str and last_str > test_end:
                errors.append(f"PIT ihlali: {ticker} verisi {last_str} > {test_end}")
                break

        # 4-5. Trade / equity pencere kontrolü
        for t in result.trades:
            trade_date = t.get("date", "") if isinstance(t, dict) else getattr(t, "date", "")
            if trade_date and not (fold.test_start <= trade_date <= fold.test_end):
                ticker_name = t.get("ticker", "") if isinstance(t, dict) else getattr(t, "ticker", "")
                errors.append(f"Trade pencere dışı: {ticker_name} @ {trade_date}")
                break

        for s in result.equity_curve:
            curve_date = s.get("date", "") if isinstance(s, dict) else getattr(s, "date", "")
            if curve_date and not (fold.test_start <= curve_date <= fold.test_end):
                errors.append(f"Equity pencere dışı: {curve_date}")
                break

        return len(errors) == 0, errors

    # ------------------------------------------------------------------
    # AGGREGATION
    # ------------------------------------------------------------------

    def _aggregate(
        self,
        run_id: str,
        folds: list[FoldBacktestResult],
    ) -> WalkForwardBacktestResult:
        """Tüm fold sonuçlarını toplulaştırıp özet metrikleri hesaplar.

        Args:
            run_id: Birleşik yürütme kimliği.
            folds: Tamamlanan ve doğrulanan fold sonuçları listesi.

        Returns:
            WalkForwardBacktestResult: Ortalama Sharpe, stabilite skoru, deflated Sharpe
            ve fold özetlerini içeren sonuç nesnesi.
        """
        if not folds:
            return self._empty_result(run_id)

        returns = [f.total_return_pct for f in folds if math.isfinite(f.total_return_pct)]
        sharpes = [f.sharpe_ratio for f in folds if math.isfinite(f.sharpe_ratio)]
        sortinos = [f.sortino_ratio for f in folds if math.isfinite(f.sortino_ratio)]
        dds = [f.max_drawdown_pct for f in folds if math.isfinite(f.max_drawdown_pct)]
        wins = [f.win_rate_pct for f in folds if math.isfinite(f.win_rate_pct)]

        mean_ret = float(np.mean(returns)) if returns else 0.0
        std_ret = float(np.std(returns)) if len(returns) > 1 else 0.0
        stability = max(0.0, 1.0 - std_ret / (abs(mean_ret) + 0.01)) if math.isfinite(std_ret) else 0.0

        # Deflated Sharpe (v5.0 — scipy tabanlı, skewness/kurtosis düzeltmeli)
        try:
            from scipy.stats import kurtosis as _kurtosis
            from scipy.stats import skew as _skew

            _sk = float(_skew(returns)) if len(returns) > 10 else 0.0
            _kt = float(_kurtosis(returns, fisher=False)) if len(returns) > 10 else 3.0
        except ImportError:
            _sk, _kt = 0.0, 3.0
        deflated = self._wf._deflated_sharpe(
            float(np.mean(sharpes)) if sharpes else 0.0,
            max(sum(f.total_scans for f in folds), 1),
            len(folds),
            skewness=_sk,
            kurtosis=_kt,
        )
        safe_deflated = float(deflated) if math.isfinite(deflated) else 0.0

        return WalkForwardBacktestResult(
            run_id=run_id,
            total_folds=len(folds),
            avg_test_return_pct=round(mean_ret, 4),
            avg_test_sharpe=round(float(np.mean(sharpes)), 4) if sharpes else 0.0,
            avg_test_sortino=round(float(np.mean(sortinos)), 4) if sortinos else 0.0,
            avg_test_max_drawdown_pct=round(float(np.mean(dds)), 4) if dds else 0.0,
            avg_win_rate_pct=round(float(np.mean(wins)), 4) if wins else 0.0,
            stability_score=round(stability, 4),
            worst_fold_return_pct=round(float(min(returns)), 4) if returns else 0.0,
            best_fold_return_pct=round(float(max(returns)), 4) if returns else 0.0,
            deflated_sharpe=round(safe_deflated, 4),
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
                "engine": "BacktestEngineV4 + WalkForwardEngineV5",
            },
        )

    def _base_run_id(self, market_data: dict[str, Any]) -> str:
        """Piyasa verisi evreni ve yapılandırmaya göre deterministik run_id üretir.

        Args:
            market_data: Ticker verilerini içeren sözlük.

        Returns:
            str: 12 karakterlik benzersiz sha256 özet kimliği.
        """
        tickers = sorted(market_data.keys())
        wf_cfg = (
            self._wf.purge_days,
            self._wf.embargo_days,
            self._wf.train_days,
            self._wf.test_days,
            self._wf.step_days,
        )
        hash_input = f"wf_{','.join(tickers)}_{self._config.to_dict()}_{wf_cfg}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:12]

    def _empty_result(self, run_id: str) -> WalkForwardBacktestResult:
        """Fold oluşturulamaması durumunda boş walk-forward sonucunu döndürür.

        Args:
            run_id: Yürütme kimliği.

        Returns:
            WalkForwardBacktestResult: Sıfırlanmış boş sonuç nesnesi.
        """
        return WalkForwardBacktestResult(
            run_id=run_id,
            total_folds=0,
            avg_test_return_pct=0.0,
            avg_test_sharpe=0.0,
            avg_test_sortino=0.0,
            avg_test_max_drawdown_pct=0.0,
            avg_win_rate_pct=0.0,
            stability_score=0.0,
            worst_fold_return_pct=0.0,
            best_fold_return_pct=0.0,
            deflated_sharpe=0.0,
            total_trades=0,
            all_leakage_ok=True,
            folds=[],
            summary={},
        )


# ============================================================================
# SINGLETON VE DIŞA AKTARIM
# ============================================================================
walk_forward_runner: WalkForwardBacktestRunner = WalkForwardBacktestRunner()

__all__ = [
    "DEFAULT_EMBARGO_DAYS",
    "DEFAULT_PURGE_DAYS",
    "DEFAULT_STEP_DAYS",
    "DEFAULT_TEST_DAYS",
    "DEFAULT_TRAIN_DAYS",
    "FoldBacktestResult",
    "WalkForwardBacktestResult",
    "WalkForwardBacktestRunner",
    "walk_forward_runner",
]
