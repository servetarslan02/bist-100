#!/usr/bin/env python3
import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
ALPHA BIST — Tatil Sistemi Gerçek Dünya Doğrulama Testi
========================================================

Bu script tatil sisteminin tüm katmanlarını gerçek dünya senaryolarıyla test eder:
1. Milli bayram doğruluğu (sabit tarihler)
2. Dini bayram hesaplama doğruluğu (Hicri takvim)
3. BIST resmi web sitesinden tatil çekme
4. SuddenHolidayDetector (anlık tatil tespiti)
5. Pipeline entegrasyonu (tatil gününde pipeline duruyor mu?)
6. Yarım gün yönetimi
7. Cache mekanizması
8. Edge case'ler (yılbaşı, hafta sonu tatil çakışması)

Kullanım:
    python scripts/verify_holiday_system_real_world.py
"""

import asyncio
import importlib.util
import json
import sys
from datetime import date, datetime
from pathlib import Path

# Proje kökünü PYTHONPATH'e ekle
sys.path.insert(0, str(Path(__file__).parent.parent))


# __init__.py zincirini tamamen bypass et
# services.core paketini boş bir modül olarak kaydet, böylece alt modüller
# import edildiğinde __init__.py çalışmaz
class _EmptyModule:
    """Boş modül — __init__.py zincirini kırmak için."""

    def __getattr__(self, name) -> Any:
        """Otomatik eklendi."""
        return type("Fake", (), {"__init__": lambda s, *a, **k: None})()


# services ve services.core'u boş olarak kaydet
if "services" not in sys.modules:
    sys.modules["services"] = _EmptyModule()
if "services.core" not in sys.modules:
    sys.modules["services.core"] = _EmptyModule()


def _load_module_direct(name, path) -> Any:
    """Otomatik eklendi."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# holiday_manager'ı yükle (structlog ve httpx gerektirir)
_hm_path = Path(__file__).parent.parent / "services" / "core" / "holiday_manager.py"
_hm_mod = _load_module_direct("services.core.holiday_manager", _hm_path)
HolidayManager = _hm_mod.HolidayManager
SuddenHolidayDetector = _hm_mod.SuddenHolidayDetector
_compute_hijri_holidays = _hm_mod._compute_hijri_holidays
_compute_half_days_eves = _hm_mod._compute_half_days_eves
fetch_bist_holidays_from_web = _hm_mod.fetch_bist_holidays_from_web


# =====================================================
# Test Yardımcıları
# =====================================================


class TestResult:
    """Otomatik eklendi."""
    def __init__(self):
        """Otomatik eklendi."""
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.details: list[str] = []

    def ok(self, msg: str) -> Any:
        """Otomatik eklendi."""
        self.passed += 1
        self.details.append(f"  ✅ {msg}")
        logger.info(f"  ✅ {msg}")

    def fail(self, msg: str) -> Any:
        """Otomatik eklendi."""
        self.failed += 1
        self.details.append(f"  ❌ {msg}")
        logger.info(f"  ❌ {msg}")

    def warn(self, msg: str) -> Any:
        """Otomatik eklendi."""
        self.warnings += 1
        self.details.append(f"  ⚠️  {msg}")
        logger.info(f"  ⚠️  {msg}")

    def summary(self) -> str:
        """Otomatik eklendi."""
        total = self.passed + self.failed
        return f"\n{'=' * 60}\nSONUÇ: {self.passed}/{total} geçti, {self.failed} başarısız, {self.warnings} uyarı\n{'=' * 60}"


# =====================================================
# TEST 1: Milli Bayram Doğruluğu
# =====================================================


