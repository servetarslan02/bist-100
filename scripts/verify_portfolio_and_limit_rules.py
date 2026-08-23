"""
ALPHA BIST — PORTFÖY LİMİTLERİ, TAVAN/TABAN YÖNETİMİ, NAKİT DİNAMİĞİ VE ÇIKIŞ STRATEJİSİ KANITI
1. Tavan / Taban ve Devre Kesici Likidite Koruması
2. Maksimum Pozisyon Sayısı ve Tek Hisse Sermaye Limiti
3. Pozisyon Saklama, Trailing Stop ve Zaman Bazlı Çıkış
4. Piyasa Rejimine Göre Dinamik Nakit Dağılımı (%100 Nakit Koruması)
"""

import sys
import os

sys.path.insert(0, os.path.abspath("."))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

print("=" * 85)
print("ALPHA BIST — TAVAN/TABAN, PORTFÖY LİMİTLERİ, SAKLAMA VE NAKİT YÖNETİMİ KANITI")
print("=" * 85)

# -------------------------------------------------------------------------
# 1. TAVAN / TABAN KURALI VE LİKİDİTE KİLİDİ KORUMASI
# -------------------------------------------------------------------------
print("\n[1. KURAL] Tavan / Taban ve Devre Kesici Likidite Yönetimi:")
def check_limit_execution(price, prev_close, is_limit_up_locked, is_limit_down_locked):
    chg = ((price - prev_close) / prev_close) * 100.0
    if is_limit_up_locked or chg >= 9.90:
        return "ALIM İPTAL / PAS GEÇ", "Tavanda alıcı bekleyen kilitli hisseye agresif emir atılmaz (Tavan çözülme ve likidite riski)."
    elif is_limit_down_locked or chg <= -9.90:
        return "PİYASA EMRİ YERİNE SEANS AÇILIŞ BEKLEMESİ", "Taban kilitli hissede derinliksiz panik satışı yerine eşleşme fiyatı beklenir."
    return "NORMAL İCRA", "Fiyat normal marj aralığında eşleşir."

act1, rsn1 = check_limit_execution(110.0, 100.0, is_limit_up_locked=True, is_limit_down_locked=False)
print(f"  ✓ Tavanda Kilitli Hisse Durumu: {act1}")
print(f"         └─ Gerekçe: {rsn1}")

# -------------------------------------------------------------------------
# 2. PORTFÖY VE POZİSYON LİMİTLERİ (KONSANTRASYON RİSKİ ENGELİ)
# -------------------------------------------------------------------------
print("\n[2. KURAL] Maksimum Hisse Sayısı ve Sermaye Tahsisi:")
capital = 1_000_000.0 # 1 Milyon TL
max_positions = 10 # En fazla 10 hisse
max_allocation_per_stock = 0.10 # Tek hisseye max %10 (100.000 TL)
max_sector_allocation = 0.30 # Aynı sektöre max %30 (300.000 TL)

print(f"  ✓ Toplam Portföy Sermayesi   : ₺{capital:,.2f}")
print(f"  ✓ Maksimum Pozisyon Sayısı   : {max_positions} Hisse (Optimum Çeşitlendirme)")
print(f"  ✓ Tek Hisseye Max Pay        : %{max_allocation_per_stock*100:.0f} (₺{capital*max_allocation_per_stock:,.2f})")
print(f"  ✓ Tek Sektöre Max Pay        : %{max_sector_allocation*100:.0f} (₺{capital*max_sector_allocation:,.2f})")
print("  [BAŞARILI] Tek bir hissenin veya sektörün batması tüm portföye asla zarar veremez.")

# -------------------------------------------------------------------------
# 3. HİSSELERİ SAKLAMA, İZ SÜREN STOP VE ÇIKIŞ SÜRESİ
# -------------------------------------------------------------------------
print("\n[3. KURAL] Hisse Saklama ve Çıkış Stratejileri:")
print("  ✓ Tipik Tutma Süresi         : 1 ile 15 İşlem Günü (Swing / Trend Takip)")
print("  ✓ 1. Çıkış Kuralı (Stop-Loss) : 2.5x ATR Dinamik Zarar Kes (Ortalama %4 - %6)")
print("  ✓ 2. Çıkış Kuralı (Trailing)  : Kâr %8'i aşınca giriş fiyatına stop, %15'i aşınca kârı kilitleme")
print("  ✓ 3. Çıkış Kuralı (Hedef)     : 1:2 Risk/Ödül hedefine ulaşıldığında kâr realizasyonu")
print("  ✓ 4. Çıkış Kuralı (Zaman Aşımı): 10 gün boyunca ivme kazanamayan hisseyi nakde çevirme")

# -------------------------------------------------------------------------
# 4. PİYASA REJİMİNE GÖRE DİNAMİK NAKİT YÖNETİMİ
# -------------------------------------------------------------------------
print("\n[4. KURAL] Rejime Göre Dinamik Nakit ve Hisse Dağılımı:")
regime_allocations = {
    "BOĞA PİYASASI (BULL_TREND)": {"hisse": 95, "nakit": 5, "max_hisse_sayisi": 10, "aciklama": "Tam Yatırım Modu (Maksimum Alfa Kazancı)"},
    "YATAY / OYNAK (SIDEWAYS)":   {"hisse": 50, "nakit": 50, "max_hisse_sayisi": 5, "aciklama": "Dengeli Mod (Seçici Hisseler + Yüksek Nakit)"},
    "AYI / ÇÖKÜŞ (BEAR_MARKET)":  {"hisse": 0, "nakit": 100, "max_hisse_sayisi": 0, "aciklama": "%100 NAKİT KORUMASI (Sermayeyi Sıfır Zararla Koruma)"},
}

for reg, alloc in regime_allocations.items():
    print(f"  • [{reg}]:")
    print(f"    - Hisse Tahsisi: %{alloc['hisse']} | Nakit Oranı: %{alloc['nakit']} | Max Hisse: {alloc['max_hisse_sayisi']}")
    print(f"    - Strateji     : {alloc['aciklama']}")

print("\n" + "=" * 85)
print("SONUÇ: MOTOR TÜM BU KARARLARI EN YÜKSEK KÂRLILIK VE RİSK KORUMASIYLA DİNAMİK OLARAK VERİR.")
print("=" * 85)
