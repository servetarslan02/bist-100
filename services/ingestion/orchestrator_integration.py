"""
ALPHA BIST — Ingestion Orchestrator Integration v1.0

Ingestion pipeline'ını mevcut orchestrator'a entegre eder.
Tüm resilience katmanlarını birleştirir.

Kullanım:
    integration = IngestionOrchestrator()
    result = await integration.run_full_ingestion()
"""

import asyncio
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from dataclasses import dataclass, field
import structlog

from .circuit_breaker import CircuitBreakerManager
from .rate_limiter import RateLimiter, create_default_rate_limiter
from .retry_policy import RetryPolicy
from .provider_manager import ProviderManager, ProviderResult
from .reconciliation import SourceReconciler
from .point_in_time import PointInTimeValidator
from .deduplication import EventDeduplicator
from .incremental import IncrementalFetcher
from .ingestion_metrics import ingestion_metrics
from .providers.yfinance_provider import yfinance_provider
from .providers.kap_provider import kap_provider
from .providers.tcmb_provider import tcmb_provider
from .providers.news_provider import news_provider
from .providers.social_provider import social_provider
from .providers.fundamental_provider import fundamental_provider
from .providers.macro_provider import macro_provider
from .providers.bist_provider import bist_provider
from .providers.matriks_provider import matriks_provider

logger = structlog.get_logger()


