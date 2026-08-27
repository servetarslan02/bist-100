"""
ALPHA BIST — Training Dataset Quality Validator

FAZ 4.2: ML training dataset kalite kontrolü.
Her eğitim öncesi çalışır, kalite sorunlarını tespit eder ve düzeltir.

Kontroller:
1. Sample metadata doğruluğu (ticker, feature_date, target_date)
2. Target = T+5 forward return doğrulaması
3. Train/test overlap/leakage tespiti
4. Cross-ticker sample oluşturma doğruluğu
5. NaN/inf/outlier tespiti ve temizleme
6. Feature dağılım analizi
7. Target dağılımı ve sample dengesi
8. Validation metrikleri (MAE, RMSE, R², directional accuracy)
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class SampleMeta:
    """Tek bir training sample'ın metadata'sı."""

    sample_key: str  # "TICKER::YYYY-MM-DD"
    ticker: str
    feature_date: str  # T
    target_date: str  # T+5
    forward_return: float  # target


@dataclass
class DataQualityReport:
    """Veri kalite kontrol raporu."""

    total_samples: int = 0
    valid_samples: int = 0
    dropped_samples: int = 0
    drop_reasons: dict[str, int] = field(default_factory=dict)

    # NaN/inf analizi
    nan_features: dict[str, int] = field(default_factory=dict)  # feature_name → NaN count
    inf_features: dict[str, int] = field(default_factory=dict)  # feature_name → inf count
    outlier_features: dict[str, int] = field(default_factory=dict)  # feature_name → outlier count

    # Target analizi
    target_mean: float = 0.0
    target_std: float = 0.0
    target_median: float = 0.0
    target_min: float = 0.0
    target_max: float = 0.0
    target_skew: float = 0.0
    target_kurtosis: float = 0.0
    target_positive_pct: float = 0.0

    # Feature dağılım analizi
    feature_stats: dict[str, dict[str, float]] = field(default_factory=dict)

    # Cross-ticker analizi
    unique_tickers: int = 0
    unique_dates: int = 0
    samples_per_date: dict[str, int] = field(default_factory=dict)

    # Leakage kontrolü
    train_test_overlap: bool = False
    overlap_details: list[str] = field(default_factory=list)

    # Genel kalite
    quality_score: float = 0.0  # 0-1 arası
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class ValidationMetrics:
    """Model validation metrikleri."""

    mae: float = 0.0
    rmse: float = 0.0
    r_squared: float = 0.0
    directional_accuracy: float = 0.0
    ic: float = 0.0  # Information Coefficient (Spearman)
    ndcg: float = 0.0
    precision_at_5: float = 0.0
    precision_at_10: float = 0.0


class TrainingDatasetValidator:
    """Training dataset kalite kontrolü.

    Kullanım:
        validator = TrainingDatasetValidator()
        report = validator.validate_dataset(features_map, returns, date_groups, feature_names)
        metrics = validator.compute_validation_metrics(y_true, y_pred)
    """

    # Outlier eşikleri (z-score)
    OUTLIER_Z_THRESHOLD = 5.0

    # Minimum kalite eşikleri
    MIN_VALID_SAMPLE_RATIO = 0.8  # En az %80 sample geçerli olmalı
    MIN_SAMPLES_PER_DATE = 2  # Her tarihte en az 2 hisse (cross-sectional için)
    MAX_NAN_RATIO_PER_FEATURE = 0.3  # Tek feature'da %30'dan fazla NaN = uyarı

    def validate_dataset(
        self,
        features_map: dict[str, dict[str, Any]],
        returns: dict[str, float],
        date_groups: dict[str, str],
        feature_names: list[str],
        test_dates: set | None = None,
    ) -> DataQualityReport:
        """Training dataset'in tamamını_validate et.

        Args:
            features_map: {sample_key: {feature: value}}
            returns: {sample_key: forward_return}
            date_groups: {sample_key: date_str}
            feature_names: Feature isimleri listesi
            test_dates: Test dönem tarihleri (leakage kontrolü için)

        Returns:
            DataQualityReport
        """
        report = DataQualityReport()
        report.total_samples = len(features_map)

        if report.total_samples == 0:
            report.errors.append("Empty dataset")
            report.quality_score = 0.0
            return report

        # === 1. SAMPLE METADATA DOĞRULUĞU ===
        self._validate_sample_metadata(features_map, returns, date_groups, report)

        # === 2. NaN/INF/OUTLIER ANALİZİ ===
        self._validate_features(features_map, feature_names, report)

        # === 3. TARGET DAĞILIM ANALİZİ ===
        self._validate_target_distribution(returns, report)

        # === 4. CROSS-TICKER ANALİZ ===
        self._validate_cross_ticker(date_groups, report)

        # === 5. TRAIN/TEST LEAKAGE KONTROLÜ ===
        if test_dates:
            self._validate_leakage(date_groups, test_dates, report)

        # === 6. KALİTE SKORU HESAPLA ===
        self._compute_quality_score(report)

        return report

    def _validate_sample_metadata(
        self,
        features_map: dict[str, dict],
        returns: dict[str, float],
        date_groups: dict[str, str],
        report: DataQualityReport,
    ):
        """Sample metadata doğruluğunu kontrol et."""
        valid = 0
        dropped = 0
        drop_reasons: dict[str, int] = {}

        for key in features_map:
            # Key formatı: "TICKER::YYYY-MM-DD"
            parts = key.split("::")
            if len(parts) != 2:
                drop_reasons["invalid_key_format"] = drop_reasons.get("invalid_key_format", 0) + 1
                dropped += 1
                continue

            ticker, feature_date = parts

            # Ticker boş olmamalı
            if not ticker:
                drop_reasons["empty_ticker"] = drop_reasons.get("empty_ticker", 0) + 1
                dropped += 1
                continue

            # Feature date geçerli olmalı
            if not feature_date or len(feature_date) < 8:
                drop_reasons["invalid_date"] = drop_reasons.get("invalid_date", 0) + 1
                dropped += 1
                continue

            # Returns ve date_groups'da olmalı
            if key not in returns:
                drop_reasons["missing_return"] = drop_reasons.get("missing_return", 0) + 1
                dropped += 1
                continue

            if key not in date_groups:
                drop_reasons["missing_date_group"] = drop_reasons.get("missing_date_group", 0) + 1
                dropped += 1
                continue

            # date_groups ile key'deki tarih eşleşmeli
            if date_groups[key] != feature_date:
                drop_reasons["date_mismatch"] = drop_reasons.get("date_mismatch", 0) + 1
                dropped += 1
                continue

            valid += 1

        report.valid_samples = valid
        report.dropped_samples = dropped
        report.drop_reasons = drop_reasons

        if dropped > 0:
            report.warnings.append(f"{dropped} samples dropped: {drop_reasons}")

    def _validate_features(
        self,
        features_map: dict[str, dict],
        feature_names: list[str],
        report: DataQualityReport,
    ):
        """Feature'larda NaN/inf/outlier kontrolü."""
        nan_counts: dict[str, int] = {f: 0 for f in feature_names}
        inf_counts: dict[str, int] = {f: 0 for f in feature_names}
        outlier_counts: dict[str, int] = {f: 0 for f in feature_names}

        # Feature değerlerini topla (istatistik için)
        feature_values: dict[str, list[float]] = {f: [] for f in feature_names}

        for _key, feats in features_map.items():
            for fname in feature_names:
                val = feats.get(fname)
                if val is None:
                    nan_counts[fname] += 1
                    continue

                try:
                    v = float(val)
                except (TypeError, ValueError):
                    nan_counts[fname] += 1
                    continue

                if np.isnan(v):
                    nan_counts[fname] += 1
                elif np.isinf(v):
                    inf_counts[fname] += 1
                else:
                    feature_values[fname].append(v)

        # Outlier tespiti (z-score)
        for fname in feature_names:
            vals = feature_values[fname]
            if len(vals) < 10:
                continue
            arr = np.array(vals)
            mean = np.mean(arr)
            std = np.std(arr)
            if std > 0:
                z_scores = np.abs((arr - mean) / std)
                outlier_counts[fname] = int(np.sum(z_scores > self.OUTLIER_Z_THRESHOLD))

        # Feature istatistikleri
        feature_stats: dict[str, dict[str, float]] = {}
        for fname in feature_names:
            vals = feature_values[fname]
            if not vals:
                continue
            arr = np.array(vals)
            feature_stats[fname] = {
                "mean": float(np.mean(arr)),
                "std": float(np.std(arr)),
                "median": float(np.median(arr)),
                "min": float(np.min(arr)),
                "max": float(np.max(arr)),
                "nan_count": nan_counts[fname],
                "inf_count": inf_counts[fname],
                "outlier_count": outlier_counts[fname],
            }

        report.nan_features = {f: c for f, c in nan_counts.items() if c > 0}
        report.inf_features = {f: c for f, c in inf_counts.items() if c > 0}
        report.outlier_features = {f: c for f, c in outlier_counts.items() if c > 0}
        report.feature_stats = feature_stats

        # Uyarılar
        n = len(features_map)
        for fname, count in nan_counts.items():
            if n > 0 and count / n > self.MAX_NAN_RATIO_PER_FEATURE:
                report.warnings.append(f"Feature '{fname}' has {count}/{n} NaN ({count / n:.0%})")

        for fname, count in inf_counts.items():
            if count > 0:
                report.warnings.append(f"Feature '{fname}' has {count} inf values")

    def _validate_target_distribution(
        self,
        returns: dict[str, float],
        report: DataQualityReport,
    ):
        """Target dağılım analizi."""
        values = list(returns.values())
        if not values:
            return

        arr = np.array(values)

        # NaN/inf temizle (istatistik için)
        clean = arr[np.isfinite(arr)]
        if len(clean) == 0:
            report.errors.append("All target values are NaN/inf")
            return

        report.target_mean = float(np.mean(clean))
        report.target_std = float(np.std(clean))
        report.target_median = float(np.median(clean))
        report.target_min = float(np.min(clean))
        report.target_max = float(np.max(clean))
        report.target_positive_pct = float(np.sum(clean > 0) / len(clean))

        # Skewness
        if len(clean) > 2:
            m = np.mean(clean)
            s = np.std(clean)
            if s > 0:
                report.target_skew = float(np.mean(((clean - m) / s) ** 3))

        # Kurtosis
        if len(clean) > 3:
            m = np.mean(clean)
            s = np.std(clean)
            if s > 0:
                report.target_kurtosis = float(np.mean(((clean - m) / s) ** 4) - 3)

        # Uyarılar
        if report.target_positive_pct < 0.3 or report.target_positive_pct > 0.7:
            report.warnings.append(f"Target dengesizliği: %{report.target_positive_pct:.0f} pozitif")

        if report.target_std < 0.1:
            report.warnings.append(f"Target std çok düşük: {report.target_std:.4f}")

    def _validate_cross_ticker(
        self,
        date_groups: dict[str, str],
        report: DataQualityReport,
    ):
        """Cross-ticker sample oluşturma doğruluğu."""
        # Ticker'ları key'den çıkar
        tickers = set()
        dates = set()
        samples_per_date: dict[str, int] = {}

        for key, date_str in date_groups.items():
            parts = key.split("::")
            if len(parts) == 2:
                tickers.add(parts[0])
                dates.add(date_str)
                samples_per_date[date_str] = samples_per_date.get(date_str, 0) + 1

        report.unique_tickers = len(tickers)
        report.unique_dates = len(dates)
        report.samples_per_date = samples_per_date

        # Her tarihte yeterli hisse var mı?
        sparse_dates = {d: c for d, c in samples_per_date.items() if c < self.MIN_SAMPLES_PER_DATE}
        if sparse_dates:
            report.warnings.append(f"{len(sparse_dates)} dates have <{self.MIN_SAMPLES_PER_DATE} samples")

    def _validate_leakage(
        self,
        date_groups: dict[str, str],
        test_dates: set,
        report: DataQualityReport,
    ):
        """Train/test tarih overlap kontrolü."""
        train_dates = set(date_groups.values())
        overlap = train_dates & test_dates

        if overlap:
            report.train_test_overlap = True
            report.overlap_details = sorted(overlap)
            report.errors.append(f"LEAKAGE: {len(overlap)} train dates overlap with test dates")

    def _compute_quality_score(self, report: DataQualityReport):
        """Genel kalite skoru hesapla (0-1)."""
        score = 1.0

        # Sample drop cezası
        if report.total_samples > 0:
            drop_ratio = report.dropped_samples / report.total_samples
            score -= drop_ratio * 0.3

        # NaN oranı cezası
        n = report.total_samples
        if n > 0 and report.nan_features:
            total_nan = sum(report.nan_features.values())
            max_possible = n * len(report.nan_features)
            if max_possible > 0:
                nan_ratio = total_nan / max_possible
                score -= nan_ratio * 0.2

        # Leakage cezası (ağır)
        if report.train_test_overlap:
            score -= 0.55  # Leakage kritik — kaliteyi 0.5'in altına düşür

        # Target dengesizliği cezası
        if report.target_positive_pct < 0.3 or report.target_positive_pct > 0.7:
            score -= 0.1

        report.quality_score = max(0.0, min(1.0, score))

    def compute_validation_metrics(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray,
    ) -> ValidationMetrics:
        """Model validation metrikleri hesapla.

        Args:
            y_true: Gerçek forward return'ler
            y_pred: Model tahminleri

        Returns:
            ValidationMetrics
        """
        metrics = ValidationMetrics()

        # NaN/inf temizle
        mask = np.isfinite(y_true) & np.isfinite(y_pred)
        yt = y_true[mask]
        yp = y_pred[mask]

        if len(yt) < 2:
            return metrics

        # MAE
        metrics.mae = float(np.mean(np.abs(yt - yp)))

        # RMSE
        metrics.rmse = float(np.sqrt(np.mean((yt - yp) ** 2)))

        # R²
        ss_res = np.sum((yt - yp) ** 2)
        ss_tot = np.sum((yt - np.mean(yt)) ** 2)
        if ss_tot > 0:
            metrics.r_squared = float(1 - ss_res / ss_tot)

        # Directional accuracy (yön doğruluğu)
        correct_direction = np.sum(np.sign(yt) == np.sign(yp))
        metrics.directional_accuracy = float(correct_direction / len(yt))

        # IC (Spearman rank correlation)
        try:
            from scipy.stats import spearmanr

            # Constant array kontrolü
            if np.std(yt) > 0 and np.std(yp) > 0:
                ic, _ = spearmanr(yt, yp)
                metrics.ic = float(ic) if np.isfinite(ic) else 0.0
            else:
                metrics.ic = 0.0
        except ImportError:
            # Fallback: Pearson correlation
            if np.std(yt) > 0 and np.std(yp) > 0:
                metrics.ic = float(np.corrcoef(yt, yp)[0, 1])

        # NDCG@10 (basitleştirilmiş)
        metrics.ndcg = self._compute_simple_ndcg(yt, yp, k=10)

        # Precision@5 ve @10
        metrics.precision_at_5 = self._precision_at_k(yt, yp, k=5)
        metrics.precision_at_10 = self._precision_at_k(yt, yp, k=10)

        return metrics

    @staticmethod
    def _compute_simple_ndcg(y_true: np.ndarray, y_pred: np.ndarray, k: int = 10) -> float:
        """Basitleştirilmiş NDCG@k."""
        if len(y_true) < 2:
            return 0.0
        # En iyi k tahmini sırala
        k = min(k, len(y_true))
        pred_order = np.argsort(y_pred)[::-1][:k]
        ideal_order = np.argsort(y_true)[::-1][:k]

        pred_gains = y_true[pred_order]
        ideal_gains = y_true[ideal_order]

        positions = np.arange(2, k + 2)
        dcg = np.sum(pred_gains / np.log2(positions))
        idcg = np.sum(ideal_gains / np.log2(positions))

        return float(dcg / idcg) if idcg > 0 else 0.0

    @staticmethod
    def _precision_at_k(y_true: np.ndarray, y_pred: np.ndarray, k: int = 5) -> float:
        """Top-k tahminde pozitif getiri oranı."""
        if len(y_true) < k:
            return 0.0
        top_k_idx = np.argsort(y_pred)[::-1][:k]
        correct = np.sum(y_true[top_k_idx] > 0)
        return float(correct / k)

    def clean_features(
        self,
        features_map: dict[str, dict],
        feature_names: list[str],
    ) -> tuple[dict[str, dict], dict[str, Any]]:
        """Feature'ları temizle: inf → NaN, outlier clamp.

        Args:
            features_map: Orijinal feature map
            feature_names: Feature isimleri

        Returns:
            (cleaned_features_map, cleaning_stats)
        """
        cleaned = {}
        stats = {"inf_replaced": 0, "outliers_clamped": 0}

        # Önce outlier sınırlarını hesapla
        bounds: dict[str, tuple[float, float]] = {}
        for fname in feature_names:
            vals = []
            for feats in features_map.values():
                v = feats.get(fname)
                if v is not None:
                    try:
                        fv = float(v)
                        if np.isfinite(fv):
                            vals.append(fv)
                    except (TypeError, ValueError):
                        logger.warning("Error in clean_features: (TypeError, ValueError)", exc_info=True)
            if len(vals) >= 20:
                arr = np.array(vals)
                mean = np.mean(arr)
                std = np.std(arr)
                if std > 0:
                    lower = mean - self.OUTLIER_Z_THRESHOLD * std
                    upper = mean + self.OUTLIER_Z_THRESHOLD * std
                    bounds[fname] = (lower, upper)

        # Temizle
        for key, feats in features_map.items():
            new_feats = {}
            for fname in feature_names:
                val = feats.get(fname)
                if val is None:
                    new_feats[fname] = None
                    continue

                try:
                    v = float(val)
                except (TypeError, ValueError):
                    new_feats[fname] = None
                    continue

                # inf → NaN (sonra impute edilecek)
                if np.isinf(v):
                    new_feats[fname] = None
                    stats["inf_replaced"] += 1
                # Outlier clamp
                elif fname in bounds:
                    lower, upper = bounds[fname]
                    if v < lower:
                        new_feats[fname] = lower
                        stats["outliers_clamped"] += 1
                    elif v > upper:
                        new_feats[fname] = upper
                        stats["outliers_clamped"] += 1
                    else:
                        new_feats[fname] = v
                else:
                    new_feats[fname] = v

            cleaned[key] = new_feats

        return cleaned, stats


