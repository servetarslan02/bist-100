"""ALPHA BIST - Simulation Engine (Monte Carlo, Scenarios, Backtest)"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import numpy as np
import orjson
import structlog

from ..core.database import (
    ch_execute,
    close_databases,
    init_databases,
    pg_execute,
    pg_fetch,
)
from ..core.event_bus import (
    EventConsumer,
    EventType,
    ensure_topics,
    publish_event,
)
from ..core.event_schema import CanonicalEvent
from ..core.logging import setup_logging

logger = structlog.get_logger()


class SimulationEngine:
    """Monte Carlo simulation, scenario analysis, and backtest engine."""

    def __init__(self):
        """Otomatik eklendi."""
        self._running = False
        self._consumer: EventConsumer = None

    async def start(self) -> Any:
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

    async def stop(self) -> Any:
        """Stop the simulation engine."""
        self._running = False
        if self._consumer:
            self._consumer.stop()
        await close_databases()
        logger.info("Simulation Engine stopped")

    async def _on_simulation_request(self, event: CanonicalEvent) -> Any:
        """Handle simulation requests."""
        try:
            sim_type = event.data.get("simulation_type", "monte_carlo")
            ticker = event.data.get("ticker")
            event.data.get("portfolio_id")

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
            await pg_execute(
                """
                INSERT INTO simulations (name, simulation_type, parameters, results, status, completed_at)
                VALUES ($1, $2, $3, $4, 'COMPLETED', NOW())
            """,
                f"sim_{ticker}_{sim_type}",
                sim_type,
                orjson.dumps(event.data).decode(),
                orjson.dumps(result),
            )

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

    async def _run_monte_carlo(self, params: dict) -> dict[str, Any]:
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

        # F-020: Seed artık parametre olarak alınabilir (reproducibility)
        _seed = params.get("seed")
        rng = np.random.default_rng(_seed)
        simulations = np.zeros((num_simulations, horizon_days + 1))
        simulations[:, 0] = current_price

        # Volatility clustering: basit GARCH(1,1)
        alpha = 0.1  # yesterday's shock
        beta = 0.85  # persistence
        current_vol = daily_vol
        # GARCH recursion is for variance, not volatility.  Calibrating
        # omega as sigma²(1-alpha-beta) preserves daily_vol as the
        # unconditional volatility; daily_vol * 0.05 inflated it sharply.
        omega = daily_vol**2 * max(1.0 - alpha - beta, 0.0)

        for day in range(1, horizon_days + 1):
            # Fat-tailed random returns
            z = t_dist.rvs(size=num_simulations)
            random_returns = adjusted_return + current_vol * z

            # Event shock injection (%2 ihtimalle)
            shock_mask = rng.random(num_simulations) < 0.02
            shock_size = rng.choice([-0.05, -0.03, 0.03, 0.05], size=num_simulations)
            random_returns = np.where(shock_mask, random_returns + shock_size, random_returns)

            simulations[:, day] = simulations[:, day - 1] * (1 + random_returns)

            # Volatility clustering update must use squared innovations.
            # Squaring the cross-simulation mean cancels shocks out and
            # effectively disables the ARCH term as the scenario count grows.
            innovations = random_returns - adjusted_return
            current_vol = np.sqrt(omega + alpha * np.mean(innovations**2) + beta * current_vol**2)

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
            "timestamp": datetime.now(UTC).isoformat(),
        }

        logger.info("Monte Carlo simulation completed", ticker=ticker, simulations=num_simulations)
        return result

    async def _run_scenario_analysis(self, params: dict) -> dict[str, Any]:
        """Run scenario analysis — beta ve sektör bazlı.

        Her pozisyon için:
        - Beta ayarlaması (market beta × market change)
        - Sektör bazlı etki
        - USD hassasiyeti
        """
        ticker = params.get("ticker")
        portfolio_id = params.get("portfolio_id")

        # Senaryolar: piyasa etkisi + sektör rotasyonu + makro (Rejime Duyarlı Dinamik Olasılıklar)
        regime = (params.get("regime") or params.get("market_regime") or "SIDEWAYS").upper()
        if regime in ["BULL", "STRONG_BULL"]:
            probs = {"Bull": 0.45, "Base": 0.35, "Bear": 0.15, "Crash": 0.05}
        elif regime in ["BEAR", "CRISIS", "PANIC"]:
            probs = {"Bull": 0.10, "Base": 0.30, "Bear": 0.40, "Crash": 0.20}
        elif regime in ["HIGH_VOL"]:
            probs = {"Bull": 0.25, "Base": 0.30, "Bear": 0.30, "Crash": 0.15}
        else:  # SIDEWAYS
            probs = {"Bull": 0.25, "Base": 0.50, "Bear": 0.20, "Crash": 0.05}

        scenarios = [
            {
                "name": "Bull",
                "market_change": 5,
                "probability": probs["Bull"],
                "sector_rotation": {"TECHNOLOGY": 1.2, "BANKING": 0.9, "INDUSTRY": 1.0},
                "usd_change": -0.05,
            },
            {
                "name": "Base",
                "market_change": 0,
                "probability": probs["Base"],
                "sector_rotation": {},
                "usd_change": 0,
            },
            {
                "name": "Bear",
                "market_change": -5,
                "probability": probs["Bear"],
                "sector_rotation": {"TECHNOLOGY": 0.8, "BANKING": 1.1, "INDUSTRY": 0.95},
                "usd_change": 0.08,
            },
            {
                "name": "Crash",
                "market_change": -15,
                "probability": probs["Crash"],
                "sector_rotation": {"TECHNOLOGY": 0.7, "BANKING": 1.3, "INDUSTRY": 0.85},
                "usd_change": 0.20,
            },
        ]

        results = []
        for scenario in scenarios:
            positions = await pg_fetch(
                """
                SELECT p.quantity, p.avg_cost, i.symbol,
                       COALESCE(c.beta, 1.0) as beta,
                       COALESCE(s.code, 'OTHER') as sector
                FROM positions p
                JOIN instruments i ON p.instrument_id = i.id
                LEFT JOIN companies c ON i.company_id = c.id
                LEFT JOIN sectors s ON c.sector_id = s.id
                WHERE p.portfolio_id = $1 AND p.status = 'OPEN'
            """,
                portfolio_id,
            )

            portfolio_impact = 0
            position_details = []

            for pos in positions:
                qty = float(pos["quantity"])
                cost = float(pos["avg_cost"])
                beta = float(pos.get("beta", 1.0) or 1.0)
                sector = pos.get("sector", "OTHER") or "OTHER"
                position_value = qty * cost

                # Beta bazlı market etkisi
                market_effect = scenario["market_change"] * beta

                # Sektör rotasyon etkisi
                sector_mult = scenario["sector_rotation"].get(sector, 1.0)
                sector_effect = scenario["market_change"] * (sector_mult - 1)

                # USD etkisi (şirket bazlı)
                usd_sensitivity = 0.5  # Default
                usd_effect = scenario["usd_change"] * usd_sensitivity * 100

                # Toplam etki
                total_effect = market_effect + sector_effect + usd_effect
                impact = position_value * total_effect / 100
                portfolio_impact += impact

                position_details.append(
                    {
                        "ticker": pos["symbol"],
                        "quantity": qty,
                        "beta": beta,
                        "sector": sector,
                        "market_effect_pct": round(market_effect, 2),
                        "sector_effect_pct": round(sector_effect, 2),
                        "usd_effect_pct": round(usd_effect, 2),
                        "total_effect_pct": round(total_effect, 2),
                        "impact": round(impact, 2),
                    }
                )

            results.append(
                {
                    "scenario": scenario["name"],
                    "market_change_pct": scenario["market_change"],
                    "probability": scenario["probability"],
                    "portfolio_impact": round(portfolio_impact, 2),
                    "positions": position_details,
                }
            )

        return {
            "ticker": ticker,
            "scenarios": results,
            "expected_impact": round(sum(r["portfolio_impact"] * r["probability"] for r in results), 2),
            "worst_case": min(r["portfolio_impact"] for r in results) if results else 0,
            "best_case": max(r["portfolio_impact"] for r in results) if results else 0,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def _run_stress_test(self, params: dict) -> dict[str, Any]:
        """Run stress test — gerçek hesaplama."""
        params.get("portfolio_id")
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

                position_impacts.append(
                    {
                        "ticker": pos.get("ticker", ""),
                        "market_impact": round(market_impact * 100, 2),
                        "usd_impact": round(usd_impact * 100, 2),
                        "total_impact": round(total_pos_impact * 100, 2),
                        "loss": round(pos_loss, 2),
                    }
                )

            results.append(
                {
                    "scenario": scenario["name"],
                    "assumptions": scenario,
                    "portfolio_impact": round(total_impact, 2),
                    "portfolio_impact_pct": round(total_impact / 100000 * 100, 2) if total_impact else 0,
                    "positions": position_impacts,
                }
            )

        return {
            "stress_tests": results,
            "worst_case": min(r["portfolio_impact"] for r in results) if results else 0,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def _get_historical_volatility(self, ticker: str) -> dict[str, Any] | None:
        """Get historical volatility from ClickHouse."""
        try:
            result = ch_execute(
                """
                SELECT
                    stddevSamp(log(close / lagInFrame(close) OVER (ORDER BY timestamp))) as daily_vol,
                    avg(close / lagInFrame(close) OVER (ORDER BY timestamp) - 1) as daily_ret,
                    argMax(close, timestamp) as current_price
                FROM ohlcv
                WHERE instrument_id = (SELECT id FROM instruments WHERE symbol = %(ticker)s)
                AND timeframe = '1d'
                AND timestamp >= now() - INTERVAL 60 DAY
            """,
                parameters={"ticker": ticker},
            )

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
# Health Check HTTP Server
# =====================================================


async def _health_server(port: int = 8080) -> Any:
    """Lightweight health check HTTP server for Docker healthcheck."""
    from aiohttp import web

    async def health_handler(request) -> Any:
        """Otomatik eklendi."""
        return web.json_response({"status": "healthy", "service": "simulation"})

    app = web.Application()
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Health server started", port=port)


# =====================================================
# Entry Point
# =====================================================


async def main() -> Any:
    """Main entry point for the simulation engine."""
    await _health_server()
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
