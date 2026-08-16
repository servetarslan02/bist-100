"""
ALPHA BIST — System Orchestrator v3.0

SÜPER AKILLI, TAM OTOMATİK SİSTEM KONTROL MERKEZİ

Bu modül:
- Tüm 7 motoru koordine eder
- Feature hesaplama → Ranking → Risk → Backtest pipeline'ını yönetir
- Sürekli öğrenme döngüsünü tetikler
- Hata durumunda self-healing başlatır
- Tüm metrikleri toplar ve raporlar

KURAL: Bu sistem insan müdahalesi olmadan 7/24 çalışmalı.
"""

import json
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from collections import deque, defaultdict
import structlog

logger = structlog.get_logger()


@dataclass
class PipelineResult:
    """Pipeline çalıştırma sonucu."""
    timestamp: str
    date: str
    regime: str
    stage: str  # FEATURES, RANKING, RISK, BACKTEST, LEARNING
    status: str  # SUCCESS, FAILED, PARTIAL
    duration_ms: float
    metrics: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class DailyReport:
    """Günlük sistem raporu."""
    date: str
    timestamp: str
    regime: str
    top_opportunities: List[Dict]
    portfolio_recommendation: Dict
    risk_metrics: Dict
    backtest_summary: Dict
    learning_status: Dict
    system_health: Dict
    alerts: List[str]