def test_national_holidays(result: TestResult) -> Any:
    """Sabit milli bayramların doğruluğunu kontrol et."""
    logger.info("\n📋 TEST 1: Milli Bayram Doğruluğu")
    logger.info("-" * 40)

    hm = HolidayManager(data_dir="/tmp/bist_holiday_test")

    expected_2026 = {
        date(2026, 1, 1): "Yılbaşı",
        date(2026, 4, 23): "Ulusal Egemenlik ve Çocuk Bayramı",
        date(2026, 5, 1): "Emek ve Dayanışma Günü",
        date(2026, 5, 19): "Atatürk'ü Anma, Gençlik ve Spor Bayramı",
        date(2026, 7, 15): "Demokrasi ve Millî Birlik Günü",
        date(2026, 8, 30): "Zafer Bayramı",
        date(2026, 10, 29): "Cumhuriyet Bayramı",
    }

    holidays_2026 = hm.get_holidays(2026)

    for expected_date, name in expected_2026.items():
        if expected_date in holidays_2026:
            result.ok(f"{name} ({expected_date}) — listede var")
        else:
            result.fail(f"{name} ({expected_date}) — LİSTEDE YOK!")

    # Gelecek yıllar
    for year in [2027, 2028, 2029, 2030]:
        holidays = hm.get_holidays(year)
        national_count = sum(
            1 for d in holidays if (d.month, d.day) in [(1, 1), (4, 23), (5, 1), (5, 19), (7, 15), (8, 30), (10, 29)]
        )
        if national_count >= 7:
            result.ok(f"{year} yılı: {national_count} milli bayram var")
        else:
            result.fail(f"{year} yılı: sadece {national_count} milli bayram (7 olmalı)")


# =====================================================
# TEST 2: Dini Bayram Hesaplama
# =====================================================


def test_religious_holidays(result: TestResult) -> Any:
    """Dini bayram hesaplamalarının doğruluğunu kontrol et."""
    logger.info("\n🕌 TEST 2: Dini Bayram Hesaplama Doğruluğu")
    logger.info("-" * 40)

    # Referans tarihler (Diyanet İşleri Başkanlığı)
    expected_ramazan = {
        2024: date(2024, 4, 10),
        2025: date(2025, 3, 30),
        2026: date(2026, 3, 20),
        2027: date(2027, 3, 10),
    }

    expected_kurban = {
        2024: date(2024, 6, 17),
        2025: date(2025, 6, 7),
        2026: date(2026, 5, 27),
        2027: date(2027, 5, 17),
    }

    for year, expected_start in expected_ramazan.items():
        computed = _compute_hijri_holidays(year)
        ramazan_days = sorted([d for d in computed if d.month in (2, 3, 4)])
        if ramazan_days:
            if ramazan_days[0] == expected_start:
                result.ok(f"{year} Ramazan Bayramı başlangıcı: {ramazan_days[0]} — DOĞRU")
            else:
                result.fail(f"{year} Ramazan Bayramı: beklenen {expected_start}, hesaplanan {ramazan_days[0]}")
            if len(ramazan_days) == 3:
                result.ok(f"{year} Ramazan Bayramı: 3 gün — DOĞRU")
            else:
                result.warn(f"{year} Ramazan Bayramı: {len(ramazan_days)} gün (beklenen 3)")
        else:
            result.fail(f"{year} Ramazan Bayramı hesaplanamadı!")

    for year, expected_start in expected_kurban.items():
        computed = _compute_hijri_holidays(year)
        kurban_days = sorted([d for d in computed if d.month in (5, 6, 7)])
        if kurban_days:
            if kurban_days[0] == expected_start:
                result.ok(f"{year} Kurban Bayramı başlangıcı: {kurban_days[0]} — DOĞRU")
            else:
                result.fail(f"{year} Kurban Bayramı: beklenen {expected_start}, hesaplanan {kurban_days[0]}")
            if len(kurban_days) == 4:
                result.ok(f"{year} Kurban Bayramı: 4 gün — DOĞRU")
            else:
                result.warn(f"{year} Kurban Bayramı: {len(kurban_days)} gün (beklenen 4)")
        else:
            result.fail(f"{year} Kurban Bayramı hesaplanamadı!")


# =====================================================
# TEST 3: Yarım Gün Yönetimi
# =====================================================


def test_half_days(result: TestResult) -> Any:
    """Yarım gün (tatil arifesi) yönetimini kontrol et."""
    logger.info("\n⏰ TEST 3: Yarım Gün Yönetimi")
    logger.info("-" * 40)

    hm = HolidayManager(data_dir="/tmp/bist_holiday_test")

    for year in [2026, 2027]:
        half_days = hm.get_half_days(year)
        if half_days:
            result.ok(f"{year} yılı: {len(half_days)} yarım gün tespit edildi")
            for hd in sorted(half_days):
                logger.info(f"      📅 {hd} — yarım gün (12:30 kapanış)")
        else:
            result.warn(f"{year} yılı: yarım gün tespit edilemedi")

    # Cumhuriyet Bayramı arifesi (28 Ekim) her yıl yarım gün olmalı
    for year in [2026, 2027, 2028]:
        half_days = hm.get_half_days(year)
        oct_28 = date(year, 10, 28)
        if oct_28 in half_days:
            result.ok(f"{year} 28 Ekim (Cumhuriyet arifesi) — yarım gün ✓")
        else:
            result.fail(f"{year} 28 Ekim yarım gün olmalı!")


