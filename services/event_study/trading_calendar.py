"""ALPHA BIST — Trading Calendar (BIST İş Günleri Takvimi).

Event study'de calendar day yerine trading day kullanmak kritiktir çünkü:
1. Hafta sonları ve tatiller fiyat oluşumu yoktur → event window şişer
2. Estimation window'da boş günler OLS tahminini bozar
3. CAR hesabında trading day olmayan günler AR=0 olarak eklenir → bias

MacKinlay (1997): "Event windows should be defined in trading days,
not calendar days, to avoid contamination from non-trading periods."

Bu modül:
- BIST resmi tatillerini yönetir (Ramazan/Kurban Bayramı, Cumhuriyet Bayramı vb.)
- Hafta sonlarını otomatik hariç tutar
- Calendar ↔ Trading day dönüşümü yapar
- Event window ve estimation window'ları trading day cinsinden hesaplar
"""

import os
import threading
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import orjson
import structlog

logger = structlog.get_logger()

# --- Sabitler ---
YEAR_RANGE_START: int = 2015
YEAR_RANGE_END: int = 2030
DEFAULT_GAP_TRADING_DAYS: int = 6
MAX_TRADING_DAY_ITERATIONS: int = 5000  # Sonsuz döngü koruması

# BIST sabit tatiller (her yıl tekrar eden, tarihi değişmeyen)
_FIXED_HOLIDAYS_MD: list[tuple[int, int]] = [
    (1, 1),  # Yılbaşı
    (4, 23),  # Ulusal Egemenlik ve Çocuk Bayramı
    (5, 1),  # Emek ve Dayanışma Günü
    (5, 19),  # Atatürk'ü Anma, Gençlik ve Spor Bayramı
    (7, 15),  # Demokrasi ve Millî Birlik Günü
    (8, 30),  # Zafer Bayramı
    (10, 29),  # Cumhuriyet Bayramı
]

# Ramazan Bayramı (3 gün) ve Kurban Bayramı (4 gün) — her yıl değişir
# Bunlar holidays.json'dan veya dinamik hesaplama ile gelir
_VARIABLE_HOLIDAY_SOURCES: list[str] = ["holidays.json", "dynamic"]


def _validate_date_param(d: Any, name: str) -> date:
    """Tarih parametresi doğrulama (datetime → date dönüşümü dahil).

    Args:
        d: Kontrol edilecek tarih
        name: Parametre adı

    Returns:
        Doğrulanmış date objesi

    Raises:
        TypeError: date veya datetime değilse
    """
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    raise TypeError(f"{name} date veya datetime olmalı, alınan: {type(d).__name__}")


def _validate_int(value: Any, name: str) -> int:
    """Integer doğrulama.

    Args:
        value: Kontrol edilecek değer
        name: Parametre adı

    Returns:
        Doğrulanmış integer

    Raises:
        TypeError: Integer değilse
    """
    if isinstance(value, (int, np.integer)):
        return int(value)
    raise TypeError(f"{name} tamsayı olmalı, alınan: {type(value).__name__}")


