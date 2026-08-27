"""
ALPHA BIST — Historical Data Adapter

Historical data repository'den canonical scoring pipeline'a köprü.

Bu adapter:
- Fundamental snapshot'tan Motor4 feature'ları üretir
- KAP/News event'lerinden Motor5 feature'ları üretir
- Catalyst event'lerinden Motor6 feature'ları üretir
- PIT-safe: sadece current_date'e kadar bilinen verileri kullanır
- Missing veriyi 50 ile doldurmaz (data_quality olarak işaretler)
"""

from typing import Any

import numpy as np
import structlog

from .historical_contracts import (
    HistoricalDataRepository,
)

logger = structlog.get_logger()


class HistoricalDataAdapter:
    """Historical data repository → canonical scoring adapter."""

    def __init__(self, repository: HistoricalDataRepository | None = None):
        if repository is None:
            from .persistent_repository import PersistentHistoricalRepository
            self._repo = PersistentHistoricalRepository()
        else:
            self._repo = repository

    def get_fundamental_features(
        self,
        ticker: str,
        current_date: str,
    ) -> dict[str, Any]:
        """Historical fundamental snapshot'tan feature dict üret.

        PIT kuralı: available_at <= current_date

        Returns:
            Canonical scoring'in beklediği format:
            - fcf_yield_pct, balance_sheet_quality, value_score, quality_score
            - raw_* (ham değerler)
        """
        snapshots = self._repo.get_fundamental_snapshots(ticker, current_date)
        if not snapshots:
            return {}

        # En güncel snapshot (available_at <= current_date)
        latest = snapshots[0]
        v = latest.values

        features = {}

        # Ham değerler (hem raw_ hem orijinal isim)
        for key, val in v.items():
            if val is not None:
                try:
                    float_val = float(val)
                    features[key] = float_val
                    features[f"raw_{key}"] = float_val
                except (TypeError, ValueError):
                    logger.warning("Error in get_fundamental_features: (TypeError, ValueError)", exc_info=True)

        # === DERIVED FEATURES (Motor4 ile uyumlu) ===

        # fcf_yield_pct
        fcf = v.get("free_cash_flow", 0)
        market_cap = v.get("market_cap", 0)
        if fcf and market_cap and market_cap > 0:
            features["fcf_yield_pct"] = round(float(fcf / market_cap * 100), 4)

        # balance_sheet_quality
        quality_score = 50
        debt_eq = v.get("debt_to_equity", 0)
        current_ratio = v.get("current_ratio", 0)
        if debt_eq:
            if debt_eq < 0.3:
                quality_score += 25
            elif debt_eq < 0.5:
                quality_score += 15
            elif debt_eq > 2:
                quality_score -= 25
            elif debt_eq > 1:
                quality_score -= 10
        if current_ratio:
            if current_ratio > 2:
                quality_score += 15
            elif current_ratio > 1.5:
                quality_score += 10
            elif current_ratio < 1:
                quality_score -= 15
        features["balance_sheet_quality"] = round(float(min(100, max(0, quality_score))), 0)

        # value_score
        # Sector-relative scoring: PE ratios are compared against sector medians.
        # A PE of 20 may be cheap for tech but expensive for utilities.
        # When sector_pe_median is available, we adjust the raw PE threshold.
        pe = v.get("pe_ratio", 0)
        pb = v.get("pb_ratio", 0)
        fcf_yield = v.get("fcf_yield", 0)
        sector_pe_median = v.get("sector_pe_median", 0)
        value_score = 0
        # Sector-adjusted PE scoring
        pe_threshold_low = 15
        pe_threshold_high = 25
        if sector_pe_median and sector_pe_median > 0:
            # Adjust thresholds relative to sector median
            pe_threshold_low = sector_pe_median * 0.7
            pe_threshold_high = sector_pe_median * 1.1
        if pe and pe > 0 and pe < pe_threshold_low:
            value_score += 30
        elif pe and pe < pe_threshold_high:
            value_score += 15
        if pb and pb > 0 and pb < 1.5:
            value_score += 30
        elif pb and pb < 3:
            value_score += 15
        if fcf_yield and fcf_yield > 0.05:
            value_score += 40
        elif fcf_yield and fcf_yield > 0.02:
            value_score += 20
        features["value_score"] = round(float(min(100, value_score)), 0)

        # quality_score
        roe = v.get("roe", 0)
        profit_margin = v.get("profit_margin", 0)
        q_score = 0
        if roe and roe > 0.15:
            q_score += 40
        elif roe and roe > 0.1:
            q_score += 20
        if profit_margin and profit_margin > 0.2:
            q_score += 30
        elif profit_margin and profit_margin > 0.1:
            q_score += 15
        q_score += features.get("balance_sheet_quality", 50) * 0.3
        features["quality_score"] = round(float(min(100, q_score)), 0)

        return features

    def get_kap_events(
        self,
        ticker: str,
        current_date: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Historical KAP event'lerinden Motor5 formatında event listesi üret.

        PIT kuralı: published_at <= current_date
        Duplicate kontrolü: aynı event_id ile sadece bir kez döner.
        """
        events = self._repo.get_event_snapshots(
            ticker, current_date, event_types=None
        )

        # Duplicate kontrolü
        seen_ids = set()
        result = []
        for event in events:
            if event.event_id in seen_ids:
                continue
            seen_ids.add(event.event_id)
            result.append({
                "id": event.event_id,
                "ticker": event.ticker,
                "title": event.title,
                "category": event.event_type,
                "publish_date": event.published_at[:10],
                "sentiment": event.sentiment,
                "importance": event.importance,
                "source": event.source,
            })
            if len(result) >= limit:
                break

        return result

    def get_news_events(
        self,
        ticker: str,
        current_date: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Historical news event'lerinden Motor5 formatında event listesi üret.

        PIT kuralı: published_at <= current_date
        Duplicate kontrolü: aynı event_id ile sadece bir kez döner.
        """
        events = self._repo.get_event_snapshots(
            ticker, current_date, event_types=None
        )

        # Sadece news kaynaklarını filtrele
        news_events = [e for e in events if e.source in ("news", "rss")]

        # Duplicate kontrolü
        seen_ids = set()
        result = []
        for event in news_events:
            if event.event_id in seen_ids:
                continue
            seen_ids.add(event.event_id)
            result.append({
                "title": event.title,
                "published": event.published_at[:10],
                "date": event.published_at[:10],
                "sentiment": event.sentiment,
                "importance": event.importance,
                "source": event.source,
                "ticker": event.ticker,
            })
            if len(result) >= limit:
                break

        return result

    def get_catalyst_events(
        self,
        ticker: str,
        current_date: str,
    ) -> list[dict[str, Any]]:
        """Historical catalyst event'lerinden Motor6 formatında event listesi üret.

        PIT kuralı: announcement_date <= current_date

        Catalyst'in kendisi gelecekte olabilir ama announcement bilgisi bilinmeli.
        """
        catalysts = self._repo.get_catalyst_snapshots(ticker, current_date)

        result = []
        for cat in catalysts:
            # days_until: event_date - current_date
            try:
                from datetime import datetime
                d_event = datetime.strptime(cat.event_date, "%Y-%m-%d")
                d_current = datetime.strptime(current_date, "%Y-%m-%d")
                days_until = (d_event - d_current).days
                if days_until < 0:
                    days_until = 0  # Geçmiş event
            except ValueError:
                days_until = 0

            result.append({
                "type": cat.catalyst_type,
                "importance": cat.importance,
                "days_until": max(0, days_until),
                "source": cat.source,
                "announcement_date": cat.announcement_date,
                "event_date": cat.event_date,
            })

        return result

    def compute_sentiment(
        self,
        kap_events: list[dict],
        news_events: list[dict],
    ) -> dict[str, float]:
        """KAP + News event'lerinden sentiment feature'ları üret.

        Mevcut keyword sentiment sistemi ile uyumlu.
        """
        features = {}

        # KAP sentiment
        if kap_events:
            sentiments = [e.get("sentiment", 0) for e in kap_events]
            importances = [e.get("importance", 0.5) for e in kap_events]

            # Ağırlıklı ortalama
            if sum(importances) > 0:
                weighted = sum(s * i for s, i in zip(sentiments, importances, strict=False)) / sum(importances)
            else:
                weighted = np.mean(sentiments) if sentiments else 0

            features["kap_sentiment_avg"] = round(float(np.mean(sentiments)), 4)
            features["kap_sentiment_weighted"] = round(float(weighted), 4)
            features["kap_sentiment_latest"] = round(float(sentiments[0]), 4) if sentiments else 0
            features["kap_avg_importance"] = round(float(np.mean(importances)), 4)

        # News sentiment
        if news_events:
            sentiments = [e.get("sentiment", 0) for e in news_events]
            importances = [e.get("importance", 0.5) for e in news_events]

            if sum(importances) > 0:
                weighted = sum(s * i for s, i in zip(sentiments, importances, strict=False)) / sum(importances)
            else:
                weighted = np.mean(sentiments) if sentiments else 0

            features["news_sentiment_weighted"] = round(float(weighted), 4)

        # Combined sentiment
        kap_sent = features.get("kap_sentiment_weighted", 0)
        news_sent = features.get("news_sentiment_weighted", 0)
        if kap_sent != 0 or news_sent != 0:
            features["combined_sentiment"] = round(0.6 * kap_sent + 0.4 * news_sent, 4)

        return features

    def compute_catalyst_features(
        self,
        catalyst_events: list[dict],
    ) -> dict[str, Any]:
        """Catalyst event'lerinden Motor6 feature'ları üret."""
        features = {}

        if not catalyst_events:
            features["catalyst_count"] = 0
            features["catalyst_importance"] = 0
            features["catalyst_days_nearest"] = 999
            features["catalyst_time_decay_score"] = 0
            return features

        features["catalyst_count"] = len(catalyst_events)

        importances = [e.get("importance", 0.5) for e in catalyst_events]
        days_list = [e.get("days_until", 999) for e in catalyst_events]

        features["catalyst_importance"] = round(float(max(importances)), 4)
        features["catalyst_avg_importance"] = round(float(np.mean(importances)), 4)
        features["catalyst_days_nearest"] = min(days_list) if days_list else 999

        # Time decay score
        time_decay_scores = []
        for event in catalyst_events:
            imp = event.get("importance", 0.5)
            days = event.get("days_until", 999)
            time_weight = np.exp(-days / 30)  # 30 gün half-life
            time_decay_scores.append(imp * time_weight)

        features["catalyst_time_decay_score"] = round(float(sum(time_decay_scores)), 4)

        return features


# Singleton Instance
historical_adapter = HistoricalDataAdapter()