# =====================================================
# TEST 4: BIST Resmi Web Çekme
# =====================================================


async def test_bist_web_fetch(result: TestResult) -> Any:
    """BIST resmi web sitesinden tatil çekmeyi test et."""
    logger.info("\n🌐 TEST 4: BIST Resmi Web Sitesinden Tatil Çekme")
    logger.info("-" * 40)

    try:
        holidays = await fetch_bist_holidays_from_web()
        if holidays:
            result.ok(f"BIST web sitesinden {len(holidays)} tatil çekildi")
            for h in sorted(holidays)[:10]:
                logger.info(f"      📅 {h}")
            if len(holidays) > 10:
                logger.info(f"      ... ve {len(holidays) - 10} tane daha")
        else:
            result.warn("BIST web sitesinden tatil çekilemedi (ağ erişimi veya sayfa yapısı değişmiş olabilir)")
    except Exception as e:
        result.warn(f"BIST web çekme hatası: {e}")


# =====================================================
# TEST 5: SuddenHolidayDetector (Anlık Tatil Tespiti)
# =====================================================


def test_sudden_holiday_detector(result: TestResult) -> Any:
    """Anlık tatil tespit mekanizmasını test et."""
    logger.info("\n⚡ TEST 5: SuddenHolidayDetector (Anlık Tatil Tespiti)")
    logger.info("-" * 40)

    detector = SuddenHolidayDetector()
    test_date = date(2026, 8, 28)

    # 1. ve 2. rapor — henüz tatil olarak kabul edilmemeli
    for i in range(2):
        detected = detector.report_no_data(test_date)
        if not detected:
            result.ok(f"Rapor {i + 1}/3: Henüz tatil olarak tespit edilmedi (beklenen)")
        else:
            result.fail(f"Rapor {i + 1}/3: Erken tespit! (3. raporu beklemeli)")

    # 3. rapor — artık tatil olarak kabul edilmeli
    detected = detector.report_no_data(test_date)
    if detected:
        result.ok("Rapor 3/3: Anlık tatil tespit edildi ✓")
    else:
        result.fail("Rapor 3/3: Tatil tespit edilemedi!")

    # Confirmed listesinde olmalı
    if detector.is_confirmed_holiday(test_date):
        result.ok("Tespit edilen tatil confirmed listesinde ✓")
    else:
        result.fail("Tespit edilen tatil confirmed listesinde DEĞİL!")

    # Farklı günlerin bağımsız çalıştığını kontrol et
    other_date = date(2026, 8, 29)
    if not detector.is_confirmed_holiday(other_date):
        result.ok("Farklı günler bağımsız çalışıyor ✓")
    else:
        result.fail("Farklı günler birbirini etkiliyor!")


# =====================================================
# TEST 6: Pipeline Entegrasyonu (Tatil Günü)
# =====================================================