class SystemOrchestrator:
    """Ana sistem kontrolcüsü — tüm pipeline'ı yönetir."""

    def __init__(self):
        self._pipeline_history: deque = deque(maxlen=100)
        self._daily_reports: deque = deque(maxlen=365)
        self._is_running = False
        self._current_regime = "UNKNOWN"

        logger.info("SystemOrchestrator v3.0 initialized")

    def run_full_pipeline(
        self,
        date: str,
        market_data: Dict[str, pd.DataFrame],  # {ticker: OHLCV DataFrame}
        sector_map: Dict[str, str],             # {ticker: sector}
        kap_data: Optional[Dict] = None,
        news_data: Optional[Dict] = None,
        historical_returns: Optional[Dict] = None,
    ) -> DailyReport:
        """Tam pipeline çalıştır.

        Pipeline:
        1. Tradability Mask hesapla
        2. 7 Motor Feature Engineering
        3. Cross-Sectional Features
        4. Ranking (LambdaRank + Ensemble)
        5. Risk & Position Sizing
        6. Backtest Validation
        7. Continuous Learning Update
        8. Rapor oluştur
        """
        start_time = datetime.now(timezone.utc)
        errors = []
        warnings = []

        logger.info("Full pipeline started", date=date, tickers=len(market_data))

        # === STAGE 1: TRADABILITY MASK ===
        try:
            from services.core.tradability_mask import tradability_mask
            masks = {}
            for ticker, df in market_data.items():
                mask_result = tradability_mask.compute_mask(
                    ticker=ticker,
                    open_=df["Open"].values,
                    high=df["High"].values,
                    low=df["Low"].values,
                    close=df["Close"].values,
                    volume=df["Volume"].values
                )
                # MaskResult dataclass -> numpy array
                masks[ticker] = mask_result.mask if hasattr(mask_result, 'mask') else mask_result
        except Exception as e:
            logger.error("Tradability mask failed", error=str(e))
            errors.append(f"Mask: {str(e)}")
            masks = {t: np.ones(len(df), dtype=int) for t, df in market_data.items()}

        # === STAGE 2: FEATURE ENGINEERING (7 Motors) ===
        try:
            from services.features.calculator import feature_calculator
            from services.features.cross_sectional import cross_sectional_engine
            from services.features.seven_motors import seven_motor_engine

            all_features = {}
            for ticker, df in market_data.items():
                mask = masks.get(ticker)

                # Teknik feature'lar
                tech_features = feature_calculator.compute_all_features(
                    df, mask=mask, ticker=ticker
                )

                # 7 motor feature'lari
                motor_features = seven_motor_engine.compute_all(ticker, df, mask)

                # Birlestir
                all_features[ticker] = {**tech_features, **motor_features}

            # Cross-sectional features
            cs_features = cross_sectional_engine.compute_all_cross_sectional(
                ticker="",  # Tüm evren için
                features={},
                universe_features=all_features,
                universe_sectors=sector_map,
            )

            # Cross-sectional'ı her hisseye ekle
            for ticker in all_features:
                # Market breadth features (evren geneli)
                for key, val in cs_features.items():
                    if key.startswith("market_") or key.startswith("sector_momentum_"):
                        all_features[ticker][key] = val

                # Rank features (hisse bazlı)
                rank_feats = cross_sectional_engine.compute_rank_features(
                    ticker, all_features[ticker], all_features
                )
                all_features[ticker].update(rank_feats)

                # Sector relative
                if ticker in sector_map:
                    sector = sector_map[ticker]
                    sector_feats = cross_sectional_engine.compute_sector_relative(
                        ticker, all_features[ticker], sector, all_features, sector_map
                    )
                    all_features[ticker].update(sector_feats)

        except Exception as e:
            logger.error("Feature engineering failed", error=str(e))
            errors.append(f"Features: {str(e)}")
            all_features = {}

        # === STAGE 3: REGIME DETECTION ===
        try:
            from services.core.regime_detector import regime_detector
            self._current_regime = regime_detector.detect_regime(market_data)
        except Exception as e:
            logger.warning("Regime detection failed", error=str(e))
            warnings.append(f"Regime: {str(e)}")
            self._current_regime = "UNKNOWN"

        # === STAGE 4: RANKING ===
        try:
            from services.ml.ranking_model import ranking_model

            # RegimeState -> string
            regime_str = self._current_regime.regime if hasattr(self._current_regime, 'regime') else str(self._current_regime)

            ranking_result = ranking_model.rank(
                features_map=all_features,
                regime=regime_str,
            )

            top_opportunities = [
                {
                    "ticker": s.ticker,
                    "rank": s.rank,
                    "score": s.score,
                    "direction": s.direction,
                    "confidence": s.confidence,
                    "regime": s.regime,
                }
                for s in ranking_result.scores[:20]
            ]

        except Exception as e:
            logger.error("Ranking failed", error=str(e))
            errors.append(f"Ranking: {str(e)}")
            top_opportunities = []
            ranking_result = None

        # === STAGE 5: RISK & POSITION SIZING ===
        try:
            from services.risk.position_sizing import position_sizer
            from services.risk.covariance import covariance_estimator

            # Portföy önerisi
            portfolio_value = 1_000_000  # 1M TL (varsayılan)

            # Secilmis hisselerin volatilitesi
            selected = top_opportunities[:10] if top_opportunities else []
            print(f"\n[ORCHESTRATOR] Position sizing: {len(selected)} opportunities selected")

            opp_with_vol = []
            for opp in selected:
                ticker = opp["ticker"]
                features = all_features.get(ticker, {})
                vol = features.get("volatility_20d", 0.2)

                # NaN/Inf kontrolu
                if np.isnan(vol) or np.isinf(vol) or vol <= 0:
                    print(f"  [{ticker}] vol invalid ({vol}), using default 0.2")
                    vol = 0.2

                # Normalize: vol % olarak geliyorsa /100
                vol_norm = vol / 100 if vol > 1 else vol

                # expected_return: score'dan turet
                exp_ret = opp.get("score", 0) * 0.01
                if np.isnan(exp_ret) or np.isinf(exp_ret):
                    exp_ret = 0.01

                opp_with_vol.append({
                    **opp,
                    "volatility": vol_norm,
                    "expected_return": exp_ret,
                })
                print(f"  [{ticker}] vol={vol_norm:.4f}, exp_ret={exp_ret:.4f}, score={opp.get('score', 0)}")

            positions = position_sizer.calculate_position_sizes(
                opportunities=opp_with_vol,
                portfolio_value=portfolio_value,
                current_volatility=0.15,
                regime=regime_str,
            )

            portfolio_recommendation = {
                "total_positions": len(positions),
                "total_weight": round(sum(p.weight for p in positions), 4),
                "positions": [
                    {
                        "ticker": p.ticker,
                        "weight": p.weight,
                        "notional": p.notional,
                        "risk_pct": p.risk_pct,
                        "kelly": p.kelly_fraction,
                    }
                    for p in positions
                ],
            }

        except Exception as e:
            logger.error("Risk sizing failed", error=str(e))
            errors.append(f"Risk: {str(e)}")
            portfolio_recommendation = {"total_positions": 0, "positions": []}

        # === STAGE 6: BACKTEST VALIDATION ===
        backtest_summary = {}
        try:
            from services.backtest.walk_forward import walk_forward_engine
            from services.backtest.engine import backtest_engine

            # Market data'dan historical returns hesapla
            hist_returns = {}
            if market_data:
                for t, df in market_data.items():
                    if not df.empty and len(df) > 1 and 'Close' in df.columns:
                        # Gunluk getiriler
                        returns = df['Close'].pct_change().dropna()
                        for date_idx, ret in returns.items():
                            date_str = date_idx.strftime("%Y-%m-%d") if hasattr(date_idx, 'strftime') else str(date_idx)[:10]
                            if date_str not in hist_returns:
                                hist_returns[date_str] = {}
                            hist_returns[date_str][t] = ret

            # Tahminler: ranking sonuclarindan
            predictions = [
                {"date": date, "ticker": opp["ticker"], "score": opp["score"]}
                for opp in top_opportunities
            ]

            if predictions and hist_returns:
                # Walk-forward validation
                dates = sorted(hist_returns.keys())
                wf_result = walk_forward_engine.run_walk_forward(
                    predictions=predictions,
                    actual_returns=hist_returns,
                    dates=dates,
                )

                backtest_summary = {
                    "status": "COMPLETED",
                    "folds": wf_result.total_folds,
                    "avg_test_return": wf_result.avg_test_return,
                    "avg_test_sharpe": wf_result.avg_test_sharpe,
                    "avg_test_drawdown": wf_result.avg_test_drawdown,
                    "avg_win_rate": wf_result.avg_win_rate,
                    "avg_precision_at_5": wf_result.avg_precision_at_5,
                    "avg_precision_at_10": wf_result.avg_precision_at_10,
                    "avg_ic": wf_result.avg_ic,
                    "stability_score": wf_result.stability_score,
                    "deflated_sharpe": wf_result.deflated_sharpe,
                    "worst_fold": wf_result.worst_fold_return,
                    "best_fold": wf_result.best_fold_return,
                }
            else:
                backtest_summary = {"status": "NO_DATA", "reason": "Insufficient predictions or returns"}

        except Exception as e:
            logger.warning("Backtest failed", error=str(e))
            warnings.append(f"Backtest: {str(e)}")
            backtest_summary = {"status": "FAILED", "error": str(e)}

        # === STAGE 7: CONTINUOUS LEARNING ===
        learning_status = {}
        try:
            from services.learning.continuous_learning import continuous_learning
            from services.learning.super_intelligence import super_intelligence

            # Günlük pipeline
            predictions = [
                {"ticker": opp["ticker"], "score": opp["score"]}
                for opp in top_opportunities
            ]

            # Actual returns (eğer varsa)
            actuals = historical_returns or {}

            learning_result = continuous_learning.run_daily_pipeline(
                date=date,
                features_map=all_features,
                predictions=predictions,
                actual_returns=actuals,
                regime=self._current_regime,
            )

            learning_status = {
                "retrain_needed": learning_result.get("should_retrain", False),
                "drift_detected": learning_result.get("drift_check", {}).get("drift_detected", False),
                "daily_sharpe": learning_result.get("daily_metrics", {}).get("sharpe", 0),
                "daily_ic": learning_result.get("daily_metrics", {}).get("ic", 0),
            }

            # Super intelligence health check
            health = super_intelligence.get_health_status()
            learning_status["system_health"] = health.overall_status

        except Exception as e:
            logger.error("Learning update failed", error=str(e))
            errors.append(f"Learning: {str(e)}")
            learning_status = {"status": "FAILED", "error": str(e)}

        # === STAGE 8: RAPOR ===
        duration = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

        report = DailyReport(
            date=date,
            timestamp=datetime.now(timezone.utc).isoformat(),
            regime=self._current_regime,
            top_opportunities=top_opportunities,
            portfolio_recommendation=portfolio_recommendation,
            risk_metrics={
                "total_risk": round(sum(p.risk_pct for p in positions), 2) if 'positions' in dir() else 0,
                "max_position": max((p.weight for p in positions), default=0) if 'positions' in dir() else 0,
            },
            backtest_summary=backtest_summary,
            learning_status=learning_status,
            system_health={
                "status": "HEALTHY" if not errors else "DEGRADED" if not any("Ranking" in e or "Features" in e for e in errors) else "CRITICAL",
                "errors": errors,
                "warnings": warnings,
                "pipeline_duration_ms": round(duration, 2),
            },
            alerts=errors + warnings,
        )

        self._daily_reports.append(report)

        # Pipeline history
        self._pipeline_history.append(PipelineResult(
            timestamp=datetime.now(timezone.utc).isoformat(),
            date=date,
            regime=self._current_regime,
            stage="FULL_PIPELINE",
            status="SUCCESS" if not errors else "PARTIAL",
            duration_ms=round(duration, 2),
            metrics={
                "tickers_processed": len(market_data),
                "features_computed": len(all_features),
                "opportunities_found": len(top_opportunities),
            },
            errors=errors,
            warnings=warnings,
        ))

        logger.info("Full pipeline completed",
                   date=date, duration_ms=round(duration, 2),
                   status="SUCCESS" if not errors else "PARTIAL",
                   errors=len(errors), warnings=len(warnings))

        return report

    def get_latest_report(self) -> Optional[DailyReport]:
        """Son günlük raporu getir."""
        return self._daily_reports[-1] if self._daily_reports else None

    def get_pipeline_stats(self) -> Dict[str, Any]:
        """Pipeline istatistikleri."""
        recent = list(self._pipeline_history)[-30:]
        return {
            "total_runs": len(self._pipeline_history),
            "success_rate": sum(1 for p in recent if p.status == "SUCCESS") / len(recent) if recent else 0,
            "avg_duration_ms": round(np.mean([p.duration_ms for p in recent]), 2) if recent else 0,
            "recent_errors": sum(len(p.errors) for p in recent),
            "recent_warnings": sum(len(p.warnings) for p in recent),
        }

    def export_daily_report_json(self, date: Optional[str] = None) -> str:
        """Günlük raporu JSON olarak dışa aktar."""
        if date:
            report = next((r for r in self._daily_reports if r.date == date), None)
        else:
            report = self.get_latest_report()

        if not report:
            return json.dumps({"error": "No report found"})

        return json.dumps(asdict(report), indent=2, default=str)


# Singleton
orchestrator = SystemOrchestrator()
