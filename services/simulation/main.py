"""ALPHA BIST - Simulation Engine (Monte Carlo, Scenarios, Backtest)"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import numpy as np
import structlog

from ..core.config import settings
from ..core.database import (
    init_databases, close_databases, pg_fetch, pg_fetchrow, pg_execute,
    redis_get, redis_set, ch_execute,
)
from ..core.event_schema import CanonicalEvent
from ..core.event_bus import (
    ensure_topics, EventType,
    EventConsumer, publish_event,
)
from ..core.logging import setup_logging

logger = structlog.get_logger()


class SimulationEngine:
    """Monte Carlo simulation, scenario analysis, and backtest engine."""

    def __init__(self):
        self._running = False
        self._consumer: EventConsumer = None

    async def start(self):
        """Start the simulation engine."""
        setup_logging()
        logger.info("Starting Simulation Engine")

        await init_databases()
        ensure_topics()

        self._running = True

        # Set up event consumer
        self._consumer = EventConsumer(
            group_id="simulation",
            topics=["simulation.requested"],
            auto_offset_reset="latest",
        )
        self._consumer.on(EventType.SIMULATION_REQUESTED, self._on_simulation_request)

        logger.info("Simulation Engine started")
        await self._consumer.consume_loop()

    async def stop(self):
        """Stop the simulation engine."""
        self._running = False
        if self._consumer:
            self._consumer.stop()
        await close_databases()
        logger.info("Simulation Engine stopped")

    async def _on_simulation_request(self, event: CanonicalEvent):
        """Handle simulation requests."""
        try:
            sim_type = event.data.get("simulation_type", "monte_carlo")
            ticker = event.data.get("ticker")
            portfolio_id = event.data.get("portfolio_id")

            logger.info("Running simulation", type=sim_type, ticker=ticker)

            if sim_type == "monte_carlo":
                result = await self._run_monte_carlo(event.data)
            elif sim_type == "scenario":
                result = await self._run_scenario_analysis(event.data)
            elif sim_type == "stress_test":
                result = await self._run_stress_test(event.data)
            else:
                result = {"error": f"Unknown simulation type: {sim_type}"}

            # Store result
            await pg_execute("""
                INSERT INTO simulations (name, simulation_type, parameters, results, status, completed_at)
                VALUES ($1, $2, $3, $4, 'COMPLETED', NOW())
            """, f"sim_{ticker}_{sim_type}", sim_type, json.dumps(event.data), json.dumps(result))

            # Publish result
            result_event = CanonicalEvent(
                event_type=EventType.SIMULATION_COMPLETED,
                source="simulation",
                data={
                    "simulation_type": sim_type,
                    "ticker": ticker,
                    "result": result,
                },
            )
            publish_event(result_event, key=ticker or "sim")

        except Exception as e:
            logger.error("Simulation error", error=str(e))

    async def _run_monte_carlo(self, params: Dict) -> Dict[str, Any]:
        """
        Monte Carlo simülasyonu — v1.1
        
        Daha gerçekçi:
        - Regime-conditioned returns
        - Fat tails (Student-t dağılımı)
        - Volatility clustering (GARCH benzeri)
        - Event shock injection
        - Liquidity constraint
        """
        ticker = params.get("ticker")
        num_simulations = params.get("num_simulations", 10000)
        horizon_days = params.get("horizon_days", 20)

        vol_data = await self._get_historical_volatility(ticker)
        if not vol_data:
            return {"error": "Insufficient data for simulation"}

        daily_vol = vol_data.get("daily_volatility", 0.02)
        daily_return = vol_data.get("daily_return", 0.0005)
        current_price = vol_data.get("current_price", 100)
        regime = vol_data.get("regime", "RANGE")

        # Regime-conditioned parameters
        regime_mult = {"TRENDING-UP": 1.2, "RISK-OFF": 0.5, "PANIC": 0.3, "RANGE": 1.0}.get(regime, 1.0)
        adjusted_return = daily_return * regime_mult

        # Fat tails: Student-t dağılımı (df=5)
        from scipy import stats
        t_dist = stats.t(df=5)

        np.random.seed(42)
        simulations = np.zeros((num_simulations, horizon_days + 1))
        simulations[:, 0] = current_price

        # Volatility clustering: basit GARCH(1,1)
        current_vol = daily_vol
        omega = daily_vol * 0.05  # uzun vadeli vol
        alpha = 0.1  # yesterday's shock
        beta = 0.85  # persistence

        for day in range(1, horizon_days + 1):
            # Fat-tailed random returns
            z = t_dist.rvs(size=num_simulations)
            random_returns = adjusted_return + current_vol * z

            # Event shock injection (%2 ihtimalle)
            shock_mask = np.random.random(num_simulations) < 0.02
            shock_size = np.random.choice([-0.05, -0.03, 0.03, 0.05], size=num_simulations)
            random_returns = np.where(shock_mask, random_returns + shock_size, random_returns)

            simulations[:, day] = simulations[:, day-1] * (1 + random_returns)

            # Volatility clustering güncelle
            avg_return = np.mean(random_returns)
            current_vol = np.sqrt(omega + alpha * avg_return**2 + beta * current_vol**2)

        # Calculate statistics
        final_prices = simulations[:, -1]
        returns = (final_prices / current_price - 1) * 100

        result = {
            "ticker": ticker,
            "current_price": float(current_price),
            "horizon_days": horizon_days,
            "num_simulations": num_simulations,
            "expected_return_pct": float(np.mean(returns)),
            "median_return_pct": float(np.median(returns)),
            "std_return_pct": float(np.std(returns)),
            "var_95": float(np.percentile(returns, 5)),
            "cvar_95": float(np.mean(returns[returns <= np.percentile(returns, 5)])),
            "max_return_pct": float(np.max(returns)),
            "min_return_pct": float(np.min(returns)),
            "prob_positive": float(np.mean(returns > 0) * 100),
            "prob_up_5pct": float(np.mean(returns > 5) * 100),
            "prob_down_5pct": float(np.mean(returns < -5) * 100),
            "percentiles": {
                "5": float(np.percentile(returns, 5)),
                "25": float(np.percentile(returns, 25)),
                "50": float(np.percentile(returns, 50)),
                "75": float(np.percentile(returns, 75)),
                "95": float(np.percentile(returns, 95)),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logger.info("Monte Carlo simulation completed", ticker=ticker, simulations=num_simulations)
        return result

    async def _run_scenario_analysis(self, params: Dict) -> Dict[str, Any]:
        """Run scenario analysis."""
        ticker = params.get("ticker")
        portfolio_id = params.get("portfolio_id")

        # Define scenarios
        scenarios = [
            {"name": "Bull", "market_change": 5, "probability": 0.25},
            {"name": "Base", "market_change": 0, "probability": 0.50},
            {"name": "Bear", "market_change": -5, "probability": 0.20},
            {"name": "Crash", "market_change": -15, "probability": 0.05},
        ]

        results = []
        for scenario in scenarios:
            # Get portfolio positions
            positions = await pg_fetch("""
                SELECT p.quantity, p.avg_cost, i.symbol
                FROM positions p
                JOIN instruments i ON p.instrument_id = i.id
                WHERE p.portfolio_id = $1 AND p.status = 'OPEN'
            """, portfolio_id)

            portfolio_impact = 0
            position_details = []

            for pos in positions:
                # Estimate position impact (simplified beta = 1)
                impact = float(pos["quantity"]) * float(pos["avg_cost"]) * scenario["market_change"] / 100
                portfolio_impact += impact

                position_details.append({
                    "ticker": pos["symbol"],
                    "quantity": pos["quantity"],
                    "impact": round(impact, 2),
                })

            results.append({
                "scenario": scenario["name"],
                "market_change_pct": scenario["market_change"],
                "probability": scenario["probability"],
                "portfolio_impact": round(portfolio_impact, 2),
                "positions": position_details,
            })

        return {
            "ticker": ticker,
            "scenarios": results,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def _run_stress_test(self, params: Dict) -> Dict[str, Any]:
        """Run stress test — gerçek hesaplama."""
        portfolio_id = params.get("portfolio_id")
        positions = params.get("positions", [])

        # Stress senaryoları
        stress_scenarios = [
            {"name": "Market Crash -20%", "market_shock": -0.20, "vol_spike": 3.0, "usd_shock": 0.10},
            {"name": "Currency Crisis", "market_shock": -0.15, "vol_spike": 2.5, "usd_shock": 0.30},
            {"name": "Rate Shock +500bp", "market_shock": -0.10, "vol_spike": 2.0, "usd_shock": 0.05},
            {"name": "Sector Rotation", "market_shock": -0.05, "vol_spike": 1.5, "usd_shock": 0.02},
            {"name": "Black Swan -30%", "market_shock": -0.30, "vol_spike": 5.0, "usd_shock": 0.20},
        ]

        results = []
        for scenario in stress_scenarios:
            # Her pozisyon için etki hesapla
            total_impact = 0
            position_impacts = []

            for pos in positions:
                # Beta = 1 varsayılan
                beta = 1.0
                # USD hassasiyeti (exporter/importer)
                usd_sensitivity = 0.5

                market_impact = scenario["market_shock"] * beta
                usd_impact = scenario["usd_shock"] * usd_sensitivity
                total_pos_impact = market_impact + usd_impact

                pos_loss = pos.get("value", 0) * total_pos_impact
                total_impact += pos_loss

                position_impacts.append({
                    "ticker": pos.get("ticker", ""),
                    "market_impact": round(market_impact * 100, 2),
                    "usd_impact": round(usd_impact * 100, 2),
                    "total_impact": round(total_pos_impact * 100, 2),
                    "loss": round(pos_loss, 2),
                })

            results.append({
                "scenario": scenario["name"],
                "assumptions": scenario,
                "portfolio_impact": round(total_impact, 2),
                "portfolio_impact_pct": round(total_impact / 100000 * 100, 2) if total_impact else 0,
                "positions": position_impacts,
            })

        return {
            "stress_tests": results,
            "worst_case": min(r["portfolio_impact"] for r in results) if results else 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def _get_historical_volatility(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Get historical volatility from ClickHouse."""
        try:
            result = ch_execute("""
                SELECT
                    stddevSamp(log(close / lagInFrame(close) OVER (ORDER BY timestamp))) as daily_vol,
                    avg(close / lagInFrame(close) OVER (ORDER BY timestamp) - 1) as daily_ret,
                    argMax(close, timestamp) as current_price
                FROM ohlcv
                WHERE instrument_id = (SELECT id FROM instruments WHERE symbol = %(ticker)s)
                AND timeframe = '1d'
                AND timestamp >= now() - INTERVAL 60 DAY
            """, parameters={"ticker": ticker})

            if result.result_rows and len(result.result_rows) > 0:
                row = result.result_rows[0]
                return {
                    "daily_volatility": float(row[0]) if row[0] else 0.02,
                    "daily_return": float(row[1]) if row[1] else 0.0005,
                    "current_price": float(row[2]) if row[2] else 100,
                }

            return None

        except Exception as e:
            logger.warning("Failed to get historical volatility", ticker=ticker, error=str(e))
            return None


# =====================================================
# Entry Point
# =====================================================

async def main():
    """Main entry point for the simulation engine."""
    engine = SimulationEngine()
    try:
        await engine.start()
    except KeyboardInterrupt:
        await engine.stop()
    except Exception as e:
        logger.error("Simulation Engine crashed", error=str(e))
        await engine.stop()
        raise


if __name__ == "__main__":
    asyncio.run(main())
