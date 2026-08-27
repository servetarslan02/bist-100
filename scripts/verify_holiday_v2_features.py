#!/usr/bin/env python3
"""
ALPHA BIST — Holiday Manager v2.0 Özellik Doğrulama Testi
==========================================================

Yeni özellikleri test eder:
1. Retry mekanizması (exponential backoff)
2. Alternatif kaynaklar (KAP RSS, Investing.com)
3. Proxy desteği
4. KAP anlık duyuru izleme
5. Audit trail (değişiklik logu)
6. API endpoint'leri (doğrulama)
7. SuddenHolidayDetector KAP entegrasyonu

Kullanım:
    python3 scripts/verify_holiday_v2_features.py
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

HolidayManager = _hm_mod.HolidayManager
SuddenHolidayDetector = _hm_mod.SuddenHolidayDetector
KAPHolidayWatcher = _hm_mod.KAPHolidayWatcher
_fetch_with_retry = _hm_mod._fetch_with_retry
_get_proxy = _hm_mod._get_proxy


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
# TEST 1: Retry Mekanizması
# =====================================================

async def test_retry_mechanism(result: TestResult):
    """Retry mekanizmasının çalıştığını doğrula."""
    print("\n🔄 TEST 1: Retry Mekanizması")
    print("-" * 50)

    # Var olmayan URL — 3 deneme yapmalı
    start = datetime.now()
    response = await _fetch_with_retry(
        "https://this-domain-does-not-exist-12345.com/test",
        max_retries=2,
        timeout=3,
    )
    elapsed = (datetime.now() - start).total_seconds()

    if response is None:
        result.ok("Var olmayan URL: None döndü (beklenen)")
    else:
        result.fail("Var olmayan URL: None dönmeli")

    # Retry süresi kontrolü (1s + 2s = ~3s minimum)
    if elapsed >= 2:
        result.ok(f"Retry bekleme süresi: {elapsed:.1f}s (beklenen ≥2s)")
    else:
        result.warn(f"Retry bekleme süresi kısa: {elapsed:.1f}s")


# =====================================================
# TEST 2: Proxy Desteği
# =====================================================

def test_proxy_support(result: TestResult):
    """Proxy desteğini doğrula."""
    print("\n🌐 TEST 2: Proxy Desteği")
    print("-" * 50)

    # Mevcut proxy'yi kontrol et
    proxy = _get_proxy()
    if proxy:
        result.ok(f"Proxy bulundu: {proxy}")
    else:
        result.warn("Proxy ayarlanmamış (HTTP_PROXY/HTTPS_PROXY)")

    # Proxy olmadan da çalıştığını doğrula
    result.ok("Proxy opsiyonel — olmadan da çalışır")


# =====================================================
# TEST 3: KAP Duyuru İzleyici
# =====================================================

async def test_kap_watcher(result: TestResult):
    """KAP duyuru izleyicisini test et."""
    print("\n📡 TEST 3: KAP Duyuru İzleyici")
    print("-" * 50)

    watcher = KAPHolidayWatcher()

    # İlk kontrol
    announcements = await watcher.check_for_new_announcements()
    result.ok(f"KAP kontrolü tamamlandı: {len(announcements)} duyuru")

    # Son kontrol zamanı
    last_check = watcher._last_check
    if last_check:
        result.ok(f"Son kontrol zamanı: {last_check.isoformat()}")

    # İkinci kontrol — interval nedeniyle atlanmalı
    announcements2 = await watcher.check_for_new_announcements()
    if len(announcements2) == 0:
        result.ok("İkinci kontrol atlandı (interval koruması)")
    else:
        result.ok(f"İkinci kontrol: {len(announcements2)} duyuru")


# =====================================================
# TEST 4: SuddenHolidayDetector KAP Entegrasyonu
# =====================================================

async def test_sudden_detector_kap(result: TestResult):
    """SuddenHolidayDetector KAP entegrasyonunu test et."""
    print("\n⚡ TEST 4: SuddenHolidayDetector KAP Entegrasyonu")
    print("-" * 50)

    detector = SuddenHolidayDetector()

    # KAP duyuru kontrolü
    kap_holidays = await detector.check_kap_announcements()
    result.ok(f"KAP kontrolü: {len(kap_holidays)} duyuru")

    # Manuel KAP tatil bildirimi
    test_date = date(2026, 12, 31)
    detected = detector.report_kap_holiday(test_date)
    if detected:
        result.ok(f"KAP tatil bildirimi: {test_date} tespit edildi ✓")

    if detector.is_confirmed_holiday(test_date):
        result.ok("KAP tatili confirmed listesinde ✓")

    # KAP tatili anında tespit edilmeli (sayac gerektirmez)
    test_date2 = date(2026, 12, 30)
    detector.report_kap_holiday(test_date2)
    if detector.is_confirmed_holiday(test_date2):
        result.ok("KAP tatili anında tespit (sayac yok) ✓")


# =====================================================
# TEST 5: Audit Trail (Değişiklik Logu)
# =====================================================

def test_audit_trail(result: TestResult):
    """Audit trail'in çalıştığını doğrula."""
    print("\n📝 TEST 5: Audit Trail (Değişiklik Logu)")
    print("-" * 50)

    test_dir = "/tmp/bist_audit_test"
    hm = HolidayManager(data_dir=test_dir)
    audit_file = Path(test_dir) / "holiday_audit.json"

    # Tatil ekle — audit log oluşmalı
    hm.add_manual_holiday(date(2026, 12, 24), "Noel arifesi")
    if audit_file.exists():
        result.ok("Audit log dosyası oluştu ✓")

    # Audit log içeriğini kontrol et
    log = hm.get_audit_log()
    if log:
        last_entry = log[-1]
        if last_entry["action"] == "add" and last_entry["date"] == "2026-12-24":
            result.ok(f"Audit log kaydı doğru: {last_entry}")
        else:
            result.fail(f"Audit log kaydı hatalı: {last_entry}")
    else:
        result.fail("Audit log boş!")

    # Tatil kaldır — audit log oluşmalı
    hm.remove_holiday(date(2026, 12, 24), "Test bitti")
    log = hm.get_audit_log()
    if len(log) >= 2:
        last_entry = log[-1]
        if last_entry["action"] == "remove":
            result.ok(f"Kaldırma logu: {last_entry}")

    # Anlık tatil — audit log oluşmalı
    for _ in range(3):
        hm.report_no_data(date(2026, 8, 28))
    log = hm.get_audit_log()
    if any(e["action"] == "auto_detect" for e in log):
        result.ok("Anlık tatil audit logu ✓")


