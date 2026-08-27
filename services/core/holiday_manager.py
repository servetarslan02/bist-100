"""
ALPHA BIST — Dynamic Holiday Manager v2.0

BIST tatil günlerini otomatik yönetir:
1. Sabit milli bayramlar (her yıl aynı)
2. Dini bayramlar (Hicri takvime göre otomatik hesaplama)
3. BIST resmi takvim çekme (API/web scraping) + retry + alternatif kaynaklar
4. KAP RSS izleme (anlık tatil duyuruları)
5. Anlık tatil tespiti (piyasa kapalıysa fark et)
6. Yarım gün yönetimi (tatil arifeleri)
7. Proxy desteği (BIST engelli bölgeler için)

v2.0 DEĞİŞİKLİKLERİ:
- Retry mekanizması (3 deneme, exponential backoff)
- Alternatif kaynaklar: KAP RSS, Investing.com, Google cache
- Proxy desteği (HTTP_PROXY / HTTPS_PROXY)
- KAP anlık duyuru izleme (tatil anahtar kelime taraması)
- SuddenHolidayDetector: KAP duyuru kontrolü eklendi
- Tatil değişiklik logu (audit trail)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# =====================================================
# 0. PROXY DESTEĞİ (BIST engelli bölgeler için)
# =====================================================

def _get_proxy() -> str | None:
    """HTTP_PROXY veya HTTPS_PROXY ortam değişkeninden proxy al."""
    return os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("http_proxy") or os.environ.get("https_proxy")


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

# Yarım gün tatil arifeleri
HALF_DAY_EVES: dict[int, tuple[int, int]] = {
    7: (10, 28),  # Cumhuriyet Bayramı arifesi
}


# =====================================================
# 2. DİNİ BAYRAM HESAPLAMA (Hicri Takvim)
# =====================================================

def _compute_hijri_holidays(gregorian_year: int) -> list[date]:
    """Hicri takvime göre Ramazan ve Kurban Bayramı tarihlerini hesapla.

    Referans noktaları (Miladi → Hicri):
    - 2024: Ramazan 10 Mart, Kurban 17 Haziran
    - 2025: Ramazan 28 Şubat, Kurban 6 Haziran
    - 2026: Ramazan 18 Şubat, Kurban 27 Mayıs

    Kaynak: Diyanet İşleri Başkanlığı resmi takvimi
    """
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
# 3. BIST RESMİ TAKVİM ÇEKME (Retry + Alternatif Kaynaklar)
# =====================================================

async def _fetch_with_retry(
    url: str,
    max_retries: int = 3,
    timeout: int = 15,
    proxy: str | None = None,
) -> str | None:
    """HTTP GET with retry and exponential backoff."""
    import httpx

    for attempt in range(max_retries):
        try:
            client_kwargs: dict[str, Any] = {
                "timeout": timeout,
                "follow_redirects": True,
            }
            if proxy:
                client_kwargs["proxy"] = proxy

            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
                    },
                )
                if resp.status_code == 200:
                    return resp.text
                else:
                    logger.warning("HTTP error", url=url, status=resp.status_code, attempt=attempt + 1)
        except Exception as e:
            logger.warning("Fetch failed", url=url, error=str(e), attempt=attempt + 1)

        if attempt < max_retries - 1:
            wait = 2 ** attempt  # 1s, 2s, 4s
            await asyncio.sleep(wait)

    return None


async def fetch_bist_holidays_from_web() -> list[date] | None:
    """BIST resmi web sitesinden tatil günlerini çek.

    Öncelik sırası:
    1. BIST resmi web sitesi (proxy ile)
    2. KAP RSS (tatil duyuruları)
    3. Investing.com TR takvimi
    """
    proxy = _get_proxy()

    # 1. BIST resmi web sitesi
    html = await _fetch_with_retry(
        "https://www.borsaistanbul.com/en/sayfa/3466/holidays",
        proxy=proxy,
    )
    if html:
        holidays = _parse_bist_holidays_html(html)
        if holidays:
            logger.info("BIST holidays fetched from official site", count=len(holidays))
            return holidays

    # 2. KAP RSS (tatil duyuruları)
    kap_holidays = await _fetch_holidays_from_kap()
    if kap_holidays:
        logger.info("BIST holidays fetched from KAP", count=len(kap_holidays))
        return kap_holidays

    # 3. Investing.com TR
    investing_holidays = await _fetch_holidays_from_investing()
    if investing_holidays:
        logger.info("BIST holidays fetched from Investing.com", count=len(investing_holidays))
        return investing_holidays

    logger.warning("All holiday sources failed")
    return None


def _parse_bist_holidays_html(html: str) -> list[date] | None:
    """BIST HTML sayfasından tatil tarihlerini parse et."""
    holidays: list[date] = []
    patterns = [
        r'(\d{1,2})[./](\d{1,2})[./](\d{4})',
        r'(\d{4})-(\d{2})-(\d{2})',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, html)
        for match in matches:
            try:
                if len(match[0]) == 4:
                    d = date(int(match[0]), int(match[1]), int(match[2]))
                else:
                    d = date(int(match[2]), int(match[1]), int(match[0]))
                if 2020 <= d.year <= 2030:
                    holidays.append(d)
            except ValueError:
                continue
    return holidays if holidays else None


async def _fetch_holidays_from_kap() -> list[date] | None:
    """KAP (Kamuyu Aydınlatma Platformu) üzerinden tatil duyurularını çek.

    KAP BIST tatil duyurularını yayınlar:
    https://www.kap.org.tr/tr/api/Bildirim/Search
    """
    proxy = _get_proxy()

    # KAP API — tatil anahtar kelimesi ile ara
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            kwargs: dict[str, Any] = {}
            if proxy:
                kwargs["proxy"] = proxy

            # KAP bildirim ara API
            resp = await client.get(
                "https://www.kap.org.tr/tr/api/Bildirim/Search",
                params={
                    "searchTerm": "borsa istanbul tatil",
                    "fromDate": f"{date.today().year}-01-01",
                    "toDate": f"{date.today().year}-12-31",
                },
                headers={"User-Agent": "Mozilla/5.0"},
                **kwargs,
            )
            if resp.status_code == 200:
                data = resp.json()
                return _parse_kap_holiday_notifications(data)
    except Exception as e:
        logger.debug("KAP holiday fetch failed", error=str(e))

    # Fallback: KAP RSS feed
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            kwargs: dict[str, Any] = {}
            if proxy:
                kwargs["proxy"] = proxy

            resp = await client.get(
                "https://www.kap.org.tr/tr/api/Bildirim/GetRssFeed",
                headers={"User-Agent": "Mozilla/5.0"},
                **kwargs,
            )
            if resp.status_code == 200:
                return _parse_kap_rss_for_holidays(resp.text)
    except Exception as e:
        logger.debug("KAP RSS fetch failed", error=str(e))

    return None


def _parse_kap_holiday_notifications(data: Any) -> list[date] | None:
    """KAP API yanıtından tatil tarihlerini çıkar."""
    holidays: list[date] = []

    if not isinstance(data, list):
        return None

    # Tatil anahtar kelimeleri
    holiday_keywords = [
        "tatil", "kapalı", "işlem yapılmayacak", "piyasa kapalı",
        "resmi tatil", "bayram", "arife", "yarım gün",
    ]

    for notification in data:
        title = str(notification.get("title", "") or notification.get("baslik", "")).lower()
        content = str(notification.get("content", "") or notification.get("icerik", "")).lower()
        text = f"{title} {content}"

        # Tatil anahtar kelimesi var mı?
        if any(kw in text for kw in holiday_keywords):
            # Tarih çıkar
            date_patterns = [
                r'(\d{1,2})[./](\d{1,2})[./](\d{4})',
                r'(\d{4})-(\d{2})-(\d{2})',
            ]
            for pattern in date_patterns:
                matches = re.findall(pattern, text)
                for match in matches:
                    try:
                        if len(match[0]) == 4:
                            d = date(int(match[0]), int(match[1]), int(match[2]))
                        else:
                            d = date(int(match[2]), int(match[1]), int(match[0]))
                        if 2020 <= d.year <= 2030:
                            holidays.append(d)
                    except ValueError:
                        continue

    return holidays if holidays else None


def _parse_kap_rss_for_holidays(xml_text: str) -> list[date] | None:
    """KAP RSS feed'inden tatil tarihlerini çıkar."""
    holidays: list[date] = []

    holiday_keywords = ["tatil", "kapalı", "işlem yapılmayacak", "piyasa kapalı"]

    # RSS item'ları arasında tatil duyurusu ara
    items = re.findall(r'<item>(.*?)</item>', xml_text, re.DOTALL)
    for item in items:
        title_match = re.search(r'<title>(.*?)</title>', item, re.DOTALL)
        desc_match = re.search(r'<description>(.*?)</description>', item, re.DOTALL)

        title = title_match.group(1) if title_match else ""
        desc = desc_match.group(1) if desc_match else ""
        text = f"{title} {desc}".lower()

        if any(kw in text for kw in holiday_keywords):
            date_matches = re.findall(r'(\d{1,2})[./](\d{1,2})[./](\d{4})', text)
            for match in date_matches:
                try:
                    d = date(int(match[2]), int(match[1]), int(match[0]))
                    if 2020 <= d.year <= 2030:
                        holidays.append(d)
                except ValueError:
                    continue

    return holidays if holidays else None


