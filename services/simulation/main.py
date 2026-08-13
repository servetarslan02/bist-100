"""ALPHA BIST - Simulation Engine (Monte Carlo, Scenarios, Backtest)"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
import numpy as np
import structlog

from ..core.config import settings
from ..core.database import (
    init_databases, close_databases, pg_fetch, pg_fetchrow, pg_execute,
    redis_get, redis_set, ch_execute,
)
from ..core.event_bus import (
    ensure_topics, AlphaEvent, EventType,
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
        """Run Monte Carlo simulation."""
        ticker = params.get("ticker")
        num_simulations = params.get("num_simulations", 10000)
        horizon_days = params.get("horizon_days", 20)

        # Get historical volatility
        vol_data = await self._get_historical_volatility(ticker)
        if not vol_data:
            return {"error": "Insufficient data for simulation"}

        daily_vol = vol_data.get("daily_volatility", 0.02)
        daily_return = vol_data.get("daily_return", 0.0005)
        current_price = vol_data.get("current_price", 100)

        # Run simulations
        np.random.seed(42)
        simulations = np.zeros((num_simulations, horizon_days + 1))
        simulations[:, 0] = current_price

        for day in range(1, horizon_days + 1):
            random_returns = np.random.normal(daily_return, daily_vol, num_simulations)
            simulations[:, day] = simulations[:, day-1] * (1 + random_returns)

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
            "timestamp": datetime.utcnow().isoformat(),
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
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def _run_stress_test(self, params: Dict) -> Dict[str, Any]:
        """Run stress test."""
        portfolio_id = params.get("portfolio_id")

        # Define stress scenarios
        stress_scenarios = [
            {"name": "Market Crash -20%", "market_change": -20, "volatility_spike": 3},
            {"name": "Currency Crisis", "usd_change": 30, "market_change": -15},
            {"name": "Rate Shock +500bp", "rate_change": 5, "market_change": -10},
            {"name": "Sector Rotation", "sector_change": {"BANK": -15, "TECH": 10}},
        ]

        results = []
        for scenario in stress_scenarios:
            result = {
                "scenario": scenario["name"],
                "assumptions": scenario,
                "impact": "calculated",  # Placeholder
            }
            results.append(result)

        return {
            "stress_tests": results,
            "timestamp": datetime.utcnow().isoformat(),
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
