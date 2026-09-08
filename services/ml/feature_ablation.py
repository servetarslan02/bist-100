# c:\Users\serve\Downloads\Compressed\bist-100\services\ml\feature_ablation.py
"""Öznitelik Ablasyon ve Fazlalık Analizi Motoru (Feature Ablation & Redundancy Engine).

Bu modül, BIST-100 kantitatif modellerinde kullanılan özniteliklerin (features) tek tek veya
gruplar halinde kaldırılarak sistem performansına (Sharpe, CAGR, Max Drawdown) etkisini ölçer.
Zararlı, gürültü üreten veya aşırı korele (redundant) öznitelikleri tespit ederek modelin
aşırı öğrenmesini (overfitting) engeller ve genelleme kabiliyetini maksimize eder.

Kullanım Prensipleri:
- Sıfır Veri Sızıntısı (Zero Data Leakage / Point-In-Time): Yalnızca geçmiş verilerle eğitilir;
  purge ve embargo sürelerine katı biçimde uyulur.
- Eşzamanlılık Güvenliği: `threading.RLock()` ile çoklu iş parçacığı koruması.
- DuckDB Entegrasyonu: SSD korumalı WAL ayarları ile denetim izi kaydı.
- Polars Desteği: Doğrudan Polars DataFrame üzerinden korelasyon ve fazlalık analizi.
- Fail-Closed Mimarisi: Veri eksikliği veya sayısal taşmalarda güvenli geri dönüşler.
"""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

from services.backtest.execution_engine import BacktestEngine
from services.backtest.walk_forward import WalkForwardEngine
from services.core.alpha_engine import AlphaEngine
from services.core.risk_manager import RiskManager

logger = structlog.get_logger(__name__)

# ==============================================================================
# 1. STANDART YAPILANDIRMA SABİTLERİ (DEFAULT_*)
# ==============================================================================
DEFAULT_TRAIN_DAYS: Final[int] = 252
DEFAULT_TEST_DAYS: Final[int] = 63
DEFAULT_STEP_DAYS: Final[int] = 63
DEFAULT_PURGE_DAYS: Final[int] = 5
DEFAULT_EMBARGO_DAYS: Final[int] = 5
DEFAULT_TARGET_FOLDS_COUNT: Final[int] = 5
DEFAULT_TOP_PICKS: Final[int] = 10
DEFAULT_EQUAL_WEIGHT: Final[float] = 0.10
DEFAULT_INITIAL_CAPITAL: Final[float] = 100_000.0
DEFAULT_COMMISSION_RATE: Final[float] = 0.001
DEFAULT_SLIPPAGE_PCT: Final[float] = 0.002
DEFAULT_HARMFUL_DIFF_THRESHOLD: Final[float] = 0.05
DEFAULT_NOISE_DIFF_THRESHOLD: Final[float] = 0.00
DEFAULT_REDUNDANCY_CORRELATION_THRESHOLD: Final[float] = 0.85

DEFAULT_DUCKDB_PATH: Final[str] = "data/ml_audit.duckdb"
DEFAULT_WAL_AUTO_CHECKPOINT: Final[str] = "10MB"
DEFAULT_WAL_CHECKPOINT_TIMEOUT: Final[float] = 10.0


def configure_duckdb_wal(
    con: duckdb.DuckDBPyConnection,
    checkpoint_size: str = DEFAULT_WAL_AUTO_CHECKPOINT,
) -> None:
    """DuckDB bağlantısını SSD korumalı WAL sınırları ile optimize eder.

    Args:
        con: Yapılandırılacak DuckDB bağlantısı.
        checkpoint_size: WAL otomatik kontrol noktası boyutu (örn: '10MB').
    """
    try:
        con.execute(f"PRAGMA wal_autocheckpoint='{checkpoint_size}';")
    except Exception as e:
        logger.warning("duckdb_wal_config_failed", error=str(e))


# ==============================================================================
# 2. VERİ MODELLERİ VE TİPLER
# ==============================================================================
class AblationImpact(StrEnum):
    """Ablasyon etkisi sınıflandırması."""

    HARMFUL = "HARMFUL"  # Çıkarıldığında sistem performansı arttı (kesinlikle zararlı)
    NOISY = "NOISY"  # Çıkarıldığında hafif artış veya değişim yok (gürültü)
    BENEFICIAL = "BENEFICIAL"  # Çıkarıldığında performans düştü (öznitelik faydalı ve tutulmalı)


