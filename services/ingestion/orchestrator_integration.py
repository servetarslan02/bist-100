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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from .circuit_breaker import CircuitBreakerManager
from .deduplication import EventDeduplicator
from .incremental import IncrementalFetcher
from .ingestion_metrics import ingestion_metrics
from .point_in_time import PointInTimeValidator
from .provider_manager import ProviderManager, ProviderResult
from .providers.bist_provider import bist_provider
from .providers.fundamental_provider import fundamental_provider
from .providers.kap_provider import kap_provider
from .providers.macro_provider import macro_provider
from .providers.matriks_provider import matriks_provider
from .providers.news_provider import news_provider
from .providers.social_provider import social_provider
from .providers.yfinance_provider import yfinance_provider
from .rate_limiter import create_default_rate_limiter

logger = structlog.get_logger()


@dataclass
class IngestionResult:
    """Tek bir hisse için ingestion sonuç raporu.

    Attributes:
        ticker: Hisse sembolü.
        market_data: Piyasa verisi sonucu.
        fundamental_data: Temel veri (bilanço, rasyo).
        kap_disclosures: KAP açıklamaları.
        news: İlgili haberler.
        social: Sosyal medya gönderileri.
        macro: Makro ekonomik veriler.
        quality_score: Veri kalite puanı (0-100).
        reconciliation: Kaynak doğrulama sonucu.
        errors: Hata mesajları listesi.
        elapsed_ms: İşlem süresi (milisaniye).
        timestamp: Sonuç zaman damgası.
    """

    ticker: str
    market_data: ProviderResult | None = None
    fundamental_data: dict[str, Any] | None = None
    kap_disclosures: list[dict[str, Any]] = field(default_factory=list)
    news: list[dict[str, Any]] = field(default_factory=list)
    social: list[dict[str, Any]] = field(default_factory=list)
    macro: dict[str, Any] = field(default_factory=dict)
    quality_score: float = 0.0
    reconciliation: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"IngestionResult(ticker={self.ticker!r}, "
            f"quality={self.quality_score:.1f}, "
            f"errors={len(self.errors)})"
        )


@dataclass
class PipelineReport:
    """Tam pipeline çalıştırma raporu.

    Attributes:
        total_tickers: Toplam hisse sayısı.
        successful: Başarılı ingestion sayısı.
        failed: Başarısız ingestion sayısı.
        skipped: Atlanan hisse sayısı (incremental).
        avg_quality_score: Ortalama kalite puanı.
        total_elapsed_s: Toplam süre (saniye).
        results: Ticker bazlı sonuçlar.
        macro_data: Makro veriler.
        errors: Genel hata mesajları.
        metrics: Sistem metrikleri.
    """

    total_tickers: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    avg_quality_score: float = 0.0
    total_elapsed_s: float = 0.0
    results: dict[str, IngestionResult] = field(default_factory=dict)
    macro_data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"PipelineReport(total={self.total_tickers}, "
            f"success={self.successful}, failed={self.failed}, "
            f"skipped={self.skipped})"
        )