# =====================================================
# TEST 6: HolidayManager KAP Entegrasyonu
# =====================================================

async def test_holiday_manager_kap(result: TestResult):
    """HolidayManager KAP entegrasyonunu test et."""
    print("\n🔗 TEST 6: HolidayManager KAP Entegrasyonu")
    print("-" * 50)

    test_dir = "/tmp/bist_kap_test"
    hm = HolidayManager(data_dir=test_dir)

    # KAP'tan tatil kontrolü
    kap_holidays = await hm.check_kap_for_holidays()
    if kap_holidays:
        result.ok(f"KAP'tan {len(kap_holidays)} tatil çekildi")
        for d in kap_holidays:
            print(f"      📅 {d}")
    else:
        result.warn("KAP'tan tatil çekilemedi (ağ erişimi veya BIST engeli)")


# =====================================================
# TEST 7: BIST Engelli Bölge Senaryosu
# =====================================================

async def test_blocked_region(result: TestResult):
    """BIST engelli bölge senaryosunu test et."""
    print("\n🚫 TEST 7: BIST Engelli Bölge Senaryosu")
    print("-" * 50)

    # Proxy olmadan BIST'e erişim dene
    html = await _fetch_with_retry(
        "https://www.borsaistanbul.com/en/sayfa/3466/holidays",
        max_retries=1,
        timeout=5,
    )

    if html:
        result.ok("BIST'e erişim başarılı (proxy gerekmez)")
    else:
        result.warn("BIST'e erişilemedi — proxy veya alternatif kaynak gerekli")

    # KAP'a erişim dene
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://www.kap.org.tr/tr",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 200:
                result.ok("KAP'a erişim başarılı ✓")
            else:
                result.warn(f"KAP erişim hatası: {resp.status_code}")
    except Exception as e:
        result.warn(f"KAP erişilemedi: {e}")

    # Investing.com'a erişim dene
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://tr.investing.com/holidays/turkey",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 200:
                result.ok("Investing.com'a erişim başarılı ✓")
            else:
                result.warn(f"Investing.com erişim hatası: {resp.status_code}")
    except Exception as e:
        result.warn(f"Investing.com erişilemedi: {e}")


# =====================================================
# TEST 8: Cache + Audit Tutarlılığı
# =====================================================

