"""ALPHA BIST — Estimation Window Manager (MacKinlay, 1997).

Estimation window, event öncesi veriyi kullanarak expected return modelinin
parametrelerini (α, β) tahmin etmek için kullanılır. Look-ahead bias'ı önler.
"""
from datetime import datetime, timedelta
from typing import Tuple, Optional
import numpy as np
import structlog

logger = structlog.get_logger()

# Event type → estimation window uzunluğu (gün)
ESTIMATION_WINDOWS = {
    "FINANCIAL_RESULTS": 120,
    "DIVIDEND": 60,
    "BUYBACK": 60,
    "CAPITAL_INCREASE": 90,
    "MERGER": 120,
    "MANAGEMENT_CHANGE": 60,
    "LEGAL": 90,
    "CONTRACT": 60,
    "GUIDANCE": 60,
    "TCMB_RATE": 90,
    "INFLATION": 60,
    "GDP": 90,
    "CPI": 60,
    "PPI": 60,
    "CURRENT_ACCOUNT": 60,
    "UNEMPLOYMENT": 60,
    "INDUSTRIAL_PRODUCTION": 60,
    "DEFAULT": 60,
}

# Event tarihinden kaç gün önce estimation window bitsin
GAP_DAYS = 6


class EstimationWindowManager:
    """Estimation window yönetimi — look-ahead bias önleme."""

    def __init__(self, gap_days: int = GAP_DAYS):
        self.gap_days = gap_days

    def get_window(
        self, event_date: datetime, event_type: str = "DEFAULT"
    ) -> Tuple[datetime, datetime]:
        """Event type'a göre estimation window döndür.

        Args:
            event_date: Event tarihi
            event_type: Event tipi (KAP/macro)

        Returns:
            (start_date, end_date) tuple
        """
        days = ESTIMATION_WINDOWS.get(event_type, ESTIMATION_WINDOWS["DEFAULT"])
        end_date = event_date - timedelta(days=self.gap_days)
        start_date = end_date - timedelta(days=days)

        logger.debug(
            "estimation_window_calculated",
            event_date=event_date.isoformat(),
            event_type=event_type,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            days=days,
        )
        return start_date, end_date

    def get_window_days(self, event_type: str = "DEFAULT") -> int:
        """Estimation window uzunluğunu gün olarak döndür."""
        return ESTIMATION_WINDOWS.get(event_type, ESTIMATION_WINDOWS["DEFAULT"])

    def validate_data(
        self,
        returns: np.ndarray,
        event_type: str = "DEFAULT",
        min_coverage: float = 0.7,
    ) -> bool:
        """Veri kalitesi kontrolü — yeterli veri var mı?"""
        expected_days = self.get_window_days(event_type)
        # Trading günleri ≈ calendar günleri * 5/7
        expected_trading = int(expected_days * 5 / 7)
        min_required = int(expected_trading * min_coverage)

        if len(returns) < min_required:
            logger.warning(
                "estimation_window_insufficient_data",
                event_type=event_type,
                expected=expected_trading,
                actual=len(returns),
                min_required=min_required,
            )
            return False
        return True

    def extract_window_data(
        self,
        returns: np.ndarray,
        dates: np.ndarray,
        event_date: datetime,
        event_type: str = "DEFAULT",
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Estimation window verisini çıkar.

        Args:
            returns: Tüm getiri serisi
            dates: Tarih dizisi
            event_date: Event tarihi
            event_type: Event tipi

        Returns:
            (window_returns, window_dates) tuple
        """
        start, end = self.get_window(event_date, event_type)

        # Tarih filtreleme
        mask = (dates >= start) & (dates <= end)
        window_returns = returns[mask]
        window_dates = dates[mask]

        if not self.validate_data(window_returns, event_type):
            logger.warning(
                "estimation_window_data_warning",
                event_type=event_type,
                data_points=len(window_returns),
            )

        return window_returns, window_dates
