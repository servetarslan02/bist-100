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

Thread-safety: _get_calendar() threading.Lock ile korunur.
"""

import threading
from datetime import datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# Event type → (başlangıç günü, bitiş günü) — TRADING DAY cinsinden
EVENT_WINDOWS: dict[str, tuple[int, int]] = {
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

# Varsayılan sabitler
DEFAULT_EVENT_TYPE: str = "DEFAULT"
ARRAY_DIM: int = 1
MIN_ARRAY_LENGTH: int = 1

# Thread-safe takvim cache
_calendar_cache: Any = None
_calendar_lock: threading.Lock = threading.Lock()


def _get_calendar() -> Any:
    """Trading calendar'ı lazy import et (thread-safe, double-checked locking).

    Returns:
        BISTTradingCalendar örneği
    """
    global _calendar_cache
    if _calendar_cache is None:
        with _calendar_lock:
            if _calendar_cache is None:
                from .trading_calendar import get_trading_calendar

                _calendar_cache = get_trading_calendar()
    return _calendar_cache


def _validate_datetime(value: datetime, name: str) -> None:
    """Datetime doğrulama.

    Args:
        value: Doğrulanacak değer
        name: Değer adı

    Raises:
        TypeError: datetime değilse
        ValueError: None ise
    """
    if value is None:
        logger.error("pencere_none_hatasi", deger_ad=name)
        raise ValueError(f"{name} None olamaz.")
    if not isinstance(value, datetime):
        logger.error("pencere_tip_hatasi", deger_ad=name, tip=type(value).__name__)
        raise TypeError(f"{name} datetime olmalı, gelen tip: {type(value).__name__}")


def _validate_array(arr: np.ndarray, name: str, min_len: int = MIN_ARRAY_LENGTH) -> None:
    """Array doğrulama — tip, boyut, boşluk, NaN/Inf kontrolü.

    Args:
        arr: Doğrulanacak array
        name: Array adı
        min_len: Minimum uzunluk

    Raises:
        TypeError: numpy array değilse
        ValueError: Boş, NaN/Inf içeriyorsa veya yanlış boyuttaysa
    """
    if not isinstance(arr, np.ndarray):
        logger.error("pencere_dizi_tip_hatasi", beklenti="np.ndarray", gercek=type(arr).__name__, dizi=name)
        raise TypeError(f"{name} numpy array olmalı, gelen tip: {type(arr).__name__}")

    if arr.ndim != ARRAY_DIM:
        logger.error("pencere_dizi_boyut_hatasi", beklenti=ARRAY_DIM, gercek=arr.ndim, dizi=name)
        raise ValueError(f"{name} tek boyutlu olmalı, gelen boyut: {arr.ndim}")

    if len(arr) < min_len:
        logger.error("pencere_dizi_bos", dizi=name, uzunluk=len(arr))
        raise ValueError(f"{name} boş olamaz (minimum {min_len} eleman gerekli).")

    # Tek traversal ile NaN ve Inf kontrolü (sadece numerik array'lerde)
    if np.issubdtype(arr.dtype, np.number) and not np.all(np.isfinite(arr)):
        has_nan = bool(np.any(np.isnan(arr)))
        has_inf = bool(np.any(np.isinf(arr)))
        logger.error("pencere_dizi_gecersiz_deger", dizi=name, nan_var=has_nan, inf_var=has_inf)
        raise ValueError(f"{name} dizisinde {'NaN' if has_nan else ''}{' ve ' if has_nan and has_inf else ''}{'Inf' if has_inf else ''} değeri var.")


class EventWindowManager:
    """Event window yönetimi — TRADING DAY bazlı pencereleme.

    v2.0: Artık tüm gün offset'leri trading day cinsinden hesaplanır.
    BIST takvimi (hafta sonları + resmi tatiller) otomatik uygulanır.
    """

    def get_window(self, event_type: str = DEFAULT_EVENT_TYPE) -> tuple[int, int]:
        """Event type'a göre event window döndür (trading day offset).

        Args:
            event_type: Event tipi

        Returns:
            (start_day, end_day) — event günü = 0, trading day cinsinden
        """
        result = EVENT_WINDOWS.get(event_type)
        if result is None:
            logger.warning("pencere_bilinmeyen_tip", event_type=event_type, varsayilan=DEFAULT_EVENT_TYPE)
            result = EVENT_WINDOWS[DEFAULT_EVENT_TYPE]
        return result

    def get_window_size(self, event_type: str = DEFAULT_EVENT_TYPE) -> int:
        """Event window boyutunu (trading day sayısı) döndür.

        Args:
            event_type: Event tipi

        Returns:
            Trading gün sayısı
        """
        start, end = self.get_window(event_type)
        return end - start + 1

    def get_window_dates(self, event_date: datetime, event_type: str = DEFAULT_EVENT_TYPE) -> tuple[datetime, datetime]:
        """Event window tarih aralığını döndür (TRADING DAY bazlı).

        Args:
            event_date: Event tarihi (t=0)
            event_type: Event tipi

        Returns:
            (start_date, end_date) tuple — calendar tarihleri

        Raises:
            TypeError: event_date datetime değilse
            ValueError: event_date None ise
        """
        _validate_datetime(event_date, "event_date")

        cal = _get_calendar()
        start_day, end_day = self.get_window(event_type)

        start_date = cal.trading_day_offset(event_date, start_day)
        end_date = cal.trading_day_offset(event_date, end_day)

        start_dt = start_date if isinstance(start_date, datetime) else datetime.combine(start_date, datetime.min.time())
        end_dt = end_date if isinstance(end_date, datetime) else datetime.combine(end_date, datetime.min.time())

        return (start_dt, end_dt)

    def extract_window_data(
        self,
        returns: np.ndarray,
        dates: np.ndarray,
        event_date: datetime,
        event_type: str = DEFAULT_EVENT_TYPE,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Event window verisini çıkar (TRADING DAY bazlı).

        Args:
            returns: Tüm getiri serisi (numpy array)
            dates: Tarih dizisi (numpy array)
            event_date: Event tarihi (t=0)
            event_type: Event tipi

        Returns:
            (window_returns, window_dates) tuple

        Raises:
            TypeError: returns/dates numpy array değilse veya event_date datetime değilse
            ValueError: Boş array, uzunluk uyuşmazlığı, NaN/Inf varsa
        """
        _validate_array(returns, "returns")
        _validate_array(dates, "dates")
        _validate_datetime(event_date, "event_date")

        if len(returns) != len(dates):
            logger.error(
                "pencere_cikarim_uzunluk_uyusmazligi",
                returns_uzunluk=len(returns),
                dates_uzunluk=len(dates),
            )
            raise ValueError(
                f"returns ve dates uzunlukları eşit olmalı: "
                f"returns={len(returns)}, dates={len(dates)}"
            )

        cal = _get_calendar()
        start_day, end_day = self.get_window(event_type)

        start_date = cal.trading_day_offset(event_date, start_day)
        end_date = cal.trading_day_offset(event_date, end_day)

        start_dt = start_date if isinstance(start_date, datetime) else datetime.combine(start_date, datetime.min.time())
        end_dt = end_date if isinstance(end_date, datetime) else datetime.combine(end_date, datetime.min.time())

        mask = (dates >= start_dt) & (dates <= end_dt)
        if not np.any(mask):
            logger.warning(
                "pencere_veri_bulunamadi",
                baslangic=start_dt.isoformat(),
                bitis=end_dt.isoformat(),
            )
            return np.array([], dtype=np.float64), np.array([], dtype="datetime64[ns]")

        window_returns = returns[mask]
        window_dates = dates[mask]

        # Sadece trading günleri filtrele
        trading_mask = np.array([cal.is_trading_day(d.date() if isinstance(d, datetime) else d) for d in window_dates])
        if not np.any(trading_mask):
            logger.warning("pencere_trading_gun_yok")
            return np.array([], dtype=np.float64), np.array([], dtype="datetime64[ns]")

        window_returns = window_returns[trading_mask]
        window_dates = window_dates[trading_mask]

        logger.debug(
            "pencere_cikarildi",
            event_tipi=event_type,
            event_tarihi=event_date.isoformat(),
            pencere_baslangic=start_date.isoformat(),
            pencere_bitis=end_date.isoformat(),
            veri_noktasi=len(window_returns),
            yontem="trading_gun",
        )

        return window_returns, window_dates

    def align_to_event_day(
        self,
        returns: np.ndarray,
        dates: np.ndarray,
        event_date: datetime,
        event_type: str = DEFAULT_EVENT_TYPE,
    ) -> dict[int, float]:
        """Event günlerine göre hizalanmış getiri sözlüğü döndür (TRADING DAY).

        Args:
            returns: Tüm getiri serisi (numpy array)
            dates: Tarih dizisi (numpy array)
            event_date: Event tarihi (t=0)
            event_type: Event tipi

        Returns:
            {trading_day_offset: return} sözlüğü

        Raises:
            TypeError: returns/dates numpy array değilse veya event_date datetime değilse
            ValueError: Boş array, uzunluk uyuşmazlığı, NaN/Inf varsa
        """
        _validate_array(returns, "returns")
        _validate_array(dates, "dates")
        _validate_datetime(event_date, "event_date")

        if len(returns) != len(dates):
            raise ValueError(
                f"returns ve dates uzunlukları eşit olmalı: "
                f"returns={len(returns)}, dates={len(dates)}"
            )

        cal = _get_calendar()
        start_day, end_day = self.get_window(event_type)

        # Tarih→indeks sözlüğü oluştur (O(1) arama için)
        date_to_idx: dict[Any, int] = {}
        for i, d in enumerate(dates):
            d_key = d.date() if isinstance(d, datetime) else d
            if d_key not in date_to_idx:
                date_to_idx[d_key] = i

        aligned: dict[int, float] = {}
        for offset in range(start_day, end_day + 1):
            target_date = cal.trading_day_offset(event_date, offset)
            idx = date_to_idx.get(target_date)
            if idx is not None:
                aligned[offset] = float(returns[idx])

        return aligned

    def get_sub_windows(self, event_type: str = DEFAULT_EVENT_TYPE) -> dict[str, tuple[int, int]]:
        """Alt pencereleri döndür (pre-event, event-day, post-event).

        Args:
            event_type: Event tipi

        Returns:
            {"pre": (start, -1), "event": (0, 0), "post": (1, end), "full": (start, end)}
        """
        start, end = self.get_window(event_type)
        return {
            "pre": (start, -1),
            "event": (0, 0),
            "post": (1, end),
            "full": (start, end),
        }

    def get_window_calendar_days(self, event_date: datetime, event_type: str = DEFAULT_EVENT_TYPE) -> int:
        """Event window'un takvim günleri cinsinden uzunluğunu döndür.

        Args:
            event_date: Event tarihi
            event_type: Event tipi

        Returns:
            Takvim gün sayısı

        Raises:
            TypeError: event_date datetime değilse
        """
        _validate_datetime(event_date, "event_date")
        cal = _get_calendar()
        start_day, end_day = self.get_window(event_type)
        start_date = cal.trading_day_offset(event_date, start_day)
        end_date = cal.trading_day_offset(event_date, end_day)
        return (end_date - start_date).days + 1
