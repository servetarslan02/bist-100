"""
ALPHA BIST — Feature Pipeline Orchestrator v1.0

Tüm feature modüllerini birleştiren ana pipeline:
1. Veri al (calculator, motors, fundamental, macro, sentiment)
2. BIST-specific features hesapla
3. Feature contract ile doğrula
4. Feature store'a kaydet (PIT-aware, versioned)
5. Drift detection çalıştır
6. Feature selection uygula
7. Sonuçları raporla

FAZ 5: Pipeline Orchestrator
"""

import time
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


# =====================================================
# Data Classes
# =====================================================

@dataclass
class PipelineConfig:
    """Pipeline konfigürasyonu."""
    # Version
    feature_version: str = "v1"

    # Drift detection
    enable_drift_detection: bool = True
    drift_ks_threshold: float = 0.05
    drift_psi_threshold: float = 0.25
    drift_zscore_threshold: float = 2.0

    # Feature selection
    enable_feature_selection: bool = True
    max_features: int = 100
    variance_threshold: float = 0.01
    correlation_threshold: float = 0.95

    # BIST features
    enable_bist_features: bool = True

    # Contract validation
    enable_contract_validation: bool = True

    # Store
    enable_store: bool = True
    store_ttl_seconds: int = 86400  # 1 gün


@dataclass
class PipelineResult:
    """Pipeline sonucu."""
    ticker: str
    timestamp: str
    version: str
    total_features: int
    selected_features: int
    features: Dict[str, float]
    drift_report: Optional[Dict] = None
    contract_report: Optional[Dict] = None
    store_snapshot_hash: Optional[str] = None
    duration_ms: float = 0.0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "timestamp": self.timestamp,
            "version": self.version,
            "total_features": self.total_features,
            "selected_features": self.selected_features,
            "feature_count": len(self.features),
            "drift_report": self.drift_report,
            "contract_report": self.contract_report,
            "store_snapshot_hash": self.store_snapshot_hash,
            "duration_ms": round(self.duration_ms, 2),
            "errors": self.errors,
        }


# =====================================================
# Pipeline Orchestrator
# =====================================================