def test_pipeline_holiday_integration(result: TestResult) -> Any:
    """Tatil gününde pipeline'ın durduğunu doğrula."""
    logger.info("\n🔧 TEST 6: Pipeline Tatil Entegrasyonu")
    logger.info("-" * 40)

    # market_session_fsm ve market_calendar'ı doğrudan yükle
    _base = Path(__file__).parent.parent / "services" / "core"
    _fsm_path = _base / "market_session_fsm.py"
    _fsm_mod = _load_module_direct("services.core.market_session_fsm", _fsm_path)
    _mc_path = _base / "market_calendar.py"
    _mc_mod = _load_module_direct("services.core.market_calendar", _mc_path)
    MarketCalendar = _mc_mod.MarketCalendar

    # Test: Tatil gününde is_trading_day False dönmeli
    hm = HolidayManager(data_dir="/tmp/bist_holiday_test")
    cal = MarketCalendar(holidays=list(hm.get_holidays(2026)))

    # Yılbaşı testi
    new_year = date(2026, 1, 1)
    if not cal.is_trading_day(new_year):
        result.ok("Yılbaşı (2026-01-01): is_trading_day=False ✓")
    else:
        result.fail("Yılbaşı işlem günü olarak görülüyor!")

    # Normal gün testi
    normal_day = date(2026, 6, 15)  # Pazartesi
    if cal.is_trading_day(normal_day):
        result.ok("Normal gün (2026-06-15 Pzt): is_trading_day=True ✓")
    else:
        result.fail("Normal gün tatil olarak görülüyor!")

    # Hafta sonu testi
    saturday = date(2026, 8, 22)
    if not cal.is_trading_day(saturday):
        result.ok("Cumartesi (2026-08-22): is_trading_day=False ✓")
    else:
        result.fail("Cumartesi işlem günü olarak görülüyor!")

    # Ramazan Bayramı testi
    ramazan_1 = date(2026, 3, 20)
    if not cal.is_trading_day(ramazan_1):
        result.ok("Ramazan Bayramı 1. gün (2026-03-20): is_trading_day=False ✓")
    else:
        result.fail("Ramazan Bayramı işlem günü olarak görülüyor!")

    # Kurban Bayramı testi
    kurban_1 = date(2026, 5, 27)
    if not cal.is_trading_day(kurban_1):
        result.ok("Kurban Bayramı 1. gün (2026-05-27): is_trading_day=False ✓")
    else:
        result.fail("Kurban Bayramı işlem günü olarak görülüyor!")

    # Zafer Bayramı (2026-08-30, Pazar — zaten hafta sonu)
    zafer = date(2026, 8, 30)
    if not cal.is_trading_day(zafer):
        result.ok("Zafer Bayramı (2026-08-30, Pazar): is_trading_day=False ✓")
    else:
        result.fail("Zafer Bayramı işlem günü olarak görülüyor!")


# =====================================================
# TEST 7: Hafta Sonu + Tatil Çakışması
# =====================================================


def test_weekend_holiday_overlap(result: TestResult) -> Any:
    """Hafta sonuna denk gelen tatillerin doğru yönetildiğini kontrol et."""
    logger.info("\n📅 TEST 7: Hafta Sonu + Tatil Çakışması")
    logger.info("-" * 40)

    hm = HolidayManager(data_dir="/tmp/bist_holiday_test")

    # 2026-08-30 Zafer Bayramı — Pazar
    zafer = date(2026, 8, 30)
    if zafer.weekday() == 6:  # Pazar
        result.ok("2026-08-30 Zafer Bayramı Pazar'a denk geliyor")
    else:
        result.warn(f"2026-08-30 haftanın {zafer.weekday()}. günü")

    # 2027-10-29 Cumhuriyet Bayramı — Cuma (işlem günü olmamalı)
    cumhuriyet_2027 = date(2027, 10, 29)
    holidays_2027 = hm.get_holidays(2027)
    if cumhuriyet_2027 in holidays_2027:
        result.ok("2027-10-29 Cumhuriyet Bayramı tatil listesinde ✓")
    else:
        result.fail("2027-10-29 Cumhuriyet Bayramı tatil listesinde DEĞİL!")

    # 2028-01-01 Yılbaşı — Cuma
    yilbasi_2028 = date(2028, 1, 1)
    holidays_2028 = hm.get_holidays(2028)
    if yilbasi_2028 in holidays_2028:
        result.ok("2028-01-01 Yılbaşı tatil listesinde ✓")
    else:
        result.fail("2028-01-01 Yılbaşı tatil listesinde DEĞİL!")


# =====================================================
# TEST 8: Cache Mekanizması
# =====================================================


