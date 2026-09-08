"""ALPHA BIST — Ensemble Modeli ve Çeşitlilik Kapısı v2.0 (Production-Hardened)

BIST pay piyasası için dinamik ağırlıklı ortalama ve stacking topluluk (ensemble) motoru:
- Model Çeşitliliği Analizi (Diversity Analysis: korelasyon matrisi ve gereksiz modellerin tespiti)
- Topluluk Fayda Kapısı (Ensemble Benefit Gate: tek modelden daha iyi değilse ensemble'ı reddetme)
- Otomatik Budama (Auto-Prune: yüksek korelasyonlu model çiftlerinden zayıf olanı eleme)
- Piyasa Rejimine Göre Dinamik Ağırlıklandırma (Regime-aware dynamic weights)
- Model Güven Skoru (Model Agreement / Prediction Confidence)
- Güvenli Durum Kalıcılığı (Save / Load State)
- Polars DataFrame ve DuckDB WAL denetim logu desteği
- threading.RLock eşzamanlı erişim koruması

Kurallar & Standartlar:
- GEMINI.md: "Ensemble default değildir; gerçek ve kanıtlanmış fayda olmadan eklenemez."
- DuckDB WAL optimizasyonu ve orjson yüksek hızlı serileştirme.
- Polars entegrasyonu (pandas yasaktır).
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl  # noqa: TC002
import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)

# ===================== SABİTLER (CONSTANTS) =====================

DEFAULT_DIVERSITY_THRESHOLD: Final[float] = 0.85
DEFAULT_BENEFIT_TOLERANCE: Final[float] = 0.95
DEFAULT_MIN_DIVERSITY: Final[float] = 0.15
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"


# ===================== DUCKDB WAL YARDIMCISI =====================


def configure_duckdb_wal(
    con: duckdb.DuckDBPyConnection,
    checkpoint_size: str = DEFAULT_CHECKPOINT_SIZE,
    wal_size: str = DEFAULT_WAL_SIZE,
) -> None:
    """DuckDB bağlantısında SSD korumalı WAL ve checkpoint parametrelerini yapılandırır.

    Args:
        con: Yapılandırılacak DuckDB bağlantısı.
        checkpoint_size: Otomatik checkpoint eşik boyutu.
        wal_size: Maksimum WAL dosya boyutu.
    """
    con.execute(f"SET checkpoint_threshold = '{checkpoint_size}';")
    con.execute(f"SET wal_autocheckpoint = '{wal_size}';")


# ===================== VERİ MODELLERİ (DATA MODELS) =====================


@dataclass(slots=True)
class DiversityReport:
    """Modeller arası korelasyon ve çeşitlilik (diversity) analizi çıktısı.

    Attributes:
        correlation_matrix: Modeller arası ikili korelasyon matrisi.
        mean_correlation: Ortalama ikili mutlak korelasyon.
        diversity_score: Çeşitlilik skoru (1.0 - mean_correlation).
        redundant_models: Eşik üzerinde korelasyona sahip gereksiz model çiftleri.
        recommendation: Çeşitlilik değerlendirmesi ve model tavsiyesi.
    """

    correlation_matrix: dict[str, dict[str, float]]
    mean_correlation: float
    diversity_score: float
    redundant_models: list[str]
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        """Raporu standart sözlüğe dönüştürür."""
        return {
            "correlation_matrix": self.correlation_matrix,
            "mean_correlation": self.mean_correlation,
            "diversity_score": self.diversity_score,
            "redundant_models": list(self.redundant_models),
            "recommendation": self.recommendation,
        }

    def to_orjson_bytes(self) -> bytes:
        """orjson serileştirmesi döndürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiversityReport:
        """Sözlükten DiversityReport nesnesi oluşturur."""
        corr = data.get("correlation_matrix", {})
        clean_corr = {
            str(k): {str(ik): float(iv) for ik, iv in v.items()}
            for k, v in corr.items()
            if isinstance(v, dict)
        }
        return cls(
            correlation_matrix=clean_corr,
            mean_correlation=float(data.get("mean_correlation", 0.0)),
            diversity_score=float(data.get("diversity_score", 0.0)),
            redundant_models=[str(m) for m in data.get("redundant_models", [])],
            recommendation=str(data.get("recommendation", "")),
        )

    def __repr__(self) -> str:
        return (
            f"DiversityReport(score={self.diversity_score:.4f}, mean_corr={self.mean_correlation:.4f}, "
            f"redundant_count={len(self.redundant_models)}, rec={self.recommendation!r})"
        )


