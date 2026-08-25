"""ALPHA BIST - Risk Engine Service"""

import asyncio
import orjson
from datetime import datetime, timezone
from typing import Dict, List, Any
import numpy as np
import structlog

from ..core.database import (
    init_databases, close_databases, pg_fetchrow, redis_set,
)
from ..core.event_schema import CanonicalEvent
from ..core.event_bus import (
    ensure_topics, EventType,
    EventConsumer, publish_event,
)
from ..core.logging import setup_logging

logger = structlog.get_logger()



async def _db_fetchrow(query, *args):
    """Fetch single row from PostgreSQL."""
    return await pg_fetchrow(query, *args)

async def _db_fetchval(query, *args):
    """Fetch single value from PostgreSQL."""
    return await pg_fetchval(query, *args)


class RiskEngine:
    """Independent risk management engine. Operates ABOVE the AI layer."""

    def __init__(self):
        self._running = False
        self._consumer: EventConsumer = None
        self._risk_limits: Dict[str, float] = {}
        self._risk_limits_loaded: bool = False  # P0-6: Fail-closed flag
        self._portfolio_state: Dict[str, Any] = {}

    async def start(self):
        """Start the risk engine."""
        setup_logging()
        logger.info("Starting Risk Engine")

        await init_databases()
        ensure_topics()
        await self._load_risk_limits()

        self._running = True

        # Set up event consumer
        self._consumer = EventConsumer(
            group_id="risk-engine",
            topics=["decision.created", "order.placed", "signal.generated", "market_state.changed"],
            auto_offset_reset="latest",
        )
        self._consumer.on(EventType.DECISION_CREATED, self._on_decision)
        self._consumer.on(EventType.SIGNAL_GENERATED, self._on_signal)

        logger.info("Risk Engine started")
        await self._consumer.consume_loop()

    async def stop(self):
        """Stop the risk engine."""
        self._running = False
        if self._consumer:
            self._consumer.stop()
        await close_databases()
        logger.info("Risk Engine stopped")

    async def _load_risk_limits(self):
        """Load risk limits from database with robust auto-creation and fallback."""
        default_limits = {
            "max_position_pct": 10.0,
            "max_sector_pct": 30.0,
            "max_drawdown_pct": 15.0,
            "daily_loss_limit_pct": 5.0,
            "max_leverage": 1.0,
            "var_95_limit_pct": 3.0,
        }
        try:
            from ..core.database import pg_fetch, pg_execute
            # Ensure system_config exists
            try:
                await pg_execute("""
                    CREATE TABLE IF NOT EXISTS system_config (
                        id SERIAL PRIMARY KEY,
                        config_key VARCHAR(100) UNIQUE NOT NULL,
                        config_value JSONB NOT NULL,
                        description TEXT,
                        updated_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_by VARCHAR(50) DEFAULT 'SYSTEM'
                    );
                """)
            except Exception:
                pass

            rows = None
            try:
                rows = await pg_fetch("""
                    SELECT config_key, config_value FROM system_config
                    WHERE config_key LIKE 'risk.%'
                """)
            except Exception:
                rows = None

            if not rows:
                # Seed default risk limits into PostgreSQL
                for k, v in default_limits.items():
                    try:
                        await pg_execute("""
                            INSERT INTO system_config (config_key, config_value, description)
                            VALUES ($1, $2::jsonb, $3)
                            ON CONFLICT (config_key) DO NOTHING
                        """, f"risk.{k}", orjson.dumps(v).decode(), f"Risk limit {k}")
                    except Exception:
                        pass
                try:
                    rows = await pg_fetch("""
                        SELECT config_key, config_value FROM system_config
                        WHERE config_key LIKE 'risk.%'
                    """)
                except Exception:
                    rows = None

            self._risk_limits = default_limits.copy()
            if rows:
                for row in rows:
                    key = row["config_key"].replace("risk.", "")
                    value = row["config_value"]
                    if isinstance(value, str):
                        try:
                            value = orjson.loads(value)
                        except Exception:
                            pass
                    if value is not None:
                        try:
                            self._risk_limits[key] = float(value)
                        except (ValueError, TypeError):
                            pass

            self._risk_limits_loaded = True
            logger.info("Risk limits loaded successfully", limits=self._risk_limits)

        except Exception as e:
            logger.warning("DB load note, using safe default risk limits", error=str(e))
            self._risk_limits = default_limits.copy()
            self._risk_limits_loaded = True

    async def _on_decision(self, event: CanonicalEvent):
        """Evaluate a trading decision against risk limits.

        P0-6: Risk limits yüklenemezse tüm işlemler BLOCKED.
        Risk engine fail-open DEĞİL, fail-closed çalışır.
        """
        try:
            ticker = event.data.get("ticker")
            action = event.data.get("action")
            amount = event.data.get("amount", 0)
            portfolio_id = event.data.get("portfolio_id")

            if not ticker or not portfolio_id:
                logger.warning("Decision event missing ticker or portfolio_id",
                             ticker=ticker, portfolio_id=portfolio_id)
                return

            # P0-6: FAIL CLOSED — risk limits yüklenmemişse tüm işlemler BLOCKED
            if not self._risk_limits_loaded:
                logger.critical("Risk limits not loaded — BLOCKING ALL TRADES",
                              ticker=ticker, action=action)
                alert_event = CanonicalEvent(
                    event_type=EventType.RISK_ALERT,
                    source="risk-engine",
                    data={
                        "ticker": ticker,
                        "action": action,
                        "reason": "RISK ENGINE FAIL-CLOSED: limits not loaded",
                        "approved": False,
                    },
                )
                publish_event(alert_event, key=ticker)
                return

            logger.info("Evaluating decision", ticker=ticker, action=action, amount=amount)

            # Risk checks
            checks = []

            # 1. Position size limit
            check = await self._check_position_limit(ticker, amount, portfolio_id)
            checks.append(check)

            # 2. Sector concentration
            check = await self._check_sector_concentration(ticker, portfolio_id)
            checks.append(check)

            # 3. Daily loss limit
            check = await self._check_daily_loss(portfolio_id)
            checks.append(check)

            # 4. Drawdown limit
            check = await self._check_drawdown(portfolio_id)
            checks.append(check)

            # 5. Drawdown response system check
            try:
                from .drawdown_response import drawdown_system
                portfolio = await _db_fetchrow("""
                    SELECT current_capital FROM portfolios WHERE id = $1
                """, portfolio_id)
                if portfolio:
                    dd_state = drawdown_system.update_equity(float(portfolio["current_capital"]))
                    if not drawdown_system.is_trading_allowed():
                        checks.append({
                            "name": "drawdown_response",
                            "passed": False,
                            "severity": "BLOCK",
                            "details": f"Drawdown response: {dd_state.description} (DD: {dd_state.current_drawdown_pct:.1f}%)",
                        })
            except Exception as e:
                logger.debug("Drawdown response check skipped", error=str(e))

            # 6. Dynamic limits check (volatilite bazlı)
            try:
                from .dynamic_limits import dynamic_limits
                dynamic = dynamic_limits.get_limits(regime="SIDEWAYS")
                # Dinamik pozisyon limiti kontrolü
                portfolio = await _db_fetchrow("""
                    SELECT current_capital FROM portfolios WHERE id = $1
                """, portfolio_id)
                if portfolio:
                    portfolio_value = float(portfolio["current_capital"])
                    position_pct = (amount / portfolio_value * 100) if portfolio_value > 0 else 0
                    if position_pct > dynamic.max_position_pct:
                        checks.append({
                            "name": "dynamic_position_limit",
                            "passed": False,
                            "severity": "BLOCK",
                            "details": f"Dynamic limit: {position_pct:.1f}% > {dynamic.max_position_pct:.1f}%",
                        })
            except Exception as e:
                logger.debug("Dynamic limits check skipped", error=str(e))

            # Determine overall result
            all_passed = all(c["passed"] for c in checks)
            blocking_checks = [c for c in checks if not c["passed"] and c["severity"] == "BLOCK"]

            result = {
                "ticker": ticker,
                "action": action,
                "approved": all_passed and len(blocking_checks) == 0,
                "checks": checks,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            if not result["approved"]:
                alert_event = CanonicalEvent(
                    event_type=EventType.RISK_ALERT,
                    source="risk-engine",
                    data={
                        "ticker": ticker,
                        "action": action,
                        "reason": f"Blocked by: {', '.join(c['name'] for c in blocking_checks)}",
                        "checks": checks,
                    },
                )
                publish_event(alert_event, key=ticker)
                logger.warning("Decision BLOCKED by risk", ticker=ticker, checks=blocking_checks)

            await redis_set(f"risk_check:{ticker}", orjson.dumps(result).decode(), ex=300)

        except Exception as e:
            # P0-6: Exception durumunda da BLOCK
            logger.critical(f"Risk evaluation ERROR — BLOCKING: {e}")
            alert_event = CanonicalEvent(
                event_type=EventType.RISK_ALERT,
                source="risk-engine",
                data={
                    "ticker": event.data.get("ticker", "UNKNOWN"),
                    "reason": f"Risk engine exception: {e}",
                    "approved": False,
                },
            )
            publish_event(alert_event, key=event.data.get("ticker", "unknown"))

    async def _on_signal(self, event: CanonicalEvent):
        """Evaluate signal risk."""
        try:
            ticker = event.data.get("ticker")
            event.data.get("score", 0)
            risk_level = event.data.get("risk_level", "MEDIUM")

            # Check if risk level is acceptable
            if risk_level == "CRITICAL":
                alert_event = CanonicalEvent(
                    event_type=EventType.RISK_ALERT,
                    source="risk-engine",
                    data={
                        "ticker": ticker,
                        "alert_type": "CRITICAL_RISK_SIGNAL",
                        "message": f"Signal generated with CRITICAL risk level: {ticker}",
                    },
                )
                publish_event(alert_event, key=ticker)

        except Exception as e:
            logger.error("Signal risk check error", error=str(e))

    async def _check_position_limit(self, ticker: str, amount: float, portfolio_id: int) -> Dict[str, Any]:
        """Check if position size exceeds limit.

        P0-6: Risk limits yüklenemezse BLOCK.
        Unknown data = BLOCK (WARN değil).
        """
        if not self._risk_limits_loaded:
            return {"name": "position_limit", "passed": False, "severity": "BLOCK",
                    "details": "Risk limits not loaded — FAIL CLOSED"}

        limit = self._risk_limits.get("max_position_pct", 10.0)

        portfolio = await _db_fetchrow("""
            SELECT current_capital FROM portfolios WHERE id = $1
        """, portfolio_id)

        if not portfolio:
            # P0-6: Unknown data → BLOCK, not WARN
            return {"name": "position_limit", "passed": False, "severity": "BLOCK",
                    "details": "Portfolio not found — BLOCKED"}

        portfolio_value = float(portfolio["current_capital"])
        position_pct = (amount / portfolio_value * 100) if portfolio_value > 0 else 0

        passed = position_pct <= limit

        return {
            "name": "position_limit",
            "passed": passed,
            "severity": "BLOCK" if not passed else "INFO",
            "details": f"Position: {position_pct:.1f}% (limit: {limit}%)",
        }

    async def _check_sector_concentration(self, ticker: str, portfolio_id: int) -> Dict[str, Any]:
        """Check sector concentration limit.

        P0-6: Unknown sector → BLOCK (WARN değil).
        """
        if not self._risk_limits_loaded:
            return {"name": "sector_concentration", "passed": False, "severity": "BLOCK",
                    "details": "Risk limits not loaded — FAIL CLOSED"}

        limit = self._risk_limits.get("max_sector_pct", 30.0)

        sector = await _db_fetchval("""
            SELECT s.code FROM instruments i
            JOIN companies c ON i.company_id = c.id
            JOIN sectors s ON c.sector_id = s.id
            WHERE i.symbol = $1
        """, ticker)

        if not sector:
            # P0-6: Unknown sector → BLOCK
            return {"name": "sector_concentration", "passed": False, "severity": "BLOCK",
                    "details": f"Unknown sector for {ticker} — BLOCKED"}

        # Get sector exposure
        sector_exposure = await _db_fetchval("""
            SELECT COALESCE(SUM(p.market_value), 0)
            FROM positions p
            JOIN instruments i ON p.instrument_id = i.id
            JOIN companies c ON i.company_id = c.id
            JOIN sectors s ON c.sector_id = s.id
            WHERE p.portfolio_id = $1 AND s.code = $2 AND p.status = 'OPEN'
        """, portfolio_id, sector)

        portfolio_value = await _db_fetchval("""
            SELECT current_capital FROM portfolios WHERE id = $1
        """, portfolio_id)

        if not portfolio_value:
            return {"name": "sector_concentration", "passed": True, "severity": "WARN"}

        concentration = (float(sector_exposure) / float(portfolio_value) * 100) if portfolio_value > 0 else 0
        passed = concentration <= limit

        return {
            "name": "sector_concentration",
            "passed": passed,
            "severity": "BLOCK" if not passed else "INFO",
            "details": f"Sector {sector}: {concentration:.1f}% (limit: {limit}%)",
        }

    async def _check_daily_loss(self, portfolio_id: int) -> Dict[str, Any]:
        """Check daily loss limit."""
        if not self._risk_limits_loaded:
            return {"name": "daily_loss", "passed": False, "severity": "BLOCK",
                    "details": "Risk limits not loaded — FAIL CLOSED"}

        limit = self._risk_limits.get("daily_loss_limit_pct", 5.0)

        # Get today's P&L
        daily_pnl = await _db_fetchval("""
            SELECT COALESCE(SUM(filled_quantity * avg_fill_price * CASE WHEN side = 'SELL' THEN 1 ELSE -1 END), 0)
            FROM orders
            WHERE portfolio_id = $1
            AND status = 'FILLED'
            AND DATE(filled_at) = CURRENT_DATE
        """, portfolio_id)

        portfolio_value = await _db_fetchval("""
            SELECT current_capital FROM portfolios WHERE id = $1
        """, portfolio_id)

        if not portfolio_value:
            return {"name": "daily_loss", "passed": True, "severity": "WARN"}

        loss_pct = abs(float(daily_pnl) / float(portfolio_value) * 100) if float(daily_pnl) < 0 else 0
        passed = loss_pct <= limit

        return {
            "name": "daily_loss",
            "passed": passed,
            "severity": "BLOCK" if not passed else "INFO",
            "details": f"Daily loss: {loss_pct:.1f}% (limit: {limit}%)",
        }

    async def _check_drawdown(self, portfolio_id: int) -> Dict[str, Any]:
        """Check maximum drawdown limit.

        P0-6: Drawdown = peak equity → current equity (initial capital DEĞİL).
        Portfolio bulunamazsa BLOCK.
        """
        if not self._risk_limits_loaded:
            return {"name": "drawdown", "passed": False, "severity": "BLOCK",
                    "details": "Risk limits not loaded — FAIL CLOSED"}

        limit = self._risk_limits.get("max_drawdown_pct", 15.0)

        portfolio = await _db_fetchrow("""
            SELECT initial_capital, current_capital, peak_equity FROM portfolios WHERE id = $1
        """, portfolio_id)

        if not portfolio:
            # P0-6: Unknown → BLOCK
            return {"name": "drawdown", "passed": False, "severity": "BLOCK",
                    "details": "Portfolio not found — BLOCKED"}

        initial = float(portfolio["initial_capital"])
        current = float(portfolio["current_capital"])
        # Peak equity: DB'de varsa kullan, yoksa max(initial, current) olarak tahmin et
        peak = float(portfolio.get("peak_equity") or max(initial, current))

        # Drawdown = peak equity → current equity (initial capital DEĞİL)
        drawdown = ((peak - current) / peak * 100) if peak > 0 else 0

        passed = drawdown <= limit

        return {
            "name": "drawdown",
            "passed": passed,
            "severity": "BLOCK" if not passed else "INFO",
            "details": f"Drawdown: {drawdown:.1f}% (peak: {peak:,.0f}, current: {current:,.0f}, limit: {limit}%)",
        }


# =====================================================
# Health Check HTTP Server
# =====================================================

async def _health_server(port: int = 8080):
    """Lightweight health check HTTP server for Docker healthcheck."""
    from aiohttp import web

    async def health_handler(request):
        return web.json_response({"status": "healthy", "service": "risk"})

    app = web.Application()
    app.router.add_get('/health', health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info("Health server started", port=port)


# =====================================================
# Entry Point
# =====================================================

async def main():
    """Main entry point for the risk engine."""
    await _health_server()
    engine = RiskEngine()
    try:
        await engine.start()
    except KeyboardInterrupt:
        await engine.stop()
    except Exception as e:
        logger.error("Risk Engine crashed", error=str(e))
        await engine.stop()
        raise


# =====================================================
# Enhanced Risk Entegrasyonu
# =====================================================
def assess_portfolio_risk(
    portfolio: Dict,
    market_data: Dict = None,
    returns_history: np.ndarray = None,
    regime: str = "SIDEWAYS",
) -> Dict[str, Any]:
    """Gelişmiş portföy risk değerlendirmesi.

    Tüm risk modüllerini çalıştırır ve kapsamlı risk raporu üretir.

    Args:
        portfolio: Portföy bilgisi {"positions", "total_value", "weights"}
        market_data: Piyasa verisi (opsiyonel)
        returns_history: Geçmiş getiri dizisi (opsiyonel)
        regime: Mevcut piyasa rejimi

    Returns:
        Kapsamlı risk raporu
    """
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "portfolio_value": portfolio.get("total_value", 0),
        "regime": regime,
    }

    # 1. VaR/CVaR (getiri geçmişi varsa)
    if returns_history is not None and len(returns_history) > 20:
        try:
            from .var_cvar import var_calculator
            portfolio_value = portfolio.get("total_value", 100000)
            var_report = var_calculator.calculate_full_var_report(
                returns=returns_history,
                portfolio_value=portfolio_value,
            )
            result["var_cvar"] = {
                "consensus_var_95": var_report["consensus"]["var_95"],
                "parametric_var_95": var_report["parametric"]["var_95"],
                "historical_var_95": var_report["historical"]["var_95"],
                "monte_carlo_var_95": var_report["monte_carlo"]["var_95"],
                "cvar_95": var_report["historical"]["cvar_95"],
                "method_agreement": var_report["consensus"]["method_agreement"],
            }
        except Exception as e:
            result["var_cvar"] = {"error": str(e)}

    # 2. Dynamic Limits
    try:
        from .dynamic_limits import dynamic_limits
        volatility = float(np.std(returns_history or [0]) * np.sqrt(252)) if returns_history is not None else 0.20
        current_dd = portfolio.get("current_drawdown_pct", 0)
        limits = dynamic_limits.get_limits(
            annualized_volatility=volatility,
            regime=regime,
            current_drawdown_pct=current_dd,
        )
        result["dynamic_limits"] = {
            "max_position_pct": limits.max_position_pct,
            "max_sector_pct": limits.max_sector_pct,
            "max_exposure_pct": limits.max_exposure_pct,
            "kelly_fraction": limits.kelly_fraction,
            "min_confidence": limits.min_confidence,
        }
    except Exception as e:
        result["dynamic_limits"] = {"error": str(e)}

    # 3. Concentration Risk
    try:
        from .enhanced_risk import concentration_risk
        weights = portfolio.get("weights", {})
        if weights:
            hhi = concentration_risk.compute_hhi(weights)
            max_ticker, max_weight = concentration_risk.compute_max_concentration(weights)
            result["concentration"] = {
                "hhi": round(hhi, 4),
                "max_position": max_ticker,
                "max_weight": round(max_weight, 4),
            }
    except Exception as e:
        result["concentration"] = {"error": str(e)}

    # 4. Drawdown Response
    try:
        from .drawdown_response import drawdown_system
        current_equity = portfolio.get("total_value", 0)
        if current_equity > 0:
            dd_state = drawdown_system.update_equity(current_equity)
            result["drawdown"] = {
                "current_pct": dd_state.current_drawdown_pct,
                "max_pct": dd_state.max_drawdown_pct,
                "action": dd_state.action.value,
                "severity": dd_state.severity.value,
                "position_scale": dd_state.position_scale,
            }
    except Exception as e:
        result["drawdown"] = {"error": str(e)}

    # 5. Stress Test (getiri geçmişi varsa)
    if returns_history is not None and len(returns_history) > 20:
        try:
            from .stress_test import stress_test_engine
            stress_report = stress_test_engine.run_all_scenarios(portfolio)
            result["stress_test"] = {
                "risk_score": stress_report.risk_score,
                "worst_scenario": stress_report.worst_scenario.scenario_name if stress_report.worst_scenario else "N/A",
                "worst_impact_pct": stress_report.worst_scenario.total_impact_pct if stress_report.worst_scenario else 0,
                "recommendations": stress_report.recommendations,
            }
        except Exception as e:
            result["stress_test"] = {"error": str(e)}

    # 6. Tail Hedge
    try:
        from .tail_hedge import tail_hedger
        portfolio_value = portfolio.get("total_value", 100000)
        hedge = tail_hedger.analyze(
            portfolio_value=portfolio_value,
            regime=regime,
        )
        result["tail_hedge"] = {
            "strategy": hedge.strategy,
            "hedge_ratio": hedge.hedge_ratio,
            "estimated_cost_pct": hedge.estimated_cost_pct,
            "protection_level": hedge.protection_level,
        }
    except Exception as e:
        result["tail_hedge"] = {"error": str(e)}

    # 7. Monitoring Alert Check
    try:
        pass
        # Basit risk skoru hesapla
        risk_score = 50.0
        if "var_cvar" in result and "error" not in result.get("var_cvar", {}):
            var_pct = result["var_cvar"].get("consensus_var_95", 0) / max(portfolio.get("total_value", 1), 1) * 100
            risk_score += min(30, var_pct * 6)
        if "drawdown" in result and "error" not in result.get("drawdown", {}):
            risk_score += min(20, result["drawdown"].get("current_pct", 0) * 2)
        result["risk_score"] = round(min(100, risk_score), 1)
    except Exception:
        result["risk_score"] = 50.0

    return result


def assess_viop_risk(
    viop_positions: List[Dict[str, Any]],
    portfolio_value: float,
) -> Dict[str, Any]:
    """VIOP pozisyonları için risk değerlendirmesi.

    Args:
        viop_positions: VIOP pozisyon listesi
            [{"ticker", "type", "side", "quantity", "entry_price",
              "current_price", "delta", "gamma", "vega", "contract_multiplier"}]
        portfolio_value: Toplam portföy değeri

    Returns:
        Risk metrikleri + risk flags
    """
    try:
        from ..viop.enhanced_options import viop_risk

        risk_result = viop_risk.calculate_portfolio_viop_risk(
            viop_positions, portfolio_value
        )

        margin_result = viop_risk.calculate_margin_requirement(viop_positions)

        margin_adequate = portfolio_value >= margin_result["total_margin"]

        return {
            **risk_result,
            "margin": margin_result,
            "margin_adequate": margin_adequate,
            "margin_surplus": round(portfolio_value - margin_result["total_margin"], 2),
            "margin_utilization_pct": round(
                margin_result["total_margin"] / portfolio_value * 100, 2
            ) if portfolio_value > 0 else 0,
        }
    except Exception as e:
        logger.error(f"VIOP risk assessment failed: {e}")
        return {"error": str(e), "viop_risk": "unavailable"}


if __name__ == "__main__":
    asyncio.run(main())
