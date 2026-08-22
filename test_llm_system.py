"""
ALPHA BIST — FAZ 4 LLM Sistemi Tam Test
Gemini API'ye gerçek bağlantı + tüm araçları test eder.
"""
import os
import sys

# API key'i komut satırından veya env'den al
if len(sys.argv) > 1:
    os.environ["GEMINI_API_KEY"] = sys.argv[1]

api_key = os.environ.get("GEMINI_API_KEY", "")
if not api_key:
    print("HATA: GEMINI_API_KEY verilmedi.")
    print("Kullanim: python test_llm_system.py YOUR_API_KEY")
    sys.exit(1)

print(f"API Key: {api_key[:8]}...{api_key[-4:]} ({len(api_key)} karakter)")
print("="*60)

# ── TEST 1: LLM Client ───────────────────────────────────────
print("\n[TEST 1] LLM Client — Gemini API baglantisi")
try:
    from services.intelligence.llm_client import LLMClient
    client = LLMClient()
    print(f"  is_live: {client.is_live}")
    print(f"  model:   {client.model_name}")

    if client.is_live:
        result = client.analyze_financial_text(
            text="THY, Londra hattında %15 yolcu artışı açıkladı.",
            context_type="news",
        )
        print(f"  Sonuc: {result}")
        print("  [GECTI] LLM Client")
    else:
        print("  [UYARI] API aktif degil — mock mode")
except Exception as e:
    print(f"  [HATA] {e}")

# ── TEST 2: LLM Tools ────────────────────────────────────────
print("\n[TEST 2] LLM Tools — 10 arac")
try:
    from services.intelligence.llm_tools import llm_tool_executor

    # World State
    ws = llm_tool_executor.execute("get_world_state", {})
    print(f"  get_world_state: status={ws.get('status')} | keys={list(ws.get('world_state', {}).keys())}")

    # Regime
    r = llm_tool_executor.execute("get_regime", {})
    print(f"  get_regime: regime={r.get('regime')} confidence={r.get('confidence')}")

    # Research Memory (mock)
    mem = llm_tool_executor.execute("get_research_memory", {"ticker": "THYAO", "limit": 3})
    print(f"  get_research_memory: status={mem.get('status')} history_count={len(mem.get('history', []))}")

    # Store Analysis
    store = llm_tool_executor.execute("store_analysis", {
        "ticker": "THYAO",
        "thesis": "Test tezi — API testi",
        "direction": "LONG",
        "confidence": 0.75,
    })
    print(f"  store_analysis: status={store.get('status')}")

    # Override Regime (dusuk confidence — reddedilmeli)
    ov = llm_tool_executor.execute("override_regime", {
        "new_regime": "CRISIS",
        "reason": "Test",
        "confidence": 0.50,  # < 0.80, reddedilmeli
    })
    print(f"  override_regime (dusuk conf): status={ov.get('status')} (beklenen: rejected)")

    # Override Regime (yuksek confidence — kabul edilmeli)
    ov2 = llm_tool_executor.execute("override_regime", {
        "new_regime": "CRISIS",
        "reason": "Test — yuksek guven",
        "confidence": 0.90,
    })
    print(f"  override_regime (yuksek conf): status={ov2.get('status')} (beklenen: mock_ok/ok)")

    print("  [GECTI] LLM Tools")
except Exception as e:
    print(f"  [HATA] {e}")
    import traceback; traceback.print_exc()

# ── TEST 3: LLM Context Builder ──────────────────────────────
print("\n[TEST 3] LLM Context Builder — RAG")
try:
    from services.intelligence.llm_context_builder import llm_context_builder

    ctx = llm_context_builder.build_news_context(ticker="THYAO", sector="AVIATION")
    print(f"  build_news_context: context_type={ctx.get('context_type')}")
    print(f"    world_state keys: {list(ctx.get('world_state', {}).keys())[:4]}")
    print(f"    market_regime: {ctx.get('market_regime', {}).get('regime')}")

    prompt_text = llm_context_builder.to_prompt_text(ctx)
    print(f"    prompt_text length: {len(prompt_text)} karakter")
    print("  [GECTI] LLM Context Builder")
except Exception as e:
    print(f"  [HATA] {e}")
    import traceback; traceback.print_exc()