@dataclass(slots=True)
class BenefitReport:
    """Ensemble'ın tekil en iyi modele kıyasla getirdiği net katma değer raporu.

    Attributes:
        ensemble_ic: Topluluk modelinin Information Coefficient (IC) değeri.
        best_individual_ic: Tekil en iyi modelin IC değeri.
        best_individual_name: Tekil en iyi modelin adı.
        ic_improvement: Net IC artışı (ensemble_ic - best_individual_ic).
        is_beneficial: Ensemble kullanımının rasyonel olup olmadığı.
        recommendation: Model seçim tavsiyesi.
    """

    ensemble_ic: float
    best_individual_ic: float
    best_individual_name: str
    ic_improvement: float
    is_beneficial: bool
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        """Raporu sözlüğe dönüştürür."""
        return {
            "ensemble_ic": self.ensemble_ic,
            "best_individual_ic": self.best_individual_ic,
            "best_individual_name": self.best_individual_name,
            "ic_improvement": self.ic_improvement,
            "is_beneficial": self.is_beneficial,
            "recommendation": self.recommendation,
        }

    def to_orjson_bytes(self) -> bytes:
        """orjson serileştirmesi döndürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BenefitReport:
        """Sözlükten BenefitReport nesnesi oluşturur."""
        return cls(
            ensemble_ic=float(data.get("ensemble_ic", 0.0)),
            best_individual_ic=float(data.get("best_individual_ic", 0.0)),
            best_individual_name=str(data.get("best_individual_name", "")),
            ic_improvement=float(data.get("ic_improvement", 0.0)),
            is_beneficial=bool(data.get("is_beneficial", False)),
            recommendation=str(data.get("recommendation", "")),
        )

    def __repr__(self) -> str:
        return (
            f"BenefitReport(beneficial={self.is_beneficial}, ic_delta={self.ic_improvement:+.4f}, "
            f"ensemble_ic={self.ensemble_ic:.4f}, best={self.best_individual_name!r})"
        )


@dataclass(slots=True)
class EnsembleDiagnostics:
    """Topluluk modeli ayrıntılı teşhis ve ağırlık gerekçelendirme raporu.

    Attributes:
        model_weights: Kullanılan model ağırlıkları.
        model_ics: Her modelin tekil IC başarı skoru.
        diversity: Çeşitlilik raporu nesnesi.
        benefit: Fayda kapısı değerlendirme raporu.
        n_models: Değerlendirmeye alınan model adedi.
        n_successful: Başarıyla tahmin üreten model adedi.
        timestamp: Rapor zaman damgası (ISO metni).
    """

    model_weights: dict[str, float]
    model_ics: dict[str, float]
    diversity: DiversityReport
    benefit: BenefitReport
    n_models: int
    n_successful: int
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        """Teşhis verisini sözlüğe dönüştürür."""
        return {
            "model_weights": self.model_weights,
            "model_ics": self.model_ics,
            "diversity": self.diversity.to_dict(),
            "benefit": self.benefit.to_dict(),
            "n_models": self.n_models,
            "n_successful": self.n_successful,
            "timestamp": self.timestamp,
        }

    def to_orjson_bytes(self) -> bytes:
        """orjson serileştirmesi döndürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EnsembleDiagnostics:
        """Sözlükten EnsembleDiagnostics nesnesi oluşturur."""
        weights = {str(k): float(v) for k, v in data.get("model_weights", {}).items()}
        ics = {str(k): float(v) for k, v in data.get("model_ics", {}).items()}
        div_raw = data.get("diversity", {})
        diversity = DiversityReport.from_dict(div_raw) if isinstance(div_raw, dict) else div_raw
        ben_raw = data.get("benefit", {})
        benefit = BenefitReport.from_dict(ben_raw) if isinstance(ben_raw, dict) else ben_raw
        return cls(
            model_weights=weights,
            model_ics=ics,
            diversity=diversity,
            benefit=benefit,
            n_models=int(data.get("n_models", 0)),
            n_successful=int(data.get("n_successful", 0)),
            timestamp=str(data.get("timestamp", "")),
        )

    def __repr__(self) -> str:
        return (
            f"EnsembleDiagnostics(models={self.n_successful}/{self.n_models}, "
            f"beneficial={self.benefit.is_beneficial}, diversity={self.diversity.diversity_score:.2f})"
        )