async def _fetch_holidays_from_investing() -> list[date] | None:
    """Investing.com TR takviminden tatil günlerini çek."""
    proxy = _get_proxy()

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            kwargs: dict[str, Any] = {}
            if proxy:
                kwargs["proxy"] = proxy

            resp = await client.get(
                "https://tr.investing.com/holidays/turkey",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept-Language": "tr-TR,tr;q=0.9",
                },
                **kwargs,
            )
            if resp.status_code == 200:
                return _parse_investing_holidays(resp.text)
    except Exception as e:
        logger.debug("Investing.com holiday fetch failed", error=str(e))

    return None


def _parse_investing_holidays(html: str) -> list[date] | None:
    """Investing.com HTML'den tatil tarihlerini parse et."""
    holidays: list[date] = []

    # Tablo satırlarından tarih çıkar
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    for row in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        for cell in cells:
            # DD/MM/YYYY veya DD.MM.YYYY formatı
            matches = re.findall(r'(\d{1,2})[./](\d{1,2})[./](\d{4})', cell)
            for match in matches:
                try:
                    d = date(int(match[2]), int(match[1]), int(match[0]))
                    if 2020 <= d.year <= 2030:
                        holidays.append(d)
                except ValueError:
                    continue

    return holidays if holidays else None


# =====================================================
# 4. KAP ANLIK DUYURU İZLEYİCİ
# =====================================================

