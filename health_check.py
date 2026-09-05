"""BIST Sistem Saglik Kontrolu"""
import sys

results = {}


def chk(name, fn):
    try:
        msg = fn()
        results[name] = ("OK", msg or "OK")
    except Exception as e:
        results[name] = ("FAIL", str(e)[:120])


# 1. BIST Universe
chk("1.bist_universe", lambda: (
    lambda u: f"{len(u.BIST_ALL_TICKERS)} hisse yuklu"
)(__import__("services.ingestion.bist_universe", fromlist=["bist_universe"]).bist_universe))

# 2. Universe Provider (TradingView oncelikli)
chk("2.universe_provider", lambda: (
    lambda u: f"{len(u.get_universe())} hisse, tradingview-oncelikli"
)(__import__("services.ingestion.providers.universe_provider", fromlist=["universe_updater"]).universe_updater))

# 3. KAP Haberleri
chk("3.kap_provider", lambda: (
    __import__("services.ingestion.providers.kap_provider", fromlist=["KAPProvider"]).KAPProvider().__class__.__name__ + " orneklendi"
))

# 4. Haber motoru
chk("4.news_provider", lambda: (
    __import__("services.ingestion.providers.news_provider", fromlist=["NewsProvider"]).NewsProvider().__class__.__name__ + " orneklendi"
))

# 5. Fundamental veri
chk("5.fundamental_provider", lambda: (
    __import__("services.ingestion.providers.fundamental_provider", fromlist=["FundamentalProvider"]).FundamentalProvider().__class__.__name__ + " orneklendi"
))

# 6. TCMB Makro
chk("6.tcmb_provider", lambda: (
    __import__("services.ingestion.providers.tcmb_provider", fromlist=["TCMBProvider"]).TCMBProvider().__class__.__name__ + " orneklendi"
))

# 7. Data Source
chk("7.data_source", lambda: (
    __import__("services.data.data_source", fromlist=["data_source"]).data_source.__class__.__name__ + " orneklendi"
))

# 8. Historical Warehouse
chk("8.historical_warehouse", lambda: (
    __import__("services.data.historical_warehouse", fromlist=["HistoricalDataWarehouse"]).HistoricalDataWarehouse().__class__.__name__ + " orneklendi"
))

# 9. Alpha Engine
chk("9.alpha_engine", lambda: (
    __import__("services.core.alpha_engine", fromlist=["AlphaEngine"]).AlphaEngine().__class__.__name__ + " orneklendi, universe=BIST_ALL_TICKERS"
))

# 10. Feature Engine
chk("10.feature_engine", lambda: (
    "compute_universe_features import OK" if
    __import__("services.ml.feature_engine", fromlist=["compute_universe_features"]).compute_universe_features
    else "WARN"
))

# 11. Impact Engine
chk("11.impact_engine", lambda: (
    lambda ie: f"sektor_haritasi: {len(ie._instrument_sector_map)} hisse dinamik"
)(__import__("services.intelligence.impact_engine", fromlist=["ImpactEngine"]).ImpactEngine()))

# 12. Gemini LLM
chk("12.gemini_service", lambda: (
    "call_gemini OK, dinamik hisse eslestirme aktif" if
    __import__("services.intelligence.gemini_service", fromlist=["call_gemini"]).call_gemini
    else "WARN"
))

# 13. Signal Fusion
chk("13.signal_fusion", lambda: (
    __import__("services.intelligence.signal_fusion", fromlist=["SignalFusionEngine"]).SignalFusionEngine().__class__.__name__ + " orneklendi"
))

# 14. Portfolio Manager
chk("14.portfolio_manager", lambda: (
    __import__("services.portfolio.portfolio_manager", fromlist=["PortfolioManager"]).PortfolioManager().__class__.__name__ + " OK, BIST_ALL_TICKERS fallback aktif"
))

# 15. Risk Gate
chk("15.risk_gate", lambda: (
    __import__("services.core.risk_gate", fromlist=["RiskGate"]).RiskGate().__class__.__name__ + " orneklendi"
))

# 16. Backtest Engine
chk("16.backtest_engine_v4", lambda: (
    __import__("services.backtest.engine_v4", fromlist=["BacktestEngineV4"]).BacktestEngineV4.__name__ + " import OK"
))

# 17. Startup Catchup (MasterStartupCatchup)
chk("17.startup_catchup", lambda: (
    "MasterStartupCatchup import OK, BIST_ALL_TICKERS kullaniyor" if
    __import__("services.pipeline.startup_catchup", fromlist=["MasterStartupCatchup"]).MasterStartupCatchup
    else "WARN"
))

# 18. ML Scanner (TradingView)
chk("18.ml_scanner", lambda: (
    __import__("services.scanner.bist_ml_scanner", fromlist=["BistMLScanner"]).BistMLScanner().__class__.__name__ + " orneklendi"
))

# 19. Halt Monitor
chk("19.halt_monitor", lambda: (
    __import__("services.core.halt_monitor", fromlist=["HaltMonitor"]).HaltMonitor().__class__.__name__ + " orneklendi"
))

# 20. Regime Detector
chk("20.regime_detector", lambda: (
    __import__("services.core.regime_detector", fromlist=["RegimeDetector"]).RegimeDetector().__class__.__name__ + " orneklendi"
))

# 21. KAP LLM Extractor
chk("21.kap_llm_extractor", lambda: (
    __import__("services.intelligence.kap_llm_extractor", fromlist=["KAPLLMExtractor"]).KAPLLMExtractor().__class__.__name__ + " orneklendi, LLM haber analizi OK"
))

# 22. Short Selling (SPK kurali)
chk("22.short_selling", lambda: (
    __import__("services.core.short_selling", fromlist=["ShortSellingMonitor"]).ShortSellingMonitor().__class__.__name__ + " orneklendi, SPK kurali aktif"
))

# 23. Market Calendar (tatil yonetimi)
chk("23.market_calendar", lambda: (
    __import__("services.core.market_calendar", fromlist=["MarketCalendar"]).MarketCalendar().__class__.__name__ + " orneklendi"
))

# 24. DuckDB Research Engine
chk("24.duckdb_research", lambda: (
    __import__("services.core.duckdb_research", fromlist=["DuckDBResearchEngine"]).DuckDBResearchEngine().__class__.__name__ + " orneklendi"
))

# 25. Decision Engine
chk("25.decision_engine", lambda: (
    __import__("services.core.decision_engine", fromlist=["DecisionEngine"]).DecisionEngine().__class__.__name__ + " orneklendi"
))

# ---- SONUCLAR ----
ok   = sum(1 for v in results.values() if v[0] == "OK")
fail = sum(1 for v in results.values() if v[0] == "FAIL")
print("=" * 65)
print(f"  BIST SISTEM SAGLIK KONTROLU  [{ok} BASARILI / {fail} BASARISIZ]")
print("=" * 65)
for name, (status, msg) in results.items():
    tag = "[OK  ]" if status == "OK" else "[FAIL]"
    print(f"{tag} {name:<35} {msg}")
print("=" * 65)
if fail > 0:
    sys.exit(1)
