"""
ALPHA BIST — Dinamik ve Otonom Tatil Yöneticisi (Dynamic Holiday Manager)

Borsa İstanbul (BIST) işlem ve tatil takvimini dinamik ve hataya kapalı yönetir:
1. Sabit milli bayramlar (her yıl aynı takvim günü)
2. Dini bayramlar (Hicri takvim projeksiyonu ve Diyanet referansları)
3. BIST resmi takvimi çekme (HTTP retry, exponential backoff ve vekil sunucu desteği)
4. Kamuyu Aydınlatma Platformu (KAP) RSS ve API anlık duyuru izleme
5. Anlık piyasa tatili tespiti (Sudden Holiday Detector - ardışık veri kesintisi)
6. Yarım gün seans yönetimi (bayram ve resmi tatil arifeleri)
7. Thread-safe durum yönetimi (threading.RLock), DuckDB denetim izi ve Polars dışa aktarımı.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import duckdb
import httpx
import orjson
import polars as pl
import structlog

from services.core.debounce import should_save
from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# =====================================================
# SABİTLER (CONSTANTS)
# =====================================================

DEFAULT_CHECK_INTERVAL_SECONDS: Final[int] = 300
DEFAULT_EXPECTED_DATA_INTERVAL_MINUTES: Final[int] = 5
DEFAULT_MAX_RETRIES: Final[int] = 3
DEFAULT_HTTP_TIMEOUT_SECONDS: Final[int] = 15
DEFAULT_CACHE_SAVE_DEBOUNCE_SECONDS: Final[float] = 60.0
DEFAULT_MAX_AUDIT_ENTRIES: Final[int] = 1000
DEFAULT_HOLIDAY_AUDIT_DB_PATH: Final[Path] = Path("data/duckdb/alpha_bist_audit.duckdb")
DEFAULT_DATA_DIR: Final[Path] = Path("data")

# Sabit Milli Bayramlar (Ay, Gün)
FIXED_HOLIDAYS: Final[dict[int, tuple[int, int]]] = {
    1: (1, 1),  # Yılbaşı
    2: (4, 23),  # Ulusal Egemenlik ve Çocuk Bayramı
    3: (5, 1),  # Emek ve Dayanışma Günü
    4: (5, 19),  # Atatürk'ü Anma, Gençlik ve Spor Bayramı
    5: (7, 15),  # Demokrasi ve Millî Birlik Günü
    6: (8, 30),  # Zafer Bayramı
    7: (10, 29),  # Cumhuriyet Bayramı
}

# Yarım Gün Tatil Arifeleri (Ay, Gün)
HALF_DAY_EVES: Final[dict[int, tuple[int, int]]] = {
    7: (10, 28),  # Cumhuriyet Bayramı arifesi
}

# Dini Bayram Başlangıç Tarihleri Referans Tablosu (Diyanet Takvimi)
RAMAZAN_REFERENCES: Final[dict[int, date]] = {
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

KURBAN_REFERENCES: Final[dict[int, date]] = {
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


# =====================================================
# VERİ MODELLERİ (DATA MODELS)
# =====================================================


class HolidayType(StrEnum):
    """Tatil türü sınıflandırması."""

    NATIONAL = "milli"
    RELIGIOUS = "dini"
    HALF_DAY = "yarim_gun"
    SUDDEN = "anlik"
    MANUAL = "manuel"


@dataclass(slots=True)
class HolidayInfo:
    """Tekil bir tatil veya yarım gün kaydının veri modeli.

    Attributes:
        date: Tatil tarihi.
        name: Tatil veya arife adı.
        holiday_type: Tatil kategorisi (milli, dini, yarim_gun vb.).
        is_half_day: Günün yarım seans olup olmadığı.
        description: Ek açıklama veya duyuru referansı.
    """

    date: date
    name: str
    holiday_type: str
    is_half_day: bool = False
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Modeli sözlük yapısına dönüştürür.

        Returns:
            dict[str, Any]: Serileştirilebilir sözlük.
        """
        return {
            "date": self.date.isoformat(),
            "name": self.name,
            "holiday_type": self.holiday_type,
            "is_half_day": self.is_half_day,
            "description": self.description,
        }

    def to_orjson_bytes(self) -> bytes:
        """Modeli yüksek performanslı JSON bayt dizisine dönüştürür.

        Returns:
            bytes: orjson ile kodlanmış bayt dizisi.
        """
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Kullanıcı dostu Türkçe metin gösterimi.

        Returns:
            str: Model özeti.
        """
        tip = "Yarım Gün" if self.is_half_day else "Tam Tatil"
        return f"HolidayInfo(tarih={self.date.isoformat()}, ad='{self.name}', tip='{self.holiday_type}', durum='{tip}')"


@dataclass(slots=True)
class HolidayAuditEntry:
    """Tatil değişiklik ve tespit denetim günlüğü veri modeli.

    Attributes:
        timestamp: Kaydın UTC ISO formatındaki zaman damgası.
        action: Gerçekleştirilen işlem (add, remove, auto_detect, kap_detect).
        date: İşlem yapılan tatil tarihi.
        reason: İşlem gerekçesi veya kaynak detayları.
    """

    timestamp: str
    action: str
    date: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        """Denetim kaydını sözlük yapısına dönüştürür.

        Returns:
            dict[str, Any]: Serileştirilebilir sözlük.
        """
        return {
            "timestamp": self.timestamp,
            "action": self.action,
            "date": self.date,
            "reason": self.reason,
        }

    def to_orjson_bytes(self) -> bytes:
        """Denetim kaydını orjson bayt dizisine dönüştürür.

        Returns:
            bytes: orjson kodlu baytlar.
        """
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Türkçe açıklayıcı metin gösterimi.

        Returns:
            str: Denetim kaydı özeti.
        """
        return f"HolidayAuditEntry(zaman={self.timestamp}, islem='{self.action}', tarih={self.date}, gerekce='{self.reason}')"


# =====================================================
# 0. VEKİL SUNUCU (PROXY) DESTEĞİ
# =====================================================