class KAPHolidayWatcher:
    """KAP'tan anlık tatil duyurularını izler.

    BIST tatil ilan ettiğinde KAP'ta yayınlanır.
    Bu sınıf KAP'ı periyodik olarak kontrol eder.
    """

    def __init__(self):
        self._last_check: datetime | None = None
        self._last_announcement_time: datetime | None = None
        self._announced_holidays: set[date] = set()
        self._check_interval_seconds: int = 300  # 5 dakika

    async def check_for_new_announcements(self) -> list[date]:
        """KAP'ta yeni tatil duyurusu var mı?"""
        now = datetime.now()

        # Son kontrol üzerinden yeterli süre geçti mi?
        if self._last_check and (now - self._last_check).total_seconds() < self._check_interval_seconds:
            return []

        self._last_check = now

        kap_holidays = await _fetch_holidays_from_kap()
        if not kap_holidays:
            return []

        # Yeni duyuruları bul
        new_holidays = [d for d in kap_holidays if d not in self._announced_holidays]
        if new_holidays:
            self._announced_holidays.update(new_holidays)
            self._last_announcement_time = now
            logger.warning(
                "KAP holiday announcement detected",
                dates=[d.isoformat() for d in new_holidays],
            )

        return new_holidays

    def get_last_announcement_time(self) -> datetime | None:
        return self._last_announcement_time

    def get_announced_holidays(self) -> set[date]:
        return self._announced_holidays.copy()


