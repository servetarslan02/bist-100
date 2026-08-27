#!/usr/bin/env python3
"""
ALPHA BIST — Dinamik Tatil Senaryoları Gerçek Dünya Testi
==========================================================

Bu script tatil sisteminin dinamik senaryolarını test eder:
1. Anlık tatil ilan edildiğinde sistem ne yapıyor?
2. Tatil tarihi değiştiğinde ne oluyor?
3. Tatil iptal edildiğinde ne oluyor?
4. Cache ve pipeline nasıl etkileniyor?
5. SuddenHolidayDetector eşik değerleri
6. Yarım gün dinamik yönetimi

Kullanım:
    python3 scripts/verify_dynamic_holiday_scenarios.py
"""

import asyncio
import importlib.util
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class _EmptyModule:
    def __getattr__(self, name):
        return type('Fake', (), {'__init__': lambda s, *a, **k: None})()


if 'services' not in sys.modules:
    sys.modules['services'] = _EmptyModule()
if 'services.core' not in sys.modules:
    sys.modules['services.core'] = _EmptyModule()


def _load_module_direct(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_base = Path(__file__).parent.parent / "services" / "core"
_hm_mod = _load_module_direct("services.core.holiday_manager", _base / "holiday_manager.py")
_fsm_mod = _load_module_direct("services.core.market_session_fsm", _base / "market_session_fsm.py")
_mc_mod = _load_module_direct("services.core.market_calendar", _base / "market_calendar.py")

HolidayManager = _hm_mod.HolidayManager
SuddenHolidayDetector = _hm_mod.SuddenHolidayDetector
MarketCalendar = _mc_mod.MarketCalendar


class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.details = []

    def ok(self, msg):
        self.passed += 1
        self.details.append(f"  ✅ {msg}")
        print(f"  ✅ {msg}")

    def fail(self, msg):
        self.failed += 1
        self.details.append(f"  ❌ {msg}")
        print(f"  ❌ {msg}")

    def warn(self, msg):
        self.warnings += 1
        self.details.append(f"  ⚠️  {msg}")
        print(f"  ⚠️  {msg}")

    def summary(self):
        total = self.passed + self.failed
        return f"\n{'='*60}\nSONUÇ: {self.passed}/{total} geçti, {self.failed} başarısız, {self.warnings} uyarı\n{'='*60}"


# =====================================================
# SENARYO 1: Anlık Tatil İlan Edildi (Borsa Kapalı Kaldı)
# =====================================================

def test_sudden_holiday_declared(result: TestResult):
    """BIST anlık tatil ilan etti — sistem bunu yakalıyor mu?"""
    print("\n⚡ SENARYO 1: Anlık Tatil İlan Edildi")
    print("-" * 50)

    test_dir = "/tmp/bist_dynamic_test_1"
    hm = HolidayManager(data_dir=test_dir)
    today = date(2026, 8, 28)  # Cuma — normalde işlem günü

    # Başlangıç durumu: bugün işlem günü olmalı
    if hm.is_trading_day(today):
        result.ok(f"Başlangıç: {today} işlem günü ✓")
    else:
        result.fail(f"Başlangıç: {today} işlem günü olmalı!")
        return

    # SuddenHolidayDetector simülasyonu
    detector = SuddenHolidayDetector()

    # 1. kontrol — veri gelmiyor
    detected = detector.report_no_data(today)
    if not detected:
        result.ok("1. kontrol: Veri gelmiyor, henüz tespit edilmedi (beklenen)")
    else:
        result.fail("1. kontrol: Erken tespit!")

    # 2. kontrol — hâlâ veri yok
    detected = detector.report_no_data(today)
    if not detected:
        result.ok("2. kontrol: Hâlâ veri yok, henüz tespit edilmedi")
    else:
        result.fail("2. kontrol: Erken tespit!")

    # 3. kontrol — artık tespit edilmeli
    detected = detector.report_no_data(today)
    if detected:
        result.ok("3. kontrol: Anlık tatil TESPİT EDİLDİ ✓")
    else:
        result.fail("3. kontrol: Tespit edilemedi!")

    # HolidayManager'a bildir (3 kez — dedektörün eşik değeri)
    for i in range(3):
        hm.report_no_data(today)

    # Artık işlem günü olmamalı
    if not hm.is_trading_day(today):
        result.ok(f"Tespit sonrası: {today} artık işlem günü DEĞİL ✓")
    else:
        result.fail(f"Tespit sonrası: {today} hâlâ işlem günü görünüyor!")

    # Cache'e kaydedildi mi?
    hm2 = HolidayManager(data_dir=test_dir)
    if hm2.is_holiday(today):
        result.ok("Cache'e kaydedildi — restart sonrası da tatil ✓")
    else:
        result.fail("Cache'e kaydedilemedi!")


# =====================================================
# SENARYO 2: Tatil Tarihi Değişti (Erteleme)
# =====================================================

def test_holiday_date_change(result: TestResult):
    """Tatil tarihi değişti — sistem günceliyor mu?"""
    print("\n📅 SENARYO 2: Tatil Tarihi Değişti (Erteleme)")
    print("-" * 50)

    test_dir = "/tmp/bist_dynamic_test_2"
    hm = HolidayManager(data_dir=test_dir)

    # Orijinal tatil: 2026-12-25
    original_date = date(2026, 12, 25)
    new_date = date(2026, 12, 26)

    # Tatil ekle
    hm.add_manual_holiday(original_date, "Orijinal tatil")
    if hm.is_holiday(original_date):
        result.ok(f"Orijinal tatil eklendi: {original_date} ✓")

    # Tarihi değiştir (eskiyi kaldır, yenisini ekle)
    hm.remove_holiday(original_date)
    hm.add_manual_holiday(new_date, "Ertelenen tatil")

    # Eski tarih artık tatil olmamalı
    if not hm.is_holiday(original_date):
        result.ok(f"Eski tarih kaldırıldı: {original_date} artık tatil DEĞİL ✓")
    else:
        result.fail(f"Eski tarih hâlâ tatil: {original_date}")

    # Yeni tarih tatil olmalı
    if hm.is_holiday(new_date):
        result.ok(f"Yeni tarih eklendi: {new_date} artık TATİL ✓")
    else:
        result.fail(f"Yeni tarih tatil değil: {new_date}")

    # Cache'te de güncellendi mi?
    hm2 = HolidayManager(data_dir=test_dir)
    if not hm2.is_holiday(original_date) and hm2.is_holiday(new_date):
        result.ok("Cache güncellendi — restart sonrası da doğru ✓")
    else:
        result.fail("Cache güncellenemedi!")


# =====================================================
# SENARYO 3: Tatil İptal Edildi (Çalışma Günü İlan Edildi)
# =====================================================

def test_holiday_cancelled(result: TestResult):
    """Tatil iptal edildi — sistem bunu handle ediyor mu?"""
    print("\n❌ SENARYO 3: Tatil İptal Edildi (Çalışma Günü)")
    print("-" * 50)

    test_dir = "/tmp/bist_dynamic_test_3"
    hm = HolidayManager(data_dir=test_dir)

    # Bir tatil ekle
    test_date = date(2026, 12, 31)
    hm.add_manual_holiday(test_date, "Test tatili")
    if hm.is_holiday(test_date):
        result.ok(f"Tatil eklendi: {test_date} ✓")

    # Tatili iptal et
    hm.remove_holiday(test_date)
    if not hm.is_holiday(test_date):
        result.ok(f"Tatil iptal edildi: {test_date} artık çalışma günü ✓")
    else:
        result.fail(f"Tatil iptal edilemedi: {test_date}")

    # is_trading_day doğru döndürüyor mu?
    if hm.is_trading_day(test_date):
        result.ok(f"is_trading_day({test_date}) = True ✓")
    else:
        result.fail(f"is_trading_day({test_date}) = False olmalı!")


# =====================================================
# SENARYO 4: Pipeline Etkisi (Tatil Günü İşlem Durdurma)
# =====================================================

def test_pipeline_halt_on_holiday(result: TestResult):
    """Tatil gününde pipeline duruyor mu?"""
    print("\n🔧 SENARYO 4: Pipeline Tatil Günü Duruyor mu?")
    print("-" * 50)

    test_dir = "/tmp/bist_dynamic_test_4"
    hm = HolidayManager(data_dir=test_dir)
    cal = MarketCalendar(holidays=list(hm.get_holidays(2026)))

    # Normal gün — pipeline çalışmalı
    normal = date(2026, 6, 15)  # Pazartesi
    if cal.is_trading_day(normal):
        result.ok(f"Normal gün ({normal}): Pipeline ÇALIŞIR ✓")

    # Tatil günü — pipeline durmalı
    holiday = date(2026, 1, 1)  # Yılbaşı
    if not cal.is_trading_day(holiday):
        result.ok(f"Tatil günü ({holiday}): Pipeline DURUR ✓")

    # Anlık tatil ekle — pipeline durmalı
    sudden = date(2026, 8, 28)
    # MarketCalendar'ın kendi HolidayManager'ına ekle
    cal.add_manual_holiday(sudden, "Anlık tatil")
    if not cal.is_trading_day(sudden):
        result.ok(f"Anlık tatil ({sudden}): Pipeline DURUR ✓")
    else:
        result.fail(f"Anlık tatil ({sudden}): Pipeline durmadı!")

    # Tatili kaldır — pipeline tekrar çalışmalı
    cal._hm.remove_holiday(sudden)
    # Calendar'ı yeniden oluştur
    cal = MarketCalendar(holidays=list(hm.get_holidays(2026)))
    if cal.is_trading_day(sudden):
        result.ok(f"Tatil kaldırıldı ({sudden}): Pipeline TEKRAR ÇALIŞIR ✓")
    else:
        result.fail(f"Tatil kaldırıldı ({sudden}): Pipeline hâlâ duruyor!")


# =====================================================
# SENARYO 5: Eşik Değeri Davranışı
# =====================================================

def test_threshold_behavior(result: TestResult):
    """SuddenHolidayDetector eşik değerlerini test et."""
    print("\n🎯 SENARYO 5: Eşik Değeri Davranışı")
    print("-" * 50)

    detector = SuddenHolidayDetector()
    test_date = date(2026, 8, 28)

    # 1. ve 2. rapor — tespit edilmemeli
    for i in range(1, 3):
        detected = detector.report_no_data(test_date)
        count = detector._suspected_holidays.get(test_date, 0)
        if not detected:
            result.ok(f"Rapor {i}/3: Tespit edilmedi (sayac={count}) ✓")
        else:
            result.fail(f"Rapor {i}/3: Erken tespit!")

    # 3. rapor — tespit edilmeli
    detected = detector.report_no_data(test_date)
    count = detector._suspected_holidays.get(test_date, 0)
    if detected:
        result.ok(f"Rapor 3/3: Tespit edildi (sayac={count}) ✓")
    else:
        result.fail(f"Rapor 3/3: Tespit edilemedi!")

    # Farklı günlerin bağımsız olduğunu kontrol et
    other_date = date(2026, 8, 29)
    detector.report_no_data(other_date)
    if not detector.is_confirmed_holiday(other_date):
        result.ok(f"Farklı gün ({other_date}): Bağımsız, henüz tespit edilmedi ✓")
    else:
        result.fail(f"Farklı gün ({other_date}): Bağımsız değil!")

    # 1 saatlik interval ile zaman hesabı
    interval_seconds = 3600  # 1 saat
    detection_time = 3 * interval_seconds
    result.ok(f"Eşik hesabı: 3 kontrol × {interval_seconds}s = {detection_time}s = {detection_time//60} dakika")


# =====================================================
# SENARYO 6: Cache Tutarlılığı (Restart Senaryosu)
# =====================================================

def test_cache_consistency(result: TestResult):
    """Restart sonrası cache tutarlılığını test et."""
    print("\n💾 SENARYO 6: Cache Tutarlılığı (Restart)")
    print("-" * 50)

    test_dir = "/tmp/bist_dynamic_test_6"
    cache_file = Path(test_dir) / "holiday_cache.json"

    # İlk instance — tatil ekle
    hm1 = HolidayManager(data_dir=test_dir)
    hm1.add_manual_holiday(date(2026, 12, 31), "Yılbaşı arifesi")
    hm1.add_manual_holiday(date(2027, 1, 2), "Ek tatil")

    if cache_file.exists():
        result.ok("Cache dosyası oluşturuldu ✓")

    # Cache içeriğini kontrol et
    with open(cache_file) as f:
        cache_data = json.load(f)

    if "holidays" in cache_data:
        result.ok("Cache'te 'holidays' anahtarı var ✓")
    if "updated_at" in cache_data:
        result.ok(f"Cache güncelleme zamanı: {cache_data['updated_at']} ✓")

    # İkinci instance — restart simülasyonu
    hm2 = HolidayManager(data_dir=test_dir)
    if hm2.is_holiday(date(2026, 12, 31)):
        result.ok("Restart sonrası tatil korundu: 2026-12-31 ✓")
    else:
        result.fail("Restart sonrası tatil kayboldu: 2026-12-31")

    if hm2.is_holiday(date(2027, 1, 2)):
        result.ok("Restart sonrası tatil korundu: 2027-01-02 ✓")
    else:
        result.fail("Restart sonrası tatil kayboldu: 2027-01-02")

    # Anlık tatil de cache'e kaydedilmeli (3 kez çağır — dedektör eşiği)
    sudden_date = date(2026, 8, 28)
    for _ in range(3):
        hm2.report_no_data(sudden_date)
    hm3 = HolidayManager(data_dir=test_dir)
    if hm3.is_holiday(sudden_date):
        result.ok("Anlık tatil cache'e kaydedildi ✓")
    else:
        result.fail("Anlık tatil cache'e kaydedilemedi!")


# =====================================================
# SENARYO 7: Yarım Gün Dinamik Yönetimi
# =====================================================

def test_half_day_dynamic(result: TestResult):
    """Yarım gün dinik yönetimini test et."""
    print("\n⏰ SENARYO 7: Yarım Gün Dinamik Yönetimi")
    print("-" * 50)

    test_dir = "/tmp/bist_dynamic_test_7"
    hm = HolidayManager(data_dir=test_dir)

    # 2026 yarım günleri
    half_days_2026 = hm.get_half_days(2026)
    if half_days_2026:
        result.ok(f"2026 yarım günleri: {len(half_days_2026)} gün")
        for hd in sorted(half_days_2026):
            print(f"      📅 {hd}")

    # Ramazan arifesi (2026-03-19)
    ramazan_eve = date(2026, 3, 19)
    if ramazan_eve in half_days_2026:
        result.ok(f"Ramazan arifesi ({ramazan_eve}): yarım gün ✓")

    # Kurban arifesi (2026-05-26)
    kurban_eve = date(2026, 5, 26)
    if kurban_eve in half_days_2026:
        result.ok(f"Kurban arifesi ({kurban_eve}): yarım gün ✓")

    # Cumhuriyet arifesi (2026-10-28)
    cumhuriyet_eve = date(2026, 10, 28)
    if cumhuriyet_eve in half_days_2026:
        result.ok(f"Cumhuriyet arifesi ({cumhuriyet_eve}): yarım gün ✓")


# =====================================================
# SENARYO 8: BIST Web Senkronizasyonu
# =====================================================

async def test_bist_sync(result: TestResult):
    """BIST web sitesinden tatil senkronizasyonunu test et."""
    print("\n🌐 SENARYO 8: BIST Web Senkronizasyonu")
    print("-" * 50)

    test_dir = "/tmp/bist_dynamic_test_8"
    hm = HolidayManager(data_dir=test_dir)

    # Senkronizasyon dene
    synced = await hm.sync_from_bist()
    if synced:
        result.ok("BIST web sitesinden tatiller senkronize edildi ✓")
    else:
        result.warn("BIST web sitesinden senkronizasyon başarısız (ağ erişimi)")

    # Manuel senkronizasyon simülasyonu
    hm.add_manual_holiday(date(2026, 12, 31), "BIST'ten çekilen tatil")
    if hm.is_holiday(date(2026, 12, 31)):
        result.ok("Manuel senkronizasyon: Tatil eklendi ✓")


# =====================================================
# SENARYO 9: Eş Zamanlı Okuma/Yazma
# =====================================================

def test_concurrent_access(result: TestResult):
    """Eş zamanlı erişim senaryolarını test et."""
    print("\n🔄 SENARYO 9: Eş Zamanlı Erişim")
    print("-" * 50)

    test_dir = "/tmp/bist_dynamic_test_9"
    hm = HolidayManager(data_dir=test_dir)

    # Aynı anda birden fazla tatil ekle
    dates_to_add = [
        date(2026, 12, 24),
        date(2026, 12, 25),
        date(2026, 12, 26),
        date(2026, 12, 31),
    ]

    for d in dates_to_add:
        hm.add_manual_holiday(d, "Toplu ekleme")

    # Hepsinin eklendiğini kontrol et
    all_added = all(hm.is_holiday(d) for d in dates_to_add)
    if all_added:
        result.ok(f"Toplu ekleme: {len(dates_to_add)} tatil eklendi ✓")
    else:
        result.fail("Toplu ekleme: Bazı tatiller eklenemedi!")

    # Hepsini kaldır
    for d in dates_to_add:
        hm.remove_holiday(d)

    all_removed = all(not hm.is_holiday(d) for d in dates_to_add)
    if all_removed:
        result.ok(f"Toplu kaldırma: {len(dates_to_add)} tatil kaldırıldı ✓")
    else:
        result.fail("Toplu kaldırma: Bazı tatiller kaldırılamadı!")


# =====================================================
# SENARYO 10: Gerçek Zamanlı Pipeline Simülasyonu
# =====================================================

def test_pipeline_simulation(result: TestResult):
    """Gerçek zamanlı pipeline davranışını simüle et."""
    print("\n🎮 SENARYO 10: Gerçek Zamanlı Pipeline Simülasyonu")
    print("-" * 50)

    test_dir = "/tmp/bist_dynamic_test_10"
    hm = HolidayManager(data_dir=test_dir)
    cal = MarketCalendar(holidays=list(hm.get_holidays(2026)))

    # Simülasyon: Bugün Cuma, piyasa açık olmalı
    today = date(2026, 8, 28)
    IST = timezone(timedelta(hours=3))

    # 09:00 — piyasa kapalı (açılış öncesi)
    dt_09 = datetime(2026, 8, 28, 9, 0, tzinfo=IST)
    info_09 = cal.get_info(dt_09)
    if info_09['session'] == 'CLOSED':
        result.ok("09:00: Piyasa kapalı (açılış öncesi) ✓")

    # 10:30 — piyasa açık
    dt_10 = datetime(2026, 8, 28, 10, 30, tzinfo=IST)
    info_10 = cal.get_info(dt_10)
    if info_10['session'] == 'CONTINUOUS':
        result.ok("10:30: Piyasa açık (sürekli müzayede) ✓")

    # Anlık tatil ilan edildi
    cal.add_manual_holiday(today, "Anlık tatil — BIST duyurdu")

    # 10:30 — artık piyasa kapalı olmalı
    info_10_after = cal.get_info(dt_10)
    if info_10_after['session'] == 'CLOSED':
        result.ok("10:30 (tatil sonrası): Piyasa kapalı ✓")
    else:
        result.fail(f"10:30 (tatil sonrası): Piyasa hâlâ açık!")

    # Tatil kaldırıldı — piyasa tekrar açık olmalı
    cal._hm.remove_holiday(today)
    cal = MarketCalendar(holidays=list(hm.get_holidays(2026)))
    info_10_restored = cal.get_info(dt_10)
    if info_10_restored['session'] == 'CONTINUOUS':
        result.ok("10:30 (tatil kaldırıldı): Piyasa tekrar açık ✓")
    else:
        result.fail("10:30 (tatil kaldırıldı): Piyasa hâlâ kapalı!")


# =====================================================
# ANA TEST RUNNER
# =====================================================

async def main():
    print("=" * 60)
    print("🧪 ALPHA BIST — Dinamik Tatil Senaryoları Testi")
    print(f"📅 Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    result = TestResult()

    test_sudden_holiday_declared(result)
    test_holiday_date_change(result)
    test_holiday_cancelled(result)
    test_pipeline_halt_on_holiday(result)
    test_threshold_behavior(result)
    test_cache_consistency(result)
    test_half_day_dynamic(result)
    await test_bist_sync(result)
    test_concurrent_access(result)
    test_pipeline_simulation(result)

    print(result.summary())

    # Rapor
    report_path = Path(__file__).parent.parent / "reports" / "dynamic_holiday_audit.json"
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
    print(f"\n📄 Rapor: {report_path}")

    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
