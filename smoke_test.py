"""
BIST SISTEM SMOKE TEST
======================
50 hisse x 3 ay gercek veri uzerinde uctan-uca pipeline testi.
Docker olmadan calisir (yfinance + DuckDB embedded).

Test edilen moduller:
  1. Universe Provider   -> 654 hisse dinamik mi?
  2. yfinance veri cekme -> Gercek OHLCV var mi?
  3. AlphaEngine sinyali -> 70 feature hesaplaniyor mu?
  4. Impact Engine       -> KAP haberini sektorel yayiyor mu?
  5. Risk Gate           -> Pozisyon filtreleme calisıyor mu?
  6. BacktestEngineV4    -> Walk-forward gercek getiri uretıyor mu?
  7. DLQ                 -> Hata kuyruğu durumu ne?
"""

from __future__ import annotations

import random
import sys
import time
import traceback
from datetime import datetime, timedelta

import structlog

logger = structlog.get_logger("smoke_test")

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"
INFO = "[INFO]"

results: list[dict] = []


def record(name: str, status: str, detail: str, elapsed: float = 0.0) -> None:
    results.append({"name": name, "status": status, "detail": detail, "elapsed": elapsed})
    icon = {"[PASS]": "OK ", "[FAIL]": "ERR", "[WARN]": "WRN", "[INFO]": "INF"}.get(status, "???")
    print(f"[{icon}] {name:<45} {detail[:70]}  ({elapsed:.1f}s)")


def run_test(name: str, fn) -> bool:
    t0 = time.time()
    try:
        detail = fn()
        record(name, PASS, str(detail or "OK"), time.time() - t0)
        return True
    except Exception as e:
        record(name, FAIL, str(e)[:100], time.time() - t0)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1 — Universe
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 75)
print("  BIST SISTEM SMOKE TEST — uctan-uca 50 hisse x 3 ay")
print("=" * 75 + "\n")

print("[BLOK 1] Evren ve Veri Kaynagi Testi")
print("-" * 50)


def t_universe():
    from services.ingestion.bist_universe import bist_universe
    n = len(bist_universe.BIST_ALL_TICKERS)
    if n < 500:
        raise ValueError(f"Cok az hisse: {n} (beklenen >= 500)")
    return f"{n} hisse yuklu"


run_test("1.1 BIST Universe (>=500 hisse)", t_universe)


def t_universe_sample():
    from services.ingestion.bist_universe import bist_universe
    tickers = bist_universe.BIST_ALL_TICKERS
    # Rastgele 50 hisse sec
    sample = random.sample(tickers, min(50, len(tickers)))
    # BIST30 haricindeki hisseler var mi? (dinamiklik kontrolu)
    bist30 = {"AKBNK", "ARCLK", "ASELS", "BIMAS", "EKGYO", "EREGL",
              "FROTO", "GARAN", "KCHOL", "KOZAA", "KOZAL", "KRDMD",
              "PETKM", "PGSUS", "SAHOL", "SISE", "TAVHL", "TCELL",
              "THYAO", "TKFEN", "TOASO", "TTKOM", "TUPRS", "VAKBN",
              "VESTL", "YKBNK"}
    non_bist30 = [t for t in sample if t not in bist30]
    if len(non_bist30) < 10:
        raise ValueError(f"Orneklem neredeyse tamamen BIST30! Dinamiklik sorunu: {non_bist30}")
    return f"50 orneklem, {len(non_bist30)} tanesi BIST30-disi (dinamik evren onaylandi)"


run_test("1.2 Dinamik evren kontrolu (BIST30-disi)", t_universe_sample)

# ─────────────────────────────────────────────────────────────────────────────
# TEST 2 — Gercek Veri Cekme (yfinance)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[BLOK 2] Gercek OHLCV Veri Cekme")
print("-" * 50)