class IngestionOrchestrator:
    """Ingestion orchestrator — tüm pipeline'ı yönetir.

    Market data + Fundamental + KAP + News + Social + Macro
    Tüm resilience katmanları (circuit breaker, rate limiter,
    dedup, incremental) ile korumalı.
    """

    def __init__(self) -> None:
        """IngestionOrchestrator örneği oluşturur.

        Tüm resilience katmanlarını ve provider manager'ı başlatır.
        """
        # Resilience katmanları
        self._cb_manager = CircuitBreakerManager()
        self._rate_limiter = create_default_rate_limiter()
        self._pit = PointInTimeValidator()
        self._dedup = EventDeduplicator()
        self._incremental = IncrementalFetcher()

        # Provider manager
        self._pm = ProviderManager(
            rate_limiter_instance=self._rate_limiter,
            circuit_breaker_manager=self._cb_manager,
        )
        self._register_providers()

    def _register_providers(self) -> None:
        """Provider'ları ProviderManager'a kaydeder.

        Market price ve fundamental provider'ları öncelik sırasıyla kaydeder.
        """
        # Market data providers
        self._pm.register(
            "market_price",
            "yfinance",
            lambda **kw: yfinance_provider.fetch_current_price(kw.get("ticker", "")),
            priority=0,
            timeout_s=20,
        )
        self._pm.register(
            "market_price",
            "bist",
            lambda **kw: bist_provider.fetch_stock_price(kw.get("ticker", "")),
            priority=1,
            timeout_s=15,
        )
        self._pm.register(
            "market_price",
            "matriks",
            lambda **kw: matriks_provider.fetch_stock_price(kw.get("ticker", "")),
            priority=2,
            timeout_s=15,
        )

        # Fundamental providers
        self._pm.register(
            "fundamental",
            "yfinance",
            lambda **kw: fundamental_provider.fetch_fundamentals(kw.get("ticker", "")),
            priority=0,
            timeout_s=20,
        )
        self._pm.register(
            "fundamental",
            "kap",
            lambda **kw: kap_provider.fetch_financial_data(kw.get("ticker", "")),
            priority=1,
            timeout_s=15,
        )

    async def run_full_ingestion(
        self,
        tickers: list[str],
        include_fundamental: bool = True,
        include_kap: bool = True,
        include_news: bool = True,
        include_social: bool = True,
        include_macro: bool = True,
        use_reconciliation: bool = True,
    ) -> PipelineReport:
        """Tam ingestion pipeline çalıştırır.

        Market data, fundamental, KAP, haber, sosyal medya ve makro
        verilerini paralel olarak çeker.

        Args:
            tickers: Hisse listesi.
            include_fundamental: Fundamental veri dahil mi.
            include_kap: KAP açıklamaları dahil mi.
            include_news: Haberler dahil mi.
            include_social: Sosyal medya dahil mi.
            include_macro: Makro veriler dahil mi.
            use_reconciliation: Kaynaklar arası doğrulama.

        Returns:
            PipelineReport: Tam pipeline raporu.
        """
        start_time = time.time()
        report = PipelineReport(total_tickers=len(tickers))

        logger.info("Starting full ingestion", tickers=len(tickers))

        with ingestion_metrics.track_pipeline("full"):
            # 1. Makro verileri paralel çek
            if include_macro:
                report.macro_data = await self._fetch_macro()

            # 2. Haberleri tek seferde çek (tüm ticker'lar paylaşır)
            shared_news: list[dict[str, Any]] = []
            if include_news:
                try:
                    shared_news = await news_provider.fetch_financial_news_rss()
                except Exception as exc:
                    logger.warning("Shared news fetch failed", error=str(exc))

            # 3. Market data + fundamental + KAP paralel
            market_tasks: list[asyncio.Task[IngestionResult]] = []
            for ticker in tickers:
                if not self._incremental.should_fetch(ticker, min_interval_seconds=60):
                    report.skipped += 1
                    continue
                market_tasks.append(
                    asyncio.create_task(
                        self._ingest_single(
                            ticker,
                            include_fundamental=include_fundamental,
                            include_kap=include_kap,
                            include_news=False,  # Haberler yukarıda çekildi
                            include_social=include_social,
                            use_reconciliation=use_reconciliation,
                            shared_news=shared_news,
                        )
                    )
                )

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
        report.avg_quality_score = round(sum(quality_scores) / len(quality_scores) if quality_scores else 0, 1)

        # Metrics
        report.metrics = {
            "circuit_breakers": self._cb_manager.get_all_states(),
            "rate_limiters": self._rate_limiter.get_all_stats(),
            "dedup": self._dedup.get_stats(),
            "incremental": self._incremental.get_stats(),
        }

        logger.info(
            "Ingestion completed",
            total=report.total_tickers,
            successful=report.successful,
            failed=report.failed,
            skipped=report.skipped,
            elapsed=report.total_elapsed_s,
        )

        return report

    async def _ingest_single(
        self,
        ticker: str,
        include_fundamental: bool = True,
        include_kap: bool = True,
        include_news: bool = True,
        include_social: bool = True,
        use_reconciliation: bool = True,
        shared_news: list[dict[str, Any]] | None = None,
    ) -> IngestionResult:
        """Tek bir hisse için tam ingestion yapar.

        Args:
            ticker: Hisse sembolü.
            include_fundamental: Fundamental veri dahil mi.
            include_kap: KAP açıklamaları dahil mi.
            include_news: Haberler dahil mi (shared_news yoksa tek başına çeker).
            include_social: Sosyal medya dahil mi.
            use_reconciliation: Kaynaklar arası doğrulama.
            shared_news: Önceden çekilmiş haber listesi (tüm ticker'lar paylaşır).

        Returns:
            IngestionResult: Hisse bazlı sonuç.
        """
        start = time.time()
        result = IngestionResult(ticker=ticker)

        # Market data
        try:
            market_result = await self._pm.fetch("market_price", ticker=ticker)
            if market_result:
                result.market_data = market_result
                result.quality_score = market_result.quality * 100 if use_reconciliation else 80.0
        except Exception as exc:
            result.errors.append(f"market_data: {exc}")

        # Fundamental
        if include_fundamental:
            try:
                fund = await self._pm.fetch("fundamental", ticker=ticker)
                if fund:
                    result.fundamental_data = fund.data
            except Exception as exc:
                result.errors.append(f"fundamental: {exc}")

        # KAP
        if include_kap:
            try:
                disclosures = await kap_provider.fetch_disclosures(ticker=ticker, limit=10)
                for disc in disclosures:
                    if not self._dedup.check_and_mark(disc):
                        result.kap_disclosures.append(disc)
            except Exception as exc:
                result.errors.append(f"kap: {exc}")

        # News — shared_news kullan veya tek başına çek
        if include_news or shared_news is not None:
            try:
                news_items = shared_news if shared_news is not None else await news_provider.fetch_financial_news_rss()
                matched = [n for n in news_items if news_provider.match_news_to_ticker(n, ticker)]
                result.news = matched[:5]
            except Exception as exc:
                result.errors.append(f"news: {exc}")

        # Social
        if include_social:
            try:
                social = await social_provider.fetch_all_social(ticker)
                result.social = social.get("items", [])[:10]
            except Exception as exc:
                result.errors.append(f"social: {exc}")

        result.elapsed_ms = round((time.time() - start) * 1000, 2)
        return result

    async def _fetch_macro(self) -> dict[str, Any]:
        """Makro ekonomik verileri çeker.

        Returns:
            Makro veri sözlüğü. Hata durumunda boş dict.
        """
        try:
            from ..core.config import settings

            tcmb_key = getattr(settings, "tcmb_evds_api_key", None)
            fred_key = getattr(settings, "fred_api_key", None)
        except Exception:
            tcmb_key = None
            fred_key = None

        try:
            return await macro_provider.fetch_all(
                tcmb_api_key=tcmb_key,
                fred_api_key=fred_key,
            )
        except Exception as exc:
            logger.warning("Macro fetch failed", error=str(exc))
            return {}

    def get_health(self) -> dict[str, Any]:
        """Sistem sağlık durumunu döndürür.

        Returns:
            Provider, circuit breaker, rate limiter, dedup ve incremental durumları.
        """
        return {
            "providers": self._pm.get_health(),
            "circuit_breakers": self._cb_manager.get_all_states(),
            "rate_limiters": self._rate_limiter.get_all_stats(),
            "dedup": self._dedup.get_stats(),
            "incremental": self._incremental.get_stats(),
        }


# Singleton
ingestion_orchestrator = IngestionOrchestrator()


__all__ = [
    "IngestionResult",
    "PipelineReport",
    "IngestionOrchestrator",
    "ingestion_orchestrator",
]