@dataclass(slots=True)
class FeatureMetrics:
    """Tek bir ablasyon denemesinde elde edilen finansal/backtest metrikleri."""

    cagr_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate_pct: float = 0.0
    calmar_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Metrikleri standart sözlük formatına çevirir."""
        return {
            "cagr_pct": float(self.cagr_pct),
            "max_drawdown_pct": float(self.max_drawdown_pct),
            "sharpe_ratio": float(self.sharpe_ratio),
            "win_rate_pct": float(self.win_rate_pct),
            "calmar_ratio": float(self.calmar_ratio),
        }

    def to_orjson_bytes(self) -> bytes:
        """Metrikleri yüksek hızlı serileştirilmiş orjson byte dizisine çevirir."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeatureMetrics:
        """Sözlükten FeatureMetrics nesnesi oluşturur."""
        return cls(
            cagr_pct=float(data.get("cagr_pct", 0.0)),
            max_drawdown_pct=float(data.get("max_drawdown_pct", 0.0)),
            sharpe_ratio=float(data.get("sharpe_ratio", 0.0)),
            win_rate_pct=float(data.get("win_rate_pct", 0.0)),
            calmar_ratio=float(data.get("calmar_ratio", 0.0)),
        )

    def __repr__(self) -> str:
        """Kullanıcı dostu metin temsili."""
        return (
            f"FeatureMetrics(cagr={self.cagr_pct:.2f}%, max_dd={self.max_drawdown_pct:.2f}%, "
            f"sharpe={self.sharpe_ratio:.2f}, calmar={self.calmar_ratio:.2f})"
        )