def _get_proxy() -> str | None:
    """Ortam değişkenlerinden HTTP/HTTPS vekil sunucu adresini alır.

    Returns:
        str | None: Yapılandırılmış vekil sunucu adresi veya None.
    """
    return (
        os.environ.get("HTTP_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("http_proxy")
        or os.environ.get("https_proxy")
    )


# =====================================================
# 1. DİNİ BAYRAM HESAPLAMA (Hicri Takvim Projeksiyonu)
# =====================================================


def _get_ramazan_start(year: int) -> date:
    """Belirtilen Miladi yılın Ramazan Bayramı 1. gün başlangıç tarihini hesaplar.

    Diyanet referans tablosunu kullanır; referans yılı dışındaysa 10.43 günlük yıllık
    kayma katsayısıyla projeksiyon yapar.

    Args:
        year: Takvim yılı.

    Returns:
        date: Ramazan Bayramı 1. gün tarihi.
    """
    if year in RAMAZAN_REFERENCES:
        return RAMAZAN_REFERENCES[year]
    closest_year = min(RAMAZAN_REFERENCES.keys(), key=lambda y: abs(y - year))
    closest_date = RAMAZAN_REFERENCES[closest_year]
    year_diff = year - closest_year
    shift_days = int(year_diff * 10.43)
    return closest_date - timedelta(days=shift_days)


def _get_kurban_start(year: int) -> date:
    """Belirtilen Miladi yılın Kurban Bayramı 1. gün başlangıç tarihini hesaplar.

    Diyanet referans tablosunu kullanır; referans yılı dışındaysa 10.43 günlük yıllık
    kayma katsayısıyla projeksiyon yapar.

    Args:
        year: Takvim yılı.

    Returns:
        date: Kurban Bayramı 1. gün tarihi.
    """
    if year in KURBAN_REFERENCES:
        return KURBAN_REFERENCES[year]
    closest_year = min(KURBAN_REFERENCES.keys(), key=lambda y: abs(y - year))
    closest_date = KURBAN_REFERENCES[closest_year]
    year_diff = year - closest_year
    shift_days = int(year_diff * 10.43)
    return closest_date - timedelta(days=shift_days)


def _compute_hijri_holidays(gregorian_year: int) -> list[date]:
    """Hicri takvime göre Ramazan ve Kurban Bayramı tarihlerini hesaplar.

    Diyanet İşleri Başkanlığı resmi referanslarını baz alır, referans dışındaki
    yıllar için dinamik projeksiyon yapar.

    Args:
        gregorian_year: Hesaplanacak Miladi takvim yılı.

    Returns:
        list[date]: Hesaplanan dini bayram tarihleri listesi.
    """
    holidays: list[date] = []

    # Ramazan Bayramı (3 gün)
    ramazan_start = _get_ramazan_start(gregorian_year)
    for i in range(3):
        d = ramazan_start + timedelta(days=i)
        if d.year == gregorian_year:
            holidays.append(d)

    # Kurban Bayramı (4 gün)
    kurban_start = _get_kurban_start(gregorian_year)
    for i in range(4):
        d = kurban_start + timedelta(days=i)
        if d.year == gregorian_year:
            holidays.append(d)

    return sorted(holidays)


def _compute_half_days_eves(
    gregorian_year: int,
    religious_holidays: list[date] | None = None,
) -> list[date]:
    """Dini bayram ve Cumhuriyet Bayramı arifelerini (yarım gün seans) hesaplar.

    Args:
        gregorian_year: Hesaplanacak takvim yılı.
        religious_holidays: Opsiyonel dini bayram listesi.

    Returns:
        list[date]: Yarım seans uygulanacak arife tarihleri listesi.
    """
    eves: list[date] = []

    # Ramazan Bayramı arifesi (1. günden 1 gün önce)
    ramazan_eve = _get_ramazan_start(gregorian_year) - timedelta(days=1)
    if ramazan_eve.year == gregorian_year:
        eves.append(ramazan_eve)

    # Kurban Bayramı arifesi (1. günden 1 gün önce)
    kurban_eve = _get_kurban_start(gregorian_year) - timedelta(days=1)
    if kurban_eve.year == gregorian_year:
        eves.append(kurban_eve)

    # Cumhuriyet Bayramı arifesi (28 Ekim)
    eves.append(date(gregorian_year, 10, 28))

    return sorted(list(set(eves)))


# =====================================================
# 2. RESMİ TAKVİM ÇEKME VE PARSING (WEB SCRAPING / API)
# =====================================================


async def _fetch_with_retry(
    url: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    timeout: int = DEFAULT_HTTP_TIMEOUT_SECONDS,
    proxy: str | None = None,
) -> str | None:
    """Üstel geri çekilme (exponential backoff) ile HTTP GET isteği gönderir.

    Args:
        url: İstek yapılacak hedef web adresi.
        max_retries: Maksimum deneme sayısı.
        timeout: Zaman aşımı saniyesi.
        proxy: Opsiyonel vekil sunucu adresi.

    Returns:
        str | None: Başarılı ise sayfa metni, aksi halde None.
    """
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

                logger.warning(
                    "http_istek_hatasi",
                    url=url,
                    durum_kodu=resp.status_code,
                    deneme=attempt + 1,
                )
        except Exception as e:
            logger.warning(
                "http_istek_istisnasi",
                url=url,
                hata=str(e),
                deneme=attempt + 1,
            )

        if attempt < max_retries - 1:
            wait = 2**attempt  # 1s, 2s, 4s...
            await asyncio.sleep(wait)

    return None


def _parse_bist_holidays_html(html: str) -> list[date] | None:
    """BIST HTML sayfa içeriğinden tatil tarihlerini ayrıştırır.

    Args:
        html: Borsa İstanbul tatil sayfası HTML metni.

    Returns:
        list[date] | None: Ayrıştırılan tatil tarihleri listesi veya None.
    """
    holidays: list[date] = []
    patterns = [
        r"(\d{1,2})[./](\d{1,2})[./](\d{4})",
        r"(\d{4})-(\d{2})-(\d{2})",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, html)
        for match in matches:
            try:
                if len(match[0]) == 4:
                    d = date(int(match[0]), int(match[1]), int(match[2]))
                else:
                    d = date(int(match[2]), int(match[1]), int(match[0]))
                if 2020 <= d.year <= 2040:
                    holidays.append(d)
            except ValueError:
                continue
    return sorted(list(set(holidays))) if holidays else None


def _parse_kap_holiday_notifications(data: Any) -> list[date] | None:
    """KAP API JSON bildirim yanıtından tatil tarihlerini ayrıştırır.

    Args:
        data: KAP API'den dönen JSON verisi.

    Returns:
        list[date] | None: Ayrıştırılan tatil tarihleri listesi veya None.
    """
    if not isinstance(data, list):
        return None

    holidays: list[date] = []
    holiday_keywords = (
        "tatil",
        "kapalı",
        "işlem yapılmayacak",
        "piyasa kapalı",
        "resmi tatil",
        "bayram",
        "arife",
        "yarım gün",
    )

    for notification in data:
        title = str(notification.get("title", "") or notification.get("baslik", "")).lower()
        content = str(notification.get("content", "") or notification.get("icerik", "")).lower()
        text = f"{title} {content}"

        if any(kw in text for kw in holiday_keywords):
            date_patterns = [
                r"(\d{1,2})[./](\d{1,2})[./](\d{4})",
                r"(\d{4})-(\d{2})-(\d{2})",
            ]
            for pattern in date_patterns:
                matches = re.findall(pattern, text)
                for match in matches:
                    try:
                        if len(match[0]) == 4:
                            d = date(int(match[0]), int(match[1]), int(match[2]))
                        else:
                            d = date(int(match[2]), int(match[1]), int(match[0]))
                        if 2020 <= d.year <= 2040:
                            holidays.append(d)
                    except ValueError:
                        continue

    return sorted(list(set(holidays))) if holidays else None


def _parse_kap_rss_for_holidays(xml_text: str) -> list[date] | None:
    """KAP RSS XML akışından tatil duyurularını ve tarihlerini ayrıştırır.

    Args:
        xml_text: KAP RSS akış XML metni.

    Returns:
        list[date] | None: Ayrıştırılan tatil tarihleri listesi veya None.
    """
    holidays: list[date] = []
    holiday_keywords = ("tatil", "kapalı", "işlem yapılmayacak", "piyasa kapalı")

    items = re.findall(r"<item>(.*?)</item>", xml_text, re.DOTALL)
    for item in items:
        title_match = re.search(r"<title>(.*?)</title>", item, re.DOTALL)
        desc_match = re.search(r"<description>(.*?)</description>", item, re.DOTALL)

        title = title_match.group(1) if title_match else ""
        desc = desc_match.group(1) if desc_match else ""
        text = f"{title} {desc}".lower()

        if any(kw in text for kw in holiday_keywords):
            date_matches = re.findall(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
            for match in date_matches:
                try:
                    d = date(int(match[2]), int(match[1]), int(match[0]))
                    if 2020 <= d.year <= 2040:
                        holidays.append(d)
                except ValueError:
                    continue

    return sorted(list(set(holidays))) if holidays else None


async def _fetch_holidays_from_kap() -> list[date] | None:
    """KAP (Kamuyu Aydınlatma Platformu) API ve RSS kaynaklarından tatil duyurusu çeker.

    Returns:
        list[date] | None: Tespit edilen tatil tarihleri veya None.
    """
    proxy = _get_proxy()
    year = date.today().year

    # 1. Öncelik: KAP Bildirim Arama API
    try:
        kwargs: dict[str, Any] = {"timeout": DEFAULT_HTTP_TIMEOUT_SECONDS}
        if proxy:
            kwargs["proxy"] = proxy

        async with httpx.AsyncClient(**kwargs) as client:
            resp = await client.get(
                "https://www.kap.org.tr/tr/api/Bildirim/Search",
                params={
                    "searchTerm": "borsa istanbul tatil",
                    "fromDate": f"{year}-01-01",
                    "toDate": f"{year}-12-31",
                },
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 200:
                data = resp.json()
                parsed = _parse_kap_holiday_notifications(data)
                if parsed:
                    return parsed
    except Exception as e:
        logger.debug("kap_api_sorgu_hatasi", hata=str(e))

    # 2. Öncelik: KAP RSS Akışı
    try:
        kwargs = {"timeout": DEFAULT_HTTP_TIMEOUT_SECONDS}
        if proxy:
            kwargs["proxy"] = proxy

        async with httpx.AsyncClient(**kwargs) as client:
            resp = await client.get(
                "https://www.kap.org.tr/tr/api/Bildirim/GetRssFeed",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 200:
                parsed_rss = _parse_kap_rss_for_holidays(resp.text)
                if parsed_rss:
                    return parsed_rss
    except Exception as e:
        logger.debug("kap_rss_sorgu_hatasi", hata=str(e))

    return None


def _parse_investing_holidays(html: str) -> list[date] | None:
    """Investing.com Türkiye tatil tablosundan tarihleri ayrıştırır.

    Args:
        html: Investing.com HTML sayfası.

    Returns:
        list[date] | None: Ayrıştırılan tarihler veya None.
    """
    holidays: list[date] = []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        for cell in cells:
            matches = re.findall(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", cell)
            for match in matches:
                try:
                    d = date(int(match[2]), int(match[1]), int(match[0]))
                    if 2020 <= d.year <= 2040:
                        holidays.append(d)
                except ValueError:
                    continue

    return sorted(list(set(holidays))) if holidays else None


async def _fetch_holidays_from_investing() -> list[date] | None:
    """Investing.com Türkiye tatil takviminden tarihleri çeker.

    Returns:
        list[date] | None: Tespit edilen tatil günleri listesi veya None.
    """
    proxy = _get_proxy()
    try:
        kwargs: dict[str, Any] = {"timeout": DEFAULT_HTTP_TIMEOUT_SECONDS}
        if proxy:
            kwargs["proxy"] = proxy

        async with httpx.AsyncClient(**kwargs) as client:
            resp = await client.get(
                "https://tr.investing.com/holidays/turkey",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept-Language": "tr-TR,tr;q=0.9",
                },
            )
            if resp.status_code == 200:
                return _parse_investing_holidays(resp.text)
    except Exception as e:
        logger.debug("investing_tatil_sorgu_hatasi", hata=str(e))

    return None


async def fetch_bist_holidays_from_web() -> list[date] | None:
    """BIST resmi web sitesi ve alternatif kaynaklardan tatil günlerini çeker.

    Öncelik sıralaması:
    1. BIST Resmi Web Sayfası
    2. KAP API ve RSS Duyuruları
    3. Investing.com Türkiye Tatil Takvimi

    Returns:
        list[date] | None: Başarılı ise tatil günleri listesi, tüm kaynaklar başarısızsa None.
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
            logger.info("bist_resmi_tatilleri_alindi", adet=len(holidays))
            return holidays

    # 2. KAP RSS ve Bildirimler
    kap_holidays = await _fetch_holidays_from_kap()
    if kap_holidays:
        logger.info("kap_tatil_duyurulari_alindi", adet=len(kap_holidays))
        return kap_holidays

    # 3. Investing.com Türkiye
    investing_holidays = await _fetch_holidays_from_investing()
    if investing_holidays:
        logger.info("investing_tatilleri_alindi", adet=len(investing_holidays))
        return investing_holidays

    logger.warning("tum_tatil_kaynaklari_basarisiz_oldu")
    return None


# =====================================================
# 3. KAP ANLIK DUYURU İZLEYİCİ
# =====================================================


class KAPHolidayWatcher:
    """Kamuyu Aydınlatma Platformu anlık tatil duyurularını izleyen servis.

    Periyodik aralıklarla KAP duyuru havuzunu sorgular, yeni tatil ilanlarını tespit eder.
    Thread-safe reentrant kilit korumasına sahiptir.
    """

    def __init__(self, check_interval_seconds: int = DEFAULT_CHECK_INTERVAL_SECONDS) -> None:
        """KAP izleyici örneğini başlatır.

        Args:
            check_interval_seconds: İki sorgu arasındaki minimum bekleme süresi.
        """
        self._lock = threading.RLock()
        self._last_check: datetime | None = None
        self._last_announcement_time: datetime | None = None
        self._announced_holidays: set[date] = set()
        self._check_interval_seconds: int = check_interval_seconds

    async def check_for_new_announcements(self) -> list[date]:
        """KAP platformunda yeni bir tatil duyurusu olup olmadığını kontrol eder.

        Returns:
            list[date]: Yeni tespit edilen tatil tarihleri listesi.
        """
        with self._lock:
            now = datetime.now(UTC)
            if self._last_check and (now - self._last_check).total_seconds() < self._check_interval_seconds:
                return []
            self._last_check = now

        kap_holidays = await _fetch_holidays_from_kap()
        if not kap_holidays:
            return []

        with self._lock:
            new_holidays = [d for d in kap_holidays if d not in self._announced_holidays]
            if new_holidays:
                self._announced_holidays.update(new_holidays)
                self._last_announcement_time = datetime.now(UTC)
                logger.warning(
                    "kap_yeni_tatil_duyurusu_tespit_edildi",
                    tarihler=[d.isoformat() for d in new_holidays],
                )
            return new_holidays

    def get_last_announcement_time(self) -> datetime | None:
        """Son tespit edilen tatil duyurusunun zaman damgasını döndürür.

        Returns:
            datetime | None: Son duyuru zamanı veya None.
        """
        with self._lock:
            return self._last_announcement_time

    def get_announced_holidays(self) -> set[date]:
        """KAP üzerinden şimdiye kadar duyurulan tüm tatil tarihlerinin kopyasını döndürür.

        Returns:
            set[date]: Duyurulan tatil tarihleri kümesi.
        """
        with self._lock:
            return self._announced_holidays.copy()

    def __repr__(self) -> str:
        """KAP izleyicisi metin gösterimi.

        Returns:
            str: Durum özeti.
        """
        with self._lock:
            return f"KAPHolidayWatcher(duyurulan_tatil_sayisi={len(self._announced_holidays)}, son_kontrol={self._last_check})"


# =====================================================
# 4. ANLIK TATİL TESPİTİ (SUDDEN HOLIDAY DETECTOR)
# =====================================================


class SuddenHolidayDetector:
    """Piyasanın beklenmedik şekilde kapalı kaldığı durumları tespit eder.

    Çalışma ilkeleri:
    1. Veri akışı kesintisi: Ardışık 3 kez veri gelmezse günü anlık tatil kabul eder.
    2. KAP bildirimi entegrasyonu: KAP'tan tatil haberi gelirse anında tatil tescil edilir.
    """

    def __init__(self, kap_watcher: KAPHolidayWatcher | None = None) -> None:
        """Anlık tatil tespit motorunu başlatır.

        Args:
            kap_watcher: Opsiyonel KAP duyuru izleyici nesnesi.
        """
        self._lock = threading.RLock()
        self._confirmed_holidays: set[date] = set()
        self._suspected_holidays: dict[date, int] = {}
        self._kap_watcher: KAPHolidayWatcher = kap_watcher if kap_watcher is not None else KAPHolidayWatcher()

    def check_market_data_freshness(
        self,
        last_data_time: datetime | None,
        expected_interval_minutes: int = DEFAULT_EXPECTED_DATA_INTERVAL_MINUTES,
    ) -> bool:
        """Piyasa veri tazeliğini kontrol eder.

        Args:
            last_data_time: Alınan son verinin zaman damgası.
            expected_interval_minutes: Beklenen maksimum veri aralığı (dakika).

        Returns:
            bool: Veri güncel ise True, gecikme varsa False.
        """
        if last_data_time is None:
            return False
        now = datetime.now(UTC)
        diff_minutes = (now - last_data_time).total_seconds() / 60.0
        return diff_minutes < (expected_interval_minutes * 3.0)

    async def check_kap_announcements(self) -> list[date]:
        """KAP platformunu sorgulayarak yeni duyurulan tatilleri getirir.

        Returns:
            list[date]: Yeni tatil tarihleri.
        """
        return await self._kap_watcher.check_for_new_announcements()

    def report_no_data(self, d: date) -> bool:
        """Belirtilen işlem gününde veri akmadığını raporlar.

        Ardışık 3 kesinti sonrası gün resmen tatil olarak tescil edilir.

        Args:
            d: Veri gelmeyen takvim tarihi.

        Returns:
            bool: 3. kesinti ile tatil tescil edildiyse True, aksi halde False.
        """
        with self._lock:
            if d in self._confirmed_holidays:
                return True
            self._suspected_holidays[d] = self._suspected_holidays.get(d, 0) + 1
            if self._suspected_holidays[d] >= 3:
                self._confirmed_holidays.add(d)
                logger.warning(
                    "anlik_tatil_tespit_edildi_veri_kesintisi",
                    tarih=d.isoformat(),
                    kesinti_sayisi=self._suspected_holidays[d],
                )
                return True
            return False

    def report_kap_holiday(self, d: date) -> bool:
        """KAP duyurusu üzerinden doğrudan tatil tescili yapar.

        Args:
            d: Tatil olarak tescil edilecek tarih.

        Returns:
            bool: Her zaman True.
        """
        with self._lock:
            self._confirmed_holidays.add(d)
            logger.warning("kap_duyurusu_ile_tatil_tescil_edildi", tarih=d.isoformat())
            return True

    def is_confirmed_holiday(self, d: date) -> bool:
        """Tarihin anlık tatil olarak onaylanıp onaylanmadığını doğrular.

        Args:
            d: Sorgulanan tarih.

        Returns:
            bool: Onaylı anlık tatil ise True.
        """
        with self._lock:
            return d in self._confirmed_holidays

    def get_confirmed(self) -> set[date]:
        """Onaylanan tüm anlık tatil tarihlerinin kopyasını döndürür.

        Returns:
            set[date]: Onaylanmış tarihler kümesi.
        """
        with self._lock:
            return self._confirmed_holidays.copy()

    def __repr__(self) -> str:
        """Dedektörün Türkçe metin gösterimi.

        Returns:
            str: Onaylı ve şüpheli tatil sayısı özeti.
        """
        with self._lock:
            return (
                f"SuddenHolidayDetector(onayli_tatil_sayisi={len(self._confirmed_holidays)}, "
                f"supheli_sayisi={len(self._suspected_holidays)})"
            )


# =====================================================
# 5. ANA TATİL YÖNETİCİSİ (HOLIDAY MANAGER)
# =====================================================


class HolidayManager:
    """BIST dinamik ve otonom tatil yöneticisi sınıfı.

    Özellikler:
    - Thread-safe RLock yapısı.
    - DuckDB denetim tablosu (`bist_holidays_audit`) ve Polars DataFrame dışa aktarımı.
    - SSD dostu debounced önbellek ve denetim logu yazımı.
    - KAP anlık duyuru izleme ve veri kesintisi dedektörü entegrasyonu.
    """

    def __init__(self, data_dir: str | Path = DEFAULT_DATA_DIR) -> None:
        """Tatil yöneticisini başlatır ve diskteki önbelleği yükler.

        Args:
            data_dir: Önbellek ve denetim loglarının saklanacağı dizin yolu.
        """
        self._lock = threading.RLock()
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._cache_file = self._data_dir / "holiday_cache.json"
        self._audit_file = self._data_dir / "holiday_audit.json"
        self._sudden_detector = SuddenHolidayDetector()

        self._holidays: dict[int, set[date]] = {}
        self._half_days: dict[int, set[date]] = {}
        self._blacklist: set[date] = set()
        self._last_cache_save: float = 0.0
        self._pending_audit_entries: list[dict[str, Any]] = []

        self._load_cache()

    # -------------------------------------------------
    # SORGULAMA METOTLARI
    # -------------------------------------------------

    @otel_trace("holiday_manager.get_holidays")
    def get_holidays(self, year: int | None = None) -> set[date]:
        """Belirtilen yılın tüm BIST tam tatil günlerini döndürür.

        Args:
            year: Hedef yıl (varsayılan: mevcut yıl).

        Returns:
            set[date]: O yıla ait tatil günleri kümesi.
        """
        with self._lock:
            if year is None:
                year = date.today().year

            if year not in self._holidays:
                self._compute_year(year)

            result = self._holidays.get(year, set()).copy()
            for d in self._sudden_detector.get_confirmed():
                if d.year == year:
                    result.add(d)

            return result

    @otel_trace("holiday_manager.get_half_days")
    def get_half_days(self, year: int | None = None) -> set[date]:
        """Belirtilen yılın yarım seans (12:30 kapanış) günlerini döndürür.

        Args:
            year: Hedef yıl (varsayılan: mevcut yıl).

        Returns:
            set[date]: Yarım seans uygulanan tarihler kümesi.
        """
        with self._lock:
            if year is None:
                year = date.today().year

            if year not in self._half_days:
                self._compute_year(year)

            return self._half_days.get(year, set()).copy()

    def get_sudden_holidays(self) -> set[date]:
        """Beklenmedik veya sonradan ilan edilen onaylı anlık tatilleri döndürür.

        Returns:
            set[date]: Onaylanmış anlık tatiller kümesi.
        """
        with self._lock:
            return self._sudden_detector.get_confirmed()

    def get_holiday_name(self, d: date) -> str:
        """Belirtilen tarihin resmi veya dini tatil adını döndürür.

        Args:
            d: Sorgulanan tarih.

        Returns:
            str: Tatil veya arife adı.
        """
        with self._lock:
            return self._get_holiday_name(d)

    def _get_holiday_name(self, d: date) -> str:
        """Tatil gününün adını belirleyen iç fonksiyon."""
        names: dict[tuple[int, int], str] = {
            (1, 1): "Yılbaşı",
            (4, 23): "Ulusal Egemenlik ve Çocuk Bayramı",
            (5, 1): "Emek ve Dayanışma Günü",
            (5, 19): "Atatürk'ü Anma, Gençlik ve Spor Bayramı",
            (7, 15): "Demokrasi ve Millî Birlik Günü",
            (8, 30): "Zafer Bayramı",
            (10, 28): "Cumhuriyet Bayramı Arifesi",
            (10, 29): "Cumhuriyet Bayramı",
        }
        key = (d.month, d.day)
        if key in names:
            return names[key]

        # Dini bayram kontrolü
        ramazan_start = _get_ramazan_start(d.year)
        if ramazan_start <= d <= ramazan_start + timedelta(days=2):
            idx = (d - ramazan_start).days + 1
            return f"Ramazan Bayramı {idx}. gün"

        kurban_start = _get_kurban_start(d.year)
        if kurban_start <= d <= kurban_start + timedelta(days=3):
            idx = (d - kurban_start).days + 1
            return f"Kurban Bayramı {idx}. gün"

        # Dini arife kontrolü
        if d == ramazan_start - timedelta(days=1):
            return "Ramazan Bayramı Arifesi"
        if d == kurban_start - timedelta(days=1):
            return "Kurban Bayramı Arifesi"

        if d in self._sudden_detector.get_confirmed():
            return "Anlık İlan Edilen Tatil"

        return "Resmi Tatil"

    @otel_trace("holiday_manager.is_holiday")
    def is_holiday(self, d: date | None = None) -> bool:
        """Belirtilen günün tam tatil olup olmadığını sorgular.

        Args:
            d: Tarih (varsayılan: bugün).

        Returns:
            bool: Tatil ise True, değilse False.
        """
        if d is None:
            d = date.today()
        holidays = self.get_holidays(d.year)
        return d in holidays

    @otel_trace("holiday_manager.is_half_day")
    def is_half_day(self, d: date | None = None) -> bool:
        """Belirtilen günün yarım seans olup olmadığını sorgular.

        Args:
            d: Tarih (varsayılan: bugün).

        Returns:
            bool: Yarım seans ise True, değilse False.
        """
        if d is None:
            d = date.today()
        half_days = self.get_half_days(d.year)
        return d in half_days

    @otel_trace("holiday_manager.is_trading_day")
    def is_trading_day(self, d: date | None = None) -> bool:
        """Belirtilen günün BIST işlem günü olup olmadığını doğrular.

        Hafta sonları (Cumartesi-Pazar) ve tam tatil günleri işlem günü değildir.
        Yarım seans günleri işlem günüdür.

        Args:
            d: Tarih (varsayılan: bugün).

        Returns:
            bool: İşlem günü ise True, kapalı ise False.
        """
        if d is None:
            d = date.today()
        if d.weekday() >= 5:
            return False
        return not self.is_holiday(d)

    # -------------------------------------------------
    # DEĞİŞİKLİK VE ANLIK MÜDAHALE METOTLARI
    # -------------------------------------------------

    @otel_trace("holiday_manager.add_manual_holiday")
    def add_manual_holiday(self, d: date, reason: str = "") -> None:
        """Manuel olarak sisteme tatil günü ekler.

        Args:
            d: Eklenecek tatil tarihi.
            reason: Eklenme gerekçesi.
        """
        with self._lock:
            year = d.year
            if year not in self._holidays:
                self._holidays[year] = set()
            self._holidays[year].add(d)
            self._blacklist.discard(d)
            self._save_cache(force=True)
            self._log_audit("add", d, reason, flush=True)
            logger.info("manuel_tatil_eklendi", tarih=d.isoformat(), gerekce=reason)

    @otel_trace("holiday_manager.remove_holiday")
    def remove_holiday(self, d: date, reason: str = "") -> None:
        """Tatil gününü iptal eder ve kara listeye ekler.

        Kara liste, sonraki hesaplamalarda bu günün tekrar otomatik eklenmesini engeller.

        Args:
            d: Kaldırılacak tatil tarihi.
            reason: Kaldırma gerekçesi.
        """
        with self._lock:
            year = d.year
            if year in self._holidays:
                self._holidays[year].discard(d)
            self._blacklist.add(d)
            self._save_cache(force=True)
            self._log_audit("remove", d, reason, flush=True)
            logger.info("tatil_kaldirildi", tarih=d.isoformat(), gerekce=reason)

    @otel_trace("holiday_manager.add_manual_half_day")
    def add_manual_half_day(self, d: date, reason: str = "") -> None:
        """Manuel olarak sisteme yarım seans (12:30 kapanış) günü ekler.

        Args:
            d: Eklenecek yarım gün tarihi.
            reason: Eklenme gerekçesi.
        """
        with self._lock:
            year = d.year
            if year not in self._half_days:
                self._half_days[year] = set()
            self._half_days[year].add(d)
            self._save_cache(force=True)
            self._log_audit("add_half_day", d, reason, flush=True)
            logger.info("manuel_yarim_gun_eklendi", tarih=d.isoformat(), gerekce=reason)

    @otel_trace("holiday_manager.remove_half_day")
    def remove_half_day(self, d: date, reason: str = "") -> None:
        """Yarım gün seans kaydını sistemden kaldırır.

        Args:
            d: Kaldırılacak yarım gün tarihi.
            reason: Kaldırma gerekçesi.
        """
        with self._lock:
            year = d.year
            if year in self._half_days:
                self._half_days[year].discard(d)
            self._save_cache(force=True)
            self._log_audit("remove_half_day", d, reason, flush=True)
            logger.info("yarim_gun_kaldirildi", tarih=d.isoformat(), gerekce=reason)

    @otel_trace("holiday_manager.report_no_data")
    def report_no_data(self, d: date | None = None) -> bool:
        """Piyasa verisi gelmediğini dedektöre bildirir.

        Ardışık 3 kez veri kesintisi olursa gün otomatik tatil ilan edilir.

        Args:
            d: Veri gelmeyen tarih (varsayılan: bugün).

        Returns:
            bool: Gün tatil ilan edildiyse True.
        """
        if d is None:
            d = date.today()

        with self._lock:
            already_confirmed = d in self._holidays.get(d.year, set())
            detected = self._sudden_detector.report_no_data(d)
            if detected and not already_confirmed:
                if d.year not in self._holidays:
                    self._holidays[d.year] = set()
                self._holidays[d.year].add(d)
                self._save_cache(force=True)
                self._log_audit("auto_detect", d, "SuddenHolidayDetector — ardışık 3 kesinti", flush=True)
            return detected

    @otel_trace("holiday_manager.check_kap_for_holidays")
    async def check_kap_for_holidays(self) -> list[date]:
        """KAP platformunu sorgular; yeni duyurulan tatilleri otomatik sisteme ekler.

        Returns:
            list[date]: Yeni eklenen tatil tarihleri.
        """
        new_holidays = await self._sudden_detector.check_kap_announcements()
        with self._lock:
            for d in new_holidays:
                if d.year not in self._holidays:
                    self._holidays[d.year] = set()
                self._holidays[d.year].add(d)
                self._log_audit("kap_detect", d, "KAP tatil duyurusu", flush=True)

            if new_holidays:
                self._save_cache(force=True)

        return new_holidays

    @otel_trace("holiday_manager.sync_from_bist")
    async def sync_from_bist(self) -> bool:
        """BIST web sitesinden resmi takvimi çeker ve takvimi senkronize eder.

        Returns:
            bool: Senkronizasyon başarılı ise True.
        """
        holidays = await fetch_bist_holidays_from_web()
        if holidays:
            with self._lock:
                for d in holidays:
                    if d not in self._blacklist:
                        if d.year not in self._holidays:
                            self._holidays[d.year] = set()
                        self._holidays[d.year].add(d)
                self._save_cache(force=True)
                logger.info("bist_tatil_senkronizasyonu_tamamlandi", adet=len(holidays))
                return True
        return False

    def get_all_holidays_text(self, year: int | None = None) -> str:
        """Belirtilen yılın tüm tatil ve yarım seanslarını okunabilir metin olarak döndürür.

        Args:
            year: Yıl (varsayılan: mevcut yıl).

        Returns:
            str: Rapor metni.
        """
        with self._lock:
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
                    lines.append(f"  {d.strftime('%d.%m.%Y')} ({d.strftime('%A')}) — {self._get_holiday_name(d)}")

            sudden = [d for d in self._sudden_detector.get_confirmed() if d.year == year]
            if sudden:
                lines.append("\n⚡ Anlık İlan Edilen Tatiller:")
                for d in sorted(sudden):
                    lines.append(f"  {d.strftime('%d.%m.%Y')} ({d.strftime('%A')}) — Tespit edildi")

            return "\n".join(lines)

    def get_audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Son tatil değişiklik kayıtlarını getirir.

        Args:
            limit: Döndürülecek maksimum kayıt sayısı.

        Returns:
            list[dict[str, Any]]: Değişiklik kayıtları listesi.
        """
        with self._lock:
            if not self._audit_file.exists():
                return []
            try:
                with open(self._audit_file, "rb") as f:
                    data = orjson.loads(f.read())
                return data.get("entries", [])[-limit:]
            except Exception as e:
                logger.warning("denetim_kaydi_okuma_hatasi", hata=str(e))
                return []

    # -------------------------------------------------
    # POLARS VE DUCKDB VERİ ENTEGRASYONU
    # -------------------------------------------------

    def export_to_polars(self, year: int | None = None) -> pl.DataFrame:
        """Tatil ve yarım gün listesini Polars DataFrame olarak dışa aktarır.

        Args:
            year: Yıl filtresi (None ise mevcut yıl).

        Returns:
            pl.DataFrame: Tatil takvimi tablosu.
        """
        with self._lock:
            if year is None:
                year = date.today().year

            holidays = sorted(self.get_holidays(year))
            half_days = sorted(self.get_half_days(year))
            national_set = self._get_national_holidays(year)
            sudden_set = self.get_sudden_holidays()

            rows: list[dict[str, Any]] = []

            # Tam tatiller
            for d in holidays:
                tip = HolidayType.NATIONAL.value if d in national_set else HolidayType.RELIGIOUS.value
                if d in sudden_set:
                    tip = HolidayType.SUDDEN.value

                rows.append({
                    "date": d.isoformat(),
                    "year": d.year,
                    "month": d.month,
                    "day": d.day,
                    "weekday": d.strftime("%A"),
                    "name": self.get_holiday_name(d),
                    "holiday_type": tip,
                    "is_half_day": False,
                    "is_trading_day": False,
                })

            # Yarım günler
            for d in half_days:
                rows.append({
                    "date": d.isoformat(),
                    "year": d.year,
                    "month": d.month,
                    "day": d.day,
                    "weekday": d.strftime("%A"),
                    "name": self.get_holiday_name(d),
                    "holiday_type": HolidayType.HALF_DAY.value,
                    "is_half_day": True,
                    "is_trading_day": True,
                })

            if not rows:
                return pl.DataFrame(schema={
                    "date": pl.String,
                    "year": pl.Int32,
                    "month": pl.Int32,
                    "day": pl.Int32,
                    "weekday": pl.String,
                    "name": pl.String,
                    "holiday_type": pl.String,
                    "is_half_day": pl.Boolean,
                    "is_trading_day": pl.Boolean,
                })

            df = pl.DataFrame(rows)
            return df.sort("date")

    def export_to_duckdb(
        self,
        db_path: str | Path | None = None,
        year: int | None = None,
    ) -> int:
        """Tatil takvimini kalıcı DuckDB tablosuna (`bist_holidays_audit`) kaydeder.

        Args:
            db_path: DuckDB veritabanı dosya yolu (None ise varsayılan).
            year: Kaydedilecek yıl.

        Returns:
            int: Kaydedilen satır sayısı.
        """
        df = self.export_to_polars(year=year)
        target_path = Path(db_path) if db_path is not None else DEFAULT_HOLIDAY_AUDIT_DB_PATH
        target_path.parent.mkdir(parents=True, exist_ok=True)

        con = duckdb.connect(str(target_path))
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS bist_holidays_audit (
                    date VARCHAR PRIMARY KEY,
                    year INTEGER,
                    month INTEGER,
                    day INTEGER,
                    weekday VARCHAR,
                    name VARCHAR,
                    holiday_type VARCHAR,
                    is_half_day BOOLEAN,
                    is_trading_day BOOLEAN,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)

            arrow_table = df.to_arrow()
            con.register("df_arrow", arrow_table)
            con.execute("""
                INSERT OR REPLACE INTO bist_holidays_audit (
                    date, year, month, day, weekday, name, holiday_type, is_half_day, is_trading_day
                )
                SELECT date, year, month, day, weekday, name, holiday_type, is_half_day, is_trading_day
                FROM df_arrow
            """)
            con.unregister("df_arrow")
            con.commit()
            return len(df)
        finally:
            con.close()

    def export_audit_to_polars(self, limit: int = DEFAULT_MAX_AUDIT_ENTRIES) -> pl.DataFrame:
        """Değişiklik ve denetim loglarını Polars DataFrame olarak döndürür.

        Args:
            limit: Getirilecek maksimum kayıt sayısı.

        Returns:
            pl.DataFrame: Denetim izi tablosu.
        """
        entries = self.get_audit_log(limit=limit)
        if not entries:
            return pl.DataFrame(schema={
                "timestamp": pl.String,
                "action": pl.String,
                "date": pl.String,
                "reason": pl.String,
            })
        return pl.DataFrame(entries)

    def export_audit_to_duckdb(
        self,
        db_path: str | Path | None = None,
        limit: int = DEFAULT_MAX_AUDIT_ENTRIES,
    ) -> int:
        """Tatil değişiklik loglarını DuckDB `bist_holiday_audit_trail` tablosuna yazar.

        Args:
            db_path: DuckDB veritabanı yolu.
            limit: Yazılacak kayıt sayısı.

        Returns:
            int: Kaydedilen satır adedi.
        """
        df = self.export_audit_to_polars(limit=limit)
        if df.is_empty():
            return 0

        target_path = Path(db_path) if db_path is not None else DEFAULT_HOLIDAY_AUDIT_DB_PATH
        target_path.parent.mkdir(parents=True, exist_ok=True)

        con = duckdb.connect(str(target_path))
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS bist_holiday_audit_trail (
                    timestamp VARCHAR,
                    action VARCHAR,
                    date VARCHAR,
                    reason VARCHAR,
                    logged_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (timestamp, action, date)
                )
            """)
            arrow_table = df.to_arrow()
            con.register("audit_arrow", arrow_table)
            con.execute("""
                INSERT OR REPLACE INTO bist_holiday_audit_trail (timestamp, action, date, reason)
                SELECT timestamp, action, date, reason FROM audit_arrow
            """)
            con.unregister("audit_arrow")
            con.commit()
            return len(df)
        finally:
            con.close()

    # -------------------------------------------------
    # İÇ YARDIMCI METOTLAR
    # -------------------------------------------------

    def _compute_year(self, year: int) -> None:
        """Belirtilen yılın sabit ve dini bayram takvimini hesaplar."""
        holidays: set[date] = set()

        # Sabit milli bayramlar
        for _, (month, day) in FIXED_HOLIDAYS.items():
            try:
                holidays.add(date(year, month, day))
            except ValueError:
                continue

        # Dini bayramlar
        religious = _compute_hijri_holidays(year)
        holidays.update(religious)

        # Önceden kayıtlı tatiller
        if year in self._holidays:
            holidays.update(self._holidays[year])

        # Kara liste filtreleme
        holidays -= self._blacklist
        self._holidays[year] = holidays

        # Yarım günler
        half_days: set[date] = set()
        religious_half = _compute_half_days_eves(year, religious)
        half_days.update(religious_half)
        self._half_days[year] = half_days

        self._save_cache(force=False)
        logger.info(
            "tatil_takvimi_hesaplandi",
            yil=year,
            tam_tatil_adedi=len(holidays),
            yarim_gun_adedi=len(half_days),
        )

    def _get_national_holidays(self, year: int) -> set[date]:
        """O yıla ait sabit milli bayram günlerinin tarihlerini döndürür."""
        result = set()
        for _, (month, day) in FIXED_HOLIDAYS.items():
            try:
                result.add(date(year, month, day))
            except ValueError:
                continue
        return result

    def _load_cache(self) -> None:
        """Diskteki önbellek dosyasından takvim verilerini yükler."""
        if not self._cache_file.exists():
            return
        try:
            with open(self._cache_file, "rb") as f:
                data = orjson.loads(f.read())
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
            logger.info("tatil_onbellegi_yuklendi", yuklenen_yil_sayisi=len(self._holidays))
        except Exception as e:
            logger.warning("tatil_onbellegi_yukleme_hatasi", hata=str(e))

    def _save_cache(self, force: bool = False) -> None:
        """Takvim durumunu diske JSON formatında kaydeder.

        SSD koruması amacıyla 60 saniyelik debounce mekanizması içerir.

        Args:
            force: True ise bekleme süresine bakılmaksızın derhal kaydeder.
        """
        now = time.time()
        if not force and (now - self._last_cache_save < DEFAULT_CACHE_SAVE_DEBOUNCE_SECONDS):
            return

        self._last_cache_save = now
        data = {
            "holidays": {str(y): [d.isoformat() for d in sorted(dates)] for y, dates in self._holidays.items()},
            "half_days": {str(y): [d.isoformat() for d in sorted(dates)] for y, dates in self._half_days.items()},
            "sudden": [d.isoformat() for d in sorted(self._sudden_detector.get_confirmed())],
            "blacklist": [d.isoformat() for d in sorted(self._blacklist)],
            "updated_at": datetime.now(UTC).isoformat(),
        }
        try:
            with open(self._cache_file, "wb") as f:
                f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2))
        except Exception as e:
            logger.warning("tatil_onbellegi_kaydetme_hatasi", hata=str(e))

    def _log_audit(self, action: str, d: date, reason: str = "", flush: bool = False) -> None:
        """Yapılan tatil değişikliklerini SSD dostu şekilde denetim dosyasına kaydeder.

        Args:
            action: İşlem kodu (add, remove, auto_detect, kap_detect).
            d: Hedef takvim tarihi.
            reason: İşlem gerekçesi.
            flush: True ise geciktirmeden derhal dosyaya yazar.
        """
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "date": d.isoformat(),
            "reason": reason,
        }
        self._pending_audit_entries.append(entry)

        if not flush and not should_save("holiday_audit", 60) and len(self._pending_audit_entries) < 10:
            return

        try:
            if self._audit_file.exists():
                with open(self._audit_file, "rb") as f:
                    data = orjson.loads(f.read())
            else:
                data = {"entries": []}

            data["entries"].extend(self._pending_audit_entries)
            self._pending_audit_entries.clear()

            if len(data["entries"]) > DEFAULT_MAX_AUDIT_ENTRIES:
                data["entries"] = data["entries"][-DEFAULT_MAX_AUDIT_ENTRIES:]

            with open(self._audit_file, "wb") as f:
                f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2))
        except Exception as e:
            logger.debug("denetim_kaydi_yazma_hatasi", hata=str(e))

    def __repr__(self) -> str:
        """Tatil yöneticisi Türkçe metin gösterimi.

        Returns:
            str: Yıl ve önbellek özeti.
        """
        with self._lock:
            return (
                f"HolidayManager(tanimli_yillar={list(self._holidays.keys())}, "
                f"anlik_tatil_adedi={len(self._sudden_detector.get_confirmed())})"
            )


# =====================================================
# MODÜL DÜZEYİNDE DIŞA AKTARIM VE YARDIMCI FONKSİYONLAR
# =====================================================


def get_holiday_manager() -> HolidayManager:
    """Global HolidayManager tekil örneğini döner.

    Returns:
        HolidayManager: Paylaşılan tatil yöneticisi.
    """
    return holiday_manager


def export_holidays_to_polars(
    year: int | None = None,
    manager: HolidayManager | None = None,
) -> pl.DataFrame:
    """Belirtilen yılın tatillerini Polars DataFrame olarak dışa aktarır.

    Args:
        year: Hedef yıl (None ise mevcut yıl).
        manager: Kullanılacak HolidayManager nesnesi (None ise global singleton).

    Returns:
        pl.DataFrame: Tatil takvimi tablosu.
    """
    mgr = manager if manager is not None else holiday_manager
    return mgr.export_to_polars(year=year)


def export_holidays_to_duckdb(
    db_path: str | Path | None = None,
    year: int | None = None,
    manager: HolidayManager | None = None,
) -> int:
    """Tatil takvimini DuckDB `bist_holidays_audit` tablosuna depolar.

    Args:
        db_path: DuckDB veritabanı dosya yolu.
        year: Hedef yıl.
        manager: Kullanılacak HolidayManager nesnesi.

    Returns:
        int: Eklenen veya güncellenen kayıt sayısı.
    """
    mgr = manager if manager is not None else holiday_manager
    return mgr.export_to_duckdb(db_path=db_path, year=year)


def export_holiday_audit_to_polars(
    limit: int = DEFAULT_MAX_AUDIT_ENTRIES,
    manager: HolidayManager | None = None,
) -> pl.DataFrame:
    """Tatil değişiklik denetim loglarını Polars DataFrame olarak dışa aktarır.

    Args:
        limit: Maksimum kayıt sayısı.
        manager: HolidayManager örneği.

    Returns:
        pl.DataFrame: Denetim logları tablosu.
    """
    mgr = manager if manager is not None else holiday_manager
    return mgr.export_audit_to_polars(limit=limit)


def export_holiday_audit_to_duckdb(
    db_path: str | Path | None = None,
    limit: int = DEFAULT_MAX_AUDIT_ENTRIES,
    manager: HolidayManager | None = None,
) -> int:
    """Tatil denetim loglarını DuckDB `bist_holiday_audit_trail` tablosuna depolar.

    Args:
        db_path: DuckDB dosya yolu.
        limit: Maksimum kayıt sayısı.
        manager: HolidayManager örneği.

    Returns:
        int: Eklenen satır sayısı.
    """
    mgr = manager if manager is not None else holiday_manager
    return mgr.export_audit_to_duckdb(db_path=db_path, limit=limit)


# Global Singleton Örneği
holiday_manager: Final[HolidayManager] = HolidayManager()

__all__: list[str] = [
    "DEFAULT_CHECK_INTERVAL_SECONDS",
    "DEFAULT_EXPECTED_DATA_INTERVAL_MINUTES",
    "DEFAULT_HOLIDAY_AUDIT_DB_PATH",
    "DEFAULT_HTTP_TIMEOUT_SECONDS",
    "DEFAULT_MAX_AUDIT_ENTRIES",
    "DEFAULT_MAX_RETRIES",
    "FIXED_HOLIDAYS",
    "HALF_DAY_EVES",
    "KURBAN_REFERENCES",
    "RAMAZAN_REFERENCES",
    "HolidayAuditEntry",
    "HolidayInfo",
    "HolidayManager",
    "HolidayType",
    "KAPHolidayWatcher",
    "SuddenHolidayDetector",
    "_compute_half_days_eves",
    "_compute_hijri_holidays",
    "_fetch_with_retry",
    "_get_kurban_start",
    "_get_proxy",
    "_get_ramazan_start",
    "export_holiday_audit_to_duckdb",
    "export_holiday_audit_to_polars",
    "export_holidays_to_duckdb",
    "export_holidays_to_polars",
    "fetch_bist_holidays_from_web",
    "get_holiday_manager",
    "holiday_manager",
]