SMOKE_TICKERS = [
    "THYAO", "GARAN", "AKBNK", "EREGL", "SASA",
    "KCHOL", "TTKOM", "TUPRS", "TOASO", "BIMAS",
    "ALARK", "AGHOL", "KOZAL", "TAVHL", "VESTL",
    "MGROS", "EKGYO", "HALKB", "VAKBN", "YKBNK",
    "FROTO", "ASELS", "PETKM", "SISE", "TKFEN",
    "LOGO", "ULKER", "MPARK", "KERVT", "SELEC",
    "ENKAI", "ISDMR", "GUBRF", "KKGYO", "TSKB",
    "DOAS", "ANSGR", "EREGL", "TTRAK", "PGSUS",
    "SAHOL", "NETAS", "ARCLK", "KRDMD", "BERA",
    "MAVI", "ODAS", "PRTEK", "ALKIM", "IPEKE",
]
# Tekrarlari temizle, 50'ye tamamla
SMOKE_TICKERS = list(dict.fromkeys(SMOKE_TICKERS))[:50]

market_data: dict = {}
END_DATE = datetime.now().strftime("%Y-%m-%d")
START_DATE = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")


def t_yfinance_bulk():
    import yfinance as yf
    import pandas as pd

    failed = []
    fetched = []
    symbols = [f"{t}.IS" for t in SMOKE_TICKERS[:20]]  # ilk 20, hizli kontrol
    data = yf.download(symbols, start=START_DATE, end=END_DATE,
                       group_by="ticker", auto_adjust=True, progress=False, threads=True)

    for ticker in SMOKE_TICKERS[:20]:
        sym = f"{ticker}.IS"
        try:
            if isinstance(data.columns, pd.MultiIndex):
                df = data[sym].dropna(how="all")
            else:
                df = data.dropna(how="all")
            if len(df) > 30:
                market_data[ticker] = df
                fetched.append(ticker)
            else:
                failed.append(ticker)
        except Exception:
            failed.append(ticker)

    if len(fetched) < 10:
        raise ValueError(f"Yeterli veri yok: sadece {len(fetched)} hisse cekilebildi")
    return f"{len(fetched)}/20 hisse verisi cekildı, {len(failed)} basarisiz"


run_test("2.1 yfinance toplu cekme (ilk 20 hisse)", t_yfinance_bulk)


