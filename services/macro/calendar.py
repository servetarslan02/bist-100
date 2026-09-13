"""
ALPHA BIST — Macro Calendar v2.0

Makro olay takvimi:
- MACRO_EVENTS: Sabit olay listesi
- get_macro_events(): Tüm olayları getir
- get_upcoming_events(): Yaklaşan olayları getir
- get_event_impact(): Olay etkisi
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# Kurumsal makro olay tanımları ve küresel/yerel etki dereceleri
MACRO_EVENTS: dict[str, dict[str, Any]] = {
    "TCMB_PPK": {
        "description": "TCMB Para Politikası Kurulu Faiz Kararı",
        "impact": "HIGH",
        "indicator": "POLICY_RATE",
        "frequency": "monthly",
        "volatility_surge_expected": True,
    },
    "CPI_RELEASE": {
        "description": "TÜİK Tüketici Fiyat Endeksi (TÜFE) Açıklaması",
        "impact": "HIGH",
        "indicator": "CPI",
        "frequency": "monthly",
        "volatility_surge_expected": True,
    },
    "PPI_RELEASE": {
        "description": "TÜİK Yurt İçi Üretici Fiyat Endeksi (Yİ-ÜFE) Açıklaması",
        "impact": "MEDIUM",
        "indicator": "PPI",
        "frequency": "monthly",
        "volatility_surge_expected": False,
    },
    "GDP_RELEASE": {
        "description": "TÜİK Dönemsel GSYH Büyüme Raporu",
        "impact": "HIGH",
        "indicator": "GDP",
        "frequency": "quarterly",
        "volatility_surge_expected": True,
    },
    "UNEMPLOYMENT": {
        "description": "TÜİK İşgücü İstatistikleri",
        "impact": "MEDIUM",
        "indicator": "UNEMPLOYMENT",
        "frequency": "monthly",
        "volatility_surge_expected": False,
    },
    "INDUSTRIAL": {
        "description": "TÜİK Sanayi Üretim Endeksi",
        "impact": "MEDIUM",
        "indicator": "INDUSTRIAL_PRODUCTION",
        "frequency": "monthly",
        "volatility_surge_expected": False,
    },
    "TRADE_BALANCE": {
        "description": "Ticaret Bakanlığı / TÜİK Dış Ticaret Dengesi",
        "impact": "MEDIUM",
        "indicator": "TRADE_BALANCE",
        "frequency": "monthly",
        "volatility_surge_expected": False,
    },
    "CURRENT_ACCOUNT": {
        "description": "TCMB Ödemeler Dengesi ve Cari İşlemler Raporu",
        "impact": "MEDIUM",
        "indicator": "CURRENT_ACCOUNT",
        "frequency": "monthly",
        "volatility_surge_expected": False,
    },
    "FOMC": {
        "description": "FED Federal Açık Piyasa Komitesi Faiz Kararı",
        "impact": "HIGH",
        "indicator": "FED_RATE",
        "frequency": "8_per_year",
        "volatility_surge_expected": True,
    },
    "ECB": {
        "description": "Avrupa Merkez Bankası Para Politikası Kararı",
        "impact": "MEDIUM",
        "indicator": "ECB_RATE",
        "frequency": "8_per_year",
        "volatility_surge_expected": False,
    },
    "US_CPI": {
        "description": "ABD Çalışma İstatistikleri Bürosu (BLS) TÜFE Açıklaması",
        "impact": "HIGH",
        "indicator": "US_CPI",
        "frequency": "monthly",
        "volatility_surge_expected": True,
    },
}

# Olay bazlı detaylı sektör duyarlılık katsayıları (-1.0 ile +1.0)
EVENT_SECTOR_SENSITIVITY: dict[str, dict[str, float]] = {
    "TCMB_PPK": {
        "BANK": 0.35,  # Faiz döngüsü marj etkisi
        "REIT_GYO": -0.85,  # Konut kredisi ve iskonto oranı duyarlılığı
        "INDUSTRIAL_LEVERAGED": -0.65,  # Finansman maliyeti artışı
        "CASH_RICH": 0.50,  # Net nakit faiz geliri artışı
        "RETAIL": -0.20,  # Tüketici talebi daralması
    },
    "CPI_RELEASE": {
        "RETAIL_SUPERMARKET": 0.70,  # Fiyat geçişkenliği ve sepet artışı (BIMAS, MGROS)
        "TELECOM": 0.40,  # Enflasyonist tarife yenilemeleri
        "INDUSTRIAL_FIXED_PRICE": -0.55,  # Girdi maliyet sıkışması
        "BANK": -0.25,  # Fonlama maliyeti baskısı
    },
    "TRADE_BALANCE": {
        "EXPORTER": 0.75,  # İhracatçı sanayi (EREGL, FROTO, ARCLK)
        "ENERGY_IMPORTER": -0.60,  # İthalat maliyeti baskısı
        "AVIATION": 0.45,  # Döviz gelir avantajı
    },
    "FOMC": {
        "EM_EQUITIES": -0.50,  # Gelişmekte olan piyasa sermaye akımları
        "BANK": -0.40,  # Küresel likidite sıkılaşması
        "GOLD_MINING": -0.60,  # Dolar endeksi baskısı
    },
}


def get_macro_events() -> dict[str, dict[str, Any]]:
    """Tüm makro olay listesini ve meta-bilgilerini döndürür."""
    return MACRO_EVENTS


def _get_first_business_day(year: int, month: int, day: int) -> datetime:
    """Belirtilen gün hafta sonuna denk geliyorsa takip eden ilk iş gününü döndürür."""
    d = datetime(year, month, day, 10, 0, tzinfo=UTC)
    while d.weekday() >= 5:  # Cumartesi (5) veya Pazar (6)
        d += timedelta(days=1)
    return d


def _get_tcmb_dates(year: int) -> list[datetime]:
    """TCMB PPK toplantı tarihlerini hesaplar (Her ayın 3. Perşembesi)."""
    dates: list[datetime] = []
    for m in range(1, 13):
        for day in range(15, 29):
            try:
                d = datetime(year, m, day, 14, 0, tzinfo=UTC)
                if d.weekday() == 3:  # Perşembe saat 14:00 PPK
                    dates.append(d)
                    break
            except ValueError:
                continue
    return dates


def _get_fomc_dates(year: int) -> list[datetime]:
    """FOMC faiz kararı tarihlerini hesaplar (Yılda 8 kez Çarşamba günleri)."""
    # Standart FOMC ayları: Ocak, Mart, Mayıs, Haziran, Temmuz, Eylül, Kasım, Aralık
    fomc_months = [1, 3, 5, 6, 7, 9, 11, 12]
    dates: list[datetime] = []
    for m in fomc_months:
        for day in range(12, 28):
            try:
                d = datetime(year, m, day, 21, 0, tzinfo=UTC)
                if d.weekday() == 2:  # Çarşamba 21:00 TR
                    dates.append(d)
                    break
            except ValueError:
                continue
    return dates


def get_upcoming_events(days: int = 14) -> list[dict[str, Any]]:
    """Belirtilen gün penceresi içindeki yaklaşan tüm yerel ve küresel makro olayları listeler.

    Args:
        days: Geleceğe dönük gün ufku (varsayılan 14 gün).

    Returns:
        list[dict[str, Any]]: Tarihe göre sıralı yaklaşan olaylar ve etki değerlendirmeleri.
    """
    now = datetime.now(UTC)
    cutoff = now + timedelta(days=days)
    upcoming: list[dict[str, Any]] = []

    # 1. TCMB PPK Tarihleri
    for date in _get_tcmb_dates(now.year) + _get_tcmb_dates(now.year + 1):
        if now.date() <= date.date() <= cutoff.date():
            upcoming.append(
                {
                    "event_type": "TCMB_PPK",
                    "date": date.strftime("%Y-%m-%d"),
                    "time": "14:00",
                    "description": MACRO_EVENTS["TCMB_PPK"]["description"],
                    "impact": MACRO_EVENTS["TCMB_PPK"]["impact"],
                    "days_until": (date.date() - now.date()).days,
                    "volatility_risk": "HIGH",
                }
            )

    # 2. TÜİK TÜFE Açıklaması (Her ayın 3'ü, hafta sonu ise ilk pazartesi saat 10:00)
    for m_offset in range(0, 3):
        m = ((now.month - 1 + m_offset) % 12) + 1
        y = now.year if (now.month + m_offset <= 12) else now.year + 1
        cpi_date = _get_first_business_day(y, m, 3)
        if now.date() <= cpi_date.date() <= cutoff.date():
            upcoming.append(
                {
                    "event_type": "CPI_RELEASE",
                    "date": cpi_date.strftime("%Y-%m-%d"),
                    "time": "10:00",
                    "description": MACRO_EVENTS["CPI_RELEASE"]["description"],
                    "impact": MACRO_EVENTS["CPI_RELEASE"]["impact"],
                    "days_until": (cpi_date.date() - now.date()).days,
                    "volatility_risk": "HIGH",
                }
            )

    # 3. ABD TÜFE Açıklaması (Her ayın 10-14 arası Çarşamba/Perşembe)
    for m_offset in range(0, 3):
        m = ((now.month - 1 + m_offset) % 12) + 1
        y = now.year if (now.month + m_offset <= 12) else now.year + 1
        for day in range(10, 15):
            d = datetime(y, m, day, 15, 30, tzinfo=UTC)
            if d.weekday() in (2, 3):  # Çarşamba veya Perşembe
                if now.date() <= d.date() <= cutoff.date():
                    upcoming.append(
                        {
                            "event_type": "US_CPI",
                            "date": d.strftime("%Y-%m-%d"),
                            "time": "15:30",
                            "description": MACRO_EVENTS["US_CPI"]["description"],
                            "impact": MACRO_EVENTS["US_CPI"]["impact"],
                            "days_until": (d.date() - now.date()).days,
                            "volatility_risk": "MEDIUM",
                        }
                    )
                break

    # 4. FOMC Faiz Kararları
    for date in _get_fomc_dates(now.year) + _get_fomc_dates(now.year + 1):
        if now.date() <= date.date() <= cutoff.date():
            upcoming.append(
                {
                    "event_type": "FOMC",
                    "date": date.strftime("%Y-%m-%d"),
                    "time": "21:00",
                    "description": MACRO_EVENTS["FOMC"]["description"],
                    "impact": MACRO_EVENTS["FOMC"]["impact"],
                    "days_until": (date.date() - now.date()).days,
                    "volatility_risk": "HIGH",
                }
            )

    return sorted(upcoming, key=lambda x: (x["days_until"], x["date"]))


def get_event_impact(event_type: str) -> dict[str, Any]:
    """Belirli bir makro olayın genel piyasa ve sektör bazlı detaylı etki analizini döndürür.

    Args:
        event_type: Makro olay kodu (ör: TCMB_PPK, CPI_RELEASE, FOMC).

    Returns:
        dict[str, Any]: Olay açıklaması, etki derecesi ve sektör duyarlılık katsayıları.
    """
    event = MACRO_EVENTS.get(event_type)
    if not event:
        return {"error": f"Unknown event type: {event_type}"}

    # Özel sektör etki matrisi varsa onu kullan, yoksa genel etki şablonu ata
    if event_type in EVENT_SECTOR_SENSITIVITY:
        sector_sensitivities = EVENT_SECTOR_SENSITIVITY[event_type]
    else:
        multiplier = 0.8 if event["impact"] == "HIGH" else (0.4 if event["impact"] == "MEDIUM" else 0.2)
        sector_sensitivities = {
            "BANK": round(0.5 * multiplier, 2),
            "INDUSTRIAL": round(0.4 * multiplier, 2),
            "RETAIL": round(0.3 * multiplier, 2),
            "ENERGY": round(0.3 * multiplier, 2),
        }

    return {
        "event_type": event_type,
        "description": event["description"],
        "impact": event["impact"],
        "indicator": event["indicator"],
        "volatility_surge_expected": event.get("volatility_surge_expected", False),
        "sector_impacts": sector_sensitivities,
    }


__all__ = [
    "MACRO_EVENTS",
    "EVENT_SECTOR_SENSITIVITY",
    "get_macro_events",
    "get_upcoming_events",
    "get_event_impact",
]


