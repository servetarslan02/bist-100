"""
ALPHA BIST — Historical Data Ingestion Pipeline

Incremental, PIT-safe, deduplication destekli veri ingestion.

Özellikler:
- Son başarılı ingestion timestamp'ini tutar
- Sadece yeni/değişmiş verileri çeker
- Provider başarısız olursa mevcut dataset'i bozmaz
- Partial ingestion güvenlidir
- Deduplication deterministic
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from .historical_contracts import (
    CatalystSnapshot,
    EventSnapshot,
)
from .historical_fundamental_provider import HistoricalFundamentalProvider
from .persistent_repository import PersistentHistoricalRepository

logger = structlog.get_logger()


class HistoricalIngestionPipeline:
    """Historical veri ingestion pipeline.

    Kullanım:
        pipeline = HistoricalIngestionPipeline(repo)
        pipeline.ingest_fundamentals(["THYAO", "GARAN", "AKBNK"])
        pipeline.ingest_kap_events(["THYAO", "GARAN"], days_back=365)
    """

    def __init__(
        self,
        repository: PersistentHistoricalRepository,
        fundamental_provider: HistoricalFundamentalProvider | None = None,
    ):
        self._repo = repository
        self._fund_provider = fundamental_provider or HistoricalFundamentalProvider()

    def ingest_fundamentals(
        self,
        tickers: list[str],
        force: bool = False,
    ) -> dict[str, Any]:
        """Ticker'lar için historical fundamental veri çek ve kaydet.

        Args:
            tickers: Hisse kodları listesi
            force: True ise cache'i bypass et ve tekrar çek

        Returns:
            {ticker: snapshot_count} veya {ticker: error_message}
        """
        results = {}
        last_ingestion = self._repo.get_last_ingestion_time("fundamental")

        # Son ingestion'dan bu yana yeterli zaman geçmediyse skip
        if not force and last_ingestion:
            try:
                last_dt = datetime.fromisoformat(last_ingestion)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=UTC)
                hours_since = (datetime.now(UTC) - last_dt).total_seconds() / 3600
                if hours_since < 1:  # 1 saatten az geçtiyse skip
                    logger.info("Fundamental ingestion skipped (too recent)", hours_since=round(hours_since, 1))
                    return {"status": "skipped", "reason": "too_recent"}
            except ValueError:
                logger.warning("Data error in ingest_fundamentals: ValueError", exc_info=True)

        success_count = 0
        for ticker in tickers:
            try:
                snapshots = self._fund_provider.fetch_historical_fundamentals(ticker, max_periods=8)

                if not snapshots:
                    results[ticker] = "no_data"
                    continue

                # Her snapshot'ı kaydet (duplicate kontrolü repository'de)
                saved = 0
                for snapshot in snapshots:
                    # Publication date yoksa UNKNOWN olarak işaretle
                    if not snapshot.available_at:
                        snapshot.status = "UNKNOWN"

                    if self._repo.add_fundamental_snapshot(snapshot):
                        saved += 1

                results[ticker] = saved
                success_count += 1

            except Exception as e:
                logger.error("Fundamental ingestion failed", ticker=ticker, error=str(e))
                results[ticker] = str(e)

        # Son ingestion timestamp'ini güncelle
        if success_count > 0:
            self._repo.set_last_ingestion_time("fundamental", datetime.now(UTC).isoformat())

        logger.info("Fundamental ingestion completed", tickers=len(tickers), success=success_count)

        return results

    def ingest_kap_events(
        self,
        tickers: list[str],
        days_back: int = 365,
        force: bool = False,
    ) -> dict[str, Any]:
        """Ticker'lar için historical KAP event'leri çek ve kaydet.

        Args:
            tickers: Hisse kodları listesi
            days_back: Kaç gün geriye gidilecek
            force: True ise son ingestion kontrolünü bypass et

        Returns:
            {ticker: event_count} veya {ticker: error_message}
        """
        results = {}
        last_ingestion = self._repo.get_last_ingestion_time("kap")

        if not force and last_ingestion:
            try:
                last_dt = datetime.fromisoformat(last_ingestion)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=UTC)
                hours_since = (datetime.now(UTC) - last_dt).total_seconds() / 3600
                if hours_since < 1:
                    logger.info("KAP ingestion skipped (too recent)", hours_since=round(hours_since, 1))
                    return {"status": "skipped", "reason": "too_recent"}
            except ValueError:
                logger.warning("Data error in ingest_kap_events: ValueError", exc_info=True)

        try:
            from ..ingestion.providers.kap_provider import KAPProvider

            kap = KAPProvider()
        except ImportError:
            logger.error("KAP provider not available")
            return {"status": "error", "reason": "provider_unavailable"}

        from_date = (datetime.now(UTC) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        to_date = datetime.now(UTC).strftime("%Y-%m-%d")

        success_count = 0
        for ticker in tickers:
            try:
                import asyncio

                events = asyncio.run(
                    kap.fetch_disclosures(
                        from_date=from_date,
                        to_date=to_date,
                        ticker=ticker,
                        limit=100,
                    )
                )

                if not events:
                    results[ticker] = 0
                    continue

                saved = 0
                for event in events:
                    event_id = event.get("id", "")
                    if not event_id:
                        continue

                    snapshot = EventSnapshot(
                        event_id=event_id,
                        ticker=ticker,
                        published_at=event.get("publish_date", ""),
                        event_type=event.get("category", "OTHER"),
                        title=event.get("title", ""),
                        sentiment=event.get("sentiment", 0),
                        importance=event.get("importance", 0.5),
                        source="kap",
                        content=event.get("summary", ""),
                    )

                    if self._repo.add_event_snapshot(snapshot):
                        saved += 1

                results[ticker] = saved
                success_count += 1

            except Exception as e:
                logger.error("KAP ingestion failed", ticker=ticker, error=str(e))
                results[ticker] = str(e)

        if success_count > 0:
            self._repo.set_last_ingestion_time("kap", datetime.now(UTC).isoformat())

        logger.info("KAP ingestion completed", tickers=len(tickers), success=success_count)

        return results

    def ingest_news_events(
        self,
        tickers: list[str],
        force: bool = False,
    ) -> dict[str, Any]:
        """RSS feed'lerden güncel haberleri çek ve kaydet.

        NOT: RSS sadece son günleri döndürür. Historical news verisi için
        ayrı bir data kaynağı gerekir.

        Args:
            tickers: Hisse kodları listesi
            force: True ise son ingestion kontrolünü bypass et

        Returns:
            {ticker: event_count} veya {ticker: error_message}
        """
        last_ingestion = self._repo.get_last_ingestion_time("news")

        if not force and last_ingestion:
            try:
                last_dt = datetime.fromisoformat(last_ingestion)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=UTC)
                hours_since = (datetime.now(UTC) - last_dt).total_seconds() / 3600
                if hours_since < 1:
                    logger.info("News ingestion skipped (too recent)")
                    return {"status": "skipped", "reason": "too_recent"}
            except ValueError:
                logger.warning("Data error in ingest_news_events: ValueError", exc_info=True)

        try:
            from ..ingestion.providers.news_provider import NewsProvider

            news = NewsProvider()
        except ImportError:
            logger.error("News provider not available")
            return {"status": "error", "reason": "provider_unavailable"}

        try:
            import asyncio

            raw_news = asyncio.run(news.fetch_financial_news_rss())
        except Exception as e:
            logger.error("News fetch failed", error=str(e))
            return {"status": "error", "reason": str(e)}

        if not raw_news:
            return {"status": "no_data"}

        # Ticker eşleştirme
        saved_total = 0
        for item in raw_news:
            title = item.get("title", "").strip()
            if not title:
                continue

            # Her ticker için eşleştir
            for ticker in tickers:
                if not news.match_news_to_ticker(item, ticker):
                    continue

                pub_date = item.get("published", "")
                if not pub_date:
                    continue

                import hashlib

                event_id = hashlib.md5(f"{pub_date}:{title}:{ticker}".encode()).hexdigest()[:16]

                snapshot = EventSnapshot(
                    event_id=event_id,
                    ticker=ticker,
                    published_at=pub_date,
                    event_type="NEWS",
                    title=title,
                    sentiment=item.get("sentiment", 0),
                    importance=item.get("importance", 0.5),
                    source="news",
                    content=item.get("summary", ""),
                )

                if self._repo.add_event_snapshot(snapshot):
                    saved_total += 1

        self._repo.set_last_ingestion_time("news", datetime.now(UTC).isoformat())

        logger.info("News ingestion completed", tickers=len(tickers), events=saved_total)

        return {"status": "ok", "events": saved_total}

    def derive_catalysts_from_events(
        self,
        tickers: list[str],
    ) -> dict[str, Any]:
        """KAP event'lerinden catalyst snapshot'ları türet.

        Catalyst = gelecekte gerçekleşecek bir olayın announcement'ı.
        announcement_date <= as_of_date olan catalyst'ler kullanılabilir.
        """
        conn = self._repo._get_conn()
        results = {}

        for ticker in tickers:
            # KAP event'lerinden catalyst türlerini belirle
            result = conn.execute(
                """SELECT * FROM event_snapshots
                   WHERE ticker = ? AND source = 'kap'
                   ORDER BY published_at DESC""",
                (ticker,),
            )
            columns = [desc[0] for desc in result.description]
            rows = [dict(zip(columns, row)) for row in result.fetchall()]

            saved = 0
            for row in rows:
                category = row["event_type"]
                published_at = row["published_at"]

                # Catalyst türünü belirle
                catalyst_type = self._category_to_catalyst_type(category)
                if not catalyst_type:
                    continue

                # Event date: published_at + 30 gün (tahmini)
                try:
                    from datetime import timedelta

                    pub_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                    event_dt = pub_dt + timedelta(days=30)
                    event_date = event_dt.strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    event_date = published_at[:10]

                snapshot = CatalystSnapshot(
                    event_id=f"CAT-{row['event_id']}",
                    ticker=ticker,
                    announcement_date=published_at[:10],
                    event_date=event_date,
                    catalyst_type=catalyst_type,
                    importance=row["importance"],
                    source="kap",
                )

                if self._repo.add_catalyst_snapshot(snapshot):
                    saved += 1

            results[ticker] = saved

        return results

    @staticmethod
    def _category_to_catalyst_type(category: str) -> str | None:
        """KAP kategorisini catalyst türüne çevir."""
        mapping = {
            "FINANCIAL_REPORT": "EARNINGS",
            "DIVIDEND": "DIVIDEND_DATE",
            "CAPITAL_INCREASE": "OTHER",
            "MERGER_ACQUISITION": "OTHER",
            "SHARE_BUYBACK": "OTHER",
            "CONTRACT": "CONTRACT_EXPIRY",
            "BOARD_CHANGE": "OTHER",
        }
        return mapping.get(category)
