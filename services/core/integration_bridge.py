"""ALPHA BIST — Integration Bridge v1.0

Tüm yeni modülleri asıl motorlara bağlayan entegrasyon katmanı.
Bu dosya, orchestrator ve learning pipeline tarafından çağrılır.

Kullanım:
    from services.core.integration_bridge import integration_bridge

    # Pipeline her hisse için çağrılır
    result = integration_bridge.enhance_pipeline_result(ticker, result, features, regime)

    # Learning cycle'da çağrılır
    learning_result = integration_bridge.enhance_learning_cycle(learning_result)

    # Trade plan'da çağrılır
    plan = integration_bridge.enhance_trade_plan(ticker, decision, prices, regime)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


class IntegrationBridge:
    """Tüm yeni modülleri asıl motorlara bağlayan entegrasyon katmanı.

    Modüller:
    - FeatureStabilityAnalyzer → feature drift tespiti
    - CalibrationEnhanced → confidence kalibrasyon
    - RegimeLimitsManager → rejime göre risk limitleri
    - PortfolioEnhancements → turnover/hysteresis/constraints
    - BacktestEnhancements → T+1/market impact/delisted
    - EventEnhancements → idempotency/retry/correlation
    - WalkForwardEnsemble → WF ensemble eğitimi
    - ModelDegradationMonitor → model degradation
    - FeatureSelector → feature selection
    - FeatureLineageTracker → feature lineage
    - FeatureVersionManager → feature versioning
    """

    def __init__(self):
        self._initialized = False
        self._feature_stability = None
        self._calibration_enhanced = None
        self._regime_limits = None
        self._portfolio_enhancements = None
        self._backtest_enhancements = None
        self._event_enhancements = None
        self._degradation_monitor = None
        self._feature_lineage = None
        self._feature_version_manager = None

    def _ensure_initialized(self) -> None:
        """Lazy initialization — sadece gerektiğinde import et."""
        if self._initialized:
            return

        try:
            from services.ml.feature_stability import feature_stability
            self._feature_stability = feature_stability
        except Exception as e:
            logger.debug("feature_stability_import_failed", error=str(e))

        try:
            from services.ml.calibration_enhanced import calibration_enhanced
            self._calibration_enhanced = calibration_enhanced
        except Exception as e:
            logger.debug("calibration_enhanced_import_failed", error=str(e))

        try:
            from services.risk.regime_limits import regime_limits
            self._regime_limits = regime_limits
        except Exception as e:
            logger.debug("regime_limits_import_failed", error=str(e))

        try:
            from services.portfolio.portfolio_enhancements import portfolio_enhancements
            self._portfolio_enhancements = portfolio_enhancements
        except Exception as e:
            logger.debug("portfolio_enhancements_import_failed", error=str(e))

        try:
            from services.backtest.backtest_enhancements import backtest_enhancements
            self._backtest_enhancements = backtest_enhancements
        except Exception as e:
            logger.debug("backtest_enhancements_import_failed", error=str(e))

        try:
            from services.core.event_enhancements import event_enhancements
            self._event_enhancements = event_enhancements
        except Exception as e:
            logger.debug("event_enhancements_import_failed", error=str(e))

        try:
            from services.learning.model_degradation_monitor import degradation_monitor
            self._degradation_monitor = degradation_monitor
        except Exception as e:
            logger.debug("degradation_monitor_import_failed", error=str(e))

        try:
            from services.features.lineage import feature_lineage
            self._feature_lineage = feature_lineage
        except Exception as e:
            logger.debug("feature_lineage_import_failed", error=str(e))

        try:
            from services.features.versioning import feature_version_manager
            self._feature_version_manager = feature_version_manager
        except Exception as e:
            logger.debug("feature_version_manager_import_failed", error=str(e))

        self._initialized = True

    # =====================================================
    # PIPELINE ENHANCEMENT
    # =====================================================

    def enhance_pipeline_result(
        self,
        ticker: str,
        result: dict[str, Any],
        features: dict[str, float],
        regime: str,
    ) -> dict[str, Any]:
        """Pipeline sonucunu yeni modüllerle zenginleştir.

        Args:
            ticker: Hisse kodu
            result: Mevcut pipeline sonucu
            features: Hesaplanan feature'lar
            regime: Tespit edilen rejim

        Returns:
            Zenginleştirilmiş result
        """
        self._ensure_initialized()

        enhancements: dict[str, Any] = {}

        # 1. Feature stability kontrolü
        if self._feature_stability and features:
            try:
                feature_data = {k: np.array([v]) for k, v in features.items() if isinstance(v, (int, float))}
                self._feature_stability.record_distribution(feature_data)
                stability_summary = self._feature_stability.check_stability()
                enhancements["feature_stability"] = {
                    "score": stability_summary.overall_stability_score,
                    "unstable": stability_summary.unstable_features,
                }
            except Exception as e:
                logger.debug("feature_stability_check_failed", ticker=ticker, error=str(e))

        # 2. Regime limits
        if self._regime_limits:
            try:
                limits = self._regime_limits.get_limits(regime)
                enhancements["regime_limits"] = {
                    "max_position_pct": limits.max_position_pct,
                    "max_total_exposure": limits.max_total_exposure,
                    "max_sector_concentration": limits.max_sector_concentration,
                    "stop_loss_pct": limits.stop_loss_pct,
                    "confidence_multiplier": limits.confidence_multiplier,
                }
            except Exception as e:
                logger.debug("regime_limits_check_failed", ticker=ticker, error=str(e))

        # 3. Feature lineage
        if self._feature_lineage and features:
            try:
                # Feature'ları lineage'e kaydet
                for fname in features:
                    if not self._feature_lineage.get_lineage(fname):
                        self._feature_lineage.record(
                            feature_name=fname,
                            raw_sources=["market_data"],
                            transformations=["computed"],
                            computed_by="orchestrator",
                        )
            except Exception as e:
                logger.debug("feature_lineage_record_failed", ticker=ticker, error=str(e))

        if enhancements:
            result["enhancements"] = enhancements

        return result

    # =====================================================
    # TRADE PLAN ENHANCEMENT
    # =====================================================

    def enhance_trade_plan(
        self,
        ticker: str,
        decision: dict[str, Any],
        prices: np.ndarray,
        regime: str,
        confidence: float = 0.5,
    ) -> dict[str, Any]:
        """Trade planını yeni modüllerle zenginleştir.

        Args:
            ticker: Hisse kodu
            decision: Karar sonucu
            prices: Fiyat serisi
            regime: Rejim
            confidence: Model confidence

        Returns:
            Zenginleştirilmiş trade planı
        """
        self._ensure_initialized()

        enhancements: dict[str, Any] = {}

        # 1. Regime-aware position sizing
        if self._regime_limits:
            try:
                base_size = decision.get("position_pct", 0.05)
                adjusted_size = self._regime_limits.adjust_for_confidence(
                    base_size, confidence, regime
                )
                enhancements["regime_adjusted_size"] = adjusted_size
            except Exception as e:
                logger.debug("regime_position_adjustment_failed", ticker=ticker, error=str(e))

        # 2. T+1 execution check
        if self._backtest_enhancements:
            try:
                from datetime import UTC, datetime
                today = datetime.now(UTC).strftime("%Y-%m-%d")
                t1_result = self._backtest_enhancements.check_t_plus_1(ticker, today)
                enhancements["t_plus_1"] = {
                    "can_execute": t1_result.can_execute,
                    "execution_date": t1_result.execution_date,
                    "delay_days": t1_result.delay_days,
                }
            except Exception as e:
                logger.debug("t_plus_1_check_failed", ticker=ticker, error=str(e))

        # 3. Market impact estimate
        if self._backtest_enhancements:
            try:
                trade_size = decision.get("notional", 0)
                adv = decision.get("adv", 0)
                if trade_size > 0 and adv > 0:
                    impact = self._backtest_enhancements.estimate_market_impact(
                        ticker, trade_size, adv
                    )
                    enhancements["market_impact"] = {
                        "total_impact_pct": impact.total_impact_pct,
                        "is_feasible": impact.is_feasible,
                        "participation_rate": impact.participation_rate,
                    }
            except Exception as e:
                logger.debug("market_impact_failed", ticker=ticker, error=str(e))

        if enhancements:
            decision["enhancements"] = enhancements

        return decision

    # =====================================================
    # LEARNING CYCLE ENHANCEMENT
    # =====================================================

    def enhance_learning_cycle(
        self,
        learning_result: dict[str, Any],
        model_predictions: dict[str, np.ndarray] | None = None,
    ) -> dict[str, Any]:
        """Learning cycle sonucunu zenginleştir.

        Args:
            learning_result: Mevcut learning sonucu
            model_predictions: Model tahminleri (diversity analizi için)

        Returns:
            Zenginleştirilmiş learning sonucu
        """
        self._ensure_initialized()

        enhancements: dict[str, Any] = {}

        # 1. Model degradation kontrolü
        if self._degradation_monitor:
            try:
                summary = self._degradation_monitor.get_model_summary()
                if summary:
                    enhancements["degradation_status"] = summary
                    alerts = self._degradation_monitor.check_all_models()
                    if alerts:
                        enhancements["degradation_alerts"] = [
                            {"model": a.model_id, "severity": a.severity, "message": a.message}
                            for a in alerts
                        ]
            except Exception as e:
                logger.debug("degradation_check_failed", error=str(e))

        # 2. Calibration drift
        if self._calibration_enhanced:
            try:
                drift = self._calibration_enhanced.check_calibration_drift()
                enhancements["calibration_drift"] = {
                    "drift_detected": drift.drift_detected,
                    "severity": drift.severity,
                    "brier_change": drift.brier_change,
                }

                retrain = self._calibration_enhanced.should_retrain_calibration()
                enhancements["calibration_retrain"] = {
                    "should_retrain": retrain.should_retrain,
                    "reason": retrain.reason,
                }
            except Exception as e:
                logger.debug("calibration_drift_check_failed", error=str(e))

        # 3. Ensemble diversity (eğer model predictions varsa)
        if model_predictions and len(model_predictions) >= 2:
            try:
                from services.ml.ensemble import EnsembleModel
                ens = EnsembleModel()
                diversity = ens.analyze_diversity(model_predictions)
                enhancements["ensemble_diversity"] = {
                    "score": diversity.diversity_score,
                    "redundant": diversity.redundant_models,
                    "recommendation": diversity.recommendation,
                }
            except Exception as e:
                logger.debug("ensemble_diversity_failed", error=str(e))

        if enhancements:
            learning_result["enhancements"] = enhancements

        return learning_result

    # =====================================================
    # EVENT ENHANCEMENT
    # =====================================================

    def enhance_event(
        self,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Event'i zenginleştir (idempotency + correlation).

        Args:
            event_id: Event ID
            event_type: Event tipi
            payload: Event payload

        Returns:
            Zenginleştirilmiş payload
        """
        self._ensure_initialized()

        if not self._event_enhancements:
            return payload

        try:
            # Idempotency kontrolü
            if self._event_enhancements.is_duplicate(event_id):
                logger.debug("event_duplicate_skipped", event_id=event_id)
                return {"_skipped": True, "_reason": "duplicate"}

            # Correlation ID ekle
            if "_correlation_id" not in payload:
                payload["_correlation_id"] = self._event_enhancements.generate_correlation_id()

            # Timestamp ekle
            from datetime import UTC, datetime
            payload["_timestamp"] = datetime.now(UTC).isoformat()

            # Sequence number
            payload["_sequence"] = self._event_enhancements.get_next_sequence(event_type)

            # İşlenmiş olarak işaretle
            self._event_enhancements.mark_processed(event_id)

        except Exception as e:
            logger.debug("event_enhancement_failed", event_id=event_id, error=str(e))

        return payload

    # =====================================================
    # PORTFOLIO ENHANCEMENT
    # =====================================================

    def enhance_portfolio_weights(
        self,
        target_weights: dict[str, float],
        current_weights: dict[str, float],
        sector_map: dict[str, str] | None = None,
        liquidity_scores: dict[str, float] | None = None,
        regime: str = "UNKNOWN",
    ) -> dict[str, float]:
        """Portföy ağırlıklarını zenginleştir.

        Args:
            target_weights: Hedef ağırlıklar
            current_weights: Mevcut ağırlıklar
            sector_map: Sektör haritası
            liquidity_scores: Likidite skorları
            regime: Mevcut rejim

        Returns:
            Düzeltilmiş ağırlıklar
        """
        self._ensure_initialized()

        if not self._portfolio_enhancements:
            return target_weights

        try:
            # 1. Hysteresis (küçük değişimleri filtrele)
            adjusted = self._portfolio_enhancements.apply_hysteresis(
                target_weights, current_weights
            )

            # 2. Sector constraints
            if sector_map:
                adjusted = self._portfolio_enhancements.apply_sector_constraints(
                    adjusted, sector_map
                )

            # 3. Liquidity constraints
            if liquidity_scores:
                adjusted = self._portfolio_enhancements.apply_liquidity_constraints(
                    adjusted, liquidity_scores
                )

            # 4. Min position filter
            adjusted = self._portfolio_enhancements.apply_min_position(adjusted)

            # 5. Position limits
            if self._regime_limits:
                limits = self._regime_limits.get_limits(regime)
                adjusted = self._portfolio_enhancements.apply_position_limits(
                    adjusted, limits.max_position_pct
                )

            return adjusted

        except Exception as e:
            logger.debug("portfolio_enhancement_failed", error=str(e))
            return target_weights

    # =====================================================
    # RECORD OUTCOME (degradation monitor için)
    # =====================================================

    def record_model_outcome(
        self,
        model_id: str,
        predicted: float,
        actual: float,
        return_pct: float = 0.0,
    ) -> None:
        """Model sonucunu degradation monitor'a kaydet.

        Args:
            model_id: Model adı
            predicted: Tahmin
            actual: Gerçek
            return_pct: Getiri %
        """
        self._ensure_initialized()

        if self._degradation_monitor:
            try:
                self._degradation_monitor.record_outcome(model_id, predicted, actual, return_pct)
            except Exception as e:
                logger.debug("degradation_record_failed", model=model_id, error=str(e))

    def record_calibration_data(
        self,
        brier_score: float,
        ece: float,
    ) -> None:
        """Calibration verisini kaydet.

        Args:
            brier_score: Brier skoru
            ece: Expected Calibration Error
        """
        self._ensure_initialized()

        if self._calibration_enhanced:
            try:
                self._calibration_enhanced.record_calibration_metrics(brier_score, ece)
            except Exception as e:
                logger.debug("calibration_record_failed", error=str(e))


# Singleton
integration_bridge = IntegrationBridge()