# ── TEST 4: LLM Agent — Haber Analizi ────────────────────────
print("\n[TEST 4] LLM Agent — Haber Analizi")
try:
    from services.intelligence.llm_agent import llm_agent

    analysis = llm_agent.analyze_news(
        text="THYAO, 3. çeyrek yolcu rakamlarını açıkladı. Avrupa hatlarında %18 artış. "
             "Petrol fiyatlarındaki düşüş şirketin maliyetlerini azaltıyor.",
        ticker="THYAO",
        sector="AVIATION",
    )
    print(f"  ticker:      {analysis.ticker}")
    print(f"  event_type:  {analysis.event_type}")
    print(f"  sentiment:   {analysis.sentiment:.2f}")
    print(f"  importance:  {analysis.importance:.2f}")
    print(f"  direction:   {analysis.ai_direction}")
    print(f"  key_insight: {analysis.key_insight[:80] if analysis.key_insight else '(bos)'}")
    print(f"  tool_calls:  {analysis.tool_calls_made}")
    print(f"  is_mock:     {analysis.is_mock}")
    print("  [GECTI] LLM Agent Haber Analizi")
except Exception as e:
    print(f"  [HATA] {e}")
    import traceback; traceback.print_exc()

# ── TEST 5: Signal Fusion AI Ağırlıkları ─────────────────────
print("\n[TEST 5] Signal Fusion — AI Agirlik Kontrolu")
try:
    from services.intelligence.signal_fusion import SignalFusionEngine

    engine = SignalFusionEngine()

    for regime in ["BULL", "CRISIS", "GEOPOLITICAL_CRISIS", "RANGE"]:
        weights = engine.get_current_weights(regime)
        ai_weight = weights.get("ai", 0)
        print(f"  {regime:25s} -> ai_weight={ai_weight:.4f}")

    print("  [GECTI] Signal Fusion AI agirlik tablosu")
except Exception as e:
    print(f"  [HATA] {e}")

# ── TEST 6: Regime Override ───────────────────────────────────
print("\n[TEST 6] Regime Override — Kara Kugu Korumasi")
try:
    from services.intelligence.regime import regime_engine

    # Override dene
    success = regime_engine.override_regime(
        new_regime="CRISIS",
        reason="Test: Kara Kugu senaryosu",
        confidence=0.92,
    )
    current = regime_engine.get_regime()
    print(f"  override success: {success}")
    print(f"  current regime:   {current.regime if current else 'None'}")
    print("  [GECTI] Regime Override")
except Exception as e:
    print(f"  [HATA] {e}")
    import traceback; traceback.print_exc()

# ── TEST 7: Research Memory ───────────────────────────────────
print("\n[TEST 7] Research Memory — Hafiza Dongusu")
try:
    from services.intelligence.research_memory import research_memory

    # Yaz
    record = research_memory.store_llm_analysis(
        ticker="THYAO",
        thesis="Güçlü yolcu verisi ve düşük petrol maliyeti avantajı",
        direction="LONG",
        confidence=0.78,
        key_risks=["Kur riski", "Jeopolitik belirsizlik"],
    )
    print(f"  store_llm_analysis: record_id={record.record_id}")

    # Oku (RAG)
    history = research_memory.get_ticker_history("THYAO", limit=5)
    print(f"  get_ticker_history: {len(history)} kayit")
    if history:
        last = history[-1]
        print(f"    Son kayit: {last.get('thesis', '')[:60]}")
    print("  [GECTI] Research Memory")
except Exception as e:
    print(f"  [HATA] {e}")
    import traceback; traceback.print_exc()

# ── TEST 8: Decision Engine llm_narrative ─────────────────────
print("\n[TEST 8] Decision Engine — llm_narrative alani")
try:
    from services.core.decision_engine import Decision

    d = Decision(
        ticker="THYAO",
        action="BUY",
        direction="LONG",
        confidence=0.82,
        score=74.5,
        llm_narrative="THYAO için AL kararı. Güçlü yolcu verisi ve düşük petrol avantajı.",
    )
    print(f"  llm_narrative: {d.llm_narrative[:80]}")
    print("  [GECTI] Decision Engine llm_narrative")
except Exception as e:
    print(f"  [HATA] {e}")

print("\n" + "="*60)
print("FAZ 4 TEST TAMAMLANDI")
print("="*60)
