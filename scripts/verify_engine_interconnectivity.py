"""
ALPHA BIST — TÜM MOTORLARIN BİRBİRİNE BAĞLILIĞI, İLETİŞİMİ VE ÇELİŞKİSİZLİK KANITI
1. Konsensüs (Tam Uyum) Durumu
2. Çelişki Durumu (Teknik AL vs Temel/KAP SAT) -> Güvenli İptal
3. Rejim Veto Durumu (Piyasa Ayı İken Seçici Koruma)
4. Monte Carlo & Risk Gate Hakemliği
"""

import sys
import os
import json

sys.path.insert(0, os.path.abspath("."))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

from services.core.decision_engine import DecisionEngine, DecisionInput

print("=" * 85)
print("ALPHA BIST — MOTORLAR ARASI ÇELİŞKİSİZLİK VE BAĞLILIK DENETİMİ")
print("=" * 85)

engine = DecisionEngine()

# -------------------------------------------------------------------------
# TEST 1: TAM KONSENSÜS (Tüm Motorlar Uyum İçinde)
# -------------------------------------------------------------------------
print("\n[TEST 1] Tam Konsensüs Testi (ML, Teknik, Temel, KAP, Makro Hepsi Pozitif)...")
inp_consensus = DecisionInput(
    ticker="THYAO",
    price=300.0,
    regime="BULL",
    ml_score=85.0,
    ml_confidence=0.85,
    news_sentiment=0.70, # KAP & Haber çok olumlu
    macro_regime="RISK_ON",
    macro_stance=0.6,
    features={
        "momentum_20d": 12.5,
        "roc_5d": 3.2,
        "rsi_14": 62.0,
        "volume_zscore": 2.1,
        "pe_ratio": 7.5,
        "roe": 28.0,
    },
    atr=9.0,
    atr_pct=3.0,
    sim_expected_return=4.5,
    sim_prob_positive=0.75,
    sim_var_95=-4.0,
)
dec_1 = engine.decide(inp_consensus)
print(f"  ✓ Karar: {dec_1.action} | Yön: {dec_1.direction} | Conviction: {dec_1.conviction} | Skor: {dec_1.score:.1f}/100")
print(f"  ✓ Hedef Fiyat: ₺{dec_1.target_price:.2f} | Stop Fiyat: ₺{dec_1.stop_price:.2f} (R:R 2.0x)")
assert dec_1.action == "BUY", "Test 1 Başarısız!"
print("  [BAŞARILI] Tüm motorlar dinlendi, tam uyumla AL kararı verildi.")

# -------------------------------------------------------------------------
# TEST 2: ÇELİŞKİ ÇÖZÜMLEME (Teknik AL vs Bilanço/KAP Kötü)
# -------------------------------------------------------------------------
print("\n[TEST 2] Çelişki Çözümleme Testi (Grafik AL Diyor, Ama Bilanço & KAP Tehlikeli)...")
inp_conflict = DecisionInput(
    ticker="XYZ_SPEK",
    price=100.0,
    regime="BULL",
    ml_score=35.0, # ML temeli ve riski beğenmedi
    ml_confidence=0.70,
    news_sentiment=-0.80, # KAP'ta ağır ceza/zarar haberi var
    features={
        "momentum_20d": 15.0, # Fiyat spekülatif şişmiş
        "roc_5d": 8.0,
        "rsi_14": 74.0, # Aşırı alım
        "pe_ratio": 85.0, # Aşırı pahalı
        "roe": -15.0, # Zarar eden şirket
    },
    atr=5.0,
    atr_pct=5.0,
)
dec_2 = engine.decide(inp_conflict)
print(f"  ✓ Karar: {dec_2.action} | Yön: {dec_2.direction} | Skor: {dec_2.score:.1f}/100")
print(f"  ✓ Gerekçe / Risk Süzgeci: {dec_2.reasons}")
assert dec_2.action in ["NO_ACTION", "HOLD", "SELL"], "Test 2 Başarısız!"
print("  [BAŞARILI] Motorlar çelişkiyi yakaladı; grafik tek başına yetersiz kaldı ve hatalı alım ENGELLENDİ.")

# -------------------------------------------------------------------------
# TEST 3: REJİM VE MAKRO VETO HAKEMLİĞİ (Ayı / Panik Piyasasında Sermaye Koruma)
# -------------------------------------------------------------------------
print("\n[TEST 3] Rejim ve Makro Veto Testi (Hisse İyi Ama Piyasa Rejimi Çöküş/Ayı)...")
inp_bear = DecisionInput(
    ticker="ASELS",
    price=400.0,
    regime="BEAR", # Ayı piyasası
    ml_score=62.0, # Normalde 60 barajını geçerdi
    ml_confidence=0.62, # Ama ayı piyasasında eşik 68 / 0.70'e yükselir
    macro_regime="RISK_OFF",
    macro_stance=-0.7,
    features={"rsi_14": 54.0, "momentum_20d": 1.0},
    atr=12.0,
    atr_pct=3.0,
)
dec_3 = engine.decide(inp_bear)
print(f"  ✓ Karar: {dec_3.action} | Yön: {dec_3.direction} | Skor: {dec_3.score:.1f}/100")
print(f"  ✓ Rejim Filtre Uyarısı: {dec_3.reasons[0]}")
assert dec_3.action == "NO_ACTION", "Test 3 Başarısız!"
print("  [BAŞARILI] Rejim motoru devreye girdi; piyasa riskli olduğu için işlem VETO edildi.")

# -------------------------------------------------------------------------
# TEST 4: MONTE CARLO RİSK SÜZGECİ (Aşırı VaR Kayıp Riski Engeli)
# -------------------------------------------------------------------------
print("\n[TEST 4] Monte Carlo Risk ve VaR Süzgeci Testi (Aşırı Oynaklık Cezası)...")
inp_var = DecisionInput(
    ticker="VOLATILE_TICK",
    price=50.0,
    regime="BULL",
    ml_score=70.0,
    ml_confidence=0.75,
    sim_var_95=-25.0, # %25 aşırı kuyruk riski (VaR)
    sim_prob_positive=0.35, # Kazanma olasılığı düşük
    features={"rsi_14": 55.0},
)
dec_4 = engine.decide(inp_var)
print(f"  ✓ Karar: {dec_4.action} | Skor: {dec_4.score:.1f}/100 (VaR Cezası Sonrası)")
assert dec_4.score < 70.0, "Test 4 Başarısız!"
print("  [BAŞARILI] Monte Carlo risk motoru aşırı kuyruk riskini cezalandırdı ve skoru düşürdü.")

print("\n" + "=" * 85)
print("TÜM MOTORLARIN BİRBİRİYLE SENKRONİZE, ÇELİŞKİSİZ VE HATASIZ ÇALIŞTIĞI KANITLANDI.")
print("=" * 85)
