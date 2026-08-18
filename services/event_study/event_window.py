"""ALPHA BIST — Event Window Manager (MacKinlay, 1997).

Event window, event etkisinin hisse fiyatına yansığı dönemdir.
Event type'a göre farklı pencere boyutları kullanılır.
"""
from datetime import datetime, timedelta
from typing import Tuple, List, Dict, Optional
import numpy as np
import structlog

logger = structlog.get_logger()

# Event type → (başlangıç günü, bitiş günü) (event günü = 0)
EVENT_WINDOWS = {
    "FINANCIAL_RESULTS": (-5, 5),
    "DIVIDEND": (-3, 3),
    "BUYBACK": (-3, 3),
    "CAPITAL_INCREASE": (-5, 5),
    "MERGER": (-10, 10),
    "MANAGEMENT_CHANGE": (-3, 3),
    "LEGAL": (-5, 5),
    "CONTRACT": (-3, 3),
    "GUIDANCE": (-3, 3),
    "TCMB_RATE": (-1, 3),
    "INFLATION": (-1, 3),
    "GDP": (-1, 3),
    "CPI": (-1, 3),
    "PPI": (-1, 3),
    "CURRENT_ACCOUNT": (-1, 3),
    "UNEMPLOYMENT": (-1, 2),
    "INDUSTRIAL_PRODUCTION": (-1, 2),
    "DEFAULT": (-5, 5),
}


class EventWindowManager:
    """Event window yönetimi — gün bazlı pencereleme."""

    def get_window(self, event_type: str = "DEFAULT") -> Tuple[int, int]:
        """Event type'a göre event window döndür.

        Returns:
            (start_day, end_day) — event günü = 0
        """
        return EVENT_WINDOWS.get(event_type, EVENT_WINDOWS["DEFAULT"])

    def get_window_size(self, event_type: str = "DEFAULT") -> int:
        """Event window boyutunu (gün sayısı) döndür."""
        start, end = self.get_window(event_type)
        return end - start + 1

    def get_window_dates(
        self, event_date: datetime, event_type: str = "DEFAULT"
    ) -> Tuple[datetime, datetime]:
        """Event window tarih aralığını döndür.

        Args:
            event_date: Event tarihi (t=0)
            event_type: Event tipi

        Returns:
            (start_date, end_date) tuple
        """
        start_day, end_day = self.get_window(event_type)
        start_date = event_date + timedelta(days=start_day)
        end_date = event_date + timedelta(days=end_day)
        return start_date, end_date

    def extract_window_data(
        self,
        returns: np.ndarray,
        dates: np.ndarray,
        event_date: datetime,
        event_type: str = "DEFAULT",
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Event window verisini çıkar.

        Args:
            returns: Tüm getiri serisi
            dates: Tarih dizisi
            event_date: Event tarihi (t=0)
            event_type: Event tipi

        Returns:
            (window_returns, window_dates) tuple
        """
        start_date, end_date = self.get_window_dates(event_date, event_type)

        mask = (dates >= start_date) & (dates <= end_date)
        window_returns = returns[mask]
        window_dates = dates[mask]

        logger.debug(
            "event_window_extracted",
            event_type=event_type,
            event_date=event_date.isoformat(),
            window_start=start_date.isoformat(),
            window_end=end_date.isoformat(),
            data_points=len(window_returns),
        )

        return window_returns, window_dates

    def align_to_event_day(
        self,
        returns: np.ndarray,
        dates: np.ndarray,
        event_date: datetime,
        event_type: str = "DEFAULT",
    ) -> Dict[int, float]:
        """Event günlerine göre hizalanmış getiri sözlüğü döndür.

        Returns:
            {day_offset: return} sözlüğü — örn: {-5: 0.01, -4: -0.02, ...}
        """
        window_returns, window_dates = self.extract_window_data(
            returns, dates, event_date, event_type
        )

        aligned = {}
        for ret, date in zip(window_returns, window_dates):
            day_offset = (date - event_date).days
            aligned[day_offset] = float(ret)

        return aligned

    def get_sub_windows(
        self, event_type: str = "DEFAULT"
    ) -> Dict[str, Tuple[int, int]]:
        """Alt pencereleri döndür (pre-event, event-day, post-event).

        Returns:
            {"pre": (start, -1), "event": (0, 0), "post": (1, end)}
        """
        start, end = self.get_window(event_type)
        return {
            "pre": (start, -1),
            "event": (0, 0),
            "post": (1, end),
            "full": (start, end),
        }