@dataclass(slots=True)
class FeatureAblationItem:
    """Tek bir özniteliğin ablasyon test sonucu."""

    feature_name: str
    baseline_metrics: FeatureMetrics
    ablated_metrics: FeatureMetrics
    sharpe_diff: float
    cagr_diff: float
    maxdd_diff: float
    impact: AblationImpact
    recommendation: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Ablasyon öğesini sözlük yapısına çevirir."""
        return {
            "feature_name": self.feature_name,
            "baseline_metrics": self.baseline_metrics.to_dict(),
            "ablated_metrics": self.ablated_metrics.to_dict(),
            "sharpe_diff": float(self.sharpe_diff),
            "cagr_diff": float(self.cagr_diff),
            "maxdd_diff": float(self.maxdd_diff),
            "impact": self.impact.value,
            "recommendation": self.recommendation,
            "metadata": self.metadata,
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı serileştirilmiş orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeatureAblationItem:
        """Sözlükten FeatureAblationItem nesnesi oluşturur."""
        b_raw = data.get("baseline_metrics", {})
        a_raw = data.get("ablated_metrics", {})
        impact_val = data.get("impact", "NOISY")
        try:
            impact_enum = AblationImpact(impact_val)
        except ValueError:
            impact_enum = AblationImpact.NOISY
        return cls(
            feature_name=str(data.get("feature_name", "")),
            baseline_metrics=FeatureMetrics.from_dict(b_raw) if isinstance(b_raw, dict) else b_raw,
            ablated_metrics=FeatureMetrics.from_dict(a_raw) if isinstance(a_raw, dict) else a_raw,
            sharpe_diff=float(data.get("sharpe_diff", 0.0)),
            cagr_diff=float(data.get("cagr_diff", 0.0)),
            maxdd_diff=float(data.get("maxdd_diff", 0.0)),
            impact=impact_enum,
            recommendation=str(data.get("recommendation", "")),
            metadata=dict(data.get("metadata", {})),
        )

    def __repr__(self) -> str:
        """Kullanıcı dostu metin temsili."""
        return (
            f"FeatureAblationItem(feature='{self.feature_name}', impact={self.impact.value}, "
            f"sharpe_diff={self.sharpe_diff:+.3f}, rec='{self.recommendation}')"
        )


@dataclass(slots=True)
class FeatureRedundancyPair:
    """Aşırı korele (fazlalık oluşturan) öznitelik çifti."""

    feature_a: str
    feature_b: str
    correlation: float
    is_redundant: bool
    recommended_to_drop: str

    def to_dict(self) -> dict[str, Any]:
        """Fazlalık çiftini sözlük formatına çevirir."""
        return {
            "feature_a": self.feature_a,
            "feature_b": self.feature_b,
            "correlation": float(self.correlation),
            "is_redundant": self.is_redundant,
            "recommended_to_drop": self.recommended_to_drop,
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı serileştirilmiş orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeatureRedundancyPair:
        """Sözlükten FeatureRedundancyPair nesnesi oluşturur."""
        return cls(
            feature_a=str(data.get("feature_a", "")),
            feature_b=str(data.get("feature_b", "")),
            correlation=float(data.get("correlation", 0.0)),
            is_redundant=bool(data.get("is_redundant", False)),
            recommended_to_drop=str(data.get("recommended_to_drop", "")),
        )

    def __repr__(self) -> str:
        """Kullanıcı dostu metin temsili."""
        return (
            f"FeatureRedundancyPair({self.feature_a} <-> {self.feature_b}, "
            f"corr={self.correlation:.3f}, drop='{self.recommended_to_drop}')"
        )


@dataclass(slots=True)
class AblationReport:
    """Kapsamlı ablasyon ve fazlalık denetim raporu."""

    study_id: str
    created_at: str
    base_features: list[str]
    baseline_metrics: FeatureMetrics
    results: list[FeatureAblationItem] = field(default_factory=list)
    redundant_pairs: list[FeatureRedundancyPair] = field(default_factory=list)
    recommended_drops: list[str] = field(default_factory=list)
    retained_features: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Tüm raporu sözlük formatına çevirir."""
        return {
            "study_id": self.study_id,
            "created_at": self.created_at,
            "base_features": self.base_features,
            "baseline_metrics": self.baseline_metrics.to_dict(),
            "results": [r.to_dict() for r in self.results],
            "redundant_pairs": [p.to_dict() for p in self.redundant_pairs],
            "recommended_drops": self.recommended_drops,
            "retained_features": self.retained_features,
        }

    def to_orjson_bytes(self) -> bytes:
        """Raporu orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AblationReport:
        """Sözlükten AblationReport nesnesi oluşturur."""
        bm_raw = data.get("baseline_metrics", {})
        res_raw = data.get("results", [])
        pairs_raw = data.get("redundant_pairs", [])
        return cls(
            study_id=str(data.get("study_id", "")),
            created_at=str(data.get("created_at", "")),
            base_features=[str(f) for f in data.get("base_features", [])],
            baseline_metrics=FeatureMetrics.from_dict(bm_raw) if isinstance(bm_raw, dict) else bm_raw,
            results=[(FeatureAblationItem.from_dict(r) if isinstance(r, dict) else r) for r in res_raw],
            redundant_pairs=[(FeatureRedundancyPair.from_dict(p) if isinstance(p, dict) else p) for p in pairs_raw],
            recommended_drops=[str(d) for d in data.get("recommended_drops", [])],
            retained_features=[str(r) for r in data.get("retained_features", [])],
        )

    def __repr__(self) -> str:
        """Kullanıcı dostu metin temsili."""
        return (
            f"AblationReport(study_id='{self.study_id}', base_count={len(self.base_features)}, "
            f"drops={len(self.recommended_drops)}, retained={len(self.retained_features)})"
        )


# ==============================================================================
# 3. YARDIMCI GÜVENLİK VE METRİK AYIKLAMA FONKSİYONLARI
# ==============================================================================
def extract_feature_metrics(raw_metrics: Any) -> FeatureMetrics:
    """Sözlük veya nesne olarak dönen backtest metriklerini güvenli biçimde FeatureMetrics'e dönüştürür.

    Args:
        raw_metrics: Sözlük veya nesne tipinde ham metrik çıktısı.

    Returns:
        Doğrulanmış ve NaN/Inf korumalı FeatureMetrics nesnesi.
    """
    if raw_metrics is None:
        return FeatureMetrics()

    def _safe_float(val: Any, default: float = 0.0) -> float:
        if val is None:
            return default
        try:
            num = float(val)
            return num if np.isfinite(num) else default
        except (ValueError, TypeError):
            return default

    if isinstance(raw_metrics, dict):
        cagr = _safe_float(raw_metrics.get("cagr_pct", raw_metrics.get("cagr", 0.0)))
        maxdd = _safe_float(raw_metrics.get("max_drawdown_pct", raw_metrics.get("maxdd", 0.0)))
        sharpe = _safe_float(raw_metrics.get("sharpe_ratio", raw_metrics.get("sharpe", 0.0)))
        win_rate = _safe_float(raw_metrics.get("win_rate_pct", raw_metrics.get("win_rate", 0.0)))
        calmar = _safe_float(raw_metrics.get("calmar_ratio", raw_metrics.get("calmar", 0.0)))
        return FeatureMetrics(
            cagr_pct=cagr,
            max_drawdown_pct=maxdd,
            sharpe_ratio=sharpe,
            win_rate_pct=win_rate,
            calmar_ratio=calmar,
        )

    # Nesne (attribute) olarak okuma
    cagr = _safe_float(getattr(raw_metrics, "cagr_pct", getattr(raw_metrics, "cagr", 0.0)))
    maxdd = _safe_float(getattr(raw_metrics, "max_drawdown_pct", getattr(raw_metrics, "maxdd", 0.0)))
    sharpe = _safe_float(getattr(raw_metrics, "sharpe_ratio", getattr(raw_metrics, "sharpe", 0.0)))
    win_rate = _safe_float(getattr(raw_metrics, "win_rate_pct", getattr(raw_metrics, "win_rate", 0.0)))
    calmar = _safe_float(getattr(raw_metrics, "calmar_ratio", getattr(raw_metrics, "calmar", 0.0)))

    return FeatureMetrics(
        cagr_pct=cagr,
        max_drawdown_pct=maxdd,
        sharpe_ratio=sharpe,
        win_rate_pct=win_rate,
        calmar_ratio=calmar,
    )


# ==============================================================================
# 4. ABLASYON VE FAZLALIK ANALİZİ ÇEKİRDEK MOTORU
# ==============================================================================
class FeatureAblator:
    """Öznitelik ablasyonu, model hassasiyeti ve gereksizlik (redundancy) analizi motoru."""

    def __init__(
        self,
        base_features: list[str],
        train_days: int = DEFAULT_TRAIN_DAYS,
        test_days: int = DEFAULT_TEST_DAYS,
        step_days: int = DEFAULT_STEP_DAYS,
        purge_days: int = DEFAULT_PURGE_DAYS,
        embargo_days: int = DEFAULT_EMBARGO_DAYS,
        target_folds_count: int = DEFAULT_TARGET_FOLDS_COUNT,
        harmful_diff_threshold: float = DEFAULT_HARMFUL_DIFF_THRESHOLD,
        noise_diff_threshold: float = DEFAULT_NOISE_DIFF_THRESHOLD,
    ) -> None:
        """FeatureAblator motorunu başlatır.

        Args:
            base_features: İncelenecek temel öznitelik listesi.
            train_days: Eğitim penceresi gün sayısı.
            test_days: Test penceresi gün sayısı.
            step_days: Walk-forward adım gün sayısı.
            purge_days: Purge penceresi gün sayısı (sıfır veri sızıntısı).
            embargo_days: Embargo penceresi gün sayısı.
            target_folds_count: Hızlı ablasyonda kullanılacak son fold sayısı.
            harmful_diff_threshold: Bir özniteliğin kesin zararlı kabul edilme Sharpe fark eşiği.
            noise_diff_threshold: Bir özniteliğin gürültü kabul edilme Sharpe fark eşiği.

        Raises:
            ValueError: `base_features` boş veya geçersizse.
        """
        if not base_features:
            raise ValueError("base_features listesi bos olamaz.")

        self._lock: Final[threading.RLock] = threading.RLock()
        self._base_features: list[str] = list(dict.fromkeys(base_features))  # Tekilleştirilmiş
        self._harmful_threshold: float = harmful_diff_threshold
        self._noise_threshold: float = noise_diff_threshold
        self._target_folds_count: int = target_folds_count

        self.engine: AlphaEngine = AlphaEngine()
        self.rm: RiskManager = RiskManager()
        self.wf: WalkForwardEngine = WalkForwardEngine(
            train_days=train_days,
            test_days=test_days,
            step_days=step_days,
            purge_days=purge_days,
            embargo_days=embargo_days,
        )

        logger.info(
            "feature_ablator_initialized",
            feature_count=len(self._base_features),
            target_folds=self._target_folds_count,
            harmful_threshold=self._harmful_threshold,
        )

    @property
    def base_features(self) -> list[str]:
        """Temel öznitelik listesinin kopyasını döndürür."""
        with self._lock:
            return list(self._base_features)

    def _run_ablation_test(
        self,
        active_features: list[str],
        market_data: dict[str, pl.DataFrame],
        bm_df: pl.DataFrame,
        sector_map: dict[str, str],
        common_dates: list[str],
    ) -> FeatureMetrics:
        """Belirtilen aktif öznitelik seti ile Walk-Forward OOS testi çalıştırır ve metrik üretir.

        Args:
            active_features: Modelde aktif tutulacak öznitelik listesi.
            market_data: Ticker bazlı piyasa verileri sözlüğü (Polars DataFrame).
            bm_df: Benchmark endeks verisi.
            sector_map: Sektör eşleme sözlüğü.
            common_dates: Ortak işlem tarihleri listesi.

        Returns:
            Elde edilen FeatureMetrics nesnesi.
        """
        with self._lock:
            if not market_data or len(common_dates) == 0:
                logger.warning("ablation_test_aborted_insufficient_data")
                return FeatureMetrics()

            all_signals: list[dict[str, Any]] = []
            folds = self.wf.create_folds(common_dates)
            if not folds:
                logger.warning("ablation_test_no_folds_generated")
                return FeatureMetrics()

            target_folds = folds[-self._target_folds_count :]

            for fold in target_folds:
                if isinstance(self.engine.params, dict):
                    self.engine.params["feature_fraction"] = 1.0

                success = self.engine.train(
                    market_data,
                    bm_df,
                    sector_map,
                    fold["train_start"],
                    fold["train_end"],
                )
                if not success:
                    continue

                preds = self.engine.predict(market_data, bm_df, sector_map, fold["test_start"])
                if not preds:
                    continue

                top_picks = preds[:DEFAULT_TOP_PICKS]
                for pick in top_picks:
                    ticker = pick.get("ticker")
                    if not ticker:
                        continue

                    df_t = market_data.get(ticker)
                    if df_t is None or len(df_t) == 0:
                        continue

                    if "Date" not in df_t.columns:
                        continue

                    df_test = df_t.filter(
                        (pl.col("Date") >= fold["test_start"]) & (pl.col("Date") <= fold["test_end"])
                    )
                    if len(df_test) == 0:
                        continue

                    start_date_str = str(df_test["Date"][0])[:10]
                    end_date_str = str(df_test["Date"][-1])[:10]
                    score = float(pick.get("score", 0.0))

                    all_signals.append(
                        {
                            "date": start_date_str,
                            "ticker": ticker,
                            "action": "BUY",
                            "score": score,
                            "weight": DEFAULT_EQUAL_WEIGHT,
                        }
                    )
                    all_signals.append(
                        {
                            "date": end_date_str,
                            "ticker": ticker,
                            "action": "SELL",
                            "score": score,
                            "weight": DEFAULT_EQUAL_WEIGHT,
                        }
                    )

            if not all_signals:
                return FeatureMetrics()

            # Polars verilerini optimize edilmiş şekilde derle
            price_data_formatted: dict[str, list[dict[str, Any]]] = {}
            for ticker, df_t in market_data.items():
                if df_t is None or len(df_t) == 0:
                    continue
                if not all(col in df_t.columns for col in ["Date", "Close", "Volume"]):
                    continue

                # Polars vektörize liste çıkarımı
                dates = [str(d)[:10] for d in df_t["Date"].to_list()]
                closes = df_t["Close"].cast(pl.Float64).fill_nan(0.0).to_list()
                volumes = df_t["Volume"].cast(pl.Float64).fill_nan(0.0).to_list()

                rows = [
                    {"date": d, "close": c, "volume": v}
                    for d, c, v in zip(dates, closes, volumes, strict=False)
                ]
                price_data_formatted[ticker] = rows

            backtest = BacktestEngine()
            report = backtest.run_backtest(
                strategy_name="Ablation",
                price_data=price_data_formatted,
                signals=all_signals,
                initial_capital=DEFAULT_INITIAL_CAPITAL,
                commission_rate=DEFAULT_COMMISSION_RATE,
                slippage_pct=DEFAULT_SLIPPAGE_PCT,
                dump_ledger=False,
                stop_loss_pct=1.0,
                trailing_stop_pct=1.0,
                market_regime=1.0,
            )

            raw_metrics = getattr(report, "metrics", {})
            return extract_feature_metrics(raw_metrics)

    def run_full_ablation(
        self,
        start_date: str = "2021-01-01",
        end_date: str = "2024-11-03",
        redundancy_threshold: float = DEFAULT_REDUNDANCY_CORRELATION_THRESHOLD,
    ) -> AblationReport:
        """Tüm temel öznitelikler üzerinde uçtan uca ablasyon ve fazlalık çalışması yürütür.

        Args:
            start_date: Veri seti başlangıç tarihi.
            end_date: Veri seti bitiş tarihi.
            redundancy_threshold: Aşırı korelasyon tespit eşiği.

        Returns:
            Eksiksiz oluşturulmuş AblationReport raporu.
        """
        with self._lock:
            study_id = f"abl_{uuid.uuid4().hex[:8]}"
            created_at = datetime.now(UTC).isoformat()

            logger.info(
                "ablation_study_started",
                study_id=study_id,
                start_date=start_date,
                end_date=end_date,
                feature_count=len(self._base_features),
            )

            market_data, bm_df, sector_map = self.engine.fetch_data(start_date, end_date)
            common_dates = (
                list(sorted([str(d)[:10] for d in bm_df["Date"]]))
                if bm_df is not None and "Date" in bm_df.columns
                else []
            )

            # Baseline (Tüm öznitelikler devrede) testi
            logger.info("ablation_evaluating_baseline")
            baseline_metrics = self._run_ablation_test(
                self._base_features,
                market_data,
                bm_df,
                sector_map,
                common_dates,
            )
            base_sharpe = baseline_metrics.sharpe_ratio

            logger.info(
                "ablation_baseline_evaluated",
                cagr_pct=baseline_metrics.cagr_pct,
                max_dd_pct=baseline_metrics.max_drawdown_pct,
                sharpe=base_sharpe,
            )

            results: list[FeatureAblationItem] = []
            recommended_drops: list[str] = []

            for i, feature in enumerate(self._base_features, 1):
                logger.info(
                    "ablation_testing_feature",
                    index=i,
                    total=len(self._base_features),
                    dropped_feature=feature,
                )

                self.engine.exclude_features = [feature]
                test_features = [f for f in self._base_features if f != feature]

                ablated_metrics = self._run_ablation_test(
                    test_features,
                    market_data,
                    bm_df,
                    sector_map,
                    common_dates,
                )

                sharpe_diff = ablated_metrics.sharpe_ratio - base_sharpe
                cagr_diff = ablated_metrics.cagr_pct - baseline_metrics.cagr_pct
                maxdd_diff = ablated_metrics.max_drawdown_pct - baseline_metrics.max_drawdown_pct

                if sharpe_diff > self._harmful_threshold:
                    impact = AblationImpact.HARMFUL
                    recommendation = "DROP"
                    recommended_drops.append(feature)
                    logger.warning(
                        "ablation_harmful_feature_detected",
                        feature=feature,
                        sharpe_gain=sharpe_diff,
                    )
                elif sharpe_diff > self._noise_threshold:
                    impact = AblationImpact.NOISY
                    recommendation = "REVIEW"
                    logger.info(
                        "ablation_noisy_feature_detected",
                        feature=feature,
                        sharpe_gain=sharpe_diff,
                    )
                else:
                    impact = AblationImpact.BENEFICIAL
                    recommendation = "KEEP"

                results.append(
                    FeatureAblationItem(
                        feature_name=feature,
                        baseline_metrics=baseline_metrics,
                        ablated_metrics=ablated_metrics,
                        sharpe_diff=sharpe_diff,
                        cagr_diff=cagr_diff,
                        maxdd_diff=maxdd_diff,
                        impact=impact,
                        recommendation=recommendation,
                    )
                )

            # Sıralama: En zararlıdan (en çok kazandıran düşüş) en faydalıya
            results.sort(key=lambda x: x.sharpe_diff, reverse=True)

            # Polars üzerinden öznitelik fazlalık (redundancy) analizi
            redundant_pairs: list[FeatureRedundancyPair] = []
            if market_data:
                first_df = next(iter(market_data.values()), None)
                if first_df is not None:
                    redundant_pairs = analyze_feature_redundancy_polars(
                        first_df,
                        self._base_features,
                        threshold=redundancy_threshold,
                    )

            retained_features = [f for f in self._base_features if f not in recommended_drops]

            report = AblationReport(
                study_id=study_id,
                created_at=created_at,
                base_features=self._base_features,
                baseline_metrics=baseline_metrics,
                results=results,
                redundant_pairs=redundant_pairs,
                recommended_drops=recommended_drops,
                retained_features=retained_features,
            )

            logger.info(
                "ablation_study_completed",
                study_id=study_id,
                harmful_drops=len(recommended_drops),
                retained_count=len(retained_features),
            )

            # Sonuçları otomatik olarak DuckDB'ye kaydet
            try:
                save_ablation_report_to_duckdb(report)
            except Exception as e:
                logger.error("ablation_duckdb_save_failed", error=str(e))

            return report

    def run_fast_analytical_ablation(
        self,
        features_df: pl.DataFrame,
        target_returns: np.ndarray,
        features: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Ağır backtest çalıştırmadan, Polars matrisleri üzerinden hızlı korelasyon/IC bazlı ablasyon analizi yapar.

        Args:
            features_df: Öznitelikleri içeren Polars DataFrame.
            target_returns: Hedef getiri serisi (numpy 1D dizi).
            features: Test edilecek öznitelik isimleri (None ise tüm numerik sütunlar).

        Returns:
            Her bir özniteliğin IC (Information Coefficient), volatilite ve tekil katkı karne listesi.
        """
        with self._lock:
            if features_df is None or len(features_df) == 0 or len(target_returns) == 0:
                return []

            active_cols = features or [
                c
                for c in features_df.columns
                if c != "Date" and features_df[c].dtype in [pl.Float32, pl.Float64, pl.Int32, pl.Int64]
            ]

            results: list[dict[str, Any]] = []
            y = np.asarray(target_returns, dtype=np.float64)

            for col_name in active_cols:
                if col_name not in features_df.columns:
                    continue

                col_arr = (
                    features_df[col_name]
                    .cast(pl.Float64)
                    .fill_null(strategy="forward")
                    .fill_null(0.0)
                    .to_numpy()
                )

                if len(col_arr) != len(y) or np.all(col_arr == col_arr[0]):
                    continue

                # Pearson / Spearmann IC hesaplama
                corr = float(np.corrcoef(col_arr, y)[0, 1])
                ic = 0.0 if np.isnan(corr) else corr
                vol = float(np.std(col_arr))

                results.append(
                    {
                        "feature": col_name,
                        "information_coefficient": ic,
                        "abs_ic": abs(ic),
                        "std_dev": vol,
                        "status": "STRONG" if abs(ic) > 0.05 else ("MODERATE" if abs(ic) > 0.02 else "WEAK"),
                    }
                )

            results.sort(key=lambda x: x["abs_ic"], reverse=True)
            return results

    def __repr__(self) -> str:
        """FeatureAblator nesnesinin metin temsili."""
        return (
            f"FeatureAblator(base_features_count={len(self._base_features)}, "
            f"target_folds={self._target_folds_count}, harmful_th={self._harmful_threshold})"
        )


