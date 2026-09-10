"""ALPHA BIST — Sector Event Analysis.

Sektör bazlı event study — peer comparison, sector-relative CAR,
sector rotation detection.
"""

from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# --- Sabitler ---
DEFAULT_SECTOR_LIST: tuple[str, ...] = (
    "BANKA", "SANAYI", "TEKNOLOJI", "ENERJI", "GIDA",
    "ULASIM", "INSAAT", "METAL", "TEKSTIL", "HOLDING",
    "SIGORTA", "MADEN",
)
DEFAULT_ROTATION_THRESHOLD: float = 0.02
PERCENTILE_MULTIPLIER: float = 100.0
DEFAULT_ALPHA: float = 0.0
DEFAULT_BETA: float = 1.0


def _validate_string(value: Any, name: str, allow_empty: bool = False) -> str:
    """String doğrulama.

    Args:
        value: Kontrol edilecek değer
        name: Parametre adı
        allow_empty: Boş string'e izin verilsin mi

    Returns:
        Doğrulanmış string

    Raises:
        TypeError: String değilse
        ValueError: Boş string ise (allow_empty=False)
    """
    if not isinstance(value, str):
        raise TypeError(f"{name} string olmalı, alınan: {type(value).__name__}")
    if not allow_empty and not value.strip():
        raise ValueError(f"{name} boş olamaz")
    return value


def _validate_array(arr: Any, name: str, min_size: int = 1) -> np.ndarray:
    """Array doğrulama (tip, boşluk, NaN/Inf).

    Args:
        arr: Kontrol edilecek array (ndarray, list veya tuple)
        name: Array adı
        min_size: Minimum boyut

    Returns:
        Doğrulanmış numpy array

    Raises:
        TypeError: Desteklenmeyen tip ise
        ValueError: Boş, yetersiz veya NaN/Inf içeriyorsa
    """
    if isinstance(arr, (list, tuple)):
        arr = np.asarray(arr, dtype=float)
    if not isinstance(arr, np.ndarray):
        raise TypeError(f"{name} numpy.ndarray, list veya tuple olmalı, alınan: {type(arr).__name__}")
    if arr.size == 0:
        raise ValueError(f"{name} boş olamaz")
    if arr.size < min_size:
        raise ValueError(f"{name} en az {min_size} örneklem içermeli, alınan: {arr.size}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} NaN veya Inf değerler içeriyor")
    return arr


def _validate_float(value: float, name: str) -> float:
    """Float değer için tip ve NaN/Inf kontrolü.

    Args:
        value: Kontrol edilecek değer
        name: Değerin adı

    Returns:
        Doğrulanmış float

    Raises:
        TypeError: Sayısal değilse
        ValueError: NaN veya Inf ise
    """
    if not isinstance(value, (int, float, np.integer, np.floating)):
        raise TypeError(f"{name} sayısal olmalı, alınan: {type(value).__name__} ({value})")
    if not np.isfinite(value):
        raise ValueError(f"{name} sonlu değil: {value}")
    return float(value)


def _validate_peer_returns(peer_returns: Any) -> dict[str, np.ndarray]:
    """Peer returns sözlüğü doğrulama.

    Args:
        peer_returns: Kontrol edilecek sözlük

    Returns:
        Doğrulanmış sözlük (her value numpy array'e dönüştürülmüş)

    Raises:
        TypeError: Sözlük değilse veya value'lar desteklenmeyen tip ise
        ValueError: Boş sözlük ise veya value'lar NaN/Inf içeriyorsa
    """
    if not isinstance(peer_returns, dict):
        raise TypeError(f"peer_returns sözlük olmalı, alınan: {type(peer_returns).__name__}")
    if len(peer_returns) == 0:
        raise ValueError("peer_returns boş olamaz")
    validated: dict[str, np.ndarray] = {}
    for ticker, rets in peer_returns.items():
        if isinstance(rets, (list, tuple)):
            rets = np.asarray(rets, dtype=float)
        if not isinstance(rets, np.ndarray):
            raise TypeError(f"peer_returns['{ticker}'] numpy.ndarray olmalı")
        if not np.all(np.isfinite(rets)):
            raise ValueError(f"peer_returns['{ticker}'] NaN veya Inf değerler içeriyor")
        validated[ticker] = rets
    return validated