class FeaturePipelineOrchestrator:
    """Feature pipeline orchestrator — tüm modülleri birleştirir.

    Kullanım:
        pipeline = FeaturePipelineOrchestrator()
        result = await pipeline.run(
            ticker="THYAO",
            ohlcv_df=df,
            macro_data=macro,
            fundamentals=fundamentals,
        )
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()

        # Modüller (lazy init)
        self._store = None
        self._drift_detector = None
        self._importance_tracker = None
        self._bist_engine = None
        self._contract_validator = None
        self._feature_selector = None

        # Calculator
        self._calculator = None

    # =====================================================
    # MODÜL ERİŞİM (lazy init)
    # =====================================================

    @property
    def store(self):
        if self._store is None:
            from .store import FeatureStore
            self._store = FeatureStore()
        return self._store

    @property
    def drift_detector(self):
        if self._drift_detector is None:
            from .drift_detector import FeatureDriftDetector
            self._drift_detector = FeatureDriftDetector(
                ks_threshold=self.config.drift_ks_threshold,
                psi_threshold=self.config.drift_psi_threshold,
                zscore_threshold=self.config.drift_zscore_threshold,
            )
        return self._drift_detector

    @property
    def importance_tracker(self):
        if self._importance_tracker is None:
            from .importance_tracker import FeatureImportanceTracker
            self._importance_tracker = FeatureImportanceTracker()
        return self._importance_tracker

    @property
    def bist_engine(self):
        if self._bist_engine is None:
            from .bist_features import BISTFeatureEngine
            self._bist_engine = BISTFeatureEngine()
        return self._bist_engine

    @property
    def feature_selector(self):
        if self._feature_selector is None:
            from .feature_selector import FeatureSelector
            self._feature_selector = FeatureSelector()
        return self._feature_selector

    @property
    def calculator(self):
        if self._calculator is None:
            from .calculator import FeatureCalculator
            self._calculator = FeatureCalculator()
        return self._calculator

    # =====================================================
    # ANA PIPELINE
    # =====================================================

    async def run(
        self,
        ticker: str,
        ohlcv_df: Any = None,
        features: Optional[Dict[str, float]] = None,
        macro_data: Optional[Dict] = None,
        fundamentals: Optional[Dict] = None,
        kap_events: Optional[List[Dict]] = None,
        foreign_data: Optional[Dict] = None,
        sector_data: Optional[Dict] = None,
        index_data: Optional[Dict] = None,
        price_history: Optional[List[float]] = None,
        volume_history: Optional[List[float]] = None,
        mask: Any = None,
    ) -> PipelineResult:
        """Tam feature pipeline çalıştır.

        Args:
            ticker: Hisse kodu
            ohlcv_df: OHLCV DataFrame (calculator için)
            features: Hazır feature dict (hesaplanmış ise)
            macro_data: Makro veriler
            fundamentals: Finansal veriler
            kap_events: KAP olayları
            foreign_data: Yabancı yatırımcı verileri
            sector_data: Sektör verileri
            index_data: Endeks verileri
            price_history: Fiyat geçmişi
            volume_history: Hacim geçmişi
            mask: Tradability mask

        Returns:
            PipelineResult
        """
        start = time.monotonic()
        errors = []
        version = self.config.feature_version
        now = datetime.now(timezone.utc).isoformat()

        logger.info("Feature pipeline started", ticker=ticker, version=version)

        # ━━━ STEP 1: Feature Hesaplama ━━━
        all_features: Dict[str, float] = {}

        # Calculator'dan hesapla (varsa)
        if ohlcv_df is not None:
            try:
                computed = self.calculator.compute_all_features(
                    ohlcv_df, mask=mask, ticker=ticker
                )
                all_features.update(computed)
                logger.debug("Calculator features", ticker=ticker, count=len(computed))
            except Exception as e:
                errors.append(f"Calculator failed: {e}")
                logger.warning("Calculator failed", ticker=ticker, error=str(e))

        # Hazır feature'ları ekle
        if features:
            all_features.update(features)

        # ━━━ STEP 2: BIST-Specific Features ━━━
        if self.config.enable_bist_features:
            try:
                bist_result = self.bist_engine.compute_all(
                    ticker=ticker,
                    price_history=price_history or self._extract_prices(ohlcv_df),
                    volume_history=volume_history or self._extract_volumes(ohlcv_df),
                    macro_data=macro_data,
                    kap_events=kap_events,
                    foreign_data=foreign_data,
                    fundamentals=fundamentals,
                    sector_data=sector_data,
                    index_data=index_data,
                )
                bist_features = bist_result.to_feature_dict()
                all_features.update(bist_features)
                logger.debug("BIST features", ticker=ticker, count=len(bist_features))
            except Exception as e:
                errors.append(f"BIST features failed: {e}")
                logger.warning("BIST features failed", ticker=ticker, error=str(e))

        total_features = len(all_features)

        # ━━━ STEP 3: Contract Validation ━━━
        contract_report = None
        if self.config.enable_contract_validation:
            contract_report = self._validate_contract(all_features, ticker)
            if contract_report.get("invalid_count", 0) > 0:
                # Invalid feature'ları kaldır
                invalid = contract_report.get("invalid_features", [])
                for name in invalid:
                    all_features.pop(name, None)
                logger.info("Contract validation removed features",
                           ticker=ticker, count=len(invalid))

        # ━━━ STEP 4: Feature Store ━━━
        snapshot_hash = None
        if self.config.enable_store:
            try:
                from .store import FeatureSource
                snapshot = self.store.set(
                    ticker=ticker,
                    features=all_features,
                    version=version,
                    source=FeatureSource.CALCULATOR,
                    available_at=now,
                )
                snapshot_hash = snapshot.snapshot_hash
                logger.debug("Features stored", ticker=ticker, hash=snapshot_hash)
            except Exception as e:
                errors.append(f"Store failed: {e}")
                logger.warning("Store failed", ticker=ticker, error=str(e))

        # ━━━ STEP 5: Drift Detection ━━━
        drift_report = None
        if self.config.enable_drift_detection:
            try:
                baseline = self.store.get_all_baselines(ticker) if self.config.enable_store else {}
                if baseline:
                    # Son 30% current, geri kalan baseline
                    current_values = {}
                    for name, values in baseline.items():
                        if len(values) >= 60:
                            split = int(len(values) * 0.7)
                            current_values[name] = values[split:]

                    # Sadece current_values'daki feature'lar için baseline
                    baseline_subset = {
                        k: v[:int(len(v) * 0.7)]
                        for k, v in baseline.items()
                        if k in current_values and len(v) >= 60
                    }

                    if baseline_subset and current_values:
                        drift_result = self.drift_detector.detect_all(
                            ticker=ticker,
                            baseline=baseline_subset,
                            current=current_values,
                        )
                        drift_report = drift_result.to_dict()

                        if drift_result.drifted_features > 0:
                            logger.warning(
                                "Feature drift detected",
                                ticker=ticker,
                                drifted=drift_result.drifted_features,
                                critical=drift_result.critical_drifts,
                            )
            except Exception as e:
                errors.append(f"Drift detection failed: {e}")
                logger.warning("Drift detection failed", ticker=ticker, error=str(e))

        # ━━━ STEP 6: Feature Selection ━━━
        selected_features = total_features
        if self.config.enable_feature_selection and total_features > self.config.max_features:
            try:
                # Importance-based selection (varsa)
                latest_importance = self.importance_tracker.get_latest(ticker)
                if latest_importance:
                    selected_names = self.importance_tracker.select_top_features(
                        latest_importance,
                        top_n=self.config.max_features,
                    )
                    all_features = {
                        k: v for k, v in all_features.items()
                        if k in selected_names
                    }
                    selected_features = len(all_features)
                else:
                    # Importance yoksa, varyans + korelasyon ile seç
                    # (feature_selector ile)
                    selected_features = min(total_features, self.config.max_features)
            except Exception as e:
                errors.append(f"Feature selection failed: {e}")

        duration = (time.monotonic() - start) * 1000

        result = PipelineResult(
            ticker=ticker,
            timestamp=now,
            version=version,
            total_features=total_features,
            selected_features=selected_features,
            features=all_features,
            drift_report=drift_report,
            contract_report=contract_report,
            store_snapshot_hash=snapshot_hash,
            duration_ms=round(duration, 2),
            errors=errors,
        )

        logger.info(
            "Feature pipeline completed",
            ticker=ticker,
            total=total_features,
            selected=selected_features,
            duration_ms=round(duration, 2),
            errors=len(errors),
        )

        return result

    # =====================================================
    # CONTRACT VALIDATION
    # =====================================================

    def _validate_contract(
        self, features: Dict[str, float], ticker: str,
    ) -> Dict[str, Any]:
        """Feature contract validation.

        Kontroller:
        - NaN/Inf kontrolü
        - Range validation (makul değerler)
        - Type kontrolü (float olmalı)
        """
        invalid = []
        warnings = []

        for name, value in features.items():
            # Type check
            if not isinstance(value, (int, float)):
                invalid.append(name)
                continue

            # NaN/Inf check
            if value != value:  # NaN
                invalid.append(name)
                continue
            if value == float('inf') or value == float('-inf'):
                invalid.append(name)
                continue

            # Range validation (geniş tolerans)
            if abs(value) > 1e12:
                warnings.append(f"{name}={value}: extremely large value")

        return {
            "total": len(features),
            "valid": len(features) - len(invalid),
            "invalid_count": len(invalid),
            "invalid_features": invalid,
            "warnings": warnings,
        }

    # =====================================================
    # YARDIMCI
    # =====================================================

    @staticmethod
    def _extract_prices(ohlcv_df: Any) -> Optional[List[float]]:
        """DataFrame'den fiyatları çıkar."""
        if ohlcv_df is None:
            return None
        try:
            if hasattr(ohlcv_df, 'columns') and 'Close' in ohlcv_df.columns:
                return ohlcv_df['Close'].tolist()
            elif hasattr(ohlcv_df, 'columns') and 'close' in ohlcv_df.columns:
                return ohlcv_df['close'].tolist()
        except Exception:
            pass
        return None

    @staticmethod
    def _extract_volumes(ohlcv_df: Any) -> Optional[List[float]]:
        """DataFrame'den hacimleri çıkar."""
        if ohlcv_df is None:
            return None
        try:
            if hasattr(ohlcv_df, 'columns') and 'Volume' in ohlcv_df.columns:
                return ohlcv_df['Volume'].tolist()
            elif hasattr(ohlcv_df, 'columns') and 'volume' in ohlcv_df.columns:
                return ohlcv_df['volume'].tolist()
        except Exception:
            pass
        return None

    # =====================================================
    # RAPOR
    # =====================================================

    def get_pipeline_status(self) -> Dict[str, Any]:
        """Pipeline durumu."""
        return {
            "config": {
                "version": self.config.feature_version,
                "drift_detection": self.config.enable_drift_detection,
                "feature_selection": self.config.enable_feature_selection,
                "bist_features": self.config.enable_bist_features,
                "contract_validation": self.config.enable_contract_validation,
                "store": self.config.enable_store,
            },
            "store_stats": self.store.get_stats() if self.config.enable_store else None,
            "importance_summary": None,  # Lazy
        }


# Singleton
feature_pipeline = FeaturePipelineOrchestrator()