# ==============================================================================
# 5. POLARS İLE ÖZNİTELİK FAZLALIK (REDUNDANCY) ANALİZİ
# ==============================================================================
def analyze_feature_redundancy_polars(
    df: pl.DataFrame,
    features: list[str],
    threshold: float = DEFAULT_REDUNDANCY_CORRELATION_THRESHOLD,
) -> list[FeatureRedundancyPair]:
    """Polars DataFrame üzerinde öznitelikler arası korelasyon matrisi çıkararak aşırı korele çiftleri belirler.

    Args:
        df: Piyasa verilerini veya feature tablosunu içeren Polars DataFrame.
        features: Korelasyonu incelenecek öznitelikler.
        threshold: Fazlalık (redundancy) sayılacak korelasyon mutlak eşiği (örn: 0.85).

    Returns:
        Tespit edilen FeatureRedundancyPair listesi.
    """
    if df is None or len(df) == 0 or not features:
        return []

    valid_cols = [c for c in features if c in df.columns]
    if len(valid_cols) < 2:
        return []

    pairs: list[FeatureRedundancyPair] = []

    # Polars korelasyon matrisi hesaplama
    for i in range(len(valid_cols)):
        for j in range(i + 1, len(valid_cols)):
            f_a = valid_cols[i]
            f_b = valid_cols[j]

            # İki sütunun korelasyonunu hesapla
            corr_val = df.select(pl.corr(f_a, f_b)).item()
            if corr_val is None or not np.isfinite(corr_val):
                continue

            corr_float = float(corr_val)
            if abs(corr_float) >= threshold:
                # İsim uzunluğu veya alfabetik sıraya göre önerilen eleme
                drop_candidate = f_b if len(f_b) >= len(f_a) else f_a
                pairs.append(
                    FeatureRedundancyPair(
                        feature_a=f_a,
                        feature_b=f_b,
                        correlation=corr_float,
                        is_redundant=True,
                        recommended_to_drop=drop_candidate,
                    )
                )

    pairs.sort(key=lambda x: abs(x.correlation), reverse=True)
    return pairs


