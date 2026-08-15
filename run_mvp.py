"""
ALPHA BIST — MVP Runner v1.0

Tam pipeline test:
1. BIST universe yükle
2. Veri çek (yfinance)
3. Feature hesapla
4. Market regime tespit et
5. Scanner çalıştır
6. Sinyal üret
7. Risk kontrolü
8. Trade planı oluştur
9. Sonuçları göster

Kullanım:
  python3 run_mvp.py
"""

import asyncio
import sys
import os
import time
import json
from datetime import datetime, timezone
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).parent))

import structlog
from services.core.logging import setup_logging

logger = structlog.get_logger()


async def main():
    setup_logging("INFO")

    print("=" * 70)
    print("  ALPHA BIST — MVP Pipeline Test")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()

    # =====================================================
    # STEP 1: Database Setup
    # =====================================================
    print("📦 [1/9] Database kuruluyor...")
    from services.core.database_dev import dev_db
    await dev_db.init()

    from services.ingestion.bist_universe import bist_universe, get_sector
    all_tickers = bist_universe.get_tickers()
    test_tickers = all_tickers[:50]  # İlk 50 hisse ile başla

    portfolio_id = await dev_db.ensure_default_portfolio()
    await dev_db.seed_instruments(test_tickers, get_sector)
    print(f"   ✓ Database hazır ({len(test_tickers)} hisse yüklendi)")
    print(f"   ✓ Portfolio ID: {portfolio_id}")
    print()

    # =====================================================
    # STEP 2: Market Data Fetch
    # =====================================================
    print("📊 [2/9] Piyasa verileri çekiliyor...")
    start = time.time()

    import yfinance as yf
    import polars as pl
    import numpy as np

    # Batch download (10'arlı gruplar)
    all_tickers = test_tickers
    data_map = {}
    batch_size = 10
    total_fetched = 0

    for i in range(0, len(all_tickers), batch_size):
        batch = all_tickers[i:i+batch_size]
        tickers_yf = [f"{t}.IS" for t in batch]
        try:
            raw_data = yf.download(tickers_yf, period="60d", group_by="ticker", threads=True, progress=False)

            for ticker in batch:
                try:
                    td = raw_data[ticker + ".IS"].dropna()
                    if len(td) < 20:
                        continue
                    td = td.reset_index()
                    df = pl.from_pandas(td[["Date", "Open", "High", "Low", "Close", "Volume"]])
                    df = df.rename({"Date": "timestamp", "Open": "open", "High": "high",
                                   "Low": "low", "Close": "close", "Volume": "volume"})
                    df = df.drop_nulls(subset=["close"])
                    if len(df) >= 20:
                        data_map[ticker] = df
                        total_fetched += 1
                except Exception:
                    pass  # Intentional: silent error handling
        except Exception as e:
            logger.warning("Batch download failed", batch=i, error=str(e))
            continue

    fetch_time = time.time() - start
    print(f"   ✓ {total_fetched} hisse için veri çekildi ({fetch_time:.1f}s)")

    if total_fetched < 5:
        print("   ⚠ Çok az veri çekildi, internet bağlantısını kontrol edin")
        return

    print(f"   ✓ {len(data_map)} hisse için veri hazır")
    print()

    # =====================================================
    # STEP 3: Feature Computation
    # =====================================================
    print("🧮 [3/9] Feature'lar hesaplanıyor...")
    start = time.time()

    from services.features.calculator import feature_calculator

    features_map = {}
    for ticker, df in data_map.items():
        try:
            features = feature_calculator.compute_all_features(df)
            if features:
                close_list = [x for x in df["close"].to_list() if x is not None]
                features["price"] = close_list[-1] if close_list else 0
                features["close"] = features["price"]
                features_map[ticker] = features
        except Exception:
            pass  # Intentional: silent error handling

    feature_time = time.time() - start
    print(f"   ✓ {len(features_map)} hisse için {sum(len(f) for f in features_map.values())} feature hesaplandı ({feature_time:.1f}s)")
    print()

    # =====================================================
    # STEP 4: Market Regime Detection
    # =====================================================
    print("🌍 [4/9] Piyasa rejimi tespit ediliyor...")

    advancing = declining = 0
    volatilities, momentums = [], []

    for ticker, features in features_map.items():
        ret = features.get("return_1d", 0)
        if ret > 0:
            advancing += 1
        elif ret < 0:
            declining += 1
        vol = features.get("realized_vol_20d", 20)
        if vol:
            volatilities.append(vol)
        mom = features.get("momentum_20d", 0)
        if mom:
            momentums.append(mom)

    total = advancing + declining
    breadth = (advancing / total * 100) if total > 0 else 50
    avg_vol = np.mean(volatilities) if volatilities else 20
    avg_mom = np.mean(momentums) if momentums else 0

    # Regime detection
    if breadth < 20 and avg_vol > 40:
        regime = "PANIC"
    elif breadth < 35:
        regime = "RISK-OFF"
    elif avg_vol > 35:
        regime = "HIGH-VOLATILITY"
    elif breadth > 70 and avg_mom > 5:
        regime = "MOMENTUM-EXPANSION"
    elif breadth > 65 and avg_mom > 0:
        regime = "TRENDING-UP"
    elif breadth < 40 and avg_mom < -5:
        regime = "TRENDING-DOWN"
    elif 45 < breadth < 55 and avg_mom > 0:
        regime = "RECOVERY"
    elif avg_vol < 12:
        regime = "LOW-VOLATILITY"
    else:
        regime = "RANGE"

    print(f"   ✓ Rejim: {regime}")
    print(f"   ✓ Breadth: %{breadth:.1f} (yükselen: {advancing}, düşen: {declining})")
    print(f"   ✓ Ort. Volatilite: %{avg_vol:.1f}")
    print(f"   ✓ Ort. Momentum: {avg_mom:.2f}")
    print()

    # =====================================================
    # STEP 5: Scanner
    # =====================================================
    print("🔍 [5/9] Tarama çalışıyor...")
    start = time.time()

    from services.scanner.alpha_scanner import alpha_scanner

    results = alpha_scanner.scan(
        universe=list(features_map.keys()),
        features_map=features_map,
        market_regime=regime,
        regime_confidence=0.7,
    )

    summary = alpha_scanner.get_summary(results)
    scan_time = time.time() - start

    print(f"   ✓ {summary['total_scanned']} hisse tarandı ({scan_time:.1f}s)")
    print(f"   ✓ {summary['signals_generated']} sinyal üretildi")
    print(f"   ✓ {summary['anomalies']} anomali tespit edildi")
    print(f"   ✓ {summary['oversold']} aşırı satım, {summary['overbought']} aşırı alım")
    print()

    # Top opportunities
    print("   📈 EN GÜÇLÜ FIRSATLAR:")
    print("   " + "-" * 60)
    print(f"   {'Hisse':<10} {'Skor':>6} {'Sinyal':<15} {'Yön':<8} {'Fiyat':>10} {'RSI':>6} {'Mom5d':>8} {'VolZ':>6}")
    print("   " + "-" * 60)
    for opp in summary.get("top_opportunities", [])[:15]:
        print(f"   {opp['ticker']:<10} {opp['score']:>6.1f} {opp.get('signal',''):<15} {opp.get('direction',''):<8} {opp['price']:>10.2f} {opp['rsi']:>6.1f} {opp['momentum_5d']:>+8.2f} {opp['volume_zscore']:>6.1f}")
    print()

    # =====================================================
    # STEP 6: Signal Generation (Top signals)
    # =====================================================
    print("🎯 [6/9] Sinyal detayları...")
    top_signals = summary.get("top_signals", [])
    if top_signals:
        for s in top_signals[:5]:
            print(f"\n   🔔 {s['ticker']} — {s['type']}")
            print(f"      Skor: {s['score']:.1f} | Yön: {s['direction']} | Güven: {s['confidence']:.0%}")
            if s.get("evidence"):
                for e in s["evidence"]:
                    print(f"      ✓ {e}")
            if s.get("risks"):
                for r in s["risks"]:
                    print(f"      ⚠ {r}")
    else:
        print("   (Sinyal üretilmedi — piyasa sakin)")
    print()

    # =====================================================
    # STEP 7: SPEC Engine
    # =====================================================
    print("🧠 [7/9] SPEC analizi...")
    from services.intelligence.spec_engine import spec_engine

    spec_results = []
    for ticker, features in features_map.items():
        try:
            market_state = {"regime": regime, "similar_signal_count": 5}
            result = spec_engine.compute_spec(ticker, features, market_state)
            if result.spec_score > 55:
                spec_results.append(result)
        except Exception:
            pass  # Intentional: silent error handling

    spec_results.sort(key=lambda r: r.spec_score, reverse=True)

    if spec_results:
        print(f"   ✓ {len(spec_results)} SPEC adayı bulundu")
        print()
        print("   🚨 SPEC ADAYLARI:")
        print("   " + "-" * 50)
        print(f"   {'Hisse':<10} {'SPEC':>6} {'Kategori':<18} {'Anomali':>8} {'Kanıt':>8}")
        print("   " + "-" * 50)
        for r in spec_results[:10]:
            print(f"   {r.ticker:<10} {r.spec_score:>6.1f} {r.category:<18} {r.anomaly_score:>8.2f} {r.evidence_consensus:>8.2f}")
    else:
        print("   (SPEC adayı bulunamadı)")
    print()

    # =====================================================
    # STEP 8: Trade Plans
    # =====================================================
    print("💼 [8/9] Trade planları oluşturuluyor...")
    from services.intelligence.trade_planner import trade_planner, format_trade_plan

    # Top 3 için trade planı oluştur
    plan_tickers = []
    if spec_results:
        plan_tickers.extend([r.ticker for r in spec_results[:2]])
    if top_signals:
        for s in top_signals:
            if s["ticker"] not in plan_tickers:
                plan_tickers.append(s["ticker"])
            if len(plan_tickers) >= 3:
                break

    if not plan_tickers and results:
        plan_tickers = [r.ticker for r in results[:3]]

    for ticker in plan_tickers[:3]:
        features = features_map.get(ticker, {})
        price = features.get("price", 0)
        spec_score = 0
        spec_cat = ""
        for r in spec_results:
            if r.ticker == ticker:
                spec_score = r.spec_score
                spec_cat = r.category
                break

        plan = trade_planner.create_plan(
            ticker=ticker,
            price=price,
            features=features,
            spec_score=spec_score,
            spec_category=spec_cat,
            market_regime=regime,
        )
        print(format_trade_plan(plan))
        print()

    # =====================================================
    # STEP 9: Summary
    # =====================================================
    print("=" * 70)
    print("  📊 MVP PIPELINE ÖZET")
    print("=" * 70)
    print(f"  Taranan hisse    : {len(features_map)}")
    print(f"  Piyasa rejimi    : {regime}")
    print(f"  Breadth          : %{breadth:.1f}")
    print(f"  Üretilen sinyal  : {summary['signals_generated']}")
    print(f"  SPEC adayı       : {len(spec_results)}")
    print(f"  Anomali          : {summary['anomalies']}")
    print(f"  Toplam süre      : {fetch_time + feature_time + scan_time:.1f}s")
    print("=" * 70)
    print()
    print("  ✅ MVP pipeline başarıyla çalıştı!")
    print()

    # Cleanup
    await dev_db.close()


if __name__ == "__main__":
    asyncio.run(main())
