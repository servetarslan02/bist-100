"""
ALPHA BIST — Etiket Kalite Analiz Motoru

ML etiketlerinin kalitesini değerlendiren kapsamlı analiz araçları.
Sınıf dengesizliği, sinyal-gürültü oranı, information coefficient (IC)
ve etiket tutarlılığı metrikleri hesaplar.

Referanslar:
  - López de Prado (2018): Label quality via uniqueness
  - Harvey & Liu (2019): Backtesting with multiple testing
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Sabitler
DEFAULT_IC_WINDOW: int = 252       # IC hesaplama penceresi (1 yıl)
DEFAULT_BINS: int = 5              # Quantile sayısı
DEFAULT_MIN_SAMPLES: int = 30      # Minimum geçerli örnek sayısı


@dataclass
class LabelQualityReport:
    """Etiket kalite analiz raporu.

    Attributes:
        ticker: Hisse senedi kodu.
        label_name: Analiz edilen etiket adı.
        total_samples: Toplam örnek sayısı.
        valid_samples: Geçerli (NaN olmayan) örnek sayısı.
        class_distribution: Her sınıfın oran sözlüğü.
        imbalance_ratio: En baskın sınıf / en az sınıf oranı (1=mükemmel, >3=sorunlu).
        ic_mean: Ortalama Information Coefficient.
        ic_std: IC standart sapması.
        ic_ir: IC Information Ratio (ic_mean / ic_std).
        label_uniqueness: Etiket benzersizliği (overlap var mı?).
        signal_to_noise: Sinyal-gürültü tahmini.
        quality_score: Genel kalite skoru (0-100).
        issues: Tespit edilen kalite sorunları listesi.
    """

    ticker: str
    label_name: str
    total_samples: int
    valid_samples: int
    class_distribution: dict[str, float]
    imbalance_ratio: float
    ic_mean: float
    ic_std: float
    ic_ir: float
    label_uniqueness: float
    signal_to_noise: float
    quality_score: float
    issues: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        """LabelQualityReport kısa temsili."""
        return (
            f"LabelQualityReport(ticker={self.ticker!r}, label={self.label_name!r}, "
            f"quality={self.quality_score:.1f}/100, issues={len(self.issues)})"
        )


@dataclass
class PortfolioLabelStats:
    """Tüm hisseler için etiket istatistikleri özeti.

    Attributes:
        label_name: Analiz edilen etiket adı.
        ticker_reports: Her hisse için ayrı rapor.
        mean_quality: Ortalama kalite skoru.
        mean_ic: Ortalama IC.
        worst_tickers: En düşük kaliteli hisseler listesi.
        best_tickers: En yüksek kaliteli hisseler listesi.
    """

    label_name: str
    ticker_reports: dict[str, LabelQualityReport]
    mean_quality: float
    mean_ic: float
    worst_tickers: list[str]
    best_tickers: list[str]

    def __repr__(self) -> str:
        """PortfolioLabelStats kısa temsili."""
        return (
            f"PortfolioLabelStats(label={self.label_name!r}, "
            f"n_tickers={len(self.ticker_reports)}, mean_quality={self.mean_quality:.1f})"
        )


class LabelQualityAnalyzer:
    """Etiket kalite analiz motoru.

    ML eğitim öncesinde etiket kalitesini değerlendirerek olası sorunları
    (sınıf dengesizliği, düşük IC, yüksek overlap) tespit eder.
    """

    def __init__(
        self,
        ic_window: int = DEFAULT_IC_WINDOW,
        min_samples: int = DEFAULT_MIN_SAMPLES,
    ) -> None:
        """LabelQualityAnalyzer başlatıcı.

        Args:
            ic_window: IC hesaplama için kayan pencere boyutu.
            min_samples: Kalite analizi için minimum geçerli örnek sayısı.

        Raises:
            ValueError: Parametreler geçersizse.
        """
        if ic_window < 10:
            raise ValueError(f"ic_window >= 10 olmalıdır: {ic_window}")
        if min_samples < 5:
            raise ValueError(f"min_samples >= 5 olmalıdır: {min_samples}")
        self.ic_window = ic_window
        self.min_samples = min_samples

    def __repr__(self) -> str:
        """LabelQualityAnalyzer kısa temsili."""
        return f"LabelQualityAnalyzer(ic_window={self.ic_window}, min={self.min_samples})"

    def _compute_ic(
        self,
        labels: np.ndarray,
        forward_returns: np.ndarray,
    ) -> tuple[float, float, float]:
        """Etiket ile gerçek getiri arasındaki Information Coefficient hesaplar.

        IC = Spearman rank korelasyonu (etiket ile forward return arasında).
        IC > 0.05 → güçlü sinyal.
        IC > 0.02 → kullanılabilir sinyal.
        IC < 0 → ters sinyal (tersine çevir veya at).

        Args:
            labels: Etiket dizisi.
            forward_returns: Gerçek forward return dizisi.

        Returns:
            (ic_mean, ic_std, ic_ir) tuple'ı.
        """
        valid_mask = ~(np.isnan(labels) | np.isnan(forward_returns))
        if int(np.sum(valid_mask)) < self.min_samples:
            return 0.0, 0.0, 0.0

        valid_labels = labels[valid_mask]
        valid_returns = forward_returns[valid_mask]

        # Spearman rank korelasyonu (scipy kullanmadan)
        n = len(valid_labels)
        ic_values: list[float] = []

        window = min(self.ic_window, n // 4)
        if window < 10:
            # Tüm veri üzerinde tek IC
            ic = self._spearman_rank_corr(valid_labels, valid_returns)
            return float(ic), 0.0, 0.0

        for i in range(window, n):
            start = max(0, i - window)
            lbl_win = valid_labels[start:i]
            ret_win = valid_returns[start:i]
            if len(lbl_win) < 10:
                continue
            ic = self._spearman_rank_corr(lbl_win, ret_win)
            if not np.isnan(ic):
                ic_values.append(ic)

        if not ic_values:
            return 0.0, 0.0, 0.0

        ic_arr = np.array(ic_values)
        ic_mean = float(np.mean(ic_arr))
        ic_std = float(np.std(ic_arr))
        ic_ir = ic_mean / ic_std if ic_std > 1e-10 else 0.0

        return ic_mean, ic_std, ic_ir

    @staticmethod
    def _spearman_rank_corr(x: np.ndarray, y: np.ndarray) -> float:
        """İki dizi arasındaki Spearman rank korelasyonunu hesaplar.

        Args:
            x: Birinci dizi.
            y: İkinci dizi.

        Returns:
            Spearman rank korelasyonu (-1 ile +1 arası).
        """
        n = len(x)
        if n < 3:
            return float("nan")
        rank_x = np.argsort(np.argsort(x)).astype(float)
        rank_y = np.argsort(np.argsort(y)).astype(float)
        d = rank_x - rank_y
        return float(1.0 - 6.0 * np.sum(d**2) / (n * (n**2 - 1)))

    def _compute_label_uniqueness(
        self,
        n: int,
        forward_period: int,
    ) -> float:
        """Etiket benzersizliğini tahmin eder.

        Çakışan gözlemler (overlapping labels) etiket bağımlılığı yaratır
        ve ML modelinin aşırı öğrenmesine yol açar.

        Args:
            n: Toplam örnek sayısı.
            forward_period: Forward return hesaplama süresi.

        Returns:
            Tahmini benzersizlik oranı (1.0 = mükemmel, düşük = çakışma var).
        """
        if forward_period <= 0 or n <= 0:
            return 1.0
        # Teorik overlap oranı
        uniqueness = 1.0 / min(forward_period, n)
        return float(np.clip(uniqueness * forward_period, 0.0, 1.0))

    def analyze(
        self,
        ticker: str,
        label_name: str,
        labels: np.ndarray,
        forward_returns: np.ndarray | None = None,
        forward_period: int = 10,
    ) -> LabelQualityReport:
        """Tek bir hisse için etiket kalitesini analiz eder.

        Args:
            ticker: Hisse senedi kodu.
            label_name: Analiz edilen etiket adı.
            labels: Etiket dizisi (NaN içerebilir).
            forward_returns: Opsiyonel gerçek forward return dizisi (IC için).
            forward_period: Forward dönemi (benzersizlik hesabı için).

        Returns:
            Detaylı LabelQualityReport nesnesi.

        Raises:
            ValueError: Diziler boşsa veya uyumsuzsa.
        """
        if len(labels) == 0:
            raise ValueError("labels dizisi boş olamaz.")
        if forward_returns is not None and len(forward_returns) != len(labels):
            raise ValueError(
                f"forward_returns ({len(forward_returns)}) ve labels ({len(labels)}) "
                "boyutları eşleşmelidir.",
            )

        n = len(labels)
        valid_mask = ~np.isnan(labels)
        valid_labels = labels[valid_mask]
        valid_samples = int(np.sum(valid_mask))

        issues: list[str] = []

        # Sınıf dağılımı
        class_dist: dict[str, float] = {}
        unique_vals, counts = np.unique(valid_labels, return_counts=True)
        for val, cnt in zip(unique_vals, counts, strict=True):
            key = f"class_{int(val):+d}" if val in (-1.0, 0.0, 1.0) else f"class_{val:.2f}"
            class_dist[key] = float(cnt) / max(valid_samples, 1)

        # Dengesizlik oranı
        if len(counts) >= 2:
            imbalance = float(max(counts)) / float(min(counts))
        else:
            imbalance = float("inf")
            issues.append("Tek sınıf var — etiketleme işlevsiz.")

        if imbalance > 5.0:
            issues.append(f"Aşırı sınıf dengesizliği: {imbalance:.1f}x.")
        elif imbalance > 3.0:
            issues.append(f"Yüksek sınıf dengesizliği: {imbalance:.1f}x.")

        # IC hesabı
        if forward_returns is not None:
            ic_mean, ic_std, ic_ir = self._compute_ic(labels, forward_returns)
        else:
            ic_mean, ic_std, ic_ir = 0.0, 0.0, 0.0

        if forward_returns is not None and abs(ic_mean) < 0.01:
            issues.append(f"Çok düşük IC: {ic_mean:.4f}. Sinyal yok.")
        elif forward_returns is not None and ic_mean < 0:
            issues.append(f"Negatif IC: {ic_mean:.4f}. Ters sinyal — etiketleri kontrol et.")

        # Benzersizlik
        uniqueness = self._compute_label_uniqueness(valid_samples, forward_period)
        if uniqueness < 0.5:
            issues.append(f"Düşük etiket benzersizliği ({uniqueness:.2f}) — overlap var.")

        # Minimum örnek kontrolü
        if valid_samples < self.min_samples:
            issues.append(f"Yetersiz geçerli örnek: {valid_samples} < {self.min_samples}.")

        # Sinyal-gürültü tahmini
        if forward_returns is not None and valid_samples > 0:
            valid_rets = forward_returns[~np.isnan(forward_returns)]
            if len(valid_rets) > 1:
                signal_to_noise = abs(ic_mean) / max(float(np.std(valid_rets)), 1e-10)
            else:
                signal_to_noise = 0.0
        else:
            signal_to_noise = max(0.0, abs(ic_ir) / 10.0)  # IC IR tabanlı yaklaşık değer

        # Kalite skoru (0-100)
        score = 100.0

        # Dengesizlik cezası (max -30)
        if imbalance < float("inf"):
            score -= min(30.0, max(0.0, (imbalance - 1.0) * 5.0))

        # IC cezası (max -30)
        if forward_returns is not None:
            ic_score = min(30.0, abs(ic_mean) * 500.0)
            score -= (30.0 - ic_score)

        # Yetersiz örnek cezası
        if valid_samples < self.min_samples * 2:
            score -= 20.0

        # Benzersizlik cezası
        if uniqueness < 0.5:
            score -= 10.0 * (1.0 - uniqueness * 2)

        score = float(np.clip(score, 0.0, 100.0))

        logger.info(
            "Etiket kalite analizi tamamlandı.",
            ticker=ticker,
            label=label_name,
            valid=valid_samples,
            quality=round(score, 1),
            ic=round(ic_mean, 4),
            issues=len(issues),
        )

        return LabelQualityReport(
            ticker=ticker,
            label_name=label_name,
            total_samples=n,
            valid_samples=valid_samples,
            class_distribution=class_dist,
            imbalance_ratio=imbalance if imbalance != float("inf") else -1.0,
            ic_mean=ic_mean,
            ic_std=ic_std,
            ic_ir=ic_ir,
            label_uniqueness=uniqueness,
            signal_to_noise=signal_to_noise,
            quality_score=score,
            issues=issues,
        )

    def analyze_portfolio(
        self,
        label_name: str,
        all_labels: dict[str, np.ndarray],
        all_returns: dict[str, np.ndarray] | None = None,
        forward_period: int = 10,
        top_k: int = 5,
    ) -> PortfolioLabelStats:
        """Tüm hisseler için etiket kalitesini toplu analiz eder.

        Args:
            label_name: Analiz edilen etiket adı.
            all_labels: {ticker: label_array} sözlüğü.
            all_returns: Opsiyonel {ticker: return_array} sözlüğü.
            forward_period: Forward dönemi.
            top_k: En iyi/kötü hisse sayısı.

        Returns:
            Tüm hisseler için özet istatistikleri içeren PortfolioLabelStats.
        """
        reports: dict[str, LabelQualityReport] = {}

        for ticker, lbl in all_labels.items():
            rets = all_returns.get(ticker) if all_returns else None
            try:
                report = self.analyze(
                    ticker=ticker,
                    label_name=label_name,
                    labels=lbl,
                    forward_returns=rets,
                    forward_period=forward_period,
                )
                reports[ticker] = report
            except ValueError as e:
                logger.warning(
                    "Etiket kalite analizi başarısız.",
                    ticker=ticker,
                    hata=str(e),
                )

        if not reports:
            return PortfolioLabelStats(
                label_name=label_name,
                ticker_reports={},
                mean_quality=0.0,
                mean_ic=0.0,
                worst_tickers=[],
                best_tickers=[],
            )

        scores = {t: r.quality_score for t, r in reports.items()}
        ics = {t: r.ic_mean for t, r in reports.items()}

        sorted_tickers = sorted(scores.keys(), key=lambda t: scores[t])
        worst = sorted_tickers[:top_k]
        best = sorted_tickers[-top_k:][::-1]

        mean_quality = float(np.mean(list(scores.values())))
        mean_ic = float(np.mean(list(ics.values())))

        logger.info(
            "Portföy etiket kalite analizi tamamlandı.",
            label=label_name,
            n_tickers=len(reports),
            mean_quality=round(mean_quality, 1),
            mean_ic=round(mean_ic, 4),
        )

        return PortfolioLabelStats(
            label_name=label_name,
            ticker_reports=reports,
            mean_quality=mean_quality,
            mean_ic=mean_ic,
            worst_tickers=worst,
            best_tickers=best,
        )


__all__: list[str] = [
    "LabelQualityAnalyzer",
    "LabelQualityReport",
    "PortfolioLabelStats",
    "label_quality_analyzer",
]

# Singleton
label_quality_analyzer = LabelQualityAnalyzer()