# ==============================================================================
# 6. DUCKDB VERİTABANI DENETİM İZİ YÖNETİMİ
# ==============================================================================
def save_ablation_report_to_duckdb(
    report: AblationReport,
    db_path: str = DEFAULT_DUCKDB_PATH,
) -> None:
    """Ablasyon raporunu DuckDB denetim tablosuna SSD korumalı WAL sınırlarıyla kaydeder.

    Args:
        report: Kaydedilecek AblationReport nesnesi.
        db_path: Hedef DuckDB veritabanı dosya yolu.
    """
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    con = duckdb.connect(db_path)
    try:
        configure_duckdb_wal(con)

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS ml_feature_ablation_reports (
                study_id VARCHAR PRIMARY KEY,
                created_at TIMESTAMP,
                base_features_json VARCHAR,
                baseline_cagr DOUBLE,
                baseline_maxdd DOUBLE,
                baseline_sharpe DOUBLE,
                drops_count BIGINT,
                recommended_drops_json VARCHAR,
                results_json VARCHAR
            );
            """
        )

        base_features_json = orjson.dumps(report.base_features).decode("utf-8")
        recommended_drops_json = orjson.dumps(report.recommended_drops).decode("utf-8")
        results_json = orjson.dumps([r.to_dict() for r in report.results]).decode("utf-8")

        con.execute(
            """
            INSERT OR REPLACE INTO ml_feature_ablation_reports
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            [
                report.study_id,
                report.created_at,
                base_features_json,
                report.baseline_metrics.cagr_pct,
                report.baseline_metrics.max_drawdown_pct,
                report.baseline_metrics.sharpe_ratio,
                len(report.recommended_drops),
                recommended_drops_json,
                results_json,
            ],
        )
        logger.info("ablation_report_saved_to_duckdb", study_id=report.study_id, db_path=db_path)
    finally:
        con.close()