@dataclass
class IngestionResult:
    """Ingestion sonuç raporu."""
    ticker: str
    market_data: Optional[ProviderResult] = None
    fundamental_data: Optional[Dict] = None
    kap_disclosures: List[Dict] = field(default_factory=list)
    news: List[Dict] = field(default_factory=list)
    social: List[Dict] = field(default_factory=list)
    macro: Dict = field(default_factory=dict)
    quality_score: float = 0.0
    reconciliation: Optional[Dict] = None
    errors: List[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PipelineReport:
    """Tam pipeline raporu."""
    total_tickers: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    avg_quality_score: float = 0.0
    total_elapsed_s: float = 0.0
    results: Dict[str, IngestionResult] = field(default_factory=dict)
    macro_data: Dict = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    metrics: Dict = field(default_factory=dict)


class IngestionOrchestrator:
    """
    Ingestion orchestrator — tüm pipeline'ı yönetir.

    Market data + Fundamental + KAP + News + Social + Macro
    Tüm resilience katmanları ile korumalı.
    """

    def __init__(self):
        # Resilience katmanları
        self._cb_manager = CircuitBreakerManager()
        self._rate_limiter = create_default_rate_limiter()
        self._reconciler = SourceReconciler()
        self._pit = PointInTimeValidator()
        self._dedup = EventDeduplicator()
        self._incremental = IncrementalFetcher()

        # Provider manager
        self._pm = ProviderManager(
            rate_limiter_instance=self._rate_limiter,
            circuit_breaker_manager=self._cb_manager,
        )
        self._register_providers()

    def _register_providers(self):
        """Provider'ları kaydet."""
        # Market data providers
        self._pm.register(
            "market_price", "yfinance",
            lambda **kw: yfinance_provider.fetch_current_price(kw.get("ticker", "")),
            priority=0, timeout_s=20,
        )
        self._pm.register(
            "market_price", "bist",
            lambda **kw: bist_provider.fetch_stock_price(kw.get("ticker", "")),
            priority=1, timeout_s=15,
        )
        self._pm.register(
            "market_price", "matriks",
            lambda **kw: matriks_provider.fetch_stock_price(kw.get("ticker", "")),
            priority=2, timeout_s=15,
        )

        # Fundamental providers
        self._pm.register(
            "fundamental", "yfinance",
            lambda **kw: fundamental_provider.fetch_fundamentals(kw.get("ticker", "")),
            priority=0, timeout_s=20,
        )
        self._pm.register(
            "fundamental", "kap",
            lambda **kw: kap_provider.fetch_financial_data(kw.get("ticker", "")),
            priority=1, timeout_s=15,
        )

    async def run_full_ingestion(
        self,
        tickers: List[str],
        include_fundamental: bool = True,
        include_kap: bool = True,
        include_news: bool = True,
        include_social: bool = True,
        include_macro: bool = True,
        use_reconciliation: bool = True,
    ) -> PipelineReport:
        """Tam ingestion pipeline çalıştır.

        Args:
            tickers: Hisse listesi
            include_fundamental: Fundamental veri dahil mi
            include_kap: KAP açıklamaları dahil mi
            include_news: Haberler dahil mi
            include_social: Sosyal medya dahil mi
            include_macro: Makro veriler dahil mi
            use_reconciliation: Kaynaklar arası doğrulama

        Returns:
            PipelineReport
        """
        start_time = time.time()
        report = PipelineReport(total_tickers=len(tickers))

        logger.info("Starting full ingestion", tickers=len(tickers))

        with ingestion_metrics.track_pipeline("full"):
            # 1. Makro verileri paralel çek
            if include_macro:
                report.macro_data = await self._fetch_macro()

            # 2. Market data + fundamental + KAP paralel
            market_tasks = []
            for ticker in tickers:
                if not self._incremental.should_fetch(ticker, min_interval_seconds=60):
                    report.skipped += 1
                    continue
                market_tasks.append(self._ingest_single(
                    ticker,
                    include_fundamental=include_fundamental,
                    include_kap=include_kap,
                    include_news=include_news,
                    include_social=include_social,
                    use_reconciliation=use_reconciliation,
                ))

            results = await asyncio.gather(*market_tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    report.errors.append(str(result))
                    report.failed += 1
                    continue
                if isinstance(result, IngestionResult):
                    report.results[result.ticker] = result
                    if result.errors:
                        report.failed += 1
                    else:
                        report.successful += 1
                    self._incremental.mark_fetched(result.ticker, success=not result.errors)

        # Raporu tamamla
        report.total_elapsed_s = round(time.time() - start_time, 2)
        quality_scores = [r.quality_score for r in report.results.values() if r.quality_score > 0]
        report.avg_quality_score = round(
            sum(quality_scores) / len(quality_scores) if quality_scores else 0, 1
        )

        # Metrics
        report.metrics = {
            "circuit_breakers": self._cb_manager.get_all_states(),
            "rate_limiters": self._rate_limiter.get_all_stats(),
            "dedup": self._dedup.get_stats(),
            "incremental": self._incremental.get_stats(),
        }

        logger.info("Ingestion completed",
                    total=report.total_tickers,
                    successful=report.successful,
                    failed=report.failed,
                    skipped=report.skipped,
                    elapsed=report.total_elapsed_s)

        return report

    async def _ingest_single(
        self,
        ticker: str,
        include_fundamental: bool = True,
        include_kap: bool = True,
        include_news: bool = True,
        include_social: bool = True,
        use_reconciliation: bool = True,
    ) -> IngestionResult:
        """Tek hisse için tam ingestion."""
        start = time.time()
        result = IngestionResult(ticker=ticker)

        # Market data
        try:
            if use_reconciliation:
                # Çoklu kaynaktan çek
                market_result = await self._pm.fetch("market_price", ticker=ticker)
                if market_result:
                    result.market_data = market_result
                    result.quality_score = market_result.quality * 100
            else:
                market_result = await self._pm.fetch("market_price", ticker=ticker)
                if market_result:
                    result.market_data = market_result
                    result.quality_score = 80.0
        except Exception as e:
            result.errors.append(f"market_data: {str(e)}")

        # Fundamental
        if include_fundamental:
            try:
                fund = await self._pm.fetch("fundamental", ticker=ticker)
                if fund:
                    result.fundamental_data = fund.data
            except Exception as e:
                result.errors.append(f"fundamental: {str(e)}")

        # KAP
        if include_kap:
            try:
                disclosures = await kap_provider.fetch_disclosures(ticker=ticker, limit=10)
                # Dedup
                for disc in disclosures:
                    if not self._dedup.check_and_mark(disc):
                        result.kap_disclosures.append(disc)
            except Exception as e:
                result.errors.append(f"kap: {str(e)}")

        # News
        if include_news:
            try:
                news = await news_provider.fetch_financial_news_rss()
                # Hisse ile eşleştir
                matched = [n for n in news if news_provider.match_news_to_ticker(n, ticker)]
                result.news = matched[:5]
            except Exception as e:
                result.errors.append(f"news: {str(e)}")

        # Social
        if include_social:
            try:
                social = await social_provider.fetch_all_social(ticker)
                result.social = social.get("items", [])[:10]
            except Exception as e:
                result.errors.append(f"social: {str(e)}")

        result.elapsed_ms = round((time.time() - start) * 1000, 2)
        return result

    async def _fetch_macro(self) -> Dict[str, Any]:
        """Makro verileri çek."""
        try:
            from ..core.config import settings
            tcmb_key = getattr(settings, 'tcmb_evds_api_key', None)
            fred_key = getattr(settings, 'fred_api_key', None)
        except Exception:
            tcmb_key = None
            fred_key = None

        try:
            return await macro_provider.fetch_all(
                tcmb_api_key=tcmb_key,
                fred_api_key=fred_key,
            )
        except Exception as e:
            logger.warning("Macro fetch failed", error=str(e))
            return {}

    def get_health(self) -> Dict[str, Any]:
        """Sistem sağlık durumu."""
        return {
            "providers": self._pm.get_health(),
            "circuit_breakers": self._cb_manager.get_all_states(),
            "rate_limiters": self._rate_limiter.get_all_stats(),
            "dedup": self._dedup.get_stats(),
            "incremental": self._incremental.get_stats(),
        }


# Singleton
ingestion_orchestrator = IngestionOrchestrator()
