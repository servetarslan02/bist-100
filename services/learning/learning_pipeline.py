"""ALPHA BIST — Master Learning & Model Performance Pipeline v2.0

Uçtan uca Otonom Öğrenme Döngüsü:
DATA -> FEATURES -> TRAIN -> PREDICT -> STORE PREDICTION -> OUTCOME -> PERFORMANCE -> RELIABILITY -> FUSION WEIGHTS -> NEXT PREDICTION
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import structlog

from .model_performance_engine import ModelPerformanceEngine, PerformanceMetrics
from .model_trust_engine import ModelTrustEngine, ModelTrustScore
from .model_memory_store import ModelMemoryStore
from .performance_reporter import ModelPerformanceReporter
from ..intelligence.signal_fusion import SignalFusionEngine

logger = structlog.get_logger()


class LearningPipeline:
    """Uçtan uca model eğitimi, performans öğrenimi ve adaptif ağırlıklandırma orkestratörü."""

    def __init__(
        self,
        memory_store: Optional[ModelMemoryStore] = None,
        trust_engine: Optional[ModelTrustEngine] = None,
        fusion_engine: Optional[SignalFusionEngine] = None,
    ):
        self.store = memory_store or ModelMemoryStore()
        self.trust_engine = trust_engine or ModelTrustEngine()
        self.fusion_engine = fusion_engine or SignalFusionEngine()
        self.perf_engine = ModelPerformanceEngine()
        self.reporter = ModelPerformanceReporter()

        # Model envanteri
        self.registered_models = [
            {"id": "LightGBM_LambdaRank", "version": "v3.2", "category": "ranking"},
            {"id": "CatBoost_Classifier", "version": "v2.1", "category": "direction"},
            {"id": "SPEC_Anomaly_Detector", "version": "v1.2", "category": "anomaly"},
            {"id": "LSTM_Sequential", "version": "v1.8", "category": "time_series"},
            {"id": "Cross_Sectional_Momentum", "version": "v2.0", "category": "factor"},
            {"id": "KAP_NLP_Sentiment", "version": "v3.0", "category": "nlp"},
        ]

        logger.info("LearningPipeline initialized", models=len(self.registered_models))

    def record_model_prediction(
        self,
        model_id: str,
        ticker: str,
        predicted_direction: str,
        confidence: float,
        entry_price: float,
        market_regime: str = "BULL_MOMENTUM",
        prediction_horizon: str = "1-5D",
        features: Optional[Dict[str, Any]] = None,
        model_version: Optional[str] = None,
    ) -> str:
        """1. Adım: Modelin ürettiği tahmini hafızaya kaydet."""
        version = model_version or "v1.0"
        for m in self.registered_models:
            if m["id"] == model_id:
                version = m["version"]
                break

        pred_id = f"PRED_{model_id}_{ticker}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        self.store.save_prediction(
            prediction_id=pred_id,
            model_id=model_id,
            model_version=version,
            ticker=ticker,
            predicted_direction=predicted_direction,
            confidence=confidence,
            market_regime=market_regime,
            prediction_horizon=prediction_horizon,
            entry_price=entry_price,
            features=features,
        )
        return pred_id

    def record_market_outcome(
        self,
        prediction_id: str,
        actual_price: float,
        evaluated_at: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """2. Adım: Piyasa sonucunu tahminle eşleştir ve net PnL hesapla."""
        return self.store.save_outcome(
            prediction_id=prediction_id,
            actual_price=actual_price,
            evaluated_at=evaluated_at,
        )

    def run_learning_cycle(
        self,
        current_regime: str = "BULL_MOMENTUM",
    ) -> Dict[str, Any]:
        """3. Adım: Tüm modellerin geçmişini değerlendir, güven skorlarını ve sinyal ağırlıklarını güncelle."""
        all_metrics: List[PerformanceMetrics] = []
        all_trust_scores: List[ModelTrustScore] = []
        window_250_metrics: List[PerformanceMetrics] = []
        window_500_metrics: List[PerformanceMetrics] = []

        for m_info in self.registered_models:
            m_id = m_info["id"]
            m_ver = m_info["version"]

            # Modelin değerlendirilmiş tahminlerini çek
            evaluated_data = self.store.get_evaluated_predictions_for_model(m_id, limit=2000)
            
            # Kapsamlı performans metriklerini hesapla (Tüm örneklem)
            metrics = self.perf_engine.calculate_metrics(
                model_id=m_id,
                model_version=m_ver,
                predictions_with_outcomes=evaluated_data,
            )
            all_metrics.append(metrics)

            # Son 250 ve Son 500 pencere metrikleri
            if len(evaluated_data) >= 50:
                m250 = self.perf_engine.calculate_metrics(
                    model_id=m_id,
                    model_version=m_ver,
                    predictions_with_outcomes=evaluated_data[:250],
                )
                window_250_metrics.append(m250)

                m500 = self.perf_engine.calculate_metrics(
                    model_id=m_id,
                    model_version=m_ver,
                    predictions_with_outcomes=evaluated_data[:500],
                )
                window_500_metrics.append(m500)

            # Dinamik güvenilirlik (trust/reliability) skoru üret
            trust = self.trust_engine.compute_trust_score(
                metrics=metrics,
                current_regime=current_regime,
            )
            all_trust_scores.append(trust)

        # Signal Fusion için normalize adaptif ağırlıkları hesapla
        fusion_weights = self.trust_engine.calculate_ensemble_weights(all_trust_scores)
        
        # Signal Fusion motoruna yeni adaptif ağırlıkları yükle
        self.fusion_engine.set_adaptive_weights(fusion_weights)

        # Deftere ve geçmiş kayıtlarına yaz
        for ts, met in zip(all_trust_scores, all_metrics):
            self.store.record_metrics_snapshot(
                model_id=ts.model_id,
                model_version=ts.model_version,
                metrics=met.__dict__,
                reliability_score=ts.reliability_score,
                fusion_weight=ts.recommended_fusion_weight,
            )

        self.store.record_fusion_weights(fusion_weights, current_regime)

        # Otomatik rapor üret
        window_comp = {
            "250": window_250_metrics,
            "500": window_500_metrics,
            "all": all_metrics,
        } if window_250_metrics else None

        report_md = self.reporter.generate_markdown_report(
            metrics_list=all_metrics,
            trust_scores=all_trust_scores,
            current_regime=current_regime,
            window_comparison=window_comp,
        )

        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "models_evaluated": len(all_metrics),
            "current_regime": current_regime,
            "fusion_weights": fusion_weights,
            "metrics": [m.__dict__ for m in all_metrics],
            "trust_scores": [t.__dict__ for t in all_trust_scores],
            "markdown_report": report_md,
        }

    def simulate_walk_forward_learning_backtest(
        self,
        historical_predictions_stream: List[Dict[str, Any]],
        regime: str = "BULL_MOMENTUM",
    ) -> Dict[str, Any]:
        """Look-ahead bias olmadan kronolojik walk-forward öğrenme simülasyonu."""
        # Tahminleri zamana göre sırala (Zero look-ahead bias)
        sorted_events = sorted(
            historical_predictions_stream,
            key=lambda x: x.get("timestamp", "")
        )

        pred_ids = []
        for evt in sorted_events:
            p_id = self.record_model_prediction(
                model_id=evt["model_id"],
                ticker=evt["ticker"],
                predicted_direction=evt["predicted_direction"],
                confidence=evt.get("confidence", 0.60),
                entry_price=evt["entry_price"],
                market_regime=evt.get("market_regime", regime),
                prediction_horizon=evt.get("prediction_horizon", "1-5D"),
                model_version=evt.get("model_version"),
            )
            pred_ids.append((p_id, evt.get("actual_price", evt["entry_price"] * 1.02), evt.get("evaluated_at")))

        # Sonuçları kronolojik olarak işle
        for p_id, act_price, eval_at in pred_ids:
            self.record_market_outcome(prediction_id=p_id, actual_price=act_price, evaluated_at=eval_at)

        # Öğrenme döngüsünü tetikle
        return self.run_learning_cycle(current_regime=regime)

    def check_and_catchup_if_needed(self) -> Dict[str, Any]:
        """PC kapali kaldiginda kacirilan egitim dongulerini ve eksik verileri kontrol edip telafi eder."""
        try:
            latest = self.store.get_latest_metrics_all_models()
            should_run = False
            reason = ""
            
            if not latest:
                should_run = True
                reason = "Ilk baslatma veya kayitli metrik bulunamadi"
            else:
                last_time_str = latest[0].get("evaluated_at")
                if last_time_str:
                    try:
                        last_dt = datetime.fromisoformat(last_time_str.replace("Z", "+00:00"))
                        now_dt = datetime.now(timezone.utc)
                        diff_hours = (now_dt - last_dt).total_seconds() / 3600.0
                        if diff_hours >= 6.0:
                            should_run = True
                            reason = f"Son egitim {diff_hours:.1f} saat once yapilmis (Hedef aralik: 6 saat)"
                    except Exception as e:
                        logger.debug("date_parse_failed", error=str(e))
                        should_run = True
                        reason = "Tarih ayrıştırma"
            
            if should_run:
                logger.info("ml_catchup_triggered", reason=reason)
                return self.run_learning_cycle(current_regime="BULL_MOMENTUM")
            else:
                logger.info("ml_models_up_to_date")
                return {"status": "up_to_date", "models": len(latest)}
        except Exception as e:
            logger.warning("check_and_catchup_failed", error=str(e))
            return {"status": "error", "error": str(e)}