# Singleton
training_validator = TrainingDatasetValidator()


# =====================================================
# CROSS-SECTIONAL NORMALIZATION (PIT-safe)
# =====================================================


class CrossSectionalNormalizer:
    """PIT-safe cross-sectional normalization.

    Her tarihte, feature'ları o günkü tüm ticker'ların
    dağılımına göre normalize eder (z-score, rank percentile).

    KURAL: Sadece o tarihe kadar bilinen veriler kullanılır.
    """

    def normalize_zscore_by_date(
        self,
        features_map: dict[str, dict[str, Any]],
        date_groups: dict[str, str],
        feature_names: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Her tarihte feature'ları cross-sectional z-score'a çevir.

        Args:
            features_map: {sample_key: {feature: value}}
            date_groups: {sample_key: date_str}
            feature_names: Normalize edilecek feature'lar

        Returns:
            Normalized features_map (yeni dict, orijinali bozmaz)
        """
        # Tarih bazlı grupla
        date_to_keys: dict[str, list[str]] = {}
        for key, date_str in date_groups.items():
            if date_str not in date_to_keys:
                date_to_keys[date_str] = []
            date_to_keys[date_str].append(key)

        # Her tarih için z-score hesapla
        normalized = {}
        for date_str, keys in date_to_keys.items():
            if len(keys) < 2:
                # Tek ticker varsa normalize etme
                for key in keys:
                    normalized[key] = dict(features_map[key])
                continue

            # Feature istatistikleri
            for fname in feature_names:
                vals = []
                valid_keys = []
                for key in keys:
                    v = features_map[key].get(fname)
                    if v is not None:
                        try:
                            fv = float(v)
                            if np.isfinite(fv):
                                vals.append(fv)
                                valid_keys.append(key)
                        except (TypeError, ValueError):
                            logger.warning("Error in normalize_zscore_by_date: (TypeError, ValueError)", exc_info=True)

                if len(vals) < 2:
                    continue

                mean = np.mean(vals)
                std = np.std(vals)
                if std < 1e-10:
                    continue

                for key in keys:
                    if key not in normalized:
                        normalized[key] = dict(features_map[key])
                    v = features_map[key].get(fname)
                    if v is not None:
                        try:
                            fv = float(v)
                            if np.isfinite(fv):
                                z = (fv - mean) / std
                                normalized[key][f"{fname}_cs_zscore"] = round(z, 4)
                        except (TypeError, ValueError):
                            logger.warning("Error in normalize_zscore_by_date: (TypeError, ValueError)", exc_info=True)

        # Normalize edilmemiş sample'ları kopyala
        for key in features_map:
            if key not in normalized:
                normalized[key] = dict(features_map[key])

        return normalized

    def normalize_rank_by_date(
        self,
        features_map: dict[str, dict[str, Any]],
        date_groups: dict[str, str],
        feature_names: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Her tarihte feature'ları rank percentile'a çevir.

        Returns:
            Normalized features_map (yeni dict)
        """
        date_to_keys: dict[str, list[str]] = {}
        for key, date_str in date_groups.items():
            if date_str not in date_to_keys:
                date_to_keys[date_str] = []
            date_to_keys[date_str].append(key)

        normalized = {}
        for date_str, keys in date_to_keys.items():
            if len(keys) < 2:
                for key in keys:
                    normalized[key] = dict(features_map[key])
                continue

            for fname in feature_names:
                vals = []
                for key in keys:
                    v = features_map[key].get(fname)
                    if v is not None:
                        try:
                            fv = float(v)
                            if np.isfinite(fv):
                                vals.append((key, fv))
                        except (TypeError, ValueError):
                            logger.warning("Error in normalize_rank_by_date: (TypeError, ValueError)", exc_info=True)

                if len(vals) < 2:
                    continue

                # Rank hesapla
                sorted_vals = sorted(vals, key=lambda x: x[1])
                n = len(sorted_vals)
                for rank, (key, _) in enumerate(sorted_vals):
                    if key not in normalized:
                        normalized[key] = dict(features_map[key])
                    percentile = rank / (n - 1) if n > 1 else 0.5
                    normalized[key][f"{fname}_cs_rank"] = round(percentile, 4)

        for key in features_map:
            if key not in normalized:
                normalized[key] = dict(features_map[key])

        return normalized


# Singleton
cross_sectional_normalizer = CrossSectionalNormalizer()


# =====================================================
# LIVE INFERENCE FEATURE PARITY
# =====================================================


def prepare_features_for_inference(
    ticker: str,
    raw_features: dict[str, Any],
    all_date_features: dict[str, dict[str, Any]],
    feature_names: list[str],
    cs_features: list[str],
    impute_values: dict[str, float] | None = None,
    date_str: str = "",
) -> dict[str, Any]:
    """Live inference icin feature'lari hazırla — training ile PARITY.

    Training pipeline ile aynı matematigi kullanir:
    1. Raw features'i al
    2. CrossSectionalNormalizer ile CS z-score ekle (PIT-safe, sadece ayni tarih)
    3. Feature contract dogrula (eksik feature varsa impute)
    4. Model'in bekledigi feature_names + cs_features sirasinda dondur

    Args:
        ticker: Hisse kodu
        raw_features: Bu hissenin ham feature'lari
        all_date_features: Ayni tarihteki TUM hisselerin feature'lari {ticker: features}
        feature_names: Model'in bekledigi temel feature'lar
        cs_features: Model'in bekledigi CS-normalized feature'lar (suffix: _cs_zscore)
        impute_values: Eksik feature'lar icin impute degerleri (None → 0.0)
        date_str: Tarih string'i (logging icin)

    Returns:
        Normalized feature dict (model.predict() icin hazir)
    """
    # 1. CS normalization (PIT-safe: sadece ayni tarih snapshot'i)
    #    all_date_features'daki ticker'lar o an piyasada olan hisseler
    date_features_map = {}
    date_groups_map = {}
    for t, feats in all_date_features.items():
        key = f"{t}::{date_str}"
        date_features_map[key] = feats
        date_groups_map[key] = date_str

    # CS normalization uygula (sadece temel feature'lar uzerinden)
    base_features = [f for f in feature_names if not f.endswith("_cs_zscore") and not f.endswith("_cs_rank")]
    if len(all_date_features) >= 2:
        normalized_map = cross_sectional_normalizer.normalize_zscore_by_date(
            date_features_map, date_groups_map, base_features
        )
        ticker_key = f"{ticker}::{date_str}"
        normalized_features = normalized_map.get(ticker_key, raw_features)
    else:
        # Tek hisse varsa CS normalization uygulanamaz
        normalized_features = dict(raw_features)

    # 2. Feature contract dogrulama ve imputation
    result = {}
    all_expected = feature_names + cs_features

    for fname in all_expected:
        val = normalized_features.get(fname)
        if val is None:
            # Impute degeri varsa kullan, yoksa 0.0
            if impute_values and fname in impute_values:
                result[fname] = impute_values[fname]
            else:
                result[fname] = 0.0
        else:
            try:
                v = float(val)
                result[fname] = v if np.isfinite(v) else 0.0
            except (TypeError, ValueError):
                result[fname] = 0.0

    return result
