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
from datetime import datetime, date, timedelta
from typing import List, Tuple, Optional, Set
import json
import os

import numpy as np
import structlog

logger = structlog.get_logger()

# BIST sabit tatiller (her yıl tekrar eden, tarihi değişmeyen)
_FIXED_HOLIDAYS_MD = [
    (1, 1),   # Yılbaşı
    (4, 23),  # Ulusal Egemenlik ve Çocuk Bayramı
    (5, 1),   # Emek ve Dayanışma Günü
    (5, 19),  # Atatürk'ü Anma, Gençlik ve Spor Bayramı
    (7, 15),  # Demokrasi ve Millî Birlik Günü
    (8, 30),  # Zafer Bayramı
    (10, 29), # Cumhuriyet Bayramı
]

# Ramazan Bayramı (3 gün) ve Kurban Bayramı (4 gün) — her yıl değişir
# Bunlar holidays.json'dan veya dinamik hesaplama ile gelir
_VARIABLE_HOLIDAY_SOURCES = ["holidays.json", "dynamic"]


class BISTTradingCalendar:
    """BIST iş günleri takvimi.

    Kullanım:
        cal = BISTTradingCalendar()
        cal.is_trading_day(datetime(2024, 1, 1))  # False (Yılbaşı)
        cal.add_trading_days(datetime(2024, 1, 5), 3)  # 3 iş günü ekle
        cal.get_trading_days_between(start, end)  # İş günleri listesi
    """

    def __init__(self, holidays_json_path: Optional[str] = None):
        self._fixed_holidays: Set[date] = set()
        self._variable_holidays: Set[date] = set()
        self._all_holidays: Set[date] = set()
        self._trading_days_cache: dict = {}

        # Sabit tatilleri yükle (tüm yıllar için)
        self._load_fixed_holidays(years=range(2015, 2030))

        # Değişken tatilleri yükle (holidays.json)
        if holidays_json_path is None:
            holidays_json_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "config", "holidays.json"
            )
        self._load_variable_holidays(holidays_json_path)

        # Tüm tatilleri birleştir
        self._all_holidays = self._fixed_holidays | self._variable_holidays

        logger.info(
            "trading_calendar_initialized",
            fixed_holidays=len(self._fixed_holidays),
            variable_holidays=len(self._variable_holidays),
            total_holidays=len(self._all_holidays),
        )

    def _load_fixed_holidays(self, years: range):
        """Sabit tatilleri tüm yıllar için yükle."""
        for year in years:
            for month, day in _FIXED_HOLIDAYS_MD:
                try:
                    self._fixed_holidays.add(date(year, month, day))
                except ValueError:
                    pass

    def _load_variable_holidays(self, path: str):
        """holidays.json'dan değişken tatilleri yükle."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for d in data.get("holidays", []):
                if isinstance(d, str):
                    self._variable_holidays.add(date.fromisoformat(d))
        except FileNotFoundError:
            logger.warning("holidays_json_not_found", path=path)
        except Exception as e:
            logger.warning("holidays_json_load_error", path=path, error=str(e))

    def is_holiday(self, d: date) -> bool:
        """Tatil günü mü?"""
        return d in self._all_holidays

    def is_weekend(self, d: date) -> bool:
        """Hafta sonu mu? (Cumartesi=5, Pazar=6)"""
        return d.weekday() >= 5

    def is_trading_day(self, d) -> bool:
        """İş günü mü? (hafta sonu ve tatil olmayan gün)"""
        if isinstance(d, datetime):
            d = d.date()
        return not self.is_weekend(d) and not self.is_holiday(d)

    def next_trading_day(self, d) -> date:
        """Bir sonraki iş günü."""
        if isinstance(d, datetime):
            d = d.date()
        d = d + timedelta(days=1)
        while not self.is_trading_day(d):
            d += timedelta(days=1)
        return d

    def previous_trading_day(self, d) -> date:
        """Bir önceki iş günü."""
        if isinstance(d, datetime):
            d = d.date()
        d = d - timedelta(days=1)
        while not self.is_trading_day(d):
            d -= timedelta(days=1)
        return d

    def add_trading_days(self, d, n: int) -> date:
        """n iş günü ekle/çıkar.

        Args:
            d: Başlangıç tarihi
            n: Eklenecek iş günü (negatif = geriye git)

        Returns:
            Hedef tarih
        """
        if isinstance(d, datetime):
            d = d.date()

        if n == 0:
            return d

        direction = 1 if n > 0 else -1
        remaining = abs(n)
        current = d

        while remaining > 0:
            current += timedelta(days=direction)
            if self.is_trading_day(current):
                remaining -= 1

        return current

    def get_trading_days_between(self, start, end) -> List[date]:
        """İki tarih arasındaki tüm iş günleri."""
        if isinstance(start, datetime):
            start = start.date()
        if isinstance(end, datetime):
            end = end.date()

        days = []
        current = start
        while current <= end:
            if self.is_trading_day(current):
                days.append(current)
            current += timedelta(days=1)
        return days

    def count_trading_days(self, start, end) -> int:
        """İki tarih arasındaki iş günü sayısı."""
        return len(self.get_trading_days_between(start, end))

    def trading_day_offset(self, event_date, offset: int) -> date:
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
        """
        if isinstance(event_date, datetime):
            event_date = event_date.date()

        # Event günü iş günü değilse, bir sonraki iş gününe kaydır
        if not self.is_trading_day(event_date):
            event_date = self.next_trading_day(event_date)

        return self.add_trading_days(event_date, offset)

    def get_event_window_dates(
        self,
        event_date,
        start_offset: int,
        end_offset: int,
    ) -> Tuple[date, date]:
        """Event window tarih aralığını trading day cinsinden hesapla.

        Args:
            event_date: Event tarihi (t=0)
            start_offset: Başlangıç offset'i (negatif, örn: -5)
            end_offset: Bitiş offset'i (pozitif, örn: +5)

        Returns:
            (start_date, end_date) tuple
        """
        start_date = self.trading_day_offset(event_date, start_offset)
        end_date = self.trading_day_offset(event_date, end_offset)
        return start_date, end_date

    def get_estimation_window_dates(
        self,
        event_date,
        estimation_days: int,
        gap_trading_days: int = 6,
    ) -> Tuple[date, date]:
        """Estimation window tarih aralığını trading day cinsinden hesapla.

        Look-ahead bias'ı önlemek için estimation window, event'ten
        gap_trading_days önce biter.

        Args:
            event_date: Event tarihi
            estimation_days: Estimation window uzunluğu (trading day)
            gap_trading_days: Event'ten önceki boşluk (trading day)

        Returns:
            (start_date, end_date) tuple
        """
        # Estimation window bitişi = event'ten gap gün önce
        end_date = self.trading_day_offset(event_date, -gap_trading_days)
        # Estimation window başlangıcı = bitişten estimation_days gün önce
        start_date = self.add_trading_days(end_date, -estimation_days)
        return start_date, end_date

    def align_returns_to_trading_days(
        self,
        returns,
        dates,
        event_date,
        start_offset: int,
        end_offset: int,
    ):
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
        """

        # Event günü iş günü değilse kaydır
        if isinstance(event_date, datetime):
            event_date_dt = event_date
            event_date_d = event_date.date()
        else:
            event_date_d = event_date
            event_date_dt = datetime.combine(event_date, datetime.min.time())

        if not self.is_trading_day(event_date_d):
            event_date_d = self.next_trading_day(event_date_d)
            event_date_dt = datetime.combine(event_date_d, datetime.min.time())

        # Trading day offset'leri hesapla
        target_offsets = list(range(start_offset, end_offset + 1))
        target_dates = [
            self.trading_day_offset(event_date_d, off) for off in target_offsets
        ]

        # Return serisinden eşleştir
        aligned_returns = []
        aligned_offsets = []

        dates_list = list(dates)
        for off, target_d in zip(target_offsets, target_dates):
            # Tarihi return serisinde bul
            for i, d in enumerate(dates_list):
                d_date = d.date() if isinstance(d, datetime) else d
                if d_date == target_d:
                    aligned_returns.append(float(returns[i]))
                    aligned_offsets.append(off)
                    break

        return np.array(aligned_returns), np.array(aligned_offsets)


# Global singleton
_trading_calendar = None


def get_trading_calendar() -> BISTTradingCalendar:
    """Global trading calendar instance."""
    global _trading_calendar
    if _trading_calendar is None:
        _trading_calendar = BISTTradingCalendar()
    return _trading_calendar