# =====================================================
# 5. ANLIK TATİL TESPİTİ (Gelişmiş)
# =====================================================

class SuddenHolidayDetector:
    """Piyasa beklenmedik şekilde kapalıysa tespit et.

    v2.0: Artık KAP duyurularını da kontrol ediyor.

    Çalışma mantığı:
    1. Radar verisi gelmiyorsa → sayacı artır
    2. KAP'ta tatil duyurusu varsa → anında tespit et
    3. 3 kez üst üste veri gelmezse → otomatik tatil ekle
    """

    def __init__(self):
        self._confirmed_holidays: set[date] = set()
        self._suspected_holidays: dict[date, int] = {}  # date → fail count
        self._kap_watcher = KAPHolidayWatcher()

    def check_market_data_freshness(
        self,
        last_data_time: datetime | None,
        expected_interval_minutes: int = 5,
    ) -> bool:
        """Piyasa verisi güncel mi?"""
        if last_data_time is None:
            return False
        now = datetime.now()
        diff = (now - last_data_time).total_seconds() / 60
        return diff < expected_interval_minutes * 3

    async def check_kap_announcements(self) -> list[date]:
        """KAP'ta yeni tatil duyurusu var mı?"""
        return await self._kap_watcher.check_for_new_announcements()

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

    def report_kap_holiday(self, d: date) -> bool:
        """KAP'tan tatil duyurusu geldi — anında tespit et."""
        self._confirmed_holidays.add(d)
        logger.warning("Holiday detected via KAP announcement", date=d.isoformat())
        return True

    def is_confirmed_holiday(self, d: date) -> bool:
        return d in self._confirmed_holidays

    def get_confirmed(self) -> set[date]:
        return self._confirmed_holidays.copy()


# =====================================================
# 6. ANA HOLIDAY MANAGER
# =====================================================