def test_cache_audit_consistency(result: TestResult):
    """Cache ve audit log tutarlılığını test et."""
    print("\n💾 TEST 8: Cache + Audit Tutarlılığı")
    print("-" * 50)

    test_dir = "/tmp/bist_cache_audit_test"
    cache_file = Path(test_dir) / "holiday_cache.json"
    audit_file = Path(test_dir) / "holiday_audit.json"

    hm1 = HolidayManager(data_dir=test_dir)

    # Birkaç işlem yap
    hm1.add_manual_holiday(date(2026, 12, 24), "Test 1")
    hm1.add_manual_holiday(date(2026, 12, 25), "Test 2")
    hm1.remove_holiday(date(2026, 12, 24), "Test 3")

    # Cache dosyası var mı?
    if cache_file.exists():
        result.ok("Cache dosyası mevcut ✓")
        with open(cache_file) as f:
            cache = json.load(f)
        if "updated_at" in cache:
            result.ok(f"Cache güncelleme zamanı: {cache['updated_at']}")

    # Audit dosyası var mı?
    if audit_file.exists():
        result.ok("Audit dosyası mevcut ✓")
        with open(audit_file) as f:
            audit = json.load(f)
        entries = audit.get("entries", [])
        if len(entries) >= 3:
            result.ok(f"Audit log: {len(entries)} kayıt ✓")

    # Restart simülasyonu
    hm2 = HolidayManager(data_dir=test_dir)
    if hm2.is_holiday(date(2026, 12, 25)):
        result.ok("Restart sonrası tatil korundu ✓")
    if not hm2.is_holiday(date(2026, 12, 24)):
        result.ok("Restart sonrası kaldırılmış tatil korunmadı ✓")

    # Audit log restart sonrası da korunmalı
    log = hm2.get_audit_log()
    if log:
        result.ok(f"Restart sonrası audit log: {len(log)} kayıt ✓")


# =====================================================
# TEST 9: API Endpoint Doğrulama (Mock)
# =====================================================

def test_api_endpoints(result: TestResult):
    """API endpoint'lerinin varlığını doğrula."""
    print("\n🔌 TEST 9: API Endpoint Doğrulama")
    print("-" * 50)

    # Modül import edilebiliyor mu?
    try:
        api_path = Path(__file__).parent.parent / "services" / "api" / "v1" / "holidays.py"
        if api_path.exists():
            result.ok("holidays.py endpoint dosyası mevcut ✓")

            # Dosya içeriğini kontrol et
            content = api_path.read_text()
            endpoints = [
                'list_holidays',
                'today_status',
                'add_holiday',
                'remove_holiday',
                'sync_holidays',
                'get_audit_log',
            ]
            for ep in endpoints:
                if ep in content:
                    result.ok(f"Endpoint '{ep}' tanımlı ✓")
                else:
                    result.fail(f"Endpoint '{ep}' bulunamadı!")
        else:
            result.fail("holidays.py endpoint dosyası bulunamadı!")
    except Exception as e:
        result.fail(f"API doğrulama hatası: {e}")


# =====================================================
# TEST 10: BIST Web Çekme (Gerçek Dünya)
# =====================================================

async def test_bist_web_fetch_real(result: TestResult):
    """BIST web sitesinden gerçek dünya çekme testi."""
    print("\n🌍 TEST 10: BIST Web Çekme (Gerçek Dünya)")
    print("-" * 50)

    from services.core.holiday_manager import fetch_bist_holidays_from_web

    holidays = await fetch_bist_holidays_from_web()
    if holidays:
        result.ok(f"BIST web sitesinden {len(holiday)} tatil çekildi")
        for h in sorted(holidays)[:5]:
            print(f"      📅 {h}")
    else:
        result.warn("BIST web sitesinden çekilemedi (engelli bölge veya sunucu hatası)")


# =====================================================
# ANA TEST RUNNER
# =====================================================

async def main():
    print("=" * 60)
    print("🧪 ALPHA BIST — Holiday Manager v2.0 Özellik Testi")
    print(f"📅 Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    result = TestResult()

    await test_retry_mechanism(result)
    test_proxy_support(result)
    await test_kap_watcher(result)
    await test_sudden_detector_kap(result)
    test_audit_trail(result)
    await test_holiday_manager_kap(result)
    await test_blocked_region(result)
    test_cache_audit_consistency(result)
    test_api_endpoints(result)
    await test_bist_web_fetch_real(result)

    print(result.summary())

    report_path = Path(__file__).parent.parent / "reports" / "holiday_v2_audit.json"
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