def test_cache_mechanism(result: TestResult) -> Any:
    """Tatil cache mekanizmasının çalıştığını doğrula."""
    logger.info("\n💾 TEST 8: Cache Mekanizması")
    logger.info("-" * 40)

    test_dir = "/tmp/bist_holiday_cache_test"
    cache_file = Path(test_dir) / "holiday_cache.json"

    # İlk yükleme — cache oluştur
    hm1 = HolidayManager(data_dir=test_dir)
    holidays1 = hm1.get_holidays(2026)

    if cache_file.exists():
        result.ok("Cache dosyası oluşturuldu ✓")
    else:
        result.fail("Cache dosyası oluşturulamadı!")

    # Cache'ten yükleme
    hm2 = HolidayManager(data_dir=test_dir)
    holidays2 = hm2.get_holidays(2026)

    if holidays1 == holidays2:
        result.ok("Cache'ten yükleme tutarlı ✓")
    else:
        result.fail("Cache'ten yükleme tutarlı DEĞİL!")

    # Manuel tatil ekleme + cache güncelleme
    hm2.add_manual_holiday(date(2026, 12, 31), "Test tatili")
    hm3 = HolidayManager(data_dir=test_dir)
    if hm3.is_holiday(date(2026, 12, 31)):
        result.ok("Manuel tatil cache'e kaydedildi ve yüklendi ✓")
    else:
        result.fail("Manuel tatil cache'e kaydedilemedi!")


# =====================================================
# TEST 9: Edge Case'ler
# =====================================================


def test_edge_cases(result: TestResult) -> Any:
    """Edge case'leri test et."""
    logger.info("\n🔍 TEST 9: Edge Case'ler")
    logger.info("-" * 40)

    hm = HolidayManager(data_dir="/tmp/bist_holiday_edge_test")

    # Geçmiş yıl tatilleri
    holidays_2024 = hm.get_holidays(2024)
    if holidays_2024:
        result.ok(f"2024 yılı tatilleri hesaplandı: {len(holidays_2024)} gün")
    else:
        result.warn("2024 yılı tatilleri hesaplanamadı")

    # Gelecek yıl tatilleri (2030+)
    holidays_2030 = hm.get_holidays(2030)
    if holidays_2030:
        result.ok(f"2030 yılı tatilleri hesaplandı: {len(holidays_2030)} gün")
    else:
        result.warn("2030 yılı tatilleri hesaplanamadı")

    # Tatil metin formatı
    text = hm.get_all_holidays_text(2026)
    if "Yılbaşı" in text and "Ramazan" in text and "Kurban" in text:
        result.ok("Tatil metin formatı doğru ✓")
    else:
        result.fail("Tatil metin formatı eksik!")

    # Tatil kaldırma
    test_date = date(2026, 12, 25)
    hm.add_manual_holiday(test_date, "Test")
    if hm.is_holiday(test_date):
        result.ok("Manuel tatil eklendi ✓")
    hm.remove_holiday(test_date)
    if not hm.is_holiday(test_date):
        result.ok("Manuel tatil kaldırıldı ✓")
    else:
        result.fail("Manuel tatil kaldırılamadı!")


# =====================================================
# TEST 10: Gerçek Zamanlı Senaryo (Bugün)
# =====================================================


def test_today_scenario(result: TestResult) -> Any:
    """Bugünün gerçek zamanlı senaryosunu test et."""
    logger.info("\n🕐 TEST 10: Gerçek Zamanlı Senaryo (Bugün)")
    logger.info("-" * 40)

    today = date.today()
    hm = HolidayManager(data_dir="/tmp/bist_holiday_today")

    is_holiday = hm.is_holiday(today)
    is_half_day = hm.is_half_day(today)
    is_weekend = today.weekday() >= 5

    logger.info(f"      📅 Bugün: {today} ({today.strftime('%A')})")
    logger.info(f"      🏖️  Tatil mi: {is_holiday}")
    logger.info(f"      ⏰ Yarım gün mü: {is_half_day}")
    logger.info(f"      📆 Hafta sonu mu: {is_weekend}")

    _base2 = Path(__file__).parent.parent / "services" / "core"
    _fsm_path2 = _base2 / "market_session_fsm.py"
    if "services.core.market_session_fsm" not in sys.modules:
        _load_module_direct("services.core.market_session_fsm", _fsm_path2)
    _mc_path2 = _base2 / "market_calendar.py"
    if "services.core.market_calendar" not in sys.modules:
        _mc_mod2 = _load_module_direct("services.core.market_calendar", _mc_path2)
    else:
        _mc_mod2 = sys.modules["services.core.market_calendar"]
    MarketCalendar2 = _mc_mod2.MarketCalendar
    cal = MarketCalendar2()
    info = cal.get_info()

    logger.info(f"      🔔 İşlem günü: {info['is_trading_day']}")
    logger.info(f"      📊 Piyasa açık: {info['is_market_open']}")
    logger.info(f"      🎯 Seans: {info['session']}")
    logger.info(f"      ⏭️  Sonraki açılış: {info['next_open']}")

    result.ok(f"Bugünkü durum: {'TATİL' if is_holiday else 'HAFTA SONU' if is_weekend else 'İŞLEM GÜNÜ'}")


