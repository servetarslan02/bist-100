"""ALPHA BIST — Champion-Challenger Model Karşılaştırma ve Terfi Motoru v2.0 (Production-Hardened)

BIST pay piyasası yapay zeka modelleri için üretim geçiş ve A/B test protokolü:
- Şampiyon (Champion: LightGBM) ve Meydan Okuyan (Challenger: CatBoost, XGBoost) modellerin gölge (Shadow) modda eşzamanlı çalıştırılması
- İki örneklemli Student's t-test, Cohen's d etki büyüklüğü ve istatistiksel güç (Power) hesaplamaları
- Çoklu finansal metrik değerlendirmesi (IC, Sharpe, Yön Doğruluğu, Maksimum Düşüş, Kâr Faktörü)
- Otomatik terfi (Auto-promote) ve otomatik red (Auto-reject) mekanizması
- Geri alma (Rollback) yeteneği ve DuckDB WAL denetim logu
- Polars DataFrame entegrasyonu ve threading.RLock eşzamanlı erişim koruması

Kurallar & Standartlar:
- İstatiksel anlamlılık eşiği (p < 0.05) ve sıfır gerileme (zero regressions) şartı.
- DuckDB WAL optimizasyonu ve orjson yüksek hızlı serileştirme.
- Polars entegrasyonu (pandas yasaktır).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl  # noqa: TC002
import structlog
from scipy import stats
from scipy.stats import norm

logger = structlog.get_logger(__name__)

# ===================== SABİTLER (CONSTANTS) =====================

DEFAULT_SIGNIFICANCE_LEVEL: Final[float] = 0.05
DEFAULT_MIN_SAMPLES: Final[int] = 30
DEFAULT_AUTO_PROMOTE_THRESHOLD: Final[float] = 0.05
DEFAULT_MAX_HISTORY_LEN: Final[int] = 1000
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
class ABTestResult:
    """Tek bir finansal metrik için A/B hipotez testi çıktısı.

    Attributes:
        champion_metric: Şampiyon modelin ortalama metrik değeri.
        challenger_metric: Meydan okuyan modelin ortalama metrik değeri.
        p_value: İki örneklem t-test p-değeri.
        significant: İstatiksel olarak anlamlı mı (p < significance_level).
        winner: Kazanan taraf ('champion', 'challenger', 'tie' veya 'insufficient_data').
        n_samples_champion: Şampiyon örneklem sayısı.
        n_samples_challenger: Meydan okuyan örneklem sayısı.
        confidence_level: Güven seviyesi (1 - alpha).
        effect_size: Cohen's d etki büyüklüğü katsayısı.
        power: Testin istatistiksel gücü (1 - beta).
    """

    champion_metric: float
    challenger_metric: float
    p_value: float
    significant: bool
    winner: str
    n_samples_champion: int
    n_samples_challenger: int
    confidence_level: float
    effect_size: float = 0.0
    power: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Modeli standart sözlüğe dönüştürür."""
        return {
            "champion_metric": self.champion_metric,
            "challenger_metric": self.challenger_metric,
            "p_value": self.p_value,
            "significant": self.significant,
            "winner": self.winner,
            "n_samples_champion": self.n_samples_champion,
            "n_samples_challenger": self.n_samples_challenger,
            "confidence_level": self.confidence_level,
            "effect_size": self.effect_size,
            "power": self.power,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ABTestResult:
        """Sözlükten ABTestResult nesnesi oluşturur."""
        return cls(
            champion_metric=float(data.get("champion_metric", 0.0)),
            challenger_metric=float(data.get("challenger_metric", 0.0)),
            p_value=float(data.get("p_value", 1.0)),
            significant=bool(data.get("significant", False)),
            winner=str(data.get("winner", "tie")),
            n_samples_champion=int(data.get("n_samples_champion", 0)),
            n_samples_challenger=int(data.get("n_samples_challenger", 0)),
            confidence_level=float(data.get("confidence_level", 0.95)),
            effect_size=float(data.get("effect_size", 0.0)),
            power=float(data.get("power", 0.0)),
        )

    def to_orjson_bytes(self) -> bytes:
        """orjson serileştirmesi döndürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        return (
            f"ABTestResult(winner={self.winner!r}, p_val={self.p_value:.4f}, "
            f"effect={self.effect_size:.2f}, champ={self.champion_metric:.4f}, chall={self.challenger_metric:.4f})"
        )


@dataclass(slots=True)
class MultiMetricResult:
    """Metrik bazlı detaylı karşılaştırma ve yüzdesel üstünlük sonucu.

    Attributes:
        metric_name: İncelenen finansal metrik adı.
        champion_value: Şampiyon modelin değeri.
        challenger_value: Meydan okuyan modelin değeri.
        winner: Üstün olan model.
        improvement_pct: Şampiyona göre yüzdesel gelişim oranı.
    """

    metric_name: str
    champion_value: float
    challenger_value: float
    winner: str
    improvement_pct: float

    def to_dict(self) -> dict[str, Any]:
        """Modeli sözlüğe dönüştürür."""
        return {
            "metric_name": self.metric_name,
            "champion_value": self.champion_value,
            "challenger_value": self.challenger_value,
            "winner": self.winner,
            "improvement_pct": self.improvement_pct,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MultiMetricResult:
        """Sözlükten MultiMetricResult nesnesi oluşturur."""
        return cls(
            metric_name=str(data.get("metric_name", "")),
            champion_value=float(data.get("champion_value", 0.0)),
            challenger_value=float(data.get("challenger_value", 0.0)),
            winner=str(data.get("winner", "tie")),
            improvement_pct=float(data.get("improvement_pct", 0.0)),
        )

    def to_orjson_bytes(self) -> bytes:
        """orjson serileştirmesi döndürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        return (
            f"MultiMetricResult(metric={self.metric_name!r}, winner={self.winner!r}, "
            f"improvement={self.improvement_pct:+.2f}%)"
        )


@dataclass(slots=True)
class PromotionDecision:
    """Meydan okuyan modelin canlıya terfi (Promote) veya red kararı.

    Attributes:
        should_promote: Model canlıya alınmalı mı.
        reason: Gerekçeli karar açıklaması.
        ab_results: Metrik bazlı hipotez testi sonuçları.
        multi_metric_results: Karşılaştırma detayları listesi.
        overall_winner: Genel kazanan taraf.
        confidence: Güven skoru (kazanılan metrik oranı).
    """

    should_promote: bool
    reason: str
    ab_results: dict[str, ABTestResult]
    multi_metric_results: list[MultiMetricResult]
    overall_winner: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        """Karar çıktısını sözlüğe dönüştürür."""
        return {
            "should_promote": self.should_promote,
            "reason": self.reason,
            "ab_results": {k: v.to_dict() for k, v in self.ab_results.items()},
            "multi_metric_results": [r.to_dict() for r in self.multi_metric_results],
            "overall_winner": self.overall_winner,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PromotionDecision:
        """Sözlükten PromotionDecision nesnesi oluşturur."""
        ab_raw = data.get("ab_results", {})
        ab_clean = {
            k: (ABTestResult.from_dict(v) if isinstance(v, dict) else v)
            for k, v in ab_raw.items()
        }
        mm_raw = data.get("multi_metric_results", [])
        mm_clean = [
            (MultiMetricResult.from_dict(m) if isinstance(m, dict) else m)
            for m in mm_raw
        ]
        return cls(
            should_promote=bool(data.get("should_promote", False)),
            reason=str(data.get("reason", "")),
            ab_results=ab_clean,
            multi_metric_results=mm_clean,
            overall_winner=str(data.get("overall_winner", "unknown")),
            confidence=float(data.get("confidence", 0.0)),
        )

    def to_orjson_bytes(self) -> bytes:
        """orjson serileştirmesi döndürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        return (
            f"PromotionDecision(promote={self.should_promote}, winner={self.overall_winner!r}, "
            f"confidence={self.confidence:.2f}, reason={self.reason!r})"
        )


# ===================== ŞAMPİYON - MEYDAN OKUYAN MOTORU =====================


class ChampionChallenger:
    """ALPHA BIST Şampiyon vs Meydan Okuyan Model Karşılaştırma Motoru v2.0.

    Özellikler:
    - Canlı piyasa simülasyonunda gölge (Shadow) metrik toplama
    - İki örneklemli t-test, Cohen's d ve Statistical Power ile A/B testi
    - Çoklu metrik karşılaştırması (Return, IC, Sharpe, Win Rate, Drawdown)
    - Katı kurallı terfi mekanizması (anlamlı üstünlük + sıfır regresyon)
    - Hızlı geri alma (Rollback) ve geçmiş denetim izi
    - Polars DataFrame ve DuckDB WAL denetim tablosu entegrasyonu
    - threading.RLock thread-safety koruması
    """

    def __init__(
        self,
        significance_level: float = DEFAULT_SIGNIFICANCE_LEVEL,
        min_samples: int = DEFAULT_MIN_SAMPLES,
        auto_promote_threshold: float = DEFAULT_AUTO_PROMOTE_THRESHOLD,
        metrics_to_compare: list[str] | None = None,
    ) -> None:
        """ChampionChallenger motorunu yapılandırır.

        Args:
            significance_level: İstatistiksel anlamlılık alfa eşiği (varsayılan 0.05).
            min_samples: Test için asgari örneklem adedi (varsayılan 30).
            auto_promote_threshold: Terfi için asgari net üstünlük farkı.
            metrics_to_compare: Karşılaştırılacak hedef finansal metrikler.
        """
        self.significance_level = max(0.001, min(0.20, float(significance_level)))
        self.min_samples = max(5, int(min_samples))
        self.auto_promote_threshold = max(0.0, float(auto_promote_threshold))
        self.metrics_to_compare = metrics_to_compare or ["return", "ic", "sharpe", "win_rate"]

        self._lock = threading.RLock()
        self._shadow_results: dict[str, dict[str, list[float]]] = {}
        self._champion_results: dict[str, list[float]] = {}
        self._history: list[dict[str, Any]] = []

    def __repr__(self) -> str:
        with self._lock:
            n_challengers = len(self._shadow_results)
            n_champ_metrics = len(self._champion_results)
            n_decisions = len(self._history)
            return (
                f"ChampionChallenger(challengers={n_challengers}, champ_metrics={n_champ_metrics}, "
                f"history_len={n_decisions}, alpha={self.significance_level})"
            )

    def record_shadow_result(self, model_key: str, metric_name: str, value: float) -> None:
        """Gölge (Shadow) modda çalışan meydan okuyan modelin metrik sonucunu kaydeder.

        Args:
            model_key: Meydan okuyan model kimliği (ör. 'catboost_v2', 'xgboost_regime').
            metric_name: Metrik adı (ör. 'ic', 'sharpe', 'return').
            value: Hesaplanan sayısal değer.
        """
        if not np.isfinite(value):
            logger.warning("gecersiz_metrik_degeri_atlandi", model=model_key, metrik=metric_name, deger=value)
            return

        with self._lock:
            if model_key not in self._shadow_results:
                self._shadow_results[model_key] = {}
            if metric_name not in self._shadow_results[model_key]:
                self._shadow_results[model_key][metric_name] = []
            self._shadow_results[model_key][metric_name].append(float(value))

    def record_champion_result(self, metric_name: str, value: float) -> None:
        """Canlıdaki şampiyon modelin gerçekleşen metrik sonucunu kaydeder.

        Args:
            metric_name: Metrik adı.
            value: Sayısal metrik değeri.
        """
        if not np.isfinite(value):
            logger.warning("gecersiz_sampiyon_metrik_atlandi", metrik=metric_name, deger=value)
            return

        with self._lock:
            if metric_name not in self._champion_results:
                self._champion_results[metric_name] = []
            self._champion_results[metric_name].append(float(value))

    def record_batch(
        self,
        model_key: str,
        metrics: dict[str, float],
        is_champion: bool = False,
    ) -> None:
        """Toplu metrik sözlüğünü ilgili modele kaydeder.

        Args:
            model_key: Model tanıtıcı anahtarı.
            metrics: {metrik_adi: deger} eşlemesi.
            is_champion: Kayıt şampiyona mı ait.
        """
        for metric_name, value in metrics.items():
            if is_champion:
                self.record_champion_result(metric_name, value)
            else:
                self.record_shadow_result(model_key, metric_name, value)

    def record_metrics_polars(
        self,
        df: pl.DataFrame,
        model_column: str,
        metric_columns: list[str],
        champion_key: str = "champion",
    ) -> None:
        """Polars DataFrame içindeki metrik kayıtlarını toplu içe aktarır.

        Args:
            df: Veriyi içeren Polars DataFrame.
            model_column: Model kimliğini belirten sütun adı.
            metric_columns: İçe aktarılacak metrik sütun adları.
            champion_key: Şampiyon modeli temsil eden anahtar değer.
        """
        for row in df.iter_rows(named=True):
            m_key = str(row.get(model_column, ""))
            is_champ = m_key == champion_key
            for m_col in metric_columns:
                val = row.get(m_col)
                if val is not None and np.isfinite(val):
                    if is_champ:
                        self.record_champion_result(m_col, float(val))
                    else:
                        self.record_shadow_result(m_key, m_col, float(val))

    def run_ab_test(
        self,
        challenger_key: str,
        metric_name: str = "return",
    ) -> ABTestResult:
        """Belirtilen tek bir metrik için iki örneklemli A/B hipotez testi yürütür.

        Args:
            challenger_key: Meydan okuyan model kimliği.
            metric_name: Test edilecek metrik adı.

        Returns:
            Detaylı ABTestResult değerlendirme nesnesi.
        """
        with self._lock:
            champ_raw = self._champion_results.get(metric_name, [])
            chall_raw = self._shadow_results.get(challenger_key, {}).get(metric_name, [])
            champion_metrics = np.array(champ_raw, dtype=np.float64)
            challenger_metrics = np.array(chall_raw, dtype=np.float64)

        n_champ = len(champion_metrics)
        n_chall = len(challenger_metrics)

        if n_champ < self.min_samples or n_chall < self.min_samples:
            return ABTestResult(
                champion_metric=float(np.mean(champion_metrics)) if n_champ > 0 else 0.0,
                challenger_metric=float(np.mean(challenger_metrics)) if n_chall > 0 else 0.0,
                p_value=1.0,
                significant=False,
                winner="insufficient_data",
                n_samples_champion=n_champ,
                n_samples_challenger=n_chall,
                confidence_level=1.0 - self.significance_level,
            )

        champ_mean = float(np.mean(champion_metrics))
        chall_mean = float(np.mean(challenger_metrics))

        # Two-sample t-test (Welch's t-test: eşit varyans varsayımı olmadan)
        t_stat, p_value = stats.ttest_ind(challenger_metrics, champion_metrics, equal_var=False)

        if not np.isfinite(p_value):
            p_value = 1.0

        # Cohen's d (etki büyüklüğü)
        s_champ = float(np.std(champion_metrics, ddof=1)) if n_champ > 1 else 0.0
        s_chall = float(np.std(challenger_metrics, ddof=1)) if n_chall > 1 else 0.0
        pooled_std = np.sqrt(((n_champ - 1) * s_champ**2 + (n_chall - 1) * s_chall**2) / max(1, n_champ + n_chall - 2))

        effect_size = (chall_mean - champ_mean) / max(pooled_std, 1e-8) if pooled_std > 1e-12 else 0.0

        # Statistical Power (İstatistiksel Güç Yaklaşımı)
        try:
            z_alpha = norm.ppf(1.0 - self.significance_level / 2.0)
            ncp = abs(effect_size) * np.sqrt((n_champ * n_chall) / max(1, n_champ + n_chall))
            power = float(1.0 - norm.cdf(z_alpha - ncp) + norm.cdf(-z_alpha - ncp))
        except Exception:
            power = 0.0

        # Kazanan tespiti
        if p_value < self.significance_level:
            winner = "challenger" if chall_mean > champ_mean else "champion"
        else:
            winner = "tie"

        return ABTestResult(
            champion_metric=round(champ_mean, 4),
            challenger_metric=round(chall_mean, 4),
            p_value=round(float(p_value), 4),
            significant=bool(p_value < self.significance_level),
            winner=winner,
            n_samples_champion=n_champ,
            n_samples_challenger=n_chall,
            confidence_level=round(1.0 - self.significance_level, 4),
            effect_size=round(float(effect_size), 4),
            power=round(float(power), 4),
        )

    def run_multi_metric_test(self, challenger_key: str) -> list[MultiMetricResult]:
        """Hedeflenen tüm finansal metrikler için karşılaştırma tablosu oluşturur.

        Args:
            challenger_key: Meydan okuyan model.

        Returns:
            MultiMetricResult nesneleri listesi.
        """
        results: list[MultiMetricResult] = []

        with self._lock:
            metrics_list = list(self.metrics_to_compare)
            champ_res = {k: list(v) for k, v in self._champion_results.items()}
            chall_res = {k: list(v) for k, v in self._shadow_results.get(challenger_key, {}).items()}

        for metric in metrics_list:
            champ_values = champ_res.get(metric, [])
            chall_values = chall_res.get(metric, [])

            if not champ_values or not chall_values:
                continue

            champ_mean = float(np.mean(champ_values))
            chall_mean = float(np.mean(chall_values))

            if chall_mean > champ_mean:
                winner = "challenger"
            elif champ_mean > chall_mean:
                winner = "champion"
            else:
                winner = "tie"

            denom = abs(champ_mean) if abs(champ_mean) > 1e-8 else 1.0
            improvement = ((chall_mean - champ_mean) / denom) * 100.0

            results.append(
                MultiMetricResult(
                    metric_name=metric,
                    champion_value=round(champ_mean, 4),
                    challenger_value=round(chall_mean, 4),
                    winner=winner,
                    improvement_pct=round(improvement, 2),
                )
            )

        return results

    def should_promote(self, challenger_key: str) -> PromotionDecision:
        """Meydan okuyan modelin canlıya terfi (promote) şartlarını denetler.

        Katı Kurallar:
        1. Çoklu metriklerin çoğunluğunda challenger üstün olmalıdır.
        2. En az bir kritik metrikte istatiksel olarak anlamlı üstünlük (p < 0.05) bulunmalıdır.
        3. Hiçbir metrikte istatiksel olarak anlamlı gerileme (regression) bulunmamalıdır.

        Args:
            challenger_key: Meydan okuyan model kimliği.

        Returns:
            PromotionDecision karar raporu.
        """
        multi_results = self.run_multi_metric_test(challenger_key)

        if not multi_results:
            return PromotionDecision(
                should_promote=False,
                reason="Karşılaştırma için yeterli metrik verisi bulunamadı",
                ab_results={},
                multi_metric_results=[],
                overall_winner="insufficient_data",
                confidence=0.0,
            )

        ab_results: dict[str, ABTestResult] = {}
        with self._lock:
            metric_names = list(self.metrics_to_compare)

        for metric in metric_names:
            ab_results[metric] = self.run_ab_test(challenger_key, metric)

        challenger_wins = sum(1 for r in multi_results if r.winner == "challenger")
        champion_wins = sum(1 for r in multi_results if r.winner == "champion")
        total = len(multi_results)

        significant_improvements = sum(
            1 for metric, ab in ab_results.items() if ab.winner == "challenger" and ab.significant
        )
        significant_regressions = sum(
            1 for metric, ab in ab_results.items() if ab.winner == "champion" and ab.significant
        )

        if challenger_wins > champion_wins:
            overall_winner = "challenger"
        elif champion_wins > challenger_wins:
            overall_winner = "champion"
        else:
            overall_winner = "tie"

        confidence = challenger_wins / max(total, 1)

        should_promote = bool(
            overall_winner == "challenger"
            and significant_improvements >= 1
            and significant_regressions == 0
        )

        if should_promote:
            reason = (
                f"Meydan okuyan {challenger_wins}/{total} metrikte üstün, "
                f"{significant_improvements} metrikte anlamlı gelişim var, 0 gerileme tespit edildi."
            )
        elif significant_regressions > 0:
            reason = f"Meydan okuyan modelde {significant_regressions} metrikte anlamlı performans kaybı var."
        elif overall_winner != "challenger":
            reason = f"Meydan okuyan model genel üstünlük sağlayamadı (üstünlük: {challenger_wins}/{total})."
        else:
            reason = "İstatistiksel anlamlılık eşiği sağlanamadı (p >= 0.05)."

        decision = PromotionDecision(
            should_promote=should_promote,
            reason=reason,
            ab_results=ab_results,
            multi_metric_results=multi_results,
            overall_winner=overall_winner,
            confidence=round(confidence, 4),
        )

        with self._lock:
            self._history.append(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "challenger_key": challenger_key,
                    "decision": decision.should_promote,
                    "reason": decision.reason,
                    "confidence": decision.confidence,
                    "overall_winner": decision.overall_winner,
                }
            )
            if len(self._history) > DEFAULT_MAX_HISTORY_LEN:
                self._history = self._history[-DEFAULT_MAX_HISTORY_LEN:]

        logger.info(
            "terfi_karari_uretildi",
            challenger=challenger_key,
            promote=should_promote,
            winner=overall_winner,
            guven=decision.confidence,
        )
        return decision

    def rollback(self, challenger_key: str) -> bool:
        """Meydan okuyan modelin tüm gölge kayıtlarını temizler ve geri alır.

        Args:
            challenger_key: Sıfırlanacak model kimliği.

        Returns:
            İşlem başarılı ise True.
        """
        with self._lock:
            if challenger_key in self._shadow_results:
                del self._shadow_results[challenger_key]
                logger.info("challenger_kayitlari_geri_alindi", model=challenger_key)
                return True
        return False

    def reset(self, challenger_key: str | None = None) -> None:
        """Belirtilen veya tüm modellerin test sonuçlarını sıfırlar."""
        with self._lock:
            if challenger_key:
                self._shadow_results.pop(challenger_key, None)
            else:
                self._shadow_results.clear()
                self._champion_results.clear()
                self._history.clear()

    def get_shadow_summary(self) -> dict[str, Any]:
        """Gölge moddaki tüm meydan okuyan modellerin özet istatistiklerini döndürür."""
        summary: dict[str, Any] = {}
        with self._lock:
            for model_key, metrics in self._shadow_results.items():
                m_summary: dict[str, Any] = {}
                for m_name, values in metrics.items():
                    if values:
                        m_summary[m_name] = {
                            "n_samples": len(values),
                            "mean": round(float(np.mean(values)), 4),
                            "std": round(float(np.std(values)), 4),
                            "min": round(float(np.min(values)), 4),
                            "max": round(float(np.max(values)), 4),
                        }
                summary[model_key] = m_summary
        return summary

    def get_champion_summary(self) -> dict[str, Any]:
        """Şampiyon modelin özet performans istatistiklerini döndürür."""
        summary: dict[str, Any] = {}
        with self._lock:
            for m_name, values in self._champion_results.items():
                if values:
                    summary[m_name] = {
                        "n_samples": len(values),
                        "mean": round(float(np.mean(values)), 4),
                        "std": round(float(np.std(values)), 4),
                    }
        return summary

    def get_history(self) -> list[dict[str, Any]]:
        """Geçmiş terfi kararlarının kopyasını döndürür."""
        with self._lock:
            return [h.copy() for h in self._history]

    # ===================== DUCKDB & POLARS ENTEGRASYONU =====================

    def export_decision_history_duckdb(
        self,
        db_path: str = ":memory:",
        table_name: str = "champion_challenger_audit",
    ) -> None:
        """Geçmiş terfi kararlarını DuckDB denetim tablosuna kaydeder.

        Args:
            db_path: DuckDB veritabanı dosya yolu.
            table_name: Hedef denetim tablosu adı.
        """
        with self._lock:
            hist_copy = list(self._history)

        con = duckdb.connect(db_path)
        try:
            configure_duckdb_wal(con)
            con.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    timestamp TIMESTAMP WITH TIME ZONE,
                    challenger_key VARCHAR,
                    decision BOOLEAN,
                    overall_winner VARCHAR,
                    confidence DOUBLE,
                    reason VARCHAR
                )
                """
            )
            for record in hist_copy:
                con.execute(
                    f"INSERT INTO {table_name} VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        record["timestamp"],
                        record["challenger_key"],
                        record["decision"],
                        record.get("overall_winner", "unknown"),
                        record.get("confidence", 0.0),
                        record["reason"],
                    ),
                )
            logger.info("ab_test_kararlari_duckdbye_kaydedildi", tablo=table_name, adet=len(hist_copy))
        finally:
            con.close()

    def read_decision_history_polars(
        self,
        db_path: str = ":memory:",
        table_name: str = "champion_challenger_audit",
    ) -> pl.DataFrame:
        """DuckDB tablosundaki karar geçmişini Polars DataFrame olarak okur.

        Args:
            db_path: DuckDB dosya yolu.
            table_name: Tablo adı.

        Returns:
            Karar geçmişi Polars DataFrame'i.
        """
        con = duckdb.connect(db_path)
        try:
            configure_duckdb_wal(con)
            arrow_table = con.execute(f"SELECT * FROM {table_name} ORDER BY timestamp ASC").arrow()
            return pl.from_arrow(arrow_table)  # type: ignore[return-value]
        finally:
            con.close()


__all__: Final[list[str]] = [
    "DEFAULT_AUTO_PROMOTE_THRESHOLD",
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_MAX_HISTORY_LEN",
    "DEFAULT_MIN_SAMPLES",
    "DEFAULT_SIGNIFICANCE_LEVEL",
    "DEFAULT_WAL_SIZE",
    "ABTestResult",
    "ChampionChallenger",
    "MultiMetricResult",
    "PromotionDecision",
    "configure_duckdb_wal",
]