@dataclass(slots=True)
class EnsembleState:
    """Ensemble modelinin diskte saklanan durum bilgisi.

    Attributes:
        weights: Model ağırlıkları eşlemesi.
        model_names: Topluluğa dahil modellerin adları.
        diversity_scores: Model bazlı tekil çeşitlilik skorları.
        benefit_report: Son kaydedilen fayda raporu.
        training_history: Geçmiş eğitim metrikleri listesi.
        created_at: Durum oluşturulma zaman damgası.
        version: Durum şema sürümü.
    """

    weights: dict[str, float]
    model_names: list[str]
    diversity_scores: dict[str, float]
    benefit_report: BenefitReport | None
    training_history: list[dict[str, Any]]
    created_at: str
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Durum verisini sözlüğe dönüştürür."""
        return {
            "weights": self.weights,
            "model_names": self.model_names,
            "diversity_scores": self.diversity_scores,
            "benefit_report": self.benefit_report.to_dict() if self.benefit_report else None,
            "training_history": self.training_history,
            "created_at": self.created_at,
            "version": self.version,
        }

    def to_orjson_bytes(self) -> bytes:
        """orjson serileştirmesi döndürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EnsembleState:
        """Sözlükten EnsembleState nesnesi oluşturur."""
        weights = {str(k): float(v) for k, v in data.get("weights", {}).items()}
        models = [str(m) for m in data.get("model_names", [])]
        divs = {str(k): float(v) for k, v in data.get("diversity_scores", {}).items()}
        ben_raw = data.get("benefit_report")
        ben = BenefitReport.from_dict(ben_raw) if isinstance(ben_raw, dict) else None
        return cls(
            weights=weights,
            model_names=models,
            diversity_scores=divs,
            benefit_report=ben,
            training_history=list(data.get("training_history", [])),
            created_at=str(data.get("created_at", "")),
            version=int(data.get("version", 1)),
        )

    def __repr__(self) -> str:
        return f"EnsembleState(version={self.version}, models={len(self.model_names)}, created_at={self.created_at!r})"


# ===================== TOPLULUK MODELİ ÇEKİRDEĞİ =====================