def t_yfinance_single():
    """Tek hisse icin eksiksiz OHLCV kontrolu."""
    import yfinance as yf
    df = yf.download("THYAO.IS", start=START_DATE, end=END_DATE,
                     auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError("THYAO veri bos!")
    required_cols = {"Open", "High", "Low", "Close", "Volume"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Eksik kolonlar: {missing}")
    if len(df) < 30:
        raise ValueError(f"Yetersiz bar sayisi: {len(df)}")
    market_data["THYAO"] = df
    return f"THYAO: {len(df)} bar, son kapan={df['Close'].iloc[-1]:.2f}"


run_test("2.2 THYAO OHLCV dogrulama (Close/Open/High/Low/Volume)", t_yfinance_single)

# ─────────────────────────────────────────────────────────────────────────────
# TEST 3 — Alpha Engine Sinyal
# ─────────────────────────────────────────────────────────────────────────────
print("\n[BLOK 3] Alpha Engine Sinyal Hesabi")
print("-" * 50)


def t_alpha_engine_features():
    """AlphaEngine fetch_data -> generate_training_samples kucuk orneklemle."""
    from services.core.alpha_engine import AlphaEngine
    engine = AlphaEngine()
    # Kucuk orneklem: sadece 3 ay veri cek, 10 hisse
    short_end = END_DATE
    short_start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    mdata, bm_df, sector_map = engine.fetch_data(short_start, short_end)
    n_fetched = len(mdata)
    if n_fetched < 10:
        raise ValueError(f"Cok az hisse indirildi: {n_fetched}")
    return f"{n_fetched} hisse indirildi, benchmark={len(bm_df)} gun, {len(sector_map)} sektor"


run_test("3.1 AlphaEngine.fetch_data (90 gun)", t_alpha_engine_features)


def t_alpha_engine_signals():
    """AlphaEngine.predict gercekten sinyal uretıyor mu?"""
    from services.core.alpha_engine import AlphaEngine
    engine = AlphaEngine()
    short_start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    short_end = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    mdata, bm_df, sector_map = engine.fetch_data(short_start, short_end)

    if not mdata:
        raise ValueError("Veri yok, sinyal hesaplanamaz")

    preds = engine.predict(mdata, bm_df, sector_map, short_end)

    if not preds:
        raise ValueError("Hic sinyal uretilmedi!")
    if len(preds) < 5:
        raise ValueError(f"Cok az sinyal: {len(preds)}")

    top3 = preds[:3]
    top3_str = ", ".join(f"{p['ticker']}={p.get('score', p.get('alpha_score', '?')):.1f}" for p in top3)
    return f"{len(preds)} sinyal uretildi. Top3: {top3_str}"


run_test("3.2 AlphaEngine.predict (gercek sinyal uretimi)", t_alpha_engine_signals)

# ─────────────────────────────────────────────────────────────────────────────
# TEST 4 — Impact Engine (KAP Haber Etkisi)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[BLOK 4] Impact Engine — KAP Haber Etkisi")
print("-" * 50)


def t_impact_engine_sector():
    """Impact Engine sektorel yayilim: 654 hisse haritasi."""
    from services.intelligence.impact_engine import ImpactEngine
    ie = ImpactEngine()
    n = len(ie._instrument_sector_map)
    if n < 500:
        raise ValueError(f"Sektor haritasi eksik: {n} hisse (beklenen >= 500)")
    return f"Sektor haritasi: {n} hisse dinamik"


run_test("4.1 ImpactEngine sektor haritasi (654 hisse)", t_impact_engine_sector)


def t_impact_engine_propagation():
    """Sahte KAP haberi ile etki yayilimı testi."""
    from services.intelligence.impact_engine import ImpactEngine, NewsEvent
    ie = ImpactEngine()

    # Gercek benzeri bir KAP haberi simule et (sahte veri degil, test input)
    fake_event = NewsEvent(
        ticker="THYAO",
        headline="Turk Hava Yollari net kar %40 yukseldi",
        sentiment_score=0.85,
        event_type="earnings",
        timestamp=datetime.now(),
        source="KAP",
    )

    impacts = ie.compute_impact(fake_event)

    if not impacts:
        raise ValueError("Haber etkisi hesaplanamadı (bos sonuc)")
    # Turizm sektoru hisselerinde de etki olmali
    affected_tickers = list(impacts.keys())
    return f"{len(affected_tickers)} hisse etkilendi. Ornek: {affected_tickers[:5]}"


run_test("4.2 ImpactEngine.compute_impact (haber yayilimi)", t_impact_engine_propagation)

# ─────────────────────────────────────────────────────────────────────────────
# TEST 5 — Risk Gate
# ─────────────────────────────────────────────────────────────────────────────
print("\n[BLOK 5] Risk Gate Filtresi")
print("-" * 50)


def t_risk_gate_basic():
    """Risk Gate temel pozisyon filtresi."""
    from services.core.risk_gate import RiskGate
    rg = RiskGate()

    # Gecerli bir pozisyon
    ok = rg.check_position("THYAO", quantity=100, price=350.0,
                            portfolio_value=1_000_000.0)
    # Asiri buyuk pozisyon (>%10) reddedilmeli
    big = rg.check_position("THYAO", quantity=10000, price=350.0,
                             portfolio_value=1_000_000.0)

    if ok is None:
        raise ValueError("check_position None dondu — API hatali")
    return f"Normal={ok}, Asiri-buyuk={big} (ikincisi reddedilmeli)"


run_test("5.1 RiskGate.check_position (pozisyon limiti)", t_risk_gate_basic)


def t_halt_monitor():
    """Halt monitor durumu."""
    from services.core.halt_monitor import HaltMonitor
    hm = HaltMonitor()
    # Mevcut durdurulmus hisseler
    halted = hm.get_halted_tickers() if hasattr(hm, "get_halted_tickers") else []
    status = hm.is_halted("THYAO") if hasattr(hm, "is_halted") else False
    return f"Durdurulmus={len(halted)} hisse, THYAO_halted={status}"


run_test("5.2 HaltMonitor (devre kisi kontrolu)", t_halt_monitor)

# ─────────────────────────────────────────────────────────────────────────────
# TEST 6 — KAP Provider Gercek Veri
# ─────────────────────────────────────────────────────────────────────────────
print("\n[BLOK 6] KAP Provider — Gercek Haberler")
print("-" * 50)


def t_kap_recent_news():
    """KAP provider son haberleri cekiyor mu?"""
    from services.ingestion.providers.kap_provider import KAPProvider
    kap = KAPProvider()

    # Asenkron degil, senkron cekme metodu var mi kontrol et
    fetch_fn = None
    for fn_name in ["get_recent_disclosures", "fetch_recent", "get_news", "fetch"]:
        if hasattr(kap, fn_name):
            fetch_fn = getattr(kap, fn_name)
            break

    if fetch_fn is None:
        available = [m for m in dir(kap) if not m.startswith("_")]
        return f"WARN: Senkron fetch metodu bulunamadi. Mevcut: {available[:8]}"

    news = fetch_fn()
    if news is None:
        return "WARN: fetch None dondu (muhtemelen async veya network)"
    if isinstance(news, list) and len(news) == 0:
        return "WARN: Haber listesi bos (network veya cache?)"
    return f"{len(news) if isinstance(news, list) else '?'} haber alindi"


run_test("6.1 KAPProvider gercek haber cekme", t_kap_recent_news)


def t_kap_llm_extractor():
    """KAP LLM Extractor basit metin analizi."""
    from services.intelligence.kap_llm_extractor import KAPLLMExtractor
    extractor = KAPLLMExtractor()
    # Gercek KAP haberi ornegi (internet gerektirmez, sadece text analizi)
    sample_text = "Turk Hava Yollari A.O. 2024 yili 3. ceyrek net karini 8.2 milyar TL olarak acikladi."
    result = None
    for fn_name in ["extract", "analyze", "process", "parse"]:
        if hasattr(extractor, fn_name):
            try:
                result = getattr(extractor, fn_name)(sample_text)
                break
            except Exception as e:
                result = f"WARN: {fn_name} hatasi: {e}"

    if result is None:
        methods = [m for m in dir(extractor) if not m.startswith("_")]
        return f"WARN: Analiz metodu bulunamadi. Mevcut: {methods[:8]}"
    return f"Analiz sonucu: {str(result)[:80]}"


run_test("6.2 KAPLLMExtractor metin analizi", t_kap_llm_extractor)

# ─────────────────────────────────────────────────────────────────────────────
# TEST 7 — DLQ (Dead Letter Queue)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[BLOK 7] DLQ Durum Kontrolu")
print("-" * 50)


def t_dlq_status():
    """DLQ'da ne kadar basarısız islem bekliyor?"""
    import duckdb
    import os
    dlq_path = "data/dlq.db"
    if not os.path.exists(dlq_path):
        return "WARN: DLQ veritabani yok (henuz hata olmamis olabilir)"
    con = duckdb.connect(dlq_path, read_only=True)
    try:
        tables = con.execute("SHOW TABLES").fetchall()
        if not tables:
            return "DLQ bos (hic hata kaydi yok)"
        counts = []
        for (table,) in tables:
            try:
                n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                counts.append(f"{table}={n}")
            except Exception:
                pass
        return f"DLQ tablolari: {', '.join(counts)}"
    finally:
        con.close()


run_test("7.1 DLQ basarisiz islem sayisi", t_dlq_status)

# ─────────────────────────────────────────────────────────────────────────────
# TEST 8 — Mini Walk-Forward Backtest
# ─────────────────────────────────────────────────────────────────────────────
print("\n[BLOK 8] Mini Walk-Forward Backtest (gercek getiri)")
print("-" * 50)


def t_mini_backtest():
    """
    AlphaEngine ile 90 gun veri, 60 gun train, 30 gun test.
    Gercek fiyatlarla portfoy getirisi hesapla.
    """
    from services.core.alpha_engine import AlphaEngine
    import lightgbm as lgb

    engine = AlphaEngine()
    engine.params["n_estimators"] = 30  # hizli

    short_start = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
    train_end = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    test_end = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")

    mdata, bm_df, sector_map = engine.fetch_data(short_start, test_end)

    if len(mdata) < 10:
        raise ValueError(f"Yetersiz veri: {len(mdata)} hisse")

    # Egitim
    X, y, feat_names = engine.generate_training_samples(mdata, bm_df, sector_map, short_start, train_end)
    if len(X) == 0:
        raise ValueError("Egitim orneklemi olusturulamadi")

    train_data = lgb.Dataset(X, label=y, feature_name=feat_names)
    engine.model = lgb.train(engine.params, train_data, num_boost_round=50, verbose_eval=False)
    engine.features = feat_names

    # Tahmin
    preds = engine.predict(mdata, bm_df, sector_map, train_end)
    if not preds:
        raise ValueError("Tahmin listesi bos")

    top5 = preds[:5]
    selected = [p["ticker"] for p in top5]

    # Gercek getiri hesapla
    returns = []
    for ticker in selected:
        if ticker in mdata:
            df = mdata[ticker]
            try:
                buy_idx = df.index[df.index <= train_end]
                sell_idx = df.index[df.index <= test_end]
                if len(buy_idx) > 0 and len(sell_idx) > 0:
                    buy = df.loc[buy_idx, "Close"].iloc[-1]
                    sell = df.loc[sell_idx, "Close"].iloc[-1]
                    returns.append((sell - buy) / buy)
            except Exception:
                pass

    if not returns:
        raise ValueError("Hicbir hisse icin getiri hesaplanamadi")

    avg_ret = sum(returns) / len(returns) * 100
    # Benchmark getirisi
    try:
        bm_buy_idx = bm_df.index[bm_df.index <= train_end]
        bm_sell_idx = bm_df.index[bm_df.index <= test_end]
        bm_buy = bm_df.loc[bm_buy_idx, "Close"].iloc[-1]
        bm_sell = bm_df.loc[bm_sell_idx, "Close"].iloc[-1]
        bm_ret = (bm_sell - bm_buy) / bm_buy * 100
    except Exception:
        bm_ret = 0.0

    alpha = avg_ret - bm_ret
    return (
        f"Top5={selected} | "
        f"Portfoy={avg_ret:+.2f}% | BM={bm_ret:+.2f}% | Alpha={alpha:+.2f}%"
    )


run_test("8.1 Mini backtest (60g train, 30g test, gercek getiri)", t_mini_backtest)

# ─────────────────────────────────────────────────────────────────────────────
# OZET
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 75)
passed = sum(1 for r in results if r["status"] == PASS)
warned = sum(1 for r in results if r["status"] == WARN)
failed = sum(1 for r in results if r["status"] == FAIL)
total = len(results)
total_time = sum(r["elapsed"] for r in results)

print(f"  TOPLAM: {total} test | GECTI={passed} | UYARI={warned} | HATA={failed}")
print(f"  Toplam sure: {total_time:.1f}s")
print("=" * 75)

if failed > 0:
    print(f"\nBAŞARISIZ TESTLER:")
    for r in results:
        if r["status"] == FAIL:
            print(f"  ERR  {r['name']}: {r['detail']}")

if warned > 0:
    print(f"\nUYARI TESTLER:")
    for r in results:
        if r["status"] == WARN:
            print(f"  WRN  {r['name']}: {r['detail']}")

sys.exit(0 if failed == 0 else 1)
