"""ALPHA BIST — Event Window Manager (MacKinlay, 1997).

Event window, event etkisinin hisse fiyatına yansıdığı dönemdir.
Event type'a göre farklı pencere boyutları kullanılır.

Trading Day Düzeltmesi (v2.0):
═══════════════════════════════
MacKinlay (1997): "Event windows should be defined in trading days,
not calendar days, to avoid contamination from non-trading periods."

Calendar day kullanmanın sorunları:
1. Hafta sonları/tatiller window'u şişirir (5 günlük event = 7 calendar gün)
2. Estimation window'da boş günler OLS tahminini bozar
3. AR hesabında trading day olmayan günler = 0 → CAR bias'ı

Çözüm: Tüm offset'ler trading day cinsinden, BIST takvimi ile dönüştürülür.
"""
from datetime import datetime, timedelta
from typing import Tuple, List, Dict, Optional
import numpy as np
import structlog

logger = structlog.get_logger()

# Event type → (başlangıç günü, bitiş günü) — TRADING DAY cinsinden
# Not: Eski calendar day değerleri korundu, ama artık trading day olarak yorumlanır
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


def _get_calendar():
    """Trading calendar'ı lazy import et (circular dependency önleme)."""
    from .trading_calendar import get_trading_calendar
    return get_trading_calendar()


class EventWindowManager:
    """Event window yönetimi — TRADING DAY bazlı pencereleme.

    v2.0: Artık tüm gün offset'leri trading day cinsinden hesaplanır.
    BIST takvimi (hafta sonları + resmi tatiller) otomatik uygulanır.
    """

    def get_window(self, event_type: str = "DEFAULT") -> Tuple[int, int]:
        """Event type'a göre event window döndür (trading day offset).

        Returns:
            (start_day, end_day) — event günü = 0, trading day cinsinden
        """
        return EVENT_WINDOWS.get(event_type, EVENT_WINDOWS["DEFAULT"])

    def get_window_size(self, event_type: str = "DEFAULT") -> int:
        """Event window boyutunu (trading day sayısı) döndür."""
        start, end = self.get_window(event_type)
        return end - start + 1

    def get_window_dates(
        self, event_date: datetime, event_type: str = "DEFAULT"
    ) -> Tuple[datetime, datetime]:
        """Event window tarih aralığını döndür (TRADING DAY bazlı).

        Calendar day yerine BIST trading calendar kullanır.
        Hafta sonları ve tatiller otomatik atlanır.

        Args:
            event_date: Event tarihi (t=0)
            event_type: Event tipi

        Returns:
            (start_date, end_date) tuple — calendar tarihleri
        """
        cal = _get_calendar()
        start_day, end_day = self.get_window(event_type)

        start_date = cal.trading_day_offset(event_date, start_day)
        end_date = cal.trading_day_offset(event_date, end_day)

        return (
            datetime.combine(start_date, datetime.min.time()),
            datetime.combine(end_date, datetime.min.time()),
        )

    def extract_window_data(
        self,
        returns: np.ndarray,
        dates: np.ndarray,
        event_date: datetime,
        event_type: str = "DEFAULT",
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Event window verisini çıkar (TRADING DAY bazlı).

        Trading calendar kullanarak sadece iş günlerini seçer.
        Hafta sonu/tatil günlerindeki boşlukları otomatik atlar.

        Args:
            returns: Tüm getiri serisi
            dates: Tarih dizisi
            event_date: Event tarihi (t=0)
            event_type: Event tipi

        Returns:
            (window_returns, window_dates) tuple
        """
        cal = _get_calendar()
        start_day, end_day = self.get_window(event_type)

        # Trading day bazlı tarihleri hesapla
        start_date = cal.trading_day_offset(event_date, start_day)
        end_date = cal.trading_day_offset(event_date, end_day)

        # Takvim bazlı filtreleme (geniş aralık)
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.min.time())

        mask = (dates >= start_dt) & (dates <= end_dt)
        window_returns = returns[mask]
        window_dates = dates[mask]

        # Sadece trading günleri filtrele
        trading_mask = np.array([
            cal.is_trading_day(d.date() if isinstance(d, datetime) else d)
            for d in window_dates
        ])
        window_returns = window_returns[trading_mask]
        window_dates = window_dates[trading_mask]

        logger.debug(
            "event_window_extracted",
            event_type=event_type,
            event_date=event_date.isoformat() if isinstance(event_date, datetime) else str(event_date),
            window_start=start_date.isoformat(),
            window_end=end_date.isoformat(),
            data_points=len(window_returns),
            method="trading_day",
        )

        return window_returns, window_dates

    def align_to_event_day(
        self,
        returns: np.ndarray,
        dates: np.ndarray,
        event_date: datetime,
        event_type: str = "DEFAULT",
    ) -> Dict[int, float]:
        """Event günlerine göre hizalanmış getiri sözlüğü döndür (TRADING DAY).

        Calendar day offset yerine trading day offset kullanır.
        Örneğin: Cuma günkü event için t=-1 Perşembe, t=+1 Pazartesi olur
        (hafta sonu atlanır).

        Returns:
            {trading_day_offset: return} sözlüğü — örn: {-5: 0.01, -4: -0.02, ...}
        """
        cal = _get_calendar()
        start_day, end_day = self.get_window(event_type)

        # Trading day offset'leri hesapla
        aligned = {}
        for offset in range(start_day, end_day + 1):
            target_date = cal.trading_day_offset(event_date, offset)

            # Return serisinde bu tarihi bul
            for i, d in enumerate(dates):
                d_date = d.date() if isinstance(d, datetime) else d
                if d_date == target_date:
                    aligned[offset] = float(returns[i])
                    break

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

    def get_window_calendar_days(
        self, event_date: datetime, event_type: str = "DEFAULT"
    ) -> int:
        """Event window'un takvim günleri cinsinden uzunluğunu döndür.

        Trading day → calendar day dönüşümü (bilgi amaçlı).
        """
        cal = _get_calendar()
        start_day, end_day = self.get_window(event_type)
        start_date = cal.trading_day_offset(event_date, start_day)
        end_date = cal.trading_day_offset(event_date, end_day)
        return (end_date - start_date).days + 1
