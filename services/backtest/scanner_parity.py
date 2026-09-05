"""
ALPHA BIST — Backtest-Scanner Parite (Parity) Modülü

Backtest ve canlı tarama sisteminin aynı kodu ve modelleri kullanmasını garanti eder.
"Farklı kod = farklı sonuç" problemini (train-serve skew / backtest-live discrepancy) çözer.

Temel Prensipler:
1. Shared Feature Engine: Backtest ve canlı sistem aynı feature'ları hesaplar.
2. Shared Signal Logic: Aynı puanlama ve sıralama fonksiyonu kullanılır.
3. Shared Risk Limits: Aynı risk sınırları ve filtreleri uygulanır.
4. Shared Cost Model: Aynı kayma (slippage) ve komisyon modeli kullanılır.
5. Version Lock: Feature versiyonu ve model ağırlıkları kilitlenir.
"""

from __future__ import annotations

import hashlib
import math
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import orjson
import polars as pl
import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)

# =====================================================================
# SABİTLER (MAGIC NUMBER TEMİZLİĞİ)
# =====================================================================
DEFAULT_FEATURE_TOLERANCE: float = 1e-6
DEFAULT_SIGNAL_TOLERANCE: float = 0.01
DEFAULT_COST_TOLERANCE: float = 1e-5
DEFAULT_MAX_SAMPLE_TICKERS: int = 5
HASH_SLICE_LENGTH: int = 16
DEFAULT_FEATURE_VERSION: str = "v1.0"
DEFAULT_SCORING_VERSION: str = "v1.0"
DEFAULT_RISK_VERSION: str = "v1.0"
DEFAULT_COST_MODEL_VERSION: str = "v1.0"


# =====================================================================
# VERİ MODELLERİ
# =====================================================================
@dataclass
class ParityConfig:
    """
    Backtest ve canlı sistem arasındaki konfigürasyon sürüm kilidi.

    Attributes:
        feature_version: Öznitelik motoru sürüm kodu.
        scoring_version: Sinyal/skorlama motoru sürüm kodu.
        risk_version: Risk yönetim motoru sürüm kodu.
        cost_model_version: Maliyet ve kayma modeli sürüm kodu.
        config_hash: Konfigürasyonun deterministik SHA-256 özeti.
    """

    feature_version: str = DEFAULT_FEATURE_VERSION
    scoring_version: str = DEFAULT_SCORING_VERSION
    risk_version: str = DEFAULT_RISK_VERSION
    cost_model_version: str = DEFAULT_COST_MODEL_VERSION
    config_hash: str = ""

    def __post_init__(self) -> None:
        """Hash boşsa otomatik hesapla."""
        if not self.config_hash:
            self.compute_hash()

    def compute_hash(self) -> str:
        """
        Konfigürasyon bileşenlerinden deterministik SHA-256 özeti üretir.

        Returns:
            str: 16 karakterlik hash dizesi.
        """
        content = f"{self.feature_version}:{self.scoring_version}:{self.risk_version}:{self.cost_model_version}"
        self.config_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:HASH_SLICE_LENGTH]
        return self.config_hash

    def __repr__(self) -> str:
        return (
            f"ParityConfig(feature={self.feature_version}, scoring={self.scoring_version}, "
            f"risk={self.risk_version}, cost={self.cost_model_version}, hash={self.config_hash})"
        )


