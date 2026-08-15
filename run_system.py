"""
ALPHA BIST — Unified System Runner v1.0

Tüm servisleri tek process'te çalıştırır.
Docker/Redis/PostgreSQL gerektirmez.
SQLite + InMemory kullanır.

Kullanım:
  python3 run_system.py
  python3 run_system.py --scan-once    # Tek tarama yap ve çık
  python3 run_system.py --port 8000    # API portu
"""

import asyncio
import sys
import os
import signal
import argparse
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import structlog
from services.core.logging import setup_logging

logger = structlog.get_logger()


class AlphaSystem:
    """ALPHA BIST — Unified system runner."""

    def __init__(self, scan_once: bool = False, api_port: int = 8000):
        self._running = False
        self._scan_once = scan_once
        self._api_port = api_port
        self._scan_count = 0
        self._start_time = None

        # Components (lazy init)
        self._db = None
        self._feature_store = None
        self._learning = None
        self._opportunity_engine = None
        self._signal_fusion = None
        self._decision_engine = None
        self._execution_simulator = None
        self._audit_log = None
        self._notification_system = None
        self._alert_engine = None
        self._snapshot_system = None
        self._health_checker = None
        self._prometheus = None
        self._config = None
        self._knowledge_graph = None
        self._regime_engine = None
        self._world_state = None
        self._macro_sensitivity = None
        self._factor_engine = None
        self._backtest_engine = None
        self._position_sizer = None
        self._tax_model = None
        self._benchmark_engine = None
        self._event_replay = None
        self._failure_injector = None
        self._market_calendar = None
        self._data_quality = None
        self._circuit_breaker = None
        self._cost_monitor = None
        self._performance_monitor = None
        self._distributed_tracing = None
        self._system_state = None
        self._safety_governance = None
        self._survivorship_bias = None
        self._outlier_detector = None
        self._cross_source_reconciliation = None
        self._universe_enhancements = None
        self._forecasting_engine = None
        self._ensemble_forecasting = None
        self._news_impact_engine = None
        self._news_duplication_engine = None
        self._event_timeline_engine = None
        self._research_memory = None
        self._data_lineage = None
        self._cache_system = None
        self._job_queue = None
        self._catalyst_engine = None
        self._event_orchestrator = None

    async def start(self):
        """Tüm sistemi başlat."""
        setup_logging("INFO")
        self._start_time = datetime.now(timezone.utc)
        self._running = True

        print("=" * 70)
        print("  ALPHA BIST — Market Intelligence & Quant Engine")
        print(f"  Başlangıç: {self._start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print("=" * 70)
        print()

        # 1. Initialize all components
        await self._init_components()

        # 2. Load universe
        await self._load_universe()

        # 3. Run initial scan
        await self._run_scan()

        # Snapshot kaydet (scan_once modunda da)
        self._save_snapshot()

        if self._scan_once:
            print("\n✓ Tek tarama tamamlandı. Çıkılıyor...")
            await self._print_summary()
            return

        # 4. Start continuous loop
        print("\n🔄 Sürekli tarama başlatılıyor... (Ctrl+C ile durdur)")
        print("   Piyasa açıkken her 1 dakikada bir tarama yapılacak.\n")

        # Signal handlers (graceful shutdown)
        import signal as sig
        loop = asyncio.get_event_loop()
        for s in (sig.SIGINT, sig.SIGTERM):
            loop.add_signal_handler(s, lambda: asyncio.create_task(self._shutdown()))

        try:
            while self._running:
                await self._main_loop()
                await asyncio.sleep(60)  # 1 dakika (anlık takip)
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\n⏹ Durduruluyor...")
        finally:
            await self._shutdown()

    async def _init_components(self):
        """Tüm bileşenleri başlat."""
        print("📦 [1/8] Bileşenler başlatılıyor...")

        # Database
        from services.core.database_dev import dev_db
        self._db = dev_db
        await self._db.init()
        print("   ✓ Database (SQLite)")

        # Feature Store
        from services.features.store import feature_store
        self._feature_store = feature_store
        print("   ✓ Feature Store")

        # Engines
        from services.scanner.opportunity_engine import opportunity_engine
        from services.intelligence.signal_fusion import signal_fusion_engine
        from services.core.decision_engine import DecisionEngine
        from services.simulation.execution_simulator import (
            execution_simulator, Order, OrderSide, OrderType, OrderStatus
        )
        from services.core.audit_log import audit_log
        from services.core.observability import (
            prometheus_metrics, distributed_tracing, performance_monitor,
            cost_monitor, resource_monitor, config_manager, health_checker,
        )
        from services.core.recovery import event_replay, graceful_shutdown, startup_recovery, failure_injector
        from services.core.infrastructure import (
            notification_system, alert_engine, snapshot_system,
            cache_system, job_queue, catalyst_engine, event_orchestrator,
        )
        from services.core.security import auth_service, authz_service, system_state, safety_governance
        from services.core.market_calendar import market_calendar
        from services.core.data_quality import data_quality_gate
        from services.core.circuit_breaker import register_protected_provider
        from services.intelligence.world_state import WorldStateManager
        from services.intelligence.regime import regime_engine
        from services.intelligence.macro_sensitivity import macro_sensitivity_engine
        from services.intelligence.factor_engine import factor_engine
        from services.intelligence.knowledge_graph import knowledge_graph
        from services.intelligence.forecasting import forecasting_engine, ensemble_forecasting
        from services.intelligence.forecasting import news_impact_engine, news_duplication_engine, event_timeline_engine
        from services.intelligence.research_memory import research_memory, data_lineage
        from services.backtest.engine import backtest_engine
        from services.risk.position_sizing import position_sizer
        from services.portfolio.enhancements import tax_model, benchmark_engine
        from services.ingestion.universe_enhancements import (
            universe_enhancements, cross_source_reconciliation,
            outlier_detector, survivorship_bias,
        )
        from services.learning.integrated_learning import integrated_learning
        from services.learning.outcome_tracker import outcome_tracker

        self._opportunity_engine = opportunity_engine
        self._signal_fusion = signal_fusion_engine
        self._decision_engine = DecisionEngine()
        self._execution_simulator = execution_simulator
        self._audit_log = audit_log
        self._prometheus = prometheus_metrics
        self._distributed_tracing = distributed_tracing
        self._performance_monitor = performance_monitor
        self._cost_monitor = cost_monitor
        self._resource_monitor = resource_monitor
        self._config = config_manager
        self._health_checker = health_checker
        self._event_replay = event_replay
        self._failure_injector = failure_injector
        self._notification_system = notification_system
        self._alert_engine = alert_engine
        self._snapshot_system = snapshot_system
        self._cache_system = cache_system
        self._job_queue = job_queue
        self._catalyst_engine = catalyst_engine
        self._event_orchestrator = event_orchestrator
        self._system_state = system_state
        self._safety_governance = safety_governance
        self._market_calendar = market_calendar
        self._data_quality = data_quality_gate
        self._world_state = WorldStateManager()
        self._regime_engine = regime_engine
        self._macro_sensitivity = macro_sensitivity_engine
        self._factor_engine = factor_engine
        self._knowledge_graph = knowledge_graph
        self._forecasting_engine = forecasting_engine
        self._ensemble_forecasting = ensemble_forecasting
        self._news_impact_engine = news_impact_engine
        self._news_duplication_engine = news_duplication_engine
        self._event_timeline_engine = event_timeline_engine
        self._research_memory = research_memory
        self._data_lineage = data_lineage
        self._backtest_engine = backtest_engine
        self._position_sizer = position_sizer
        self._tax_model = tax_model
        self._benchmark_engine = benchmark_engine
        self._survivorship_bias = survivorship_bias
        self._outlier_detector = outlier_detector
        self._cross_source_reconciliation = cross_source_reconciliation
        self._universe_enhancements = universe_enhancements
        self._learning = integrated_learning
        self._outcome_tracker = outcome_tracker

        # System state
        self._system_state.transition("INITIALIZING", "components loaded")

        # Health checks
        self._health_checker.register("database")
        self._health_checker.register("feature_store")
        self._health_checker.register("opportunity_engine")
        self._health_checker.register("decision_engine")
        self._health_checker.register("risk_engine")

        self._health_checker.update_status("database", "HEALTHY")
        self._health_checker.update_status("feature_store", "HEALTHY")

        # Knowledge graph
        self._knowledge_graph.load_bist_defaults()

        # Config defaults
        self._config.set("risk.max_position_pct", 10.0, actor="system")
        self._config.set("risk.max_sector_pct", 30.0, actor="system")
        self._config.set("risk.max_drawdown_pct", 15.0, actor="system")
        self._config.set("risk.daily_loss_limit_pct", 5.0, actor="system")

        # Graceful shutdown
        graceful_shutdown.register_handler(self._shutdown)

        # Startup recovery — diskten son snapshot'ı yükle
        self._load_snapshot()

        self._system_state.transition("READY", "all components initialized")
        print(f"   ✓ {len(self._knowledge_graph._entities)} knowledge entities")
        print(f"   ✓ {len(self._knowledge_graph._relations)} knowledge relations")
        print("   ✓ Tüm bileşenler hazır")

    def _load_snapshot(self):
        """Diskten son snapshot'ı yükle (restart sonrası)."""
        try:
            import json
            snapshot_path = Path("data/system_snapshot.json")
            if snapshot_path.exists():
                with open(snapshot_path) as f:
                    snapshot = json.load(f)
                self._scan_count = snapshot.get("scan_count", 0)
                logger.info("Snapshot loaded from disk",
                          scan_count=self._scan_count,
                          saved_at=snapshot.get("timestamp", "unknown"))
                print(f"   ✓ Son snapshot yüklendi (tarama #{self._scan_count})")
            else:
                print("   ~ İlk çalıştırma — snapshot yok")
        except Exception as e:
            logger.warning("Snapshot load failed", error=str(e))

    async def _load_universe(self):
        """BIST evrenini yükle."""
        print("\n📊 [2/8] BIST evreni yükleniyor...")
        from services.ingestion.bist_universe import bist_universe, get_sector

        tickers = bist_universe.get_tickers()
        self._tickers = tickers

        # Database'e seed et
        await self._db.seed_instruments(tickers[:100], get_sector)

        # Portfolio oluştur
        self._portfolio_id = await self._db.ensure_default_portfolio()

        print(f"   ✓ {len(tickers)} hisse yüklendi")
        print(f"   ✓ Portfolio ID: {self._portfolio_id}")

    async def _run_scan(self):
        """Tam tarama çalıştır."""
        from services.simulation.execution_simulator import (
            Order, OrderSide, OrderType, OrderStatus
        )
        print("\n🔍 [3/8] Veri çekiliyor...")
        start = time.time()

        import yfinance as yf
        import polars as pl
        import numpy as np
        from services.features.calculator import feature_calculator
        from services.ingestion.providers.yfinance_provider import yfinance_provider
        from services.ingestion.providers.fundamental_provider import fundamental_provider
        from services.features.fundamental import fundamental_feature_engine

        # Market data — BIST evreninin tamamı, anlık fiyatlar
        test_tickers = self._tickers
        data_map = {}
        batch_size = 20

        # 1. Anlık fiyatlar çek (sadece close — hızlı)
        print("   Anlık fiyatlar çekiliyor...")
        live_prices = {}
        try:
            tickers_yf = [f"{t}.IS" for t in test_tickers]
            live_data = yf.download(tickers_yf, period="1d", group_by="ticker", threads=True, progress=False)
            for ticker in test_tickers:
                try:
                    td = live_data[f"{ticker}.IS"].dropna()
                    if len(td) > 0:
                        live_prices[ticker] = float(td["Close"].iloc[-1])
                except Exception:
                    pass
        except Exception:
            pass
        print(f"   ✓ {len(live_prices)} anlık fiyat")

        # 2. Tarihsel veri çek (feature hesaplama için)
        print("   Tarihsel veri çekiliyor...")
        for i in range(0, len(test_tickers), batch_size):
            batch = test_tickers[i:i + batch_size]
            tickers_yf = [f"{t}.IS" for t in batch]
            try:
                raw = yf.download(tickers_yf, period="60d", group_by="ticker", threads=True, progress=False)
                for ticker in batch:
                    try:
                        td = raw[f"{ticker}.IS"].dropna()
                        if len(td) < 20:
                            continue
                        td = td.reset_index()
                        df = pl.from_pandas(td[["Date", "Open", "High", "Low", "Close", "Volume"]])
                        df = df.rename({"Date": "timestamp", "Open": "open", "High": "high",
                                       "Low": "low", "Close": "close", "Volume": "volume"})
                        if len(df) >= 20:
                            data_map[ticker] = df
                    except Exception:
                        pass
            except Exception:
                pass

        fetch_time = time.time() - start
        print(f"   ✓ {len(data_map)} hisse için tarihsel veri ({fetch_time:.1f}s)")

        # Features
        print("\n🧮 [4/8] Feature'lar hesaplanıyor...")
        features_map = {}
        for ticker, df in data_map.items():
            try:
                features = feature_calculator.compute_all_features(df)
                if features:
                    close_list = [x for x in df["close"].to_list() if x is not None]
                    features["price"] = close_list[-1] if close_list else 0
                    features_map[ticker] = features
                    self._feature_store.set(ticker, features, version="v1")
            except Exception:
                pass

        print(f"   ✓ {len(features_map)} hisse için feature hesaplandı")

        # Haber verilerini çek ve ticker'a ata
        print("\n📰 [4.5/8] Haberler çekiliyor...")
        from services.ingestion.providers.news_provider import news_provider
        from services.features.sentiment import SentimentFeatureEngine

        news_articles = news_provider.fetch_financial_news_rss()
        ticker_news: Dict[str, List] = {}
        general_news = []

        for article in news_articles:
            tickers = article.get("tickers", [])
            if tickers:
                for t in tickers:
                    if t not in ticker_news:
                        ticker_news[t] = []
                    ticker_news[t].append(article)
            else:
                general_news.append(article)

        print(f"   ✓ {len(news_articles)} haber çekildi")
        print(f"   ✓ {len(ticker_news)} hisse ile ilişkilendirildi")

        # Haber sentiment'larını feature'lara ekle
        now = datetime.now(timezone.utc)
        for ticker, articles in ticker_news.items():
            if ticker not in features_map:
                continue
            news_events = [{
                "sentiment": a.get("sentiment", 0),
                "importance": a.get("importance", 0.5),
                "credibility": a.get("credibility", 0.5),
                "timestamp": a.get("published_at", now.isoformat()),
            } for a in articles]
            sf_engine = SentimentFeatureEngine()
            for ne in news_events:
                sf_engine.add_news_event(ticker, ne)
            sf = sf_engine.compute_all_sentiment_features(ticker)
            features_map[ticker].update(sf)

        # Fundamental
        print("\n📈 [5/8] Fundamental veriler çekiliyor...")
        fundamental_scores = {}
        for ticker in list(features_map.keys())[:20]:
            try:
                fund = fundamental_provider.fetch_fundamentals(ticker)
                if fund:
                    fund_features = fundamental_feature_engine.compute_all_fundamental_features(fund)
                    features_map[ticker].update(fund_features)
                    # Simple fundamental score
                    roe = fund.get("roe", 0) or 0
                    growth = fund.get("revenue_growth", 0) or 0
                    if abs(roe) < 1:
                        roe *= 100
                    if abs(growth) < 1:
                        growth *= 100
                    fundamental_scores[ticker] = min(100, max(0, 50 + roe * 2 + growth))
            except Exception:
                pass

        print(f"   ✓ {len(fundamental_scores)} hisse için fundamental veri çekildi")

        # Regime detection
        print("\n🌍 [6/8] Piyasa rejimi tespit ediliyor...")
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
        avg_vol = float(np.mean(volatilities)) if volatilities else 20
        avg_mom = float(np.mean(momentums)) if momentums else 0

        regime_features = {
            "breadth_pct": breadth, "momentum_avg": avg_mom,
            "volatility_avg": avg_vol, "rsi_avg": 50,
            "risk_appetite": 0.5, "usdtry_momentum": 0,
            "vix_level": 15, "global_momentum": 0,
        }
        regime_result = self._regime_engine.detect_regime(regime_features)
        regime = regime_result.regime.value

        print(f"   ✓ Rejim: {regime}")
        print(f"   ✓ Breadth: %{breadth:.1f} ({advancing}↑ {declining}↓)")
        print(f"   ✓ Volatilite: %{avg_vol:.1f}")

        # Opportunity scan
        print("\n🎯 [7/8] Fırsatlar taranıyor...")
        results = self._opportunity_engine.scan_universe(
            universe=list(features_map.keys()),
            features_map=features_map,
            market_regime=regime,
            fundamental_scores=fundamental_scores,
        )

        # Adaptif eşik: piyasa koşullarına göre belirle (sabit kriter yok)
        all_scores = [r.risk_adjusted_score for r in results if r.risk_adjusted_score > 0]
        if all_scores:
            import numpy as np
            median_score = float(np.median(all_scores))
            std_score = float(np.std(all_scores))
            # Piyasa zorsa eşik düşer, iyiyse yükselir
            adaptive_threshold = max(40, median_score + 0.5 * std_score)
        else:
            median_score = 50
            adaptive_threshold = 45

        top_opps = self._opportunity_engine.get_top_opportunities(results, limit=100, min_score=adaptive_threshold)
        signals = [r for r in results if r.signal_type]

        print(f"   ✓ {len(results)} hisse tarandı")
        print(f"   ✓ {len(signals)} sinyal üretildi")
        print(f"   ✓ Adaptif eşik: {adaptive_threshold:.1f} (medyan={median_score:.1f})")
        print(f"   ✓ {len(top_opps)} fırsat bulundu (kriteri geçen hepsi)")

        # Decision + Execution for ALL opportunities (yapay sİnIr yok)
        print("\n💼 [8/8] Kararlar ve İşlemler...")
        decisions_made = 0
        orders_filled = 0

        for opp in top_opps:
            ticker = opp["ticker"]
            features = features_map.get(ticker, {})
            price = features.get("price", 0)

            if price <= 0:
                continue

            # Signal fusion
            signals_dict = {
                "technical": {"direction": opp["direction"], "score": opp.get("decomposition", {}).get("technical", 50) * 5},
                "fundamental": {"direction": "LONG", "score": fundamental_scores.get(ticker, 50)},
                "momentum": {"direction": opp["direction"], "score": opp.get("decomposition", {}).get("momentum", 50) * 5},
                "sentiment": {"direction": "NEUTRAL", "score": 50},
                "macro": {"direction": "NEUTRAL", "score": 50},
                "valuation": {"direction": "LONG", "score": 60},
                "ai": {"direction": opp["direction"], "score": opp["score"]},
                "opportunity": {"score": opp["score"]},
            }
            fused = self._signal_fusion.fuse_signals(ticker, signals_dict, regime)

            # Decision
            from services.core.decision_engine import DecisionInput
            inp = DecisionInput(
                ticker=ticker, price=price,
                ml_return_5d=features.get("roc_5d", 0),
                ml_return_20d=features.get("momentum_20d", 0),
                ml_confidence=fused.fused_confidence,
                spec_score=opp["score"],
                world_alignment=0.5,
                sim_expected_return=opp["score"] / 10,
                sim_var_95=-5,
                sim_prob_positive=60,
                ai_direction=fused.fused_direction,
                ai_confidence=fused.fused_confidence,
                max_position_pct=10,
                current_position_pct=0,
                portfolio_drawdown=0,
                avg_volume=features.get("volume", 100000),
                spread_pct=0.1,
            )
            decision = self._decision_engine.decide(inp)
            decisions_made += 1

            # Audit
            self._audit_log.log_decision(
                ticker, decision.action, decision.direction,
                decision.composite_score / 100, decision.reasons, decision.risks,
            )

            # Learning: Her kararı tahmin olarak kaydet
            self._learning.record_decision(
                ticker=ticker,
                decision={
                    "action": decision.action,
                    "direction": decision.direction,
                    "composite_score": decision.composite_score,
                    "conviction": decision.conviction,
                    "confidence": fused.fused_confidence,
                    "reasons": decision.reasons,
                    "risks": decision.risks,
                },
                features=features,
                regime=regime,
            )

            # Outcome tracker'a ekle (sonuç takibi başlat)
            self._outcome_tracker.add_prediction({
                "prediction_id": f"{ticker}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                "ticker": ticker,
                "predicted_direction": decision.direction,
                "feature_snapshot": {**features, "price": price},
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "horizon": "1-5D",
            })

            # Learning feedback: Geçmiş öğrenmeye göre ayarlama
            adjustment = self._learning.get_decision_adjustment(ticker, regime, opp["score"])
            if adjustment["should_adjust"]:
                for warning in adjustment["warnings"]:
                    logger.warning("Learning adjustment", ticker=ticker, warning=warning)
                self._notification_system.notify(
                    "MODEL", "Learning Adjustment",
                    f"{ticker}: {adjustment.get('reason', 'Confidence reduced')}",
                    severity="INFO",
                )

            if decision.action == "BUY":
                # Position sizing
                from services.risk.position_sizing import position_sizer
                stop_price = price * 0.93  # %7 stop
                pos_size = position_sizer.calculate(
                    ticker, price, stop_price, 100000,
                    max_position_pct=10, max_risk_per_trade_pct=2,
                    confidence=fused.fused_confidence,
                )

                if pos_size.shares > 0:
                    # Execute
                    order = Order(
                        order_id=f"ORD-{self._scan_count}-{ticker}",
                        portfolio_id=self._portfolio_id,
                        instrument_id=1,
                        ticker=ticker,
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        quantity=pos_size.shares,
                    )
                    result = self._execution_simulator.execute_order(order, market_price=price)

                    if result.status.value in ["FILLED", "PARTIALLY_FILLED"]:
                        orders_filled += 1
                        self._audit_log.log_fill(
                            f"FILL-{ticker}", result.order_id, ticker,
                            "BUY", result.filled_quantity, result.avg_fill_price,
                            result.commission,
                        )

        self._scan_count += 1

        # Summary
        print(f"\n{'=' * 70}")
        print(f"  📊 TARAMA SONUÇLARI (#{self._scan_count})")
        print(f"{'=' * 70}")
        print(f"  Taranan hisse    : {len(features_map)} / {len(test_tickers)}")
        print(f"  Piyasa rejimi    : {regime}")
        print(f"  Breadth          : %{breadth:.1f}")
        print(f"  Üretilen sinyal  : {len(signals)}")
        print(f"  Fırsat adayı     : {len(top_opps)}")
        print(f"  Karar            : {decisions_made}")
        print(f"  İşlem            : {orders_filled}")
        print(f"  Süre             : {time.time() - start:.1f}s")
        print(f"{'=' * 70}")

        # Top opportunities
        if top_opps:
            print(f"\n  🏆 FIRSATLAR ({len(top_opps)} adet):")
            print(f"  {'#':<4} {'Hisse':<10} {'Skor':>6} {'Sinyal':<15} {'Yön':<8} {'Fiyat':>10}")
            print(f"  {'-'*55}")
            for i, opp in enumerate(top_opps, 1):
                print(f"  {i:<4} {opp['ticker']:<10} {opp['score']:>6.1f} {opp.get('signal',''):<15} {opp.get('direction',''):<8} {features_map.get(opp['ticker'], {}).get('price', 0):>10.2f}")

        # Snapshot
        self._snapshot_system.take_snapshot({
            "scan_count": self._scan_count,
            "tickers_scanned": len(features_map),
            "regime": regime,
            "signals": len(signals),
            "opportunities": len(top_opps),
            "decisions": decisions_made,
            "orders": orders_filled,
        })

        # Health update
        self._health_checker.update_status("opportunity_engine", "HEALTHY")
        self._health_checker.update_status("decision_engine", "HEALTHY")
        self._health_checker.update_status("risk_engine", "HEALTHY")

    async def _main_loop(self):
        """Ana döngü — periyodik tarama + outcome kontrolü + bakım."""
        now = datetime.now(timezone.utc)

        # 1. Bekleyen outcome'ları kontrol et (her zaman)
        await self._check_outcomes()

        # 2. Snapshot kaydet (her döngüde)
        self._save_snapshot()

        # 3. Piyasa açık mı kontrol et
        if not self._market_calendar.is_market_open(now):
            # Piyasa kapalı — bakım görevleri yap
            await self._maintenance_tasks()
            return

        # 4. Piyasa açık — tarama yap
        await self._run_scan()

    async def _maintenance_tasks(self):
        """Piyasa kapalıyken yapılacak bakım görevleri."""
        # Learning insights güncelle
        insights = self._learning.get_insights()
        if insights.get('total_resolved', 0) > 0:
            logger.info("Market closed — learning maintenance",
                       accuracy=insights.get('overall_accuracy', 0),
                       resolved=insights.get('total_resolved', 0))

        # Eski snapshot'ları temizle
        self._snapshot_system._snapshots = self._snapshot_system._snapshots[-20:]

    def _save_snapshot(self):
        """Snapshot'ı diske kaydet (restart sonrası kurtarma için)."""
        try:
            import json
            snapshot_path = Path("data/system_snapshot.json")
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "scan_count": self._scan_count,
                "state": self._system_state.get_health(),
                "learning": self._learning.get_insights(),
                "outcome_tracker": self._outcome_tracker.get_stats(),
                "health": self._health_checker.check_all(),
            }
            with open(snapshot_path, "w") as f:
                json.dump(snapshot, f, default=str, indent=2)
        except Exception as e:
            logger.warning("Snapshot save failed", error=str(e))

    async def _check_outcomes(self):
        """Bekleyen tahminlerin sonuçlarını kontrol et."""
        async def price_fetcher(ticker: str) -> float:
            """Anlık fiyat çek."""
            try:
                import yfinance as yf
                t = yf.Ticker(f"{ticker}.IS")
                info = t.info
                return info.get("regularMarketPrice", 0)
            except:
                return 0

        results = await self._outcome_tracker.check_pending_outcomes(
            self._learning, price_fetcher
        )

        if results:
            for r in results:
                self._notification_system.notify(
                    "LEARNING", "Outcome Recorded",
                    f"{r['ticker']}: {r['actual_return']:+.2f}% (predicted: {r['predicted_direction']})",
                    severity="INFO",
                )

            # Öğrenme özeti
            insights = self._learning.get_insights()
            logger.info("Learning update",
                       accuracy=insights.get("overall_accuracy", 0),
                       recent_accuracy=insights.get("recent_accuracy", 0),
                       pending=self._outcome_tracker.get_pending_count())

    async def _shutdown(self):
        """Sistemi kapat — state'i diske kaydet."""
        if not self._running:
            return
        self._running = False
        self._system_state.transition("SHUTDOWN", "user initiated")

        # Final snapshot diske kaydet
        self._save_snapshot()

        # Memory snapshot
        self._snapshot_system.take_snapshot({
            "shutdown": True,
            "total_scans": self._scan_count,
            "uptime_seconds": (datetime.now(timezone.utc) - self._start_time).total_seconds() if self._start_time else 0,
        })

        # Learning state kaydet
        self._learning._save_state()

        # Close database
        if self._db:
            await self._db.close()

        self._system_state.transition("FAILED", "shutdown complete")
        print("\n✓ ALPHA BIST kapatıldı. State diske kaydedildi.")

    async def _print_summary(self):
        """Özet yazdır."""
        health = self._health_checker.check_all()
        metrics = self._prometheus.get_metrics()
        audit_stats = self._audit_log.get_stats()

        print(f"\n{'=' * 70}")
        print(f"  📊 SİSTEM ÖZETİ")
        print(f"{'=' * 70}")
        print(f"  Sistem durumu    : {health['overall']}")
        print(f"  Toplam tarama    : {self._scan_count}")
        print(f"  Audit entries    : {audit_stats['total_entries']}")
        print(f"  Knowledge graph  : {len(self._knowledge_graph._entities)} entities")
        print(f"  Feature store    : {len(self._feature_store._store)} tickers")
        print(f"  Config           : {len(self._config.get_all())} keys")

        # Learning insights
        insights = self._learning.get_insights()
        outcome_stats = self._outcome_tracker.get_stats()
        print(f"  ---")
        print(f"  Öğrenme")
        print(f"  Tahmin sayısı   : {insights.get('total_predictions', 0)}")
        print(f"  Outcome bekleyen: {outcome_stats.get('pending', 0)}")
        if insights.get('total_resolved', 0) > 0:
            print(f"  Çözümlenen      : {insights['total_resolved']}")
            print(f"  Genel doğruluk  : %{insights['overall_accuracy']*100:.1f}")
            print(f"  Son doğruluk    : %{insights['recent_accuracy']*100:.1f}")
            print(f"  En iyi rejim    : {insights['best_regime']} (%{insights.get('best_regime_accuracy', 0)*100:.0f})")
            print(f"  En kötü rejim   : {insights['worst_regime']} (%{insights.get('worst_regime_accuracy', 0)*100:.0f})")
            if insights.get('error_patterns'):
                errors = insights['error_patterns'].get('total_errors', 0)
                print(f"  Toplam hata      : {errors}")

        print(f"{'=' * 70}")


async def main():
    parser = argparse.ArgumentParser(description="ALPHA BIST System Runner")
    parser.add_argument("--scan-once", action="store_true", help="Tek tarama yap ve çık")
    parser.add_argument("--port", type=int, default=8000, help="API portu")
    args = parser.parse_args()

    system = AlphaSystem(scan_once=args.scan_once, api_port=args.port)
    await system.start()


if __name__ == "__main__":
    asyncio.run(main())