class BISTTradingCalendar:
    """BIST iş günleri takvimi.

    Kullanım:
        cal = BISTTradingCalendar()
        cal.is_trading_day(datetime(2024, 1, 1))  # False (Yılbaşı)
        cal.add_trading_days(datetime(2024, 1, 5), 3)  # 3 iş günü ekle
        cal.get_trading_days_between(start, end)  # İş günleri listesi
    """

    def __init__(self, holidays_json_path: str | None = None) -> None:
        """BIST trading calendar başlat.

        Args:
            holidays_json_path: holidays.json dosya yolu (None ise varsayılan yol)

        Raises:
            FileNotFoundError: holidays.json bulunamazsa (opsiyonel, warning log)
        """
        self._fixed_holidays: set[date] = set()
        self._variable_holidays: set[date] = set()
        self._all_holidays: set[date] = set()
        self._trading_days_cache: dict[tuple[date, date], list[date]] = {}

        # Sabit tatilleri yükle (tüm yıllar için)
        self._load_fixed_holidays(years=range(YEAR_RANGE_START, YEAR_RANGE_END))

        # Değişken tatilleri yükle (holidays.json)
        if holidays_json_path is None:
            holidays_json_path = os.path.join(os.path.dirname(__file__), "..", "..", "config", "holidays.json")
        self._load_variable_holidays(holidays_json_path)

        # Tüm tatilleri birleştir
        self._all_holidays = self._fixed_holidays | self._variable_holidays

        logger.debug(
            "takvim_baslatildi",
            sabit_tatil=len(self._fixed_holidays),
            degisken_tatil=len(self._variable_holidays),
            toplam_tatil=len(self._all_holidays),
        )

    def _load_fixed_holidays(self, years: range) -> None:
        """Sabit tatilleri tüm yıllar için yükle.

        Args:
            years: Yıl aralığı
        """
        for year in years:
            for month, day in _FIXED_HOLIDAYS_MD:
                try:
                    self._fixed_holidays.add(date(year, month, day))
                except ValueError as exc:
                    logger.warning(
                        "sabit_tatil_hatasi",
                        year=year,
                        month=month,
                        day=day,
                        hata=str(exc),
                    )

    def _load_variable_holidays(self, path: str) -> None:
        """holidays.json'dan değişken tatilleri yükle.

        Args:
            path: JSON dosya yolu
        """
        try:
            with open(path, encoding="utf-8") as f:
                data = orjson.loads(f.read())
            for d in data.get("holidays", []):
                if isinstance(d, str):
                    self._variable_holidays.add(date.fromisoformat(d))
        except FileNotFoundError:
            logger.warning("degisken_tatil_dosya_bulunamadi", path=path)
        except orjson.JSONDecodeError as exc:
            logger.warning("degisken_tatil_json_hatasi", path=path, hata=str(exc))
        except ValueError as exc:
            logger.warning("degisken_tatil_tarih_hatasi", path=path, hata=str(exc))

    def is_holiday(self, d: date) -> bool:
        """Tatil günü mü?

        Args:
            d: Kontrol edilecek tarih

        Returns:
            Tatil ise True

        Raises:
            TypeError: date değilse
        """
        if not isinstance(d, date):
            raise TypeError(f"d date olmalı, alınan: {type(d).__name__}")
        return d in self._all_holidays

    def is_weekend(self, d: date) -> bool:
        """Hafta sonu mu? (Cumartesi=5, Pazar=6)

        Args:
            d: Kontrol edilecek tarih

        Returns:
            Hafta sonu ise True

        Raises:
            TypeError: date değilse
        """
        if not isinstance(d, date):
            raise TypeError(f"d date olmalı, alınan: {type(d).__name__}")
        return d.weekday() >= 5

    def is_trading_day(self, d: Any) -> bool:
        """İş günü mü? (hafta sonu ve tatil olmayan gün)

        Args:
            d: Kontrol edilecek tarih (date veya datetime)

        Returns:
            İş günü ise True

        Raises:
            TypeError: date veya datetime değilse
        """
        d = _validate_date_param(d, "d")
        return not self.is_weekend(d) and not self.is_holiday(d)

    def next_trading_day(self, d: Any) -> date:
        """Bir sonraki iş günü.

        Args:
            d: Başlangıç tarihi (date veya datetime)

        Returns:
            Bir sonraki iş günü

        Raises:
            TypeError: date veya datetime değilse
            RuntimeError: Maksimum iterasyon sayısına ulaşıldıysa
        """
        d = _validate_date_param(d, "d")
        d = d + timedelta(days=1)
        iterations = 0
        while not self.is_trading_day(d):
            d += timedelta(days=1)
            iterations += 1
            if iterations >= MAX_TRADING_DAY_ITERATIONS:
                raise RuntimeError(
                    f"Bir sonraki iş günü bulunamadı ({MAX_TRADING_DAY_ITERATIONS} gün denendi)"
                )
        return d

    def previous_trading_day(self, d: Any) -> date:
        """Bir önceki iş günü.

        Args:
            d: Başlangıç tarihi (date veya datetime)

        Returns:
            Bir önceki iş günü

        Raises:
            TypeError: date veya datetime değilse
            RuntimeError: Maksimum iterasyon sayısına ulaşıldıysa
        """
        d = _validate_date_param(d, "d")
        d = d - timedelta(days=1)
        iterations = 0
        while not self.is_trading_day(d):
            d -= timedelta(days=1)
            iterations += 1
            if iterations >= MAX_TRADING_DAY_ITERATIONS:
                raise RuntimeError(
                    f"Bir önceki iş günü bulunamadı ({MAX_TRADING_DAY_ITERATIONS} gün denendi)"
                )
        return d

    def add_trading_days(self, d: Any, n: int) -> date:
        """n iş günü ekle/çıkar.

        Args:
            d: Başlangıç tarihi (date veya datetime)
            n: Eklenecek iş günü (negatif = geriye git)

        Returns:
            Hedef tarih

        Raises:
            TypeError: Parametre tipleri uygun değilse
            RuntimeError: Maksimum iterasyon sayısına ulaşıldıysa
        """
        d = _validate_date_param(d, "d")
        n = _validate_int(n, "n")

        if n == 0:
            return d

        direction = 1 if n > 0 else -1
        remaining = abs(n)
        current = d
        iterations = 0

        while remaining > 0:
            current += timedelta(days=direction)
            if self.is_trading_day(current):
                remaining -= 1
            iterations += 1
            if iterations >= MAX_TRADING_DAY_ITERATIONS:
                raise RuntimeError(
                    f"add_trading_days: {abs(n)} iş günü eklenemedi ({MAX_TRADING_DAY_ITERATIONS} gün denendi)"
                )

        return current

    def get_trading_days_between(self, start: Any, end: Any) -> list[date]:
        """İki tarih arasındaki tüm iş günleri.

        Args:
            start: Başlangıç tarihi (date veya datetime)
            end: Bitiş tarihi (date veya datetime)

        Returns:
            İş günleri listesi

        Raises:
            TypeError: Parametre tipleri uygun değilse
        """
        start = _validate_date_param(start, "start")
        end = _validate_date_param(end, "end")

        if start > end:
            logger.warning(
                "takvim_start_end_ters",
                start=start.isoformat(),
                end=end.isoformat(),
            )
            return []

        days: list[date] = []
        current = start
        while current <= end:
            if self.is_trading_day(current):
                days.append(current)
            current += timedelta(days=1)
        return days

    def count_trading_days(self, start: Any, end: Any) -> int:
        """İki tarih arasındaki iş günü sayısı.

        Args:
            start: Başlangıç tarihi
            end: Bitiş tarihi

        Returns:
            İş günü sayısı
        """
        return len(self.get_trading_days_between(start, end))

    def trading_day_offset(self, event_date: Any, offset: int) -> date:
        """Event offset'ini (trading day cinsinden) takvime çevir.

        Event study'de offset:
            -5 = event'ten 5 trading day önce
             0 = event günü (eğer iş günü değilse bir sonraki iş günü)
            +3 = event'ten 3 trading day sonra

        Args:
            event_date: Event tarihi (t=0)
            offset: Trading day offset (negatif = önce, pozitif = sonra)

        Returns:
            Takvim tarihi

        Raises:
            TypeError: Parametre tipleri uygun değilse
        """
        event_date = _validate_date_param(event_date, "event_date")
        offset = _validate_int(offset, "offset")

        # Event günü iş günü değilse, bir sonraki iş gününe kaydır
        if not self.is_trading_day(event_date):
            event_date = self.next_trading_day(event_date)

        return self.add_trading_days(event_date, offset)

    def get_event_window_dates(
        self,
        event_date: Any,
        start_offset: int,
        end_offset: int,
    ) -> tuple[date, date]:
        """Event window tarih aralığını trading day cinsinden hesapla.

        Args:
            event_date: Event tarihi (t=0)
            start_offset: Başlangıç offset'i (negatif, örn: -5)
            end_offset: Bitiş offset'i (pozitif, örn: +5)

        Returns:
            (start_date, end_date) tuple

        Raises:
            TypeError: Parametre tipleri uygun değilse
        """
        start_date = self.trading_day_offset(event_date, start_offset)
        end_date = self.trading_day_offset(event_date, end_offset)
        return start_date, end_date

    def get_estimation_window_dates(
        self,
        event_date: Any,
        estimation_days: int,
        gap_trading_days: int = DEFAULT_GAP_TRADING_DAYS,
    ) -> tuple[date, date]:
        """Estimation window tarih aralığını trading day cinsinden hesapla.

        Look-ahead bias'ı önlemek için estimation window, event'ten
        gap_trading_days önce biter.

        Args:
            event_date: Event tarihi
            estimation_days: Estimation window uzunluğu (trading day)
            gap_trading_days: Event'ten önceki boşluk (trading day)

        Returns:
            (start_date, end_date) tuple

        Raises:
            TypeError: Parametre tipleri uygun değilse
        """
        # Estimation window bitişi = event'ten gap gün önce
        end_date = self.trading_day_offset(event_date, -gap_trading_days)
        # Estimation window başlangıcı = bitişten estimation_days gün önce
        start_date = self.add_trading_days(end_date, -estimation_days)
        return start_date, end_date

    def align_returns_to_trading_days(
        self,
        returns: np.ndarray,
        dates: np.ndarray,
        event_date: Any,
        start_offset: int,
        end_offset: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return serisini trading day offset'lerine hizala.

        Calendar day yerine trading day kullanarak event window'u çıkarır.
        Bu, hafta sonu/tatil günlerindeki boşlukları ortadan kaldırır.

        Args:
            returns: Getiri serisi (numpy array)
            dates: Tarih dizisi (numpy array of datetime/date)
            event_date: Event tarihi
            start_offset: Başlangıç offset'i
            end_offset: Bitiş offset'i

        Returns:
            (aligned_returns, aligned_offsets) — offset'ler trading day cinsinden

        Raises:
            TypeError: Parametre tipleri uygun değilse
            ValueError: Array'ler boş ise
        """
        if isinstance(returns, (list, tuple)):
            returns = np.asarray(returns, dtype=float)
        if not isinstance(returns, np.ndarray):
            raise TypeError(f"returns numpy.ndarray olmalı, alınan: {type(returns).__name__}")
        if returns.size == 0:
            raise ValueError("returns boş olamaz")

        if isinstance(dates, (list, tuple)):
            dates = np.asarray(dates)
        if not isinstance(dates, np.ndarray):
            raise TypeError(f"dates numpy.ndarray olmalı, alınan: {type(dates).__name__}")
        if dates.size == 0:
            raise ValueError("dates boş olamaz")

        event_date_d = _validate_date_param(event_date, "event_date")

        # Event günü iş günü değilse kaydır
        if not self.is_trading_day(event_date_d):
            event_date_d = self.next_trading_day(event_date_d)

        # Trading day offset'leri hesapla
        target_offsets = list(range(start_offset, end_offset + 1))
        target_dates = [self.trading_day_offset(event_date_d, off) for off in target_offsets]

        # Return serisinden eşleştir
        aligned_returns: list[float] = []
        aligned_offsets: list[int] = []

        dates_list = list(dates)
        for off, target_d in zip(target_offsets, target_dates, strict=False):
            for i, d in enumerate(dates_list):
                d_date = d.date() if isinstance(d, datetime) else d
                if d_date == target_d:
                    aligned_returns.append(float(returns[i]))
                    aligned_offsets.append(off)
                    break

        return np.array(aligned_returns), np.array(aligned_offsets)


# Global singleton (thread-safe)
_trading_calendar: BISTTradingCalendar | None = None
_calendar_lock = threading.Lock()


def get_trading_calendar() -> BISTTradingCalendar:
    """Global trading calendar instance (thread-safe singleton).

    Returns:
        BISTTradingCalendar singleton instance
    """
    global _trading_calendar
    if _trading_calendar is None:
        with _calendar_lock:
            if _trading_calendar is None:
                _trading_calendar = BISTTradingCalendar()
    return _trading_calendar