def _validate_sector_cars(sector_cars: dict[str, float]) -> dict[str, float]:
    """Sector CAR sözlüğü doğrulama.

    Args:
        sector_cars: Kontrol edilecek sözlük

    Returns:
        Doğrulanmış sözlük

    Raises:
        TypeError: Sözlük değilse
        ValueError: Boş sözlük ise veya value'lar sonlu değilse
    """
    if not isinstance(sector_cars, dict):
        raise TypeError(f"sector_cars sözlük olmalı, alınan: {type(sector_cars).__name__}")
    if len(sector_cars) == 0:
        raise ValueError("sector_cars boş olamaz")
    validated: dict[str, float] = {}
    for sector, car in sector_cars.items():
        validated[sector] = _validate_float(car, f"sector_cars['{sector}']")
    return validated


class DynamicSectorMap(dict):
    """BIST evreninden dinamik sektör eşleme haritası."""

    def get(self, key: Any, default: Any = None) -> list[str]:
        """Sektöre göre hisse listesi döndür.

        Args:
            key: Sektör adı
            default: Varsayılan değer

        Returns:
            Hisse listesi veya default
        """
        try:
            from services.ingestion.bist_universe import bist_universe

            stocks = bist_universe.get_tickers_by_sector(str(key))
            if stocks:
                return stocks
        except ImportError:
            logger.debug(
                "sektor_harita_bulunamadi",
                sector=str(key),
                aciklama="bist_universe modülü yüklenemedi, varsayılan liste kullanılıyor",
            )
        except Exception as exc:
            logger.warning(
                "sektor_harita_hatasi",
                sector=str(key),
                hata=str(exc),
            )
        return default if default is not None else []

    def items(self) -> Any:
        """Tüm sektörler ve hisseleri.

        Returns:
            [(sector, stocks)] listesi
        """
        try:
            from services.ingestion.bist_universe import bist_universe

            return [(s, bist_universe.get_tickers_by_sector(s)) for s in DEFAULT_SECTOR_LIST]
        except ImportError:
            logger.debug(
                "sektor_harita_items_bulunamadi",
                aciklama="bist_universe modülü yüklenemedi",
            )
        except Exception as exc:
            logger.warning("sektor_harita_items_hatasi", hata=str(exc))
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
        alpha: float = DEFAULT_ALPHA,
        beta: float = DEFAULT_BETA,
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

        Raises:
            TypeError: Parametre tipleri uygun değilse
            ValueError: Değerler sonlu değilse veya veri yetersiz ise
        """
        from .abnormal_return import calculate_abnormal_return
        from .car import calculate_car

        # --- Validasyon ---
        _validate_string(sector, "sector")
        _validate_string(event_type, "event_type")
        sr = _validate_array(stock_returns, "stock_returns")
        mr = _validate_array(market_returns, "market_returns")
        alpha = _validate_float(alpha, "alpha")
        beta = _validate_float(beta, "beta")

        if sector_returns is not None:
            if isinstance(sector_returns, (list, tuple)):
                sector_returns = np.asarray(sector_returns, dtype=float)
            if not isinstance(sector_returns, np.ndarray):
                raise TypeError("sector_returns numpy.ndarray olmalı")
            if not np.all(np.isfinite(sector_returns)):
                raise ValueError("sector_returns NaN veya Inf değerler içeriyor")

        # Hisse AR
        stock_ar = calculate_abnormal_return(sr, mr, alpha, beta)
        stock_car = calculate_car(stock_ar)

        # Sektör AR (varsa)
        sector_car = 0.0
        if sector_returns is not None:
            sector_ar = calculate_abnormal_return(sector_returns, mr, alpha, beta)
            sector_car = calculate_car(sector_ar)

        # BIST-100 CAR = kümülatif getiri (market kendi benchmark'ı → AR=0, raw return kullan)
        bist_car = float(np.sum(mr))

        # Relative performance
        relative_car = stock_car - bist_car

        result: dict[str, Any] = {
            "sector": sector,
            "event_type": event_type,
            "stock_car": round(stock_car, 4),
            "sector_car": round(sector_car, 4),
            "bist_car": round(bist_car, 4),
            "relative_car": round(relative_car, 4),
            "outperformed_bist": relative_car > 0,
            "outperformed_sector": (stock_car - sector_car) > 0 if sector_returns is not None else None,
        }

        logger.debug(
            "sektor_event_analiz_edildi",
            sector=sector,
            event_type=event_type,
            stock_car=round(stock_car, 4),
            bist_car=round(bist_car, 4),
            outperformed=result["outperformed_bist"],
        )

        return result

    def analyze_peer_comparison(
        self,
        sector: str,
        event_type: str,
        peer_returns: dict[str, np.ndarray],
        market_returns: np.ndarray,
        target_ticker: str | None = None,
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

        Raises:
            TypeError: Parametre tipleri uygun değilse
            ValueError: Boş sözlük veya NaN/Inf içeriyorsa
        """
        from .abnormal_return import calculate_abnormal_return
        from .car import calculate_car

        # --- Validasyon ---
        _validate_string(sector, "sector")
        _validate_string(event_type, "event_type")
        peer_returns = _validate_peer_returns(peer_returns)
        mr = _validate_array(market_returns, "market_returns")

        peer_cars: dict[str, float] = {}
        for ticker, returns in peer_returns.items():
            n = min(len(returns), len(mr))
            ar = calculate_abnormal_return(returns[:n], mr[:n], DEFAULT_ALPHA, DEFAULT_BETA)
            car = calculate_car(ar)
            peer_cars[ticker] = round(car, 4)

        # Sektör ortalaması
        all_cars = list(peer_cars.values())
        sector_avg = round(float(np.mean(all_cars)), 4)

        # Sıralama
        sorted_peers = sorted(peer_cars.items(), key=lambda x: x[1], reverse=True)
        rankings = {ticker: rank + 1 for rank, (ticker, _) in enumerate(sorted_peers)}

        result: dict[str, Any] = {
            "sector": sector,
            "event_type": event_type,
            "peer_cars": peer_cars,
            "sector_average_car": sector_avg,
            "rankings": rankings,
            "n_peers": len(peer_cars),
            "best_performer": sorted_peers[0][0] if sorted_peers else None,
            "worst_performer": sorted_peers[-1][0] if sorted_peers else None,
        }

        # Target hisse analizi
        if target_ticker and target_ticker in peer_cars:
            target_car = peer_cars[target_ticker]
            n_below = sum(1 for c in all_cars if c < target_car)
            result["target_analysis"] = {
                "ticker": target_ticker,
                "car": target_car,
                "rank": rankings[target_ticker],
                "vs_sector_avg": round(target_car - sector_avg, 4),
                "percentile": round(n_below / len(all_cars) * PERCENTILE_MULTIPLIER, 1),
            }

        logger.debug(
            "sektor_karsilastirma_analiz_edildi",
            sector=sector,
            n_peers=len(peer_cars),
            sector_avg=sector_avg,
        )

        return result

    def detect_sector_rotation(
        self,
        sector_cars: dict[str, float],
        threshold: float = DEFAULT_ROTATION_THRESHOLD,
    ) -> dict[str, Any]:
        """Sektör rotasyonu tespiti.

        Args:
            sector_cars: {sector: CAR} sözlüğü
            threshold: Outperform/underperform eşik değeri

        Returns:
            Dict with inflow_sectors, outflow_sectors, rotation_signal

        Raises:
            TypeError: Parametre tipleri uygun değilse
            ValueError: Boş sözlük, sonlu olmayan değerler veya negatif threshold
        """
        sector_cars = _validate_sector_cars(sector_cars)
        threshold = _validate_float(threshold, "threshold")
        if threshold < 0:
            raise ValueError(f"threshold negatif olamaz, alınan: {threshold}")

        avg_car = float(np.mean(list(sector_cars.values())))

        inflow: list[dict[str, Any]] = []
        outflow: list[dict[str, Any]] = []

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
        """Sektördeki hisseleri döndür.

        Args:
            sector: Sektör adı

        Returns:
            Hisse listesi

        Raises:
            TypeError: String değilse
        """
        _validate_string(sector, "sector")
        return SECTOR_STOCKS.get(sector.upper(), [])

    def get_stock_sector(self, ticker: str) -> str | None:
        """Hissenin sektörünü döndür.

        Args:
            ticker: Hisse kodu

        Returns:
            Sektör adı veya None

        Raises:
            TypeError: String değilse
        """
        _validate_string(ticker, "ticker")
        for sector, stocks in SECTOR_STOCKS.items():
            if ticker in stocks:
                return sector
        return None