class EnsembleModel:
    """ALPHA BIST Dinamik Topluluk ve Çeşitlilik Motoru v2.0.

    Özellikler:
    - Çoklu model ağırlıklı tahmin ve mutabakat güven skoru (confidence)
    - Pearson korelasyonu ile modeller arası çeşitlilik analizi
    - BIST için katı Ensemble Benefit Gate (tek modelden üstünlük şartı)
    - Redundant (birbirini tekrar eden) modelleri otomatik budama (Auto-Prune)
    - Piyasa rejimine duyarlı dinamik ağırlıklandırma
    - DuckDB WAL denetim logu ve Polars DataFrame entegrasyonu
    - threading.RLock eşzamanlı erişim koruması
    """

    def __init__(
        self,
        diversity_threshold: float = DEFAULT_DIVERSITY_THRESHOLD,
        benefit_tolerance: float = DEFAULT_BENEFIT_TOLERANCE,
    ) -> None:
        """EnsembleModel motorunu yapılandırır.

        Args:
            diversity_threshold: Gereksiz benzerlik korelasyon eşiği (varsayılan 0.85).
            benefit_tolerance: Asgari kabul edilebilir IC çarpanı (varsayılan 0.95).
        """
        self._lock = threading.RLock()
        self._state: EnsembleState | None = None
        self._diversity_threshold = max(0.5, min(0.99, float(diversity_threshold)))
        self._benefit_tolerance = max(0.8, min(1.0, float(benefit_tolerance)))

    def __repr__(self) -> str:
        with self._lock:
            loaded = self._state is not None
            models_count = len(self._state.model_names) if self._state else 0
            return (
                f"EnsembleModel(loaded={loaded}, active_models={models_count}, "
                f"div_thr={self._diversity_threshold}, benefit_tol={self._benefit_tolerance})"
            )

    @property
    def state(self) -> EnsembleState | None:
        """Kayıtlı topluluk durumunu döndürür."""
        with self._lock:
            return self._state

    @property
    def is_loaded(self) -> bool:
        """Geçerli bir topluluk durumunun yüklenip yüklenmediğini belirtir."""
        with self._lock:
            return self._state is not None

    def predict(
        self,
        models: dict[str, Callable[[np.ndarray], np.ndarray]],
        weights: dict[str, float],
        X: np.ndarray,
    ) -> np.ndarray:
        """Ağırlıklı topluluk tahmini üretir.

        Args:
            models: {model_adi: tahmin_fonksiyonu} eşleme sözlüğü.
            weights: {model_adi: agirlik_katsayisi} eşleme sözlüğü.
            X: Öznitelik matrisi.

        Returns:
            Ağırlıklı ortalama tahmin dizisi.
        """
        X_arr = np.asarray(X)
        if len(X_arr) == 0 or not models:
            logger.warning("ensemble_tahmin_edilemedi", sebep="bos_veri_veya_model_yok")
            return np.full(len(X_arr), np.nan, dtype=np.float64)

        total_weight = 0.0
        weighted_sum = np.zeros(len(X_arr), dtype=np.float64)
        failed_models: list[str] = []

        for name, fn in models.items():
            w = float(weights.get(name, 1.0))
            if w <= 0.0:
                continue

            try:
                preds = np.asarray(fn(X_arr), dtype=np.float64).ravel()
                if len(preds) != len(X_arr):
                    logger.warning("ensemble_uzunluk_uyusmazligi", model=name, beklenen=len(X_arr), alinan=len(preds))
                    failed_models.append(name)
                    continue

                if not np.all(np.isfinite(preds)):
                    logger.warning("ensemble_tahminde_nan_veya_inf", model=name)
                    preds = np.nan_to_num(preds, nan=0.0, posinf=0.0, neginf=0.0)

                weighted_sum += preds * w
                total_weight += w
            except Exception as err:
                logger.warning("ensemble_tekil_model_hatasi", model=name, hata=str(err))
                failed_models.append(name)

        if total_weight <= 0.0:
            logger.error("ensemble_tum_modeller_basarisiz", toplam_model=len(models))
            return np.full(len(X_arr), np.nan, dtype=np.float64)

        return weighted_sum / total_weight

    def predict_polars(
        self,
        models: dict[str, Callable[[np.ndarray], np.ndarray]],
        weights: dict[str, float],
        df: pl.DataFrame,
        feature_columns: list[str],
    ) -> np.ndarray:
        """Polars DataFrame girdisi üzerinden doğrudan ağırlıklı topluluk tahmini üretir.

        Args:
            models: Model tahmin fonksiyonları sözlüğü.
            weights: Model ağırlıkları.
            df: Veriyi içeren Polars DataFrame.
            feature_columns: Model öznitelik sütunları.

        Returns:
            Ağırlıklı tahmin dizisi.
        """
        X = df.select(feature_columns).to_numpy()
        return self.predict(models=models, weights=weights, X=X)

    def predict_with_confidence(
        self,
        models: dict[str, Callable[[np.ndarray], np.ndarray]],
        weights: dict[str, float],
        X: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Ağırlıklı tahmin ile birlikte model mutabakatı (confidence) skoru üretir.

        Args:
            models: Model fonksiyonları.
            weights: Model ağırlıkları.
            X: Öznitelik matrisi.

        Returns:
            (tahminler_dizisi, guven_skorlari_dizisi) demeti [0, 1].
        """
        X_arr = np.asarray(X)
        if len(X_arr) == 0 or not models:
            return np.full(len(X_arr), np.nan, dtype=np.float64), np.zeros(len(X_arr), dtype=np.float64)

        all_preds: list[np.ndarray] = []
        valid_weights: list[float] = []

        for name, fn in models.items():
            w = float(weights.get(name, 1.0))
            try:
                preds = np.asarray(fn(X_arr), dtype=np.float64).ravel()
                if len(preds) == len(X_arr) and np.all(np.isfinite(preds)):
                    all_preds.append(preds)
                    valid_weights.append(w)
            except Exception as err:
                logger.warning("guven_tahmini_model_hatasi", model=name, hata=str(err))

        if not all_preds:
            return np.full(len(X_arr), np.nan, dtype=np.float64), np.zeros(len(X_arr), dtype=np.float64)

        preds_matrix = np.array(all_preds, dtype=np.float64)  # (M, N)
        weights_arr = np.array(valid_weights, dtype=np.float64)
        sum_w = np.sum(weights_arr)
        norm_weights = weights_arr / sum_w if sum_w > 0.0 else np.full(len(weights_arr), 1.0 / len(weights_arr))

        # Ağırlıklı ortalama
        weighted_mean = np.sum(preds_matrix * norm_weights[:, None], axis=0)

        # Standart sapma üzerinden güven hesabı
        pred_range = float(np.max(preds_matrix) - np.min(preds_matrix))
        max_possible_std = max(pred_range / 2.0, 1e-6)
        pred_std = np.std(preds_matrix, axis=0)
        confidence = np.clip(1.0 - (pred_std / max_possible_std), 0.0, 1.0)

        return weighted_mean, confidence

    def predict_dynamic(
        self,
        models: dict[str, Callable[[np.ndarray], np.ndarray]],
        X: np.ndarray,
        regime: str = "NORMAL",
        regime_weights: dict[str, dict[str, float]] | None = None,
    ) -> np.ndarray:
        """Piyasa rejimine duyarlı dinamik ağırlıklandırma ile topluluk tahmini yürütür.

        Args:
            models: Model fonksiyonları.
            X: Öznitelik matrisi.
            regime: Piyasa rejimi etiketi (BULL, BEAR, SIDEWAYS, HIGH_VOL, NORMAL).
            regime_weights: {rejim: {model: agirlik}} eşleme sözlüğü.

        Returns:
            Rejim ağırlıklı tahmin dizisi.
        """
        valid_regimes = {"BULL", "BEAR", "SIDEWAYS", "HIGH_VOL", "NORMAL"}
        if regime not in valid_regimes:
            logger.warning("bilinmeyen_piyasa_rejimi", rejim=regime, gecerli=sorted(valid_regimes))

        if regime_weights is None:
            weights = {name: 1.0 for name in models}
        else:
            weights = regime_weights.get(regime, {name: 1.0 for name in models})

        return self.predict(models=models, weights=weights, X=X)

    def analyze_diversity(
        self,
        model_predictions: dict[str, np.ndarray],
        threshold: float | None = None,
    ) -> DiversityReport:
        """Modeller arası tahmin korelasyon matrisini ve çeşitlilik skorunu hesaplar.

        Args:
            model_predictions: {model_adi: tahmin_dizisi} sözlüğü.
            threshold: Benzerlik eşik değeri (varsayılan: self._diversity_threshold).

        Returns:
            DiversityReport analiz raporu.
        """
        thr = threshold if threshold is not None else self._diversity_threshold
        names = sorted(model_predictions.keys())
        n = len(names)

        if n < 2:
            return DiversityReport(
                correlation_matrix={},
                mean_correlation=0.0,
                diversity_score=1.0,
                redundant_models=[],
                recommendation="Tek model var — çeşitlilik analizi uygulanamaz",
            )

        corr_matrix: dict[str, dict[str, float]] = {}
        correlations: list[float] = []

        for i, name_i in enumerate(names):
            corr_matrix[name_i] = {}
            for j, name_j in enumerate(names):
                if i == j:
                    corr_matrix[name_i][name_j] = 1.0
                elif name_j in corr_matrix and name_i in corr_matrix[name_j]:
                    corr_matrix[name_i][name_j] = corr_matrix[name_j][name_i]
                else:
                    try:
                        p_i = np.asarray(model_predictions[name_i], dtype=np.float64).ravel()
                        p_j = np.asarray(model_predictions[name_j], dtype=np.float64).ravel()
                        mask = np.isfinite(p_i) & np.isfinite(p_j)

                        if np.sum(mask) < 10 or np.std(p_i[mask]) < 1e-12 or np.std(p_j[mask]) < 1e-12:
                            corr = 0.0
                        else:
                            corr = float(np.corrcoef(p_i[mask], p_j[mask])[0, 1])
                            if not np.isfinite(corr):
                                corr = 0.0

                        corr_val = round(corr, 4)
                        corr_matrix[name_i][name_j] = corr_val
                        if i < j:
                            correlations.append(abs(corr_val))
                    except Exception as err:
                        logger.warning("cesitlilik_korelasyon_hatasi", model_i=name_i, model_j=name_j, hata=str(err))
                        corr_matrix[name_i][name_j] = 0.0

        mean_corr = float(np.mean(correlations)) if correlations else 0.0
        diversity_score = max(0.0, min(1.0, 1.0 - mean_corr))

        redundant: list[str] = []
        for i, name_i in enumerate(names):
            for j, name_j in enumerate(names):
                if i < j and abs(corr_matrix[name_i].get(name_j, 0.0)) > thr:
                    redundant.append(f"{name_i}↔{name_j}")

        if redundant:
            rec = f"Gereksiz benzer model çiftleri: {redundant}. Biri elenmeli."
        elif diversity_score < DEFAULT_MIN_DIVERSITY:
            rec = "Düşük çeşitlilik — modeller aşırı benzer. Farklı algoritma veya özellik kümesi deneyin."
        else:
            rec = "Yeterli çeşitlilik — topluluk (ensemble) faydalı olabilir."

        return DiversityReport(
            correlation_matrix=corr_matrix,
            mean_correlation=round(mean_corr, 4),
            diversity_score=round(diversity_score, 4),
            redundant_models=redundant,
            recommendation=rec,
        )

    def check_benefit(
        self,
        ensemble_predictions: np.ndarray,
        individual_predictions: dict[str, np.ndarray],
        y_true: np.ndarray,
        tolerance: float | None = None,
    ) -> BenefitReport:
        """Topluluk tahmininin tekil en iyi modeli geçip geçmediğini (Benefit Gate) denetler.

        Args:
            ensemble_predictions: Topluluk modelinin ürettiği tahminler.
            individual_predictions: Tekil modellerin tahminleri.
            y_true: Gerçekleşen hedef değerler.
            tolerance: Kabul edilebilir asgari başarı toleransı.

        Returns:
            BenefitReport fayda raporu.
        """
        tol = tolerance if tolerance is not None else self._benefit_tolerance
        y_arr = np.asarray(y_true, dtype=np.float64).ravel()
        ens_arr = np.asarray(ensemble_predictions, dtype=np.float64).ravel()

        # Ensemble IC
        try:
            mask_ens = np.isfinite(ens_arr) & np.isfinite(y_arr)
            if np.sum(mask_ens) > 5 and np.std(ens_arr[mask_ens]) > 1e-12 and np.std(y_arr[mask_ens]) > 1e-12:
                ensemble_ic = float(np.corrcoef(ens_arr[mask_ens], y_arr[mask_ens])[0, 1])
            else:
                ensemble_ic = 0.0
            if not np.isfinite(ensemble_ic):
                ensemble_ic = 0.0
        except Exception:
            ensemble_ic = 0.0

        # Tekil Model IC'leri
        individual_ics: dict[str, float] = {}
        for name, preds in individual_predictions.items():
            try:
                p_arr = np.asarray(preds, dtype=np.float64).ravel()
                mask_ind = np.isfinite(p_arr) & np.isfinite(y_arr)
                if np.sum(mask_ind) > 5 and np.std(p_arr[mask_ind]) > 1e-12 and np.std(y_arr[mask_ind]) > 1e-12:
                    ic = float(np.corrcoef(p_arr[mask_ind], y_arr[mask_ind])[0, 1])
                else:
                    ic = 0.0
                individual_ics[name] = round(ic, 4) if np.isfinite(ic) else 0.0
            except Exception:
                individual_ics[name] = 0.0

        if not individual_ics:
            return BenefitReport(
                ensemble_ic=round(ensemble_ic, 4),
                best_individual_ic=0.0,
                best_individual_name="",
                ic_improvement=round(ensemble_ic, 4),
                is_beneficial=True,
                recommendation="Bireysel model yok — topluluk kullanılıyor",
            )

        best_name = max(individual_ics, key=individual_ics.get)  # type: ignore[arg-type]
        best_ic = individual_ics[best_name]
        improvement = ensemble_ic - best_ic

        is_beneficial = bool(ensemble_ic >= best_ic * tol)

        if is_beneficial:
            if improvement > 0.02:
                rec = f"Topluluk tekil modele göre belirgin üstünlük sağladı (+{improvement:.4f} IC). Kullanınız."
            else:
                rec = f"Topluluk performansı kabul edilebilir düzeyde ({improvement:+.4f} IC). Kullanılabilir."
        else:
            rec = (
                f"Topluluk tek modelden daha zayıf (ensemble={ensemble_ic:.4f}, "
                f"best={best_ic:.4f} [{best_name}]). En iyi tekil modeli kullanınız."
            )

        return BenefitReport(
            ensemble_ic=round(ensemble_ic, 4),
            best_individual_ic=round(best_ic, 4),
            best_individual_name=best_name,
            ic_improvement=round(improvement, 4),
            is_beneficial=is_beneficial,
            recommendation=rec,
        )

    def diagnose(
        self,
        models: dict[str, Callable[[np.ndarray], np.ndarray]],
        weights: dict[str, float],
        X: np.ndarray,
        y_true: np.ndarray,
    ) -> EnsembleDiagnostics:
        """Topluluk modelinin tüm bileşenlerini test edip detaylı teşhis raporu üretir.

        Args:
            models: Model fonksiyonları sözlüğü.
            weights: Model ağırlıkları.
            X: Öznitelik matrisi.
            y_true: Gerçekleşen hedef değerler.

        Returns:
            EnsembleDiagnostics teşhis çıktısı.
        """
        individual_preds: dict[str, np.ndarray] = {}
        for name, fn in models.items():
            try:
                preds = fn(X)
                if len(preds) == len(X):
                    individual_preds[name] = preds
            except Exception as err:
                logger.warning("teshis_model_tahmin_hatasi", model=name, hata=str(err))

        diversity = self.analyze_diversity(individual_preds)
        ensemble_preds = self.predict(models, weights, X)
        benefit = self.check_benefit(ensemble_preds, individual_preds, y_true)

        model_ics: dict[str, float] = {}
        y_arr = np.asarray(y_true, dtype=np.float64).ravel()
        for name, preds in individual_preds.items():
            try:
                p_arr = np.asarray(preds, dtype=np.float64).ravel()
                mask = np.isfinite(p_arr) & np.isfinite(y_arr)
                if np.sum(mask) > 5 and np.std(p_arr[mask]) > 1e-12 and np.std(y_arr[mask]) > 1e-12:
                    ic = float(np.corrcoef(p_arr[mask], y_arr[mask])[0, 1])
                else:
                    ic = 0.0
                model_ics[name] = round(ic, 4) if np.isfinite(ic) else 0.0
            except Exception:
                model_ics[name] = 0.0

        return EnsembleDiagnostics(
            model_weights=weights,
            model_ics=model_ics,
            diversity=diversity,
            benefit=benefit,
            n_models=len(models),
            n_successful=len(individual_preds),
            timestamp=datetime.now(UTC).isoformat(),
        )

    def auto_prune_redundant(
        self,
        model_predictions: dict[str, np.ndarray],
        model_ics: dict[str, float] | None = None,
        threshold: float | None = None,
    ) -> tuple[dict[str, np.ndarray], list[str]]:
        """Yüksek benzerlik gösteren model çiftlerinden zayıf olanı otomatik eler.

        Args:
            model_predictions: {model_adi: tahmin_dizisi} eşlemesi.
            model_ics: İsteğe bağlı {model_adi: IC_skoru} eşlemesi.
            threshold: Benzerlik eşiği (None ise varsayılan eşik kullanılır).

        Returns:
            (budanmis_tahminler, elenen_model_adlari) demeti.
        """
        diversity = self.analyze_diversity(model_predictions, threshold)
        if not diversity.redundant_models:
            return model_predictions.copy(), []

        removed: list[str] = []
        pruned = model_predictions.copy()

        for pair in diversity.redundant_models:
            parts = pair.split("↔")
            if len(parts) != 2:
                continue

            name_a, name_b = parts[0], parts[1]
            if name_a not in pruned or name_b not in pruned:
                continue

            if model_ics:
                ic_a = model_ics.get(name_a, 0.0)
                ic_b = model_ics.get(name_b, 0.0)
                remove_name = name_a if ic_a < ic_b else name_b
            else:
                remove_name = name_b

            if remove_name in pruned:
                del pruned[remove_name]
                removed.append(remove_name)
                logger.info("gereksiz_model_budandi", elenen=remove_name, korunan=name_a if remove_name == name_b else name_b)

        return pruned, removed

    def should_use_ensemble(
        self,
        diversity_report: DiversityReport,
        benefit_report: BenefitReport,
        min_diversity: float = DEFAULT_MIN_DIVERSITY,
    ) -> tuple[bool, str]:
        """Çeşitlilik ve fayda kapısı sonuçlarına göre topluluk kullanım kararını doğrular.

        Args:
            diversity_report: Çeşitlilik analiz raporu.
            benefit_report: Fayda analiz raporu.
            min_diversity: Asgari kabul edilebilir çeşitlilik skoru.

        Returns:
            (kullanilsin_mi, gerekce) ikilisi.
        """
        if diversity_report.diversity_score < min_diversity:
            return False, (
                f"Düşük çeşitlilik skoru ({diversity_report.diversity_score:.4f} < {min_diversity}). "
                f"Modeller birbirini tekrar ediyor — en iyi tekil modeli kullanınız."
            )

        if not benefit_report.is_beneficial:
            return False, (
                f"Topluluk tekil en iyi modelden daha düşük başarı gösterdi "
                f"(Ensemble={benefit_report.ensemble_ic:.4f}, "
                f"Best={benefit_report.best_individual_ic:.4f} [{benefit_report.best_individual_name}])."
            )

        return True, (
            f"Topluluk kullanımı rasyonel ve faydalı: Çeşitlilik={diversity_report.diversity_score:.4f}, "
            f"IC Artışı={benefit_report.ic_improvement:+.4f}"
        )

    def save_state(
        self,
        path: str,
        weights: dict[str, float],
        model_names: list[str],
        diversity_scores: dict[str, float] | None = None,
        benefit_report: BenefitReport | None = None,
        training_history: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Topluluk durumunu diske güvenli safe_pickle formatında kaydeder.

        Args:
            path: Dosya hedef yolu.
            weights: Model ağırlıkları.
            model_names: Model adları listesi.
            diversity_scores: Model bazlı çeşitlilik skorları.
            benefit_report: Son kaydedilen fayda raporu.
            training_history: Geçmiş eğitim metrikleri.

        Returns:
            Kayıt başarılı ise True.
        """
        try:
            from services.core.safe_pickle import safe_pickle_dump

            state = EnsembleState(
                weights=weights,
                model_names=model_names,
                diversity_scores=diversity_scores or {},
                benefit_report=benefit_report,
                training_history=training_history or [],
                created_at=datetime.now(UTC).isoformat(),
            )
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            safe_pickle_dump(state, path)
            with self._lock:
                self._state = state
            logger.info("ensemble_durumu_kaydedildi", dosya=path, model_sayisi=len(model_names))
            return True
        except Exception as err:
            logger.error("ensemble_kaydetme_hatasi", dosya=path, hata=str(err))
            return False

    def load_state(self, path: str) -> bool:
        """Diskteki güvenli safe_pickle dosyasından topluluk durumunu yükler.

        Args:
            path: Dosya yolu.

        Returns:
            Yükleme başarılı ise True.
        """
        try:
            from services.core.safe_pickle import safe_pickle_load

            state = safe_pickle_load(path)
            if not isinstance(state, EnsembleState):
                logger.error("gecersiz_ensemble_durumu", dosya=path)
                return False

            with self._lock:
                self._state = state
            logger.info("ensemble_durumu_yuklendi", dosya=path, model_sayisi=len(state.model_names))
            return True
        except Exception as err:
            logger.error("ensemble_yukleme_hatasi", dosya=path, hata=str(err))
            return False

    # ===================== DUCKDB & POLARS ENTEGRASYONU =====================

    def export_diagnostics_duckdb(
        self,
        diagnostics: EnsembleDiagnostics,
        db_path: str = ":memory:",
        table_name: str = "ensemble_diagnostics_audit",
    ) -> None:
        """Teşhis raporunu DuckDB denetim tablosuna aktarır.

        Args:
            diagnostics: EnsembleDiagnostics raporu.
            db_path: DuckDB veritabanı yolu.
            table_name: Hedef tablo adı.
        """
        con = duckdb.connect(db_path)
        try:
            configure_duckdb_wal(con)
            con.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    timestamp TIMESTAMP WITH TIME ZONE,
                    diversity_score DOUBLE,
                    mean_correlation DOUBLE,
                    ensemble_ic DOUBLE,
                    best_individual_ic DOUBLE,
                    best_individual_name VARCHAR,
                    is_beneficial BOOLEAN,
                    n_models BIGINT,
                    diagnostics_json VARCHAR
                )
                """
            )
            diag_json = diagnostics.to_orjson_bytes().decode("utf-8")
            con.execute(
                f"INSERT INTO {table_name} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    diagnostics.timestamp,
                    diagnostics.diversity.diversity_score,
                    diagnostics.diversity.mean_correlation,
                    diagnostics.benefit.ensemble_ic,
                    diagnostics.benefit.best_individual_ic,
                    diagnostics.benefit.best_individual_name,
                    diagnostics.benefit.is_beneficial,
                    diagnostics.n_successful,
                    diag_json,
                ),
            )
            logger.info("ensemble_teshis_duckdbye_kaydedildi", tablo=table_name)
        finally:
            con.close()

    def read_diagnostics_polars(
        self,
        db_path: str = ":memory:",
        table_name: str = "ensemble_diagnostics_audit",
    ) -> pl.DataFrame:
        """DuckDB tablosundaki topluluk teşhis kayıtlarını Polars DataFrame olarak okur.

        Args:
            db_path: DuckDB dosya yolu.
            table_name: Tablo adı.

        Returns:
            Teşhis geçmişi Polars DataFrame'i.
        """
        con = duckdb.connect(db_path)
        try:
            configure_duckdb_wal(con)
            arrow_table = con.execute(f"SELECT * FROM {table_name} ORDER BY timestamp ASC").arrow()
            return pl.from_arrow(arrow_table)  # type: ignore[return-value]
        finally:
            con.close()


# Singleton Örneği
ensemble_model = EnsembleModel()

__all__: Final[list[str]] = [
    "DEFAULT_BENEFIT_TOLERANCE",
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_DIVERSITY_THRESHOLD",
    "DEFAULT_MIN_DIVERSITY",
    "DEFAULT_WAL_SIZE",
    "BenefitReport",
    "DiversityReport",
    "EnsembleDiagnostics",
    "EnsembleModel",
    "EnsembleState",
    "configure_duckdb_wal",
    "ensemble_model",
]