# =====================================================
# TEST 11: Dini Bayram Tutarlılık Kontrolü
# =====================================================


def test_religious_holiday_consistency(result: TestResult) -> Any:
    """Dini bayramların yıl bazında tutarlılığını kontrol et."""
    logger.info("\n🔄 TEST 11: Dini Bayram Tutarlılık Kontrolü")
    logger.info("-" * 40)

    # Her yıl Ramazan ve Kurban bayramları olmalı
    # _compute_hijri_holidays sıralı döndürür: önce Ramazan (3 gün), sonra Kurban (4 gün)
    # Ay filtresi yerine pozisyon bazlı filtre kullan (ayakışması sorununu önlemek için)
    for year in range(2024, 2031):
        computed = sorted(_compute_hijri_holidays(year))
        # Ramazan: ilk 3 gün, Kurban: sonraki 4 gün
        ramazan = computed[:3] if len(computed) >= 3 else computed
        kurban = computed[3:7] if len(computed) >= 7 else []

        if len(ramazan) == 3:
            result.ok(f"{year} Ramazan Bayramı: 3 gün ({ramazan[0]} - {ramazan[-1]})")
        else:
            result.fail(f"{year} Ramazan Bayramı: {len(ramazan)} gün (beklenen 3)")

        if len(kurban) == 4:
            result.ok(f"{year} Kurban Bayramı: 4 gün ({kurban[0]} - {kurban[-1]})")
        else:
            result.fail(f"{year} Kurban Bayramı: {len(kurban)} gün (beklenen 4)")

    # Yıllar arası kayma kontrolü (her yıl ~10-11 gün geri kaymalı)
    # Not: Ramazan her yıl ~10-11 gün ÖNE kayar (Hicri takvim 354 gün)
    # Yıl günü (day-of-year) kullanarak kayma hesapla
    prev_doy = None
    prev_year = None
    for year in range(2024, 2031):
        computed = sorted(_compute_hijri_holidays(year))
        ramazan = computed[:3] if len(computed) >= 3 else computed
        if ramazan:
            this_doy = ramazan[0].timetuple().tm_yday
            if prev_doy is not None:
                shift = prev_doy - this_doy  # Pozitif = yıl içinde öne kayma
                if 8 <= shift <= 14:
                    result.ok(f"{prev_year}→{year} Ramazan kayması: {shift} gün öne (beklenen ~10-11)")
                elif shift > 0:
                    result.warn(f"{prev_year}→{year} Ramazan kayması: {shift} gün (beklenen ~10-11)")
                else:
                    result.fail(f"{prev_year}→{year} Ramazan kayması: {shift} gün (beklenen pozitif)")
            prev_doy = this_doy
            prev_year = year


# =====================================================
# ANA TEST RUNNER
# =====================================================


async def main() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 60)
    logger.info("🧪 ALPHA BIST — Tatil Sistemi Gerçek Dünya Doğrulama Testi")
    logger.info(f"📅 Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    result = TestResult()

    # Tüm testleri çalıştır
    test_national_holidays(result)
    test_religious_holidays(result)
    test_half_days(result)
    await test_bist_web_fetch(result)
    test_sudden_holiday_detector(result)
    test_pipeline_holiday_integration(result)
    test_weekend_holiday_overlap(result)
    test_cache_mechanism(result)
    test_edge_cases(result)
    test_today_scenario(result)
    test_religious_holiday_consistency(result)

    # Sonuç
    logger.info(result.summary())

    # Rapor dosyası
    report_path = Path(__file__).parent.parent / "reports" / "holiday_system_audit.json"
    report_path.parent.mkdir(exist_ok=True)
    report = {
        "timestamp": datetime.now().isoformat(),
        "passed": result.passed,
        "failed": result.failed,
        "warnings": result.warnings,
        "details": result.details,
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info(f"\n📄 Rapor kaydedildi: {report_path}")

    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