class HolidayManager:
    """BIST tatil yöneticisi — dinamik, otomatik, self-updating.

    v2.0:
    - KAP anlık duyuru izleme
    - Tatil değişiklik logu (audit trail)
    - Proxy desteği
    - Retry mekanizması
    """

    def __init__(self, data_dir: str = "data"):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(exist_ok=True)
        self._cache_file = self._data_dir / "holiday_cache.json"
        self._audit_file = self._data_dir / "holiday_audit.json"
        self._sudden_detector = SuddenHolidayDetector()

        # Cache'ten yükle
        self._holidays: dict[int, set[date]] = {}
        self._half_days: dict[int, set[date]] = {}
        self._blacklist: set[date] = set()  # Manuel kaldırılan tatiller
        self._load_cache()

    def get_holidays(self, year: int | None = None) -> set[date]:
        """Belirli bir yılın tatil günlerini getir."""
        if year is None:
            year = date.today().year

        if year not in self._holidays:
            self._compute_year(year)

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
        self._log_audit("add", d, reason)
        logger.info("Manual holiday added", date=d.isoformat(), reason=reason)

    def remove_holiday(self, d: date, reason: str = "") -> None:
        """Tatil gününü kaldır (iptal edilen tatiller için).

        Kara listeye eklenir, böylece _compute_year() tekrar eklemez.
        """
        year = d.year
        if year in self._holidays:
            self._holidays[year].discard(d)
        self._blacklist.add(d)
        self._save_cache()
        self._log_audit("remove", d, reason)
        logger.info("Holiday removed", date=d.isoformat(), reason=reason)

    def report_no_data(self, d: date | None = None) -> bool:
        """Veri gelmediğini rapor et — anlık tatil tespiti."""
        if d is None:
            d = date.today()
        detected = self._sudden_detector.report_no_data(d)
        if detected:
            if d.year not in self._holidays:
                self._holidays[d.year] = set()
            self._holidays[d.year].add(d)
            self._save_cache()
            self._log_audit("auto_detect", d, "SuddenHolidayDetector — no market data")
        return detected

    async def check_kap_for_holidays(self) -> list[date]:
        """KAP'ta yeni tatil duyurusu var mı? Varsa otomatik ekle."""
        new_holidays = await self._sudden_detector.check_kap_announcements()
        for d in new_holidays:
            if d.year not in self._holidays:
                self._holidays[d.year] = set()
            self._holidays[d.year].add(d)
            self._log_audit("kap_detect", d, "KAP announcement detected")
        if new_holidays:
            self._save_cache()
        return new_holidays

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

        national = [d for d in holidays if d in self._get_national_holidays(year)]
        if national:
            lines.append("🇹🇷 Milli Bayramlar:")
            for d in national:
                lines.append(f"  {d.strftime('%d.%m.%Y')} ({d.strftime('%A')}) — {self._get_holiday_name(d)}")

        religious = [d for d in holidays if d not in self._get_national_holidays(year)]
        if religious:
            lines.append("\n🕌 Dini Bayramlar:")
            for d in religious:
                lines.append(f"  {d.strftime('%d.%m.%Y')} ({d.strftime('%A')}) — {self._get_holiday_name(d)}")

        if half_days:
            lines.append("\n⏰ Yarım Günler (12:30 kapanış):")
            for d in half_days:
                lines.append(f"  {d.strftime('%d.%m.%Y')} ({d.strftime('%A')}) — {self._get_holiday_name(d)} arifesi")

        sudden = [d for d in self._sudden_detector.get_confirmed() if d.year == year]
        if sudden:
            lines.append("\n⚡ Anlık İlan Edilen Tatiller:")
            for d in sorted(sudden):
                lines.append(f"  {d.strftime('%d.%m.%Y')} ({d.strftime('%A')}) — Tespit edildi")

        return "\n".join(lines)

    def get_audit_log(self, limit: int = 50) -> list[dict]:
        """Son tatil değişiklik loglarını getir."""
        if not self._audit_file.exists():
            return []
        try:
            with open(self._audit_file) as f:
                data = json.load(f)
            return data.get("entries", [])[-limit:]
        except Exception:
            return []

    # =====================================================
    # İÇ METODLAR
    # =====================================================

    def _compute_year(self, year: int) -> None:
        """Bir yılın tüm tatillerini hesapla."""
        holidays: set[date] = set()

        for _, (month, day) in FIXED_HOLIDAYS.items():
            try:
                holidays.add(date(year, month, day))
            except ValueError:
                continue

        religious = _compute_hijri_holidays(year)
        holidays.update(religious)

        if year in self._holidays:
            holidays.update(self._holidays[year])

        # Kara listedeki tatilleri çıkar (manuel kaldırılmış)
        holidays -= self._blacklist

        self._holidays[year] = holidays

        half_days: set[date] = set()
        religious_half = _compute_half_days_eves(year, religious)
        half_days.update(religious_half)
        self._half_days[year] = half_days

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
            for d_str in data.get("blacklist", []):
                d = date.fromisoformat(d_str)
                self._blacklist.add(d)
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
            "blacklist": [d.isoformat() for d in sorted(self._blacklist)],
            "updated_at": datetime.now().isoformat(),
        }
        try:
            with open(self._cache_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("Holiday cache save failed", error=str(e))

    def _log_audit(self, action: str, d: date, reason: str = "") -> None:
        """Tatil değişiklik logu (audit trail)."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "date": d.isoformat(),
            "reason": reason,
        }

        try:
            if self._audit_file.exists():
                with open(self._audit_file) as f:
                    data = json.load(f)
            else:
                data = {"entries": []}

            data["entries"].append(entry)

            # Son 1000 kaydı tut
            if len(data["entries"]) > 1000:
                data["entries"] = data["entries"][-1000:]

            with open(self._audit_file, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.debug("Audit log failed", error=str(e))


# Singleton
holiday_manager = HolidayManager()