def read_ablation_history_polars(
    db_path: str = DEFAULT_DUCKDB_PATH,
    limit: int = 50,
) -> pl.DataFrame:
    """DuckDB'de kayıtlı geçmiş ablasyon çalışmalarını Polars DataFrame olarak döndürür.

    Args:
        db_path: DuckDB veritabanı dosya yolu.
        limit: Alınacak azami rapor sayısı.

    Returns:
        Polars DataFrame formatında rapor geçmişi.
    """
    if not os.path.exists(db_path):
        return pl.DataFrame()

    con = duckdb.connect(db_path, read_only=True)
    try:
        configure_duckdb_wal(con)
        query = f"""
            SELECT study_id, created_at, baseline_cagr, baseline_maxdd, baseline_sharpe,
                   drops_count, recommended_drops_json
            FROM ml_feature_ablation_reports
            ORDER BY created_at DESC
            LIMIT {limit};
        """
        arrow_table = con.execute(query).arrow()
        return pl.from_arrow(arrow_table)
    except Exception as e:
        logger.warning("read_ablation_history_polars_failed", error=str(e))
        return pl.DataFrame()
    finally:
        con.close()


# ==============================================================================
# 7. DIŞA AKTARILAN MODÜL SEMBOLLERİ (__all__)
# ==============================================================================
__all__: Final[list[str]] = [
    "DEFAULT_COMMISSION_RATE",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EMBARGO_DAYS",
    "DEFAULT_EQUAL_WEIGHT",
    "DEFAULT_HARMFUL_DIFF_THRESHOLD",
    "DEFAULT_INITIAL_CAPITAL",
    "DEFAULT_NOISE_DIFF_THRESHOLD",
    "DEFAULT_PURGE_DAYS",
    "DEFAULT_REDUNDANCY_CORRELATION_THRESHOLD",
    "DEFAULT_SLIPPAGE_PCT",
    "DEFAULT_STEP_DAYS",
    "DEFAULT_TARGET_FOLDS_COUNT",
    "DEFAULT_TEST_DAYS",
    "DEFAULT_TRAIN_DAYS",
    "DEFAULT_WAL_AUTO_CHECKPOINT",
    "AblationImpact",
    "FeatureMetrics",
    "FeatureAblationItem",
    "FeatureRedundancyPair",
    "AblationReport",
    "FeatureAblator",
    "extract_feature_metrics",
    "analyze_feature_redundancy_polars",
    "configure_duckdb_wal",
    "save_ablation_report_to_duckdb",
    "read_ablation_history_polars",
]