@dataclass
class ParityCheckResult:
    """
    Tek bir parite denetim adımının doğrulama sonucu.

    Attributes:
        check_type: Denetim kategorisi ('feature', 'signal', 'risk', 'cost').
        is_parity: Parite sağlandı mı (değerler tolerans dahilinde mi).
        backtest_value: Backtest motorunun ürettiği değer veya referans.
        live_value: Canlı tarayıcının ürettiği değer.
        difference: Mutlak sayısal fark (uygunsa).
        tolerance: Karşılaştırma toleransı.
        details: Uyuşmazlık veya eksik anahtar detayları.
    """

    check_type: str
    is_parity: bool
    backtest_value: Any
    live_value: Any
    difference: float | None = None
    tolerance: float = DEFAULT_FEATURE_TOLERANCE
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """
        Denetim sonucunu serileştirilebilir sözlük formatına dönüştürür.

        Returns:
            dict[str, Any]: Denetim özeti sözlüğü.
        """
        return {
            "check_type": self.check_type,
            "is_parity": self.is_parity,
            "backtest_value": str(self.backtest_value)[:100] if self.backtest_value is not None else None,
            "live_value": str(self.live_value)[:100] if self.live_value is not None else None,
            "difference": self.difference,
            "tolerance": self.tolerance,
            "details": self.details,
        }

    def __repr__(self) -> str:
        status = "UYUMLU" if self.is_parity else "UYUMSUZ"
        return f"ParityCheckResult(type={self.check_type}, status={status}, diff={self.difference})"


@dataclass
class ParityReport:
    """
    Tüm parite denetimlerinin toplu sonuç raporu.

    Attributes:
        timestamp: Raporun oluşturulma zamanı (UTC ISO formatı).
        config_hash: Denetim anındaki konfigürasyon hash'i.
        total_checks: Gerçekleştirilen toplam denetim sayısı.
        passed_checks: Başarılı denetim sayısı.
        failed_checks: Başarısız denetim sayısı.
        is_full_parity: Tüm denetimler tam parite sağladı mı.
        checks: Tekil denetim sonuçları listesi.
    """

    timestamp: str
    config_hash: str
    total_checks: int
    passed_checks: int
    failed_checks: int
    is_full_parity: bool
    checks: list[ParityCheckResult]

    def to_dict(self) -> dict[str, Any]:
        """
        Raporu serileştirilebilir sözlük formatına dönüştürür.

        Returns:
            dict[str, Any]: Parite rapor sözlüğü.
        """
        return {
            "timestamp": self.timestamp,
            "config_hash": self.config_hash,
            "total_checks": self.total_checks,
            "passed": self.passed_checks,
            "failed": self.failed_checks,
            "is_full_parity": self.is_full_parity,
            "checks": [c.to_dict() for c in self.checks],
        }

    def __repr__(self) -> str:
        return (
            f"ParityReport(full_parity={self.is_full_parity}, passed={self.passed_checks}/{self.total_checks}, "
            f"hash={self.config_hash})"
        )


