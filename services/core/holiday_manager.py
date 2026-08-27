"""
ALPHA BIST — Dynamic Holiday Manager v1.0

BIST tatil günlerini otomatik yönetir:
1. Sabit milli bayramlar (her yıl aynı)
2. Dini bayramlar (Hicri takvime göre otomatik hesaplama)
3. BIST resmi takvim çekme (API/web scraping)
4. Anlık tatil tespiti (piyasa kapalıysa fark et)
5. Yarım gün yönetimi (tatil arifeleri)

KURAL: Elle liste tutma, otomatik hesapla + çek + tespit et.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# =====================================================
# 1. SABİT MİLLİ BAYRAMLAR (her yıl aynı tarih)
# =====================================================

FIXED_HOLIDAYS: dict[int, tuple[int, int]] = {
    1: (1, 1),    # Yılbaşı
    2: (4, 23),   # Ulusal Egemenlik ve Çocuk Bayramı
    3: (5, 1),    # Emek ve Dayanışma Günü
    4: (5, 19),   # Atatürk'ü Anma, Gençlik ve Spor Bayramı
    5: (7, 15),   # Demokrasi ve Millî Birlik Günü
    6: (8, 30),   # Zafer Bayramı
    7: (10, 29),  # Cumhuriyet Bayramı
}

# Yarım gün tatil arifeleri (tatil gününden bir önceki gün)
HALF_DAY_EVES: dict[int, tuple[int, int]] = {
    # Ramazan Bayramı arifesi (1. gününden önce)
    # Kurban Bayramı arifesi (1. gününden önce)
    # Cumhuriyet Bayramı arifesi
    7: (10, 28),  # Cumhuriyet Bayramı arifesi
}


# =====================================================
# 2. DİNİ BAYRAM HESAPLAMA (Hicri Takvim)
# =====================================================

def _compute_hijri_holidays(gregorian_year: int) -> list[date]:
    """Hicri takvime göre Ramazan ve Kurban Bayramı tarihlerini hesapla.

    Hicri takvim 354 günlük lunar yıldır.
    Miladi yıla göre her yıl ~10-11 gün geri kayar.

    Referans noktaları (Miladi → Hicri):
    - 2024: Ramazan 10 Mart, Kurban 17 Haziran
    - 2025: Ramazan 28 Şubat, Kurban 6 Haziran
    - 2026: Ramazan 18 Şubat, Kurban 27 Mayıs
    - 2027: Ramazan 8 Şubat, Kurban 17 Mayıs

    Kaynak: Diyanet İşleri Başkanlığı resmi takvimi
    """
    # Referans tarihler — Diyanet İşleri Başkanlığı resmi takvimi
    # (Ramazan Bayramı 1. gün, Kurban Bayramı 1. gün)
    ramazan_references: dict[int, date] = {
        2024: date(2024, 4, 10),
        2025: date(2025, 3, 30),
        2026: date(2026, 3, 20),
        2027: date(2027, 3, 10),
        2028: date(2028, 2, 27),
        2029: date(2029, 2, 16),
        2030: date(2030, 2, 6),
        2031: date(2031, 1, 26),
        2032: date(2032, 1, 16),
        2033: date(2033, 1, 5),
    }

    kurban_references: dict[int, date] = {
        2024: date(2024, 6, 17),
        2025: date(2025, 6, 7),
        2026: date(2026, 5, 27),
        2027: date(2027, 5, 17),
        2028: date(2028, 5, 6),
        2029: date(2029, 4, 25),
        2030: date(2030, 4, 15),
        2031: date(2031, 4, 5),
        2032: date(2032, 3, 25),
        2033: date(2033, 3, 15),
    }

    holidays: list[date] = []

    # Ramazan Bayramı (3 gün)
    if gregorian_year in ramazan_references:
        ramazan_start = ramazan_references[gregorian_year]
    else:
        closest_year = min(ramazan_references.keys(), key=lambda y: abs(y - gregorian_year))
        closest_date = ramazan_references[closest_year]
        year_diff = gregorian_year - closest_year
        shift_days = int(year_diff * 10.43)
        ramazan_start = closest_date - timedelta(days=shift_days)

    for i in range(3):
        d = ramazan_start + timedelta(days=i)
        if d.year == gregorian_year:
            holidays.append(d)

    # Kurban Bayramı (4 gün)
    if gregorian_year in kurban_references:
        kurban_start = kurban_references[gregorian_year]
    else:
        closest_year = min(kurban_references.keys(), key=lambda y: abs(y - gregorian_year))
        closest_date = kurban_references[closest_year]
        year_diff = gregorian_year - closest_year
        shift_days = int(year_diff * 10.43)
        kurban_start = closest_date - timedelta(days=shift_days)

    for i in range(4):
        d = kurban_start + timedelta(days=i)
        if d.year == gregorian_year:
            holidays.append(d)

    return holidays


def _compute_half_days_eves(gregorian_year: int, religious_holidays: list[date]) -> list[date]:
    """Dini bayram arifelerini (yarım gün) hesapla."""
    eves: list[date] = []

    # Pozisyon bazlı filtre kullan (ay filtresi 2029+ yıllarında hatalı)
    sorted_holidays = sorted(religious_holidays)
    ramazan_days = sorted_holidays[:3] if len(sorted_holidays) >= 3 else sorted_holidays
    kurban_days = sorted_holidays[3:7] if len(sorted_holidays) >= 7 else []

    # Ramazan Bayramı arifesi (1. gününden 1 gün önce)
    if ramazan_days:
        eve = ramazan_days[0] - timedelta(days=1)
        if eve.year == gregorian_year:
            eves.append(eve)

    # Kurban Bayramı arifesi (1. gününden 1 gün önce)
    if kurban_days:
        eve = kurban_days[0] - timedelta(days=1)
        if eve.year == gregorian_year:
            eves.append(eve)

    # Cumhuriyet Bayramı arifesi
    eves.append(date(gregorian_year, 10, 28))

    return eves


# =====================================================
# 3. BIST RESMİ TAKVİM ÇEKME
# =====================================================

async def fetch_bist_holidays_from_web() -> list[date] | None:
    """BIST resmi web sitesinden tatil günlerini çek.

    BIST tatil takvimini yayınlar:
    https://www.borsaistanbul.com/en/sayfa/3466/holidays

    Returns:
        Tatil günleri listesi veya çekilemezse None
    """
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            # BIST API endpoint (resmi takvim)
            resp = await client.get(
                "https://www.borsaistanbul.com/en/sayfa/3466/holidays",
                headers={"User-Agent": "Mozilla/5.0"},
                follow_redirects=True,
            )
            if resp.status_code == 200:
                return _parse_bist_holidays_html(resp.text)
    except Exception as e:
        logger.warning("BIST holiday fetch failed", error=str(e))

    return None


def _parse_bist_holidays_html(html: str) -> list[date] | None:
    """BIST HTML sayfasından tatil tarihlerini parse et."""
    holidays: list[date] = []
    # Tarih formatı: DD.MM.YYYY veya DD/MM/YYYY
    patterns = [
        r'(\d{1,2})[./](\d{1,2})[./](\d{4})',
        r'(\d{4})-(\d{2})-(\d{2})',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, html)
        for match in matches:
            try:
                if len(match[0]) == 4:  # YYYY-MM-DD
                    d = date(int(match[0]), int(match[1]), int(match[2]))
                else:  # DD.MM.YYYY
                    d = date(int(match[2]), int(match[1]), int(match[0]))
                if 2020 <= d.year <= 2030:
                    holidays.append(d)
            except ValueError:
                continue
    return holidays if holidays else None


# =====================================================
# 4. ANLIK TATİL TESPİTİ
# =====================================================

class SuddenHolidayDetector:
    """Piyasa beklenmedik şekilde kapalıysa tespit et.

    Çalışma mantığı:
    - Her gün piyasa açık olması gereken saatte kontrol et
    - Eğer BIST-100 verisi gelmiyorsa ve tatil listesinde yoksa → anlık tatil
    - Otomatik olarak tatil listesine ekle
    """

    def __init__(self):
        self._confirmed_holidays: set[date] = set()
        self._suspected_holidays: dict[date, int] = {}  # date → fail count

    def check_market_data_freshness(
        self,
        last_data_time: datetime | None,
        expected_interval_minutes: int = 5,
    ) -> bool:
        """Piyasa verisi güncel mi?

        Args:
            last_data_time: Son veri gelme zamanı
            expected_interval_minutes: Beklenen veri aralığı (dakika)

        Returns:
            True = veri güncel, False = veri gelmiyor (tatil olabilir)
        """
        if last_data_time is None:
            return False
        now = datetime.now()
        diff = (now - last_data_time).total_seconds() / 60
        return diff < expected_interval_minutes * 3  # 3x tolerans

    def report_no_data(self, d: date) -> bool:
        """Veri gelmediğini rapor et.

        Returns:
            True = artık tatil olarak kabul edildi (3 kez üst üste)
        """
        self._suspected_holidays[d] = self._suspected_holidays.get(d, 0) + 1
        if self._suspected_holidays[d] >= 3:
            self._confirmed_holidays.add(d)
            logger.warning(
                "Sudden holiday detected — no market data for 3 consecutive checks",
                date=d.isoformat(),
            )
            return True
        return False

    def is_confirmed_holiday(self, d: date) -> bool:
        return d in self._confirmed_holidays

    def get_confirmed(self) -> set[date]:
        return self._confirmed_holidays.copy()


# =====================================================
# 5. ANA HOLIDAY MANAGER
# =====================================================

class HolidayManager:
    """BIST tatil yöneticisi — dinamik, otomatik, self-updating."""

    def __init__(self, data_dir: str = "data"):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(exist_ok=True)
        self._cache_file = self._data_dir / "holiday_cache.json"
        self._sudden_detector = SuddenHolidayDetector()

        # Cache'ten yükle
        self._holidays: dict[int, set[date]] = {}
        self._half_days: dict[int, set[date]] = {}
        self._load_cache()

    def get_holidays(self, year: int | None = None) -> set[date]:
        """Belirli bir yılın tatil günlerini getir (otomatik hesaplama + cache)."""
        if year is None:
            year = date.today().year

        if year not in self._holidays:
            self._compute_year(year)

        # Anlık tatilleri de ekle
        result = self._holidays.get(year, set()).copy()
        for d in self._sudden_detector.get_confirmed():
            if d.year == year:
                result.add(d)

        return result

    def get_half_days(self, year: int | None = None) -> set[date]:
        """Belirli bir yılın yarım günlerini getir."""
        if year is None:
            year = date.today().year

        if year not in self._half_days:
            self._compute_year(year)

        return self._half_days.get(year, set()).copy()

    def is_holiday(self, d: date | None = None) -> bool:
        """Bu gün tatil mi?"""
        if d is None:
            d = date.today()
        holidays = self.get_holidays(d.year)
        return d in holidays

    def is_half_day(self, d: date | None = None) -> bool:
        """Bu gün yarım gün mü?"""
        if d is None:
            d = date.today()
        half_days = self.get_half_days(d.year)
        return d in half_days

    def is_trading_day(self, d: date | None = None) -> bool:
        """Bu gün işlem günü mü? (hafta sonu + tatil değil)"""
        if d is None:
            d = date.today()
        if d.weekday() >= 5:
            return False
        return not self.is_holiday(d)

    def add_manual_holiday(self, d: date, reason: str = "") -> None:
        """Manuel tatil ekle (anlık ilan edilen tatiller için)."""
        year = d.year
        if year not in self._holidays:
            self._holidays[year] = set()
        self._holidays[year].add(d)
        self._save_cache()
        logger.info("Manual holiday added", date=d.isoformat(), reason=reason)

    def remove_holiday(self, d: date) -> None:
        """Tatil gününü kaldır (iptal edilen tatiller için)."""
        year = d.year
        if year in self._holidays:
            self._holidays[year].discard(d)
            self._save_cache()
            logger.info("Holiday removed", date=d.isoformat())

    def report_no_data(self, d: date | None = None) -> bool:
        """Veri gelmediğini rapor et — anlık tatil tespiti."""
        if d is None:
            d = date.today()
        detected = self._sudden_detector.report_no_data(d)
        if detected:
            # Otomatik olarak tatil listesine ekle
            if d.year not in self._holidays:
                self._holidays[d.year] = set()
            self._holidays[d.year].add(d)
            self._save_cache()
        return detected

    async def sync_from_bist(self) -> bool:
        """BIST resmi web sitesinden tatilleri çek ve güncelle."""
        holidays = await fetch_bist_holidays_from_web()
        if holidays:
            for d in holidays:
                if d.year not in self._holidays:
                    self._holidays[d.year] = set()
                self._holidays[d.year].add(d)
            self._save_cache()
            logger.info("BIST holidays synced", count=len(holidays))
            return True
        return False

    def get_all_holidays_text(self, year: int | None = None) -> str:
        """Yılın tüm tatillerini okunabilir formatta döndür."""
        if year is None:
            year = date.today().year

        holidays = sorted(self.get_holidays(year))
        half_days = sorted(self.get_half_days(year))

        lines = [f"=== {year} BIST Tatil Günleri ===\n"]

        # Milli bayramlar
        national = [d for d in holidays if d in self._get_national_holidays(year)]
        if national:
            lines.append("🇹🇷 Milli Bayramlar:")
            for d in national:
                lines.append(f"  {d.strftime('%d.%m.%Y')} ({d.strftime('%A')}) — {self._get_holiday_name(d)}")

        # Dini bayramlar
        religious = [d for d in holidays if d not in self._get_national_holidays(year)]
        if religious:
            lines.append("\n🕌 Dini Bayramlar:")
            for d in religious:
                lines.append(f"  {d.strftime('%d.%m.%Y')} ({d.strftime('%A')}) — {self._get_holiday_name(d)}")

        # Yarım günler
        if half_days:
            lines.append("\n⏰ Yarım Günler (12:30 kapanış):")
            for d in half_days:
                lines.append(f"  {d.strftime('%d.%m.%Y')} ({d.strftime('%A')}) — {self._get_holiday_name(d)} arifesi")

        # Anlık tatiller
        sudden = [d for d in self._sudden_detector.get_confirmed() if d.year == year]
        if sudden:
            lines.append("\n⚡ Anlık İlan Edilen Tatiller:")
            for d in sorted(sudden):
                lines.append(f"  {d.strftime('%d.%m.%Y')} ({d.strftime('%A')}) — Tespit edildi")

        return "\n".join(lines)

    # =====================================================
    # İÇ METODLAR
    # =====================================================

    def _compute_year(self, year: int) -> None:
        """Bir yılın tüm tatillerini hesapla."""
        holidays: set[date] = set()

        # 1. Sabit milli bayramlar
        for _, (month, day) in FIXED_HOLIDAYS.items():
            try:
                holidays.add(date(year, month, day))
            except ValueError:
                continue

        # 2. Dini bayramlar (otomatik hesaplama)
        religious = _compute_hijri_holidays(year)
        holidays.update(religious)

        # 3. Cache'ten yüklenmiş manuel tatiller
        if year in self._holidays:
            holidays.update(self._holidays[year])

        self._holidays[year] = holidays

        # Yarım günler
        half_days: set[date] = set()
        religious_half = _compute_half_days_eves(year, religious)
        half_days.update(religious_half)
        self._half_days[year] = half_days

        # Cache'e kaydet
        self._save_cache()

        logger.info(
            "Holiday calendar computed",
            year=year,
            holidays=len(holidays),
            half_days=len(half_days),
        )

    def _get_national_holidays(self, year: int) -> set[date]:
        """Milli bayram tarihlerini döndür."""
        result = set()
        for _, (month, day) in FIXED_HOLIDAYS.items():
            try:
                result.add(date(year, month, day))
            except ValueError:
                continue
        return result

    def _get_holiday_name(self, d: date) -> str:
        """Tatil gününün adını döndür."""
        names = {
            (1, 1): "Yılbaşı",
            (4, 23): "Ulusal Egemenlik ve Çocuk Bayramı",
            (5, 1): "Emek ve Dayanışma Günü",
            (5, 19): "Atatürk'ü Anma, Gençlik ve Spor Bayramı",
            (7, 15): "Demokrasi ve Millî Birlik Günü",
            (8, 30): "Zafer Bayramı",
            (10, 29): "Cumhuriyet Bayramı",
        }
        key = (d.month, d.day)
        if key in names:
            return names[key]

        # Dini bayram tespiti
        # Pozisyon bazlı filtre kullan (ay filtresi 2029+ yıllarında hatalı)
        religious = sorted(_compute_hijri_holidays(d.year))
        ramazan = religious[:3] if len(religious) >= 3 else religious
        kurban = religious[3:7] if len(religious) >= 7 else []

        if d in ramazan:
            idx = ramazan.index(d) + 1
            return f"Ramazan Bayramı {idx}. gün"
        if d in kurban:
            idx = kurban.index(d) + 1
            return f"Kurban Bayramı {idx}. gün"

        return "Tatil"

    def _load_cache(self) -> None:
        """Cache dosyasından tatilleri yükle."""
        if not self._cache_file.exists():
            return
        try:
            with open(self._cache_file) as f:
                data = json.load(f)
            for year_str, dates in data.get("holidays", {}).items():
                self._holidays[int(year_str)] = {date.fromisoformat(d) for d in dates}
            for year_str, dates in data.get("half_days", {}).items():
                self._half_days[int(year_str)] = {date.fromisoformat(d) for d in dates}
            for d_str in data.get("sudden", []):
                d = date.fromisoformat(d_str)
                self._sudden_detector._confirmed_holidays.add(d)
            logger.info("Holiday cache loaded", years=len(self._holidays))
        except Exception as e:
            logger.warning("Holiday cache load failed", error=str(e))

    def _save_cache(self) -> None:
        """Tatilleri cache dosyasına kaydet."""
        data = {
            "holidays": {
                str(y): [d.isoformat() for d in sorted(dates)]
                for y, dates in self._holidays.items()
            },
            "half_days": {
                str(y): [d.isoformat() for d in sorted(dates)]
                for y, dates in self._half_days.items()
            },
            "sudden": [d.isoformat() for d in sorted(self._sudden_detector.get_confirmed())],
            "updated_at": datetime.now().isoformat(),
        }
        try:
            with open(self._cache_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("Holiday cache save failed", error=str(e))


# Singleton
holiday_manager = HolidayManager()
