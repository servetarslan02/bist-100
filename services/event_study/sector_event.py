"""ALPHA BIST — Sector Event Analysis.

Sektör bazlı event study — peer comparison, sector-relative CAR,
sector rotation detection.
"""

from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

class DynamicSectorMap(dict):
    """BIST evreninden dinamik sektör eşleme haritası."""

    def get(self, key: Any, default: Any = None) -> list[str]:
        try:
            from services.ingestion.bist_universe import bist_universe

            stocks = bist_universe.get_tickers_by_sector(str(key))
            if stocks:
                return stocks
        except Exception:
            pass
        return default if default is not None else []

    def items(self) -> Any:
        try:
            from services.ingestion.bist_universe import bist_universe

            sectors = ["BANKA", "SANAYI", "TEKNOLOJI", "ENERJI", "GIDA", "ULASIM", "INSAAT", "METAL", "TEKSTIL", "HOLDING", "SIGORTA", "MADEN"]
            return [(s, bist_universe.get_tickers_by_sector(s)) for s in sectors]
        except Exception:
            return []


SECTOR_STOCKS = DynamicSectorMap()


class SectorEventAnalyzer:
    """Sektör bazlı event study analizi."""

    def analyze_sector_event(
        self,
        sector: str,
        event_type: str,
        stock_returns: np.ndarray,
        market_returns: np.ndarray,
        sector_returns: np.ndarray | None = None,
        alpha: float = 0.0,
        beta: float = 1.0,
    ) -> dict[str, Any]:
        """Sektör bazlı event study.

        Args:
            sector: Sektör adı
            event_type: Event tipi
            stock_returns: Hisse getirileri
            market_returns: BIST-100 getirileri
            sector_returns: Sektör getirileri (opsiyonel)
            alpha: Expected return intercept
            beta: Market beta

        Returns:
            Dict with sector_car, bist_car, relative_car, outperformed
        """
        from .abnormal_return import calculate_abnormal_return
        from .car import calculate_car

        # Hisse AR
        stock_ar = calculate_abnormal_return(stock_returns, market_returns, alpha, beta)
        stock_car = calculate_car(stock_ar)

        # Sektör AR (varsa)
        sector_car = 0.0
        if sector_returns is not None:
            sector_ar = calculate_abnormal_return(sector_returns, market_returns, alpha, beta)
            sector_car = calculate_car(sector_ar)

        # BIST-100 CAR = kümülatif getiri (market kendi benchmark'ı → AR=0, raw return kullan)
        bist_car = float(np.sum(market_returns))

        # Relative performance
        relative_car = stock_car - bist_car

        result = {
            "sector": sector,
            "event_type": event_type,
            "stock_car": round(stock_car, 4),
            "sector_car": round(sector_car, 4),
            "bist_car": round(bist_car, 4),
            "relative_car": round(relative_car, 4),
            "outperformed_bist": relative_car > 0,
            "outperformed_sector": (stock_car - sector_car) > 0 if sector_returns is not None else None,
        }

        return result

    def analyze_peer_comparison(
        self,
        sector: str,
        event_type: str,
        peer_returns: dict[str, np.ndarray],
        market_returns: np.ndarray,
        target_ticker: str = None,
    ) -> dict[str, Any]:
        """Peer comparison — aynı sektördeki hisseleri karşılaştır.

        Args:
            sector: Sektör adı
            event_type: Event tipi
            peer_returns: {ticker: returns} sözlüğü
            market_returns: BIST-100 getirileri
            target_ticker: Hedef hisse (opsiyonel)

        Returns:
            Dict with peer_cars, sector_average, rankings
        """
        from .abnormal_return import calculate_abnormal_return
        from .car import calculate_car

        peer_cars = {}
        for ticker, returns in peer_returns.items():
            n = min(len(returns), len(market_returns))
            ar = calculate_abnormal_return(returns[:n], market_returns[:n], 0.0, 1.0)
            car = calculate_car(ar)
            peer_cars[ticker] = round(car, 4)

        # Sektör ortalaması
        all_cars = list(peer_cars.values())
        sector_avg = float(np.mean(all_cars)) if all_cars else 0.0

        # Sıralama
        sorted_peers = sorted(peer_cars.items(), key=lambda x: x[1], reverse=True)
        rankings = {ticker: rank + 1 for rank, (ticker, _) in enumerate(sorted_peers)}

        result = {
            "sector": sector,
            "event_type": event_type,
            "peer_cars": peer_cars,
            "sector_average_car": round(sector_avg, 4),
            "rankings": rankings,
            "n_peers": len(peer_cars),
            "best_performer": sorted_peers[0][0] if sorted_peers else None,
            "worst_performer": sorted_peers[-1][0] if sorted_peers else None,
        }

        # Target hisse analizi
        if target_ticker and target_ticker in peer_cars:
            target_car = peer_cars[target_ticker]
            result["target_analysis"] = {
                "ticker": target_ticker,
                "car": target_car,
                "rank": rankings[target_ticker],
                "vs_sector_avg": round(target_car - sector_avg, 4),
                "percentile": round(sum(1 for c in all_cars if c < target_car) / len(all_cars) * 100, 1)
                if all_cars
                else 0,
            }

        return result

    def detect_sector_rotation(
        self,
        sector_cars: dict[str, float],
        threshold: float = 0.02,
    ) -> dict[str, Any]:
        """Sektör rotasyonu tespiti.

        Args:
            sector_cars: {sector: CAR} sözlüğü
            threshold: Outperform/underperform eşik değeri

        Returns:
            Dict with inflow_sectors, outflow_sectors, rotation_signal
        """
        if not sector_cars:
            return {"inflow_sectors": [], "outflow_sectors": [], "rotation_signal": "NEUTRAL"}

        avg_car = float(np.mean(list(sector_cars.values())))

        inflow = []  # Para giren sektörler
        outflow = []  # Para çıkan sektörler

        for sector, car in sector_cars.items():
            relative = car - avg_car
            if relative > threshold:
                inflow.append({"sector": sector, "car": car, "relative_car": round(relative, 4)})
            elif relative < -threshold:
                outflow.append({"sector": sector, "car": car, "relative_car": round(relative, 4)})

        # Rotasyon sinyali
        if len(inflow) > 0 and len(outflow) > 0:
            rotation_signal = "ACTIVE_ROTATION"
        elif len(inflow) > 0:
            rotation_signal = "BROAD_BASED_UP"
        elif len(outflow) > 0:
            rotation_signal = "BROAD_BASED_DOWN"
        else:
            rotation_signal = "NEUTRAL"

        return {
            "inflow_sectors": sorted(inflow, key=lambda x: x["relative_car"], reverse=True),
            "outflow_sectors": sorted(outflow, key=lambda x: x["relative_car"]),
            "rotation_signal": rotation_signal,
            "sector_dispersion": round(float(np.std(list(sector_cars.values()))), 4),
        }

    def get_sector_stocks(self, sector: str) -> list[str]:
        """Sektördeki hisseleri döndür."""
        return SECTOR_STOCKS.get(sector.upper(), [])

    def get_stock_sector(self, ticker: str) -> str | None:
        """Hissenin sektörünü döndür."""
        for sector, stocks in SECTOR_STOCKS.items():
            if ticker in stocks:
                return sector
        return None