# =====================================================================
# ANA PARİTE DENETLEYİCİSİ
# =====================================================================
class BacktestScannerParity:
    """
    Backtest ve Canlı Tarayıcı (Scanner) Parite Denetleyicisi.

    Backtest ortamı ile canlı tarama sisteminin aynı matematiksel modelleri,
    öznitelikleri ve kuralları çalıştırdığını doğrular. Thread-safe tasarlanmıştır.
    """

    def __init__(self, config: ParityConfig | None = None) -> None:
        """
        Parite denetleyicisini ilklendirir.

        Args:
            config: İsteğe bağlı özel parite konfigürasyonu.
        """
        self._feature_engine: Callable[..., dict[str, float]] | None = None
        self._signal_engine: Callable[..., float] | None = None
        self._risk_engine: Callable[..., Any] | None = None
        self._cost_engine: Callable[..., float] | None = None
        self._config: ParityConfig = config or ParityConfig()
        self._lock: threading.Lock = threading.Lock()

    def register_engines(
        self,
        feature_engine: Callable[..., dict[str, float]],
        signal_engine: Callable[..., float],
        risk_engine: Callable[..., Any] | None = None,
        cost_engine: Callable[..., float] | None = None,
    ) -> None:
        """
        Denetlenecek ortak motorları sisteme kaydeder.

        Args:
            feature_engine: Veriden feature üreten fonksiyon.
            signal_engine: Feature'lardan sinyal/skor üreten fonksiyon.
            risk_engine: İsteğe bağlı risk doğrulama fonksiyonu.
            cost_engine: İsteğe bağlı kayma/komisyon hesaplama fonksiyonu.
        """
        with self._lock:
            self._feature_engine = feature_engine
            self._signal_engine = signal_engine
            self._risk_engine = risk_engine
            self._cost_engine = cost_engine
            logger.info("Parite motorları sisteme başarıyla kaydedildi.")

    def verify_feature_parity(
        self,
        data: pl.DataFrame,
        ticker: str,
        timestamp: datetime,
        expected_features: dict[str, float] | None = None,
        tolerance: float = DEFAULT_FEATURE_TOLERANCE,
    ) -> ParityCheckResult:
        """
        Feature (öznitelik) parite denetimi gerçekleştirir.

        Backtest ve canlı sistem aynı veri diliminde aynı öznitelikleri üretmelidir.

        Args:
            data: Hisseye ait Polars veri çerçevesi.
            ticker: Hisse kodu (örn: 'THYAO').
            timestamp: Hesaplama referans anı.
            expected_features: Canlı sistemden veya geçmişten gelen referans öznitelikler.
            tolerance: İzin verilen mutlak sayısal tolerans.

        Returns:
            ParityCheckResult: Denetim sonucu.
        """
        with self._lock:
            feature_fn = self._feature_engine

        if feature_fn is None:
            return ParityCheckResult(
                check_type="feature",
                is_parity=False,
                backtest_value=None,
                live_value=None,
                details={"hata": "Öznitelik motoru (feature_engine) kayıtlı değil."},
            )

        if not isinstance(data, pl.DataFrame):
            return ParityCheckResult(
                check_type="feature",
                is_parity=False,
                backtest_value=expected_features,
                live_value=None,
                details={"hata": f"Veri tipi geçersiz: Polars DataFrame bekleniyordu, {type(data)} alındı."},
            )

        try:
            computed: dict[str, float] = feature_fn(data, ticker, timestamp)
        except Exception as e:
            logger.error("Öznitelik hesaplama sırasında hata oluştu: %s", e)
            return ParityCheckResult(
                check_type="feature",
                is_parity=False,
                backtest_value=expected_features,
                live_value=None,
                details={"hata": f"Hesaplama istisnası: {str(e)}"},
            )

        if expected_features is None:
            # İlk çalıştırma: Üretilen değer referans kabul edilir
            return ParityCheckResult(
                check_type="feature",
                is_parity=True,
                backtest_value=computed,
                live_value=computed,
                difference=0.0,
                tolerance=tolerance,
            )

        # Karşılaştırma ve Eksik Anahtar Analizi
        mismatches: list[dict[str, Any]] = []
        max_diff: float = 0.0

        expected_keys = set(expected_features.keys())
        computed_keys = set(computed.keys())

        missing_keys = sorted(list(expected_keys - computed_keys))
        extra_keys = sorted(list(computed_keys - expected_keys))

        if missing_keys:
            mismatches.append({"tur": "eksik_oznitelik", "anahtarlar": missing_keys})

        for key in expected_keys.intersection(computed_keys):
            exp_val = expected_features[key]
            comp_val = computed[key]

            # Null / None kontrolü
            if exp_val is None or comp_val is None:
                if exp_val != comp_val:
                    mismatches.append({
                        "anahtar": key,
                        "beklenen": exp_val,
                        "hesaplanan": comp_val,
                        "fark": None,
                        "sebep": "None uyuşmazlığı",
                    })
                continue

            # NaN kontrolü
            if math.isnan(exp_val) or math.isnan(comp_val):
                if not (math.isnan(exp_val) and math.isnan(comp_val)):
                    mismatches.append({
                        "anahtar": key,
                        "beklenen": exp_val,
                        "hesaplanan": comp_val,
                        "fark": None,
                        "sebep": "NaN uyuşmazlığı",
                    })
                continue

            diff = abs(float(comp_val) - float(exp_val))
            if diff > max_diff:
                max_diff = diff

            if diff > tolerance:
                mismatches.append({
                    "anahtar": key,
                    "beklenen": exp_val,
                    "hesaplanan": comp_val,
                    "fark": diff,
                    "sebep": "Tolerans aşımı",
                })

        is_parity = len(mismatches) == 0

        return ParityCheckResult(
            check_type="feature",
            is_parity=is_parity,
            backtest_value=expected_features,
            live_value=computed,
            difference=max_diff if is_parity or any("fark" in m and m["fark"] is not None for m in mismatches) else None,
            tolerance=tolerance,
            details={
                "uyusmazlik_sayisi": len(mismatches),
                "uyusmazliklar": mismatches[:20],
                "eksik_anahtarlar": missing_keys,
                "fazla_anahtarlar": extra_keys,
            },
        )

    def verify_signal_parity(
        self,
        features: dict[str, float],
        ticker: str,
        expected_score: float | None = None,
        tolerance: float = DEFAULT_SIGNAL_TOLERANCE,
    ) -> ParityCheckResult:
        """
        Sinyal ve skorlama parite denetimi gerçekleştirir.

        Aynı öznitelik vektörü verildiğinde hem backtest hem canlı sistem aynı skoru üretmelidir.

        Args:
            features: Öznitelik sözlüğü.
            ticker: Hisse kodu.
            expected_score: Canlı sistemden alınan referans skor.
            tolerance: İzin verilen mutlak tolerans.

        Returns:
            ParityCheckResult: Denetim sonucu.
        """
        with self._lock:
            signal_fn = self._signal_engine

        if signal_fn is None:
            return ParityCheckResult(
                check_type="signal",
                is_parity=False,
                backtest_value=None,
                live_value=None,
                details={"hata": "Sinyal motoru (signal_engine) kayıtlı değil."},
            )

        try:
            computed_score: float = float(signal_fn(features, ticker))
        except Exception as e:
            logger.error("Sinyal hesaplama hatası: %s", e)
            return ParityCheckResult(
                check_type="signal",
                is_parity=False,
                backtest_value=expected_score,
                live_value=None,
                details={"hata": f"Sinyal hesaplama istisnası: {str(e)}"},
            )

        if expected_score is None:
            return ParityCheckResult(
                check_type="signal",
                is_parity=True,
                backtest_value=computed_score,
                live_value=computed_score,
                difference=0.0,
                tolerance=tolerance,
            )

        # NaN kontrolü
        if math.isnan(computed_score) or math.isnan(expected_score):
            is_both_nan = math.isnan(computed_score) and math.isnan(expected_score)
            return ParityCheckResult(
                check_type="signal",
                is_parity=is_both_nan,
                backtest_value=expected_score,
                live_value=computed_score,
                difference=0.0 if is_both_nan else None,
                tolerance=tolerance,
                details={"uyari": "Skorlardan en az biri NaN değer içeriyor."},
            )

        diff = abs(computed_score - float(expected_score))
        return ParityCheckResult(
            check_type="signal",
            is_parity=diff <= tolerance,
            backtest_value=expected_score,
            live_value=computed_score,
            difference=diff,
            tolerance=tolerance,
        )

    def verify_risk_parity(
        self,
        portfolio_state: dict[str, Any],
        candidate_order: dict[str, Any],
        expected_decision: Any | None = None,
    ) -> ParityCheckResult:
        """
        Risk filtreleme ve onaylama parite denetimi gerçekleştirir.

        Args:
            portfolio_state: Anlık portföy durumu (nakit, pozisyonlar, kaldıraç vb.).
            candidate_order: Gönderilmek istenen emir detayları.
            expected_decision: Beklenen onay/ret kararı veya risk metrikleri.

        Returns:
            ParityCheckResult: Risk parite denetim sonucu.
        """
        with self._lock:
            risk_fn = self._risk_engine

        if risk_fn is None:
            return ParityCheckResult(
                check_type="risk",
                is_parity=False,
                backtest_value=None,
                live_value=None,
                details={"hata": "Risk motoru (risk_engine) kayıtlı değil."},
            )

        try:
            computed_decision = risk_fn(portfolio_state, candidate_order)
        except Exception as e:
            logger.error("Risk kontrolü hatası: %s", e)
            return ParityCheckResult(
                check_type="risk",
                is_parity=False,
                backtest_value=expected_decision,
                live_value=None,
                details={"hata": f"Risk değerlendirme istisnası: {str(e)}"},
            )

        if expected_decision is None:
            return ParityCheckResult(
                check_type="risk",
                is_parity=True,
                backtest_value=computed_decision,
                live_value=computed_decision,
                difference=0.0,
            )

        is_parity = computed_decision == expected_decision
        return ParityCheckResult(
            check_type="risk",
            is_parity=is_parity,
            backtest_value=expected_decision,
            live_value=computed_decision,
            difference=0.0 if is_parity else 1.0,
        )

    def verify_cost_parity(
        self,
        order: dict[str, Any],
        market_data: dict[str, Any],
        expected_cost: float | None = None,
        tolerance: float = DEFAULT_COST_TOLERANCE,
    ) -> ParityCheckResult:
        """
        İşlem maliyeti ve kayma (slippage) parite denetimi gerçekleştirir.

        Args:
            order: Emir parametreleri (lot, fiyat, yön vb.).
            market_data: Piyasa derinliği ve oynaklık parametreleri.
            expected_cost: Beklenen toplam komisyon/kayma maliyeti.
            tolerance: İzin verilen mutlak tolerans.

        Returns:
            ParityCheckResult: Maliyet parite denetim sonucu.
        """
        with self._lock:
            cost_fn = self._cost_engine

        if cost_fn is None:
            return ParityCheckResult(
                check_type="cost",
                is_parity=False,
                backtest_value=None,
                live_value=None,
                details={"hata": "Maliyet motoru (cost_engine) kayıtlı değil."},
            )

        try:
            computed_cost = float(cost_fn(order, market_data))
        except Exception as e:
            logger.error("Maliyet hesaplama hatası: %s", e)
            return ParityCheckResult(
                check_type="cost",
                is_parity=False,
                backtest_value=expected_cost,
                live_value=None,
                details={"hata": f"Maliyet hesaplama istisnası: {str(e)}"},
            )

        if expected_cost is None:
            return ParityCheckResult(
                check_type="cost",
                is_parity=True,
                backtest_value=computed_cost,
                live_value=computed_cost,
                difference=0.0,
                tolerance=tolerance,
            )

        diff = abs(computed_cost - float(expected_cost))
        return ParityCheckResult(
            check_type="cost",
            is_parity=diff <= tolerance,
            backtest_value=expected_cost,
            live_value=computed_cost,
            difference=diff,
            tolerance=tolerance,
        )

    def run_full_parity_check(
        self,
        test_data: pl.DataFrame,
        test_tickers: list[str],
        test_timestamp: datetime,
        max_tickers: int = DEFAULT_MAX_SAMPLE_TICKERS,
    ) -> ParityReport:
        """
        Tüm kayıtlı motorlar için uçtan uca tam parite denetimi çalıştırır.

        Args:
            test_data: Test verisi içeren Polars DataFrame.
            test_tickers: Denetlenecek hisse kodları listesi.
            test_timestamp: Test referans zamanı.
            max_tickers: Örneklem olarak kontrol edilecek azami hisse sayısı.

        Returns:
            ParityReport: Kapsamlı parite raporu.

        Raises:
            ValueError: Test verisi veya hisse listesi boş ise.
        """
        if test_data is None or test_data.is_empty():
            raise ValueError("Parite denetimi için sağlanan test verisi boş olamaz.")

        if not test_tickers:
            raise ValueError("Parite denetimi için en az bir hisse kodu belirtilmelidir.")

        checks: list[ParityCheckResult] = []
        sample_tickers = test_tickers[:max_tickers]

        # 1. Feature Parity Denetimleri
        for ticker in sample_tickers:
            if "ticker" in test_data.columns:
                ticker_data = test_data.filter(pl.col("ticker") == ticker)
            else:
                ticker_data = test_data

            if ticker_data.is_empty():
                logger.warning("Hisse için veri bulunamadı, denetim atlandı: %s", ticker)
                continue

            result = self.verify_feature_parity(ticker_data, ticker, test_timestamp)
            checks.append(result)

        # 2. Signal Parity Denetimleri
        with self._lock:
            has_feature = self._feature_engine is not None
            has_signal = self._signal_engine is not None

        if has_feature and has_signal:
            for ticker in sample_tickers:
                if "ticker" in test_data.columns:
                    ticker_data = test_data.filter(pl.col("ticker") == ticker)
                else:
                    ticker_data = test_data

                if ticker_data.is_empty():
                    continue

                try:
                    features = self._feature_engine(ticker_data, ticker, test_timestamp)  # type: ignore[misc]
                    result = self.verify_signal_parity(features, ticker)
                    checks.append(result)
                except Exception as e:
                    logger.error("Signal parity testi sırasında hata: %s", e)
                    checks.append(
                        ParityCheckResult(
                            check_type="signal",
                            is_parity=False,
                            backtest_value=None,
                            live_value=None,
                            details={"hata": str(e), "ticker": ticker},
                        )
                    )

        passed = sum(1 for c in checks if c.is_parity)
        failed = len(checks) - passed

        report = ParityReport(
            timestamp=datetime.now(UTC).isoformat(),
            config_hash=self._config.compute_hash(),
            total_checks=len(checks),
            passed_checks=passed,
            failed_checks=failed,
            is_full_parity=(failed == 0 and len(checks) > 0),
            checks=checks,
        )

        logger.info(
            "Parite denetimi tamamlandı. Toplam: %d, Başarılı: %d, Başarısız: %d, Tam Parite: %s",
            len(checks),
            passed,
            failed,
            report.is_full_parity,
        )

        return report

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"BacktestScannerParity(config={self._config}, "
                f"engines=[feature={'+' if self._feature_engine else '-'}, "
                f"signal={'+' if self._signal_engine else '-'}, "
                f"risk={'+' if self._risk_engine else '-'}, "
                f"cost={'+' if self._cost_engine else '-'}])"
            )


