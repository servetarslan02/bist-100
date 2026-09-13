"""ALPHA BIST — Otonom KAP (Kamuyu Aydınlatma Platformu) İstihbarat ve Duygu Servisi.

Bu servis:
1. Resmi ve kamuya açık KAP bildirimlerini (kap.org.tr ve açık RSS akışları) sıfır maliyetle çeker.
2. KAP bildirimlerini NLP ve kural tabanlı semantik motorla ayrıştırır:
   - Şirket kodu (ticker)
   - Olay türü (Sözleşme/İhale, Bedelsiz, Pay Geri Alımı, Yatırım/Kapasite, Temettü vb.)
   - Finansal etki yönü (-1.0 ile +1.0 arası) ve şiddeti (0.0 ile 1.0)
3. Her hisse senedi için normalize edilmiş 'kap_sentiment_avg', 'kap_sentiment_latest' ve 'kap_avg_importance'
   metriklerini canlı olarak BistMLScanner ve yapay zeka modellerine sunar.
4. DuckDB yerel veri tabanında (data/kap_intelligence.duckdb) geçmiş olay hafızası tutar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import structlog

from services.intelligence.kap_extractor import KAPExtractedEvent, KAPExtractor

logger = structlog.get_logger("kap_intelligence")

DB_PATH = Path("data/kap_intelligence.duckdb")


@dataclass
class TickerKAPMetrics:
    ticker: str
    kap_sentiment_avg: float = 0.50
    kap_sentiment_latest: float = 0.50
    kap_avg_importance: float = 0.0
    has_positive_catalyst: bool = False
    has_negative_catalyst: bool = False
    latest_event_type: str = "NEUTRAL"
    latest_title: str = ""
    event_count_30d: int = 0


class KAPIntelligenceService:
    """KAP bildirimlerini toplayan, NLP ile puanlayan ve tarama modellerine besleyen ana servis."""

    _instance: KAPIntelligenceService | None = None

    def __new__(cls) -> KAPIntelligenceService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.extractor = KAPExtractor()
        self._metrics_cache: dict[str, TickerKAPMetrics] = {}
        self._recent_events: list[dict[str, Any]] = []
        self._init_db()

    def _init_db(self) -> None:
        """KAP olay hafızası için yerel DuckDB tablosunu hazırlar."""
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = duckdb.connect(str(DB_PATH))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kap_events (
                    ticker VARCHAR,
                    kap_id VARCHAR,
                    event_type VARCHAR,
                    financial_impact DOUBLE,
                    impact_magnitude DOUBLE,
                    raw_title VARCHAR,
                    raw_summary VARCHAR,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (ticker, kap_id)
                )
            """)
            # Geçmiş verilerden hafızayı doldur
            rows = conn.execute("""
                SELECT ticker, event_type, financial_impact, impact_magnitude, raw_title, created_at
                FROM kap_events
                ORDER BY created_at DESC
                LIMIT 500
            """).fetchall()
            conn.close()

            # Önbelleği güncelle
            self._recalculate_cache_from_rows(rows)
            logger.info("kap_intelligence_db_hazirlandi", yuklenen_olay_sayisi=len(rows))
        except Exception as exc:
            logger.warning("kap_db_baglanti_notu", hata=str(exc))

    def _recalculate_cache_from_rows(self, rows: list[tuple]) -> None:
        """Veritabanındaki kayıtlardan hisse bazlı KAP metriklerini hesaplar."""
        ticker_data: dict[str, list[tuple]] = {}
        for r in rows:
            tk, ev_type, impact, mag, title, dt = r
            if tk not in ticker_data:
                ticker_data[tk] = []
            ticker_data[tk].append((ev_type, impact, mag, title, dt))

        for tk, ev_list in ticker_data.items():
            impacts = [x[1] for x in ev_list]
            mags = [x[2] for x in ev_list]
            latest_ev = ev_list[0]

            # [-1.0, 1.0] aralığını [0.0, 1.0] aralığına normalize et (0.5 nötr)
            norm_avg = float(np_clip(0.5 + (sum(impacts) / len(impacts)) * 0.5, 0.0, 1.0))
            norm_latest = float(np_clip(0.5 + latest_ev[1] * 0.5, 0.0, 1.0))
            avg_mag = float(np_clip(sum(mags) / len(mags), 0.0, 1.0))

            has_pos = any(x[1] >= 0.15 for x in ev_list)
            has_neg = any(x[1] <= -0.15 for x in ev_list)

            self._metrics_cache[tk] = TickerKAPMetrics(
                ticker=tk,
                kap_sentiment_avg=round(norm_avg, 3),
                kap_sentiment_latest=round(norm_latest, 3),
                kap_avg_importance=round(avg_mag, 3),
                has_positive_catalyst=has_pos,
                has_negative_catalyst=has_neg,
                latest_event_type=latest_ev[0],
                latest_title=latest_ev[3],
                event_count_30d=len(ev_list),
            )

    def get_ticker_kap_metrics(self, ticker: str) -> dict[str, Any]:
        """BistMLScanner ve modeller için anlık hisse KAP duygu metriklerini döner."""
        clean_tk = ticker.replace(".IS", "").strip().upper()
        metrics = self._metrics_cache.get(clean_tk)
        if metrics:
            return {
                "kap_sentiment_avg": metrics.kap_sentiment_avg,
                "kap_sentiment_latest": metrics.kap_sentiment_latest,
                "kap_avg_importance": metrics.kap_avg_importance,
                "has_positive_catalyst": metrics.has_positive_catalyst,
                "has_negative_catalyst": metrics.has_negative_catalyst,
                "latest_event_type": metrics.latest_event_type,
                "latest_title": metrics.latest_title,
            }
        # Varsayılan nötr metrikler
        return {
            "kap_sentiment_avg": 0.50,
            "kap_sentiment_latest": 0.50,
            "kap_avg_importance": 0.0,
            "has_positive_catalyst": False,
            "has_negative_catalyst": False,
            "latest_event_type": "NONE",
            "latest_title": "",
        }

    async def ingest_disclosure(
        self,
        ticker: str,
        title: str,
        summary: str = "",
        kap_id: str | None = None,
    ) -> KAPExtractedEvent:
        """Tekil bir KAP bildirimini sisteme işler, puanlar ve veritabanına yazar."""
        clean_tk = ticker.replace(".IS", "").strip().upper()
        actual_id = kap_id or f"kap_{clean_tk}_{int(datetime.now(UTC).timestamp())}"

        event = self.extractor.extract(
            ticker=clean_tk,
            kap_id=actual_id,
            title=title,
            summary=summary,
        )

        # Veritabanına kaydet
        try:
            conn = duckdb.connect(str(DB_PATH))
            conn.execute("""
                INSERT OR REPLACE INTO kap_events
                (ticker, kap_id, event_type, financial_impact, impact_magnitude, raw_title, raw_summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (event.ticker, event.kap_id, event.event_type, event.financial_impact, event.impact_magnitude, event.raw_title, event.raw_summary))
            conn.close()
        except Exception as exc:
            logger.warning("kap_event_db_kayit_hatasi", hata=str(exc))

        # Önbelleği güncelle
        norm_latest = float(np_clip(0.5 + event.financial_impact * 0.5, 0.0, 1.0))
        cur_metric = self._metrics_cache.get(clean_tk)
        if cur_metric:
            cur_metric.kap_sentiment_latest = norm_latest
            cur_metric.latest_event_type = event.event_type
            cur_metric.latest_title = event.raw_title
            cur_metric.kap_avg_importance = max(cur_metric.kap_avg_importance, event.impact_magnitude)
            if event.financial_impact >= 0.15:
                cur_metric.has_positive_catalyst = True
            elif event.financial_impact <= -0.15:
                cur_metric.has_negative_catalyst = True
            cur_metric.event_count_30d += 1
        else:
            self._metrics_cache[clean_tk] = TickerKAPMetrics(
                ticker=clean_tk,
                kap_sentiment_avg=norm_latest,
                kap_sentiment_latest=norm_latest,
                kap_avg_importance=event.impact_magnitude,
                has_positive_catalyst=event.financial_impact >= 0.15,
                has_negative_catalyst=event.financial_impact <= -0.15,
                latest_event_type=event.event_type,
                latest_title=event.raw_title,
                event_count_30d=1,
            )

        self._recent_events.insert(0, {
            "ticker": clean_tk,
            "event_type": event.event_type,
            "financial_impact": event.financial_impact,
            "impact_magnitude": event.impact_magnitude,
            "title": event.raw_title,
            "timestamp": datetime.now(UTC).isoformat(),
        })
        if len(self._recent_events) > 100:
            self._recent_events.pop()

        logger.info(
            "kap_bildirimi_islendi",
            ticker=clean_tk,
            event_type=event.event_type,
            etki=f"{event.financial_impact:+.2f}",
            siddet=event.impact_magnitude,
        )
        return event

    def get_recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        """Son işlenen KAP bildirimlerinin özet listesini döner."""
        return self._recent_events[:limit]

    async def sync_live_disclosures(self, limit: int = 50) -> int:
        """KAPProvider (ağ sağlayıcısı) üzerinden en güncel bildirimleri çeker ve sisteme kaydeder."""
        try:
            from services.ingestion.providers.kap_provider import KAPProvider

            provider = KAPProvider()
            items = await provider.fetch_disclosures(limit=limit)
            ingested_count = 0
            for item in items:
                ticker = item.get("ticker")
                title = item.get("title", "")
                summary = item.get("summary", "")
                if ticker and title:
                    self.ingest_disclosure(
                        ticker=ticker,
                        title=title,
                        summary=summary,
                        kap_id=item.get("kap_id"),
                    )
                    ingested_count += 1
            logger.info("canli_kap_bildirimleri_senkronize_edildi", adet=ingested_count)
            return ingested_count
        except Exception as exc:
            logger.warning("canli_kap_senkronizasyonu_hatasi", hata=str(exc))
            return 0


def np_clip(val: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, val))


# Global Singleton instance
kap_intelligence_service = KAPIntelligenceService()