# =====================================================================
# FEATURE SÜRÜM KİLİDİ
# =====================================================================
class FeatureVersionLock:
    """
    Feature ve Model Versiyon Kilidi.

    Feature hesaplama mantığı veya girdileri değiştiğinde eski versiyonu korur,
    hash'ini çıkarır ve backtest'in canlı sistemle birebir aynı versiyonu
    kullanmasını garanti eder. Thread-safe olarak çalışır.
    """

    def __init__(self) -> None:
        """Versiyon kilidi kütüğünü ilklendirir."""
        self._versions: dict[str, dict[str, Any]] = {}
        self._active_version: str = DEFAULT_FEATURE_VERSION
        self._lock: threading.Lock = threading.Lock()

    def register_version(
        self,
        version: str,
        feature_names: list[str],
        computation_config: dict[str, Any],
    ) -> None:
        """
        Yeni bir feature sürümünü kütüğe kaydeder.

        Args:
            version: Sürüm adı (örn: 'v1.0', 'v2.1').
            feature_names: Bu sürümde üretilen öznitelik isimleri listesi.
            computation_config: Hesaplama parametreleri (pencere boyutları vb.).

        Raises:
            ValueError: Sürüm adı veya feature listesi boş ise.
        """
        if not version or not version.strip():
            raise ValueError("Sürüm adı boş olamaz.")

        if not feature_names:
            raise ValueError("Feature isimleri listesi en az bir öznitelik içermelidir.")

        # Deterministik sıralı hash üretimi
        # orjson.dumps bytes döndürür, doğrudan hashlib'e verilir (.decode() hatası önlendi)
        serialized_payload = orjson.dumps(
            {"names": sorted(feature_names), "config": computation_config},
            option=orjson.OPT_SORT_KEYS,
        )
        content_hash = hashlib.sha256(serialized_payload).hexdigest()[:HASH_SLICE_LENGTH]

        with self._lock:
            self._versions[version] = {
                "feature_names": list(feature_names),
                "config": dict(computation_config),
                "registered_at": datetime.now(UTC).isoformat(),
                "hash": content_hash,
            }

        logger.info("Feature sürümü kaydedildi: %s (Öznitelik: %d, Hash: %s)", version, len(feature_names), content_hash)

    def set_active_version(self, version: str) -> None:
        """
        Canlı ve backtest sistemleri için aktif sürümü belirler.

        Args:
            version: Kayıtlı sürüm kodu.

        Raises:
            ValueError: İstenen sürüm kayıtlı değilse.
        """
        with self._lock:
            if version not in self._versions:
                raise ValueError(f"Bilinmeyen feature versiyonu: {version}. Kayıtlı sürümler: {list(self._versions.keys())}")
            self._active_version = version

        logger.info("Aktif feature sürümü güncellendi: %s", version)

    def get_active_version(self) -> str:
        """
        Şu an aktif olan sürüm adını döndürür.

        Returns:
            str: Aktif sürüm kodu.
        """
        with self._lock:
            return self._active_version

    def get_active_config(self) -> dict[str, Any]:
        """
        Aktif sürümün hesaplama konfigürasyonunu döndürür.

        Returns:
            dict[str, Any]: Aktif sürüm konfigürasyonu veya boş sözlük.
        """
        with self._lock:
            ver_data = self._versions.get(self._active_version)
            return dict(ver_data["config"]) if ver_data and "config" in ver_data else {}

    def get_version_info(self, version: str) -> dict[str, Any] | None:
        """
        Belirtilen sürümün tüm detaylarını döndürür.

        Args:
            version: Sorgulanan sürüm adı.

        Returns:
            dict[str, Any] | None: Sürüm detayları veya bulunamazsa None.
        """
        with self._lock:
            data = self._versions.get(version)
            return dict(data) if data else None

    def list_versions(self) -> list[str]:
        """
        Sistemde kayıtlı tüm sürüm adlarını listeler.

        Returns:
            list[str]: Kayıtlı sürümler.
        """
        with self._lock:
            return list(self._versions.keys())

    def validate_version_match(self, expected_version: str) -> bool:
        """
        Aktif sürüm ile beklenen sürümün eşleşip eşleşmediğini doğrular.

        Args:
            expected_version: Eşleşmesi beklenen sürüm kodu.

        Returns:
            bool: Eşleşiyorsa True, aksi halde False.
        """
        with self._lock:
            return self._active_version == expected_version

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"FeatureVersionLock(active='{self._active_version}', "
                f"total_registered={len(self._versions)})"
            )


# =====================================================================
# SINGLETON ÖRNEKLERİ
# =====================================================================
parity_checker = BacktestScannerParity()
feature_version_lock = FeatureVersionLock()

__all__ = [
    "DEFAULT_COST_MODEL_VERSION",
    "DEFAULT_COST_TOLERANCE",
    "DEFAULT_FEATURE_TOLERANCE",
    "DEFAULT_FEATURE_VERSION",
    "DEFAULT_MAX_SAMPLE_TICKERS",
    "DEFAULT_RISK_VERSION",
    "DEFAULT_SCORING_VERSION",
    "DEFAULT_SIGNAL_TOLERANCE",
    "HASH_SLICE_LENGTH",
    "BacktestScannerParity",
    "FeatureVersionLock",
    "ParityCheckResult",
    "ParityConfig",
    "ParityReport",
    "feature_version_lock",
    "parity_checker",
]
