"""ALPHA BIST — Event Clustering Detection.

Yakın tarihli event'lerin etkileşimini tespit etme ve düzeltme.
MacKinlay (1997) — clustered events problem.
"""

from datetime import datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


class EventClusteringDetector:
    """Event clustering tespiti ve düzeltmesi."""

    def __init__(self, window_days: int = 5, min_cluster_size: int = 2):
        """
        Args:
            window_days: Cluster oluşturma penceresi (gün)
            min_cluster_size: Minimum cluster boyutu
        """
        self.window_days = window_days
        self.min_cluster_size = min_cluster_size

    def detect_clusters(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Event'leri tarihe göre cluster'lara ayır.

        Args:
            events: [{date, ticker, event_type, car, ...}]

        Returns:
            Cluster listesi — her cluster bir event grubu
        """
        if not events:
            return []

        # Tarihe göre sırala
        sorted_events = sorted(events, key=lambda e: e.get("date", ""))

        clusters = []
        used = set()

        for i, event in enumerate(sorted_events):
            if i in used:
                continue

            cluster = [event]
            used.add(i)

            for j in range(i + 1, len(sorted_events)):
                if j in used:
                    continue

                # Tarih farkı kontrolü
                date_i = self._parse_date(event.get("date"))
                date_j = self._parse_date(sorted_events[j].get("date"))

                if date_i and date_j and (date_j - date_i).days <= self.window_days:
                    cluster.append(sorted_events[j])
                    used.add(j)
                else:
                    break

            if len(cluster) >= self.min_cluster_size:
                clusters.append(
                    {
                        "events": cluster,
                        "size": len(cluster),
                        "start_date": cluster[0].get("date"),
                        "end_date": cluster[-1].get("date"),
                        "tickers": list(set(e.get("ticker") for e in cluster)),
                        "event_types": list(set(e.get("event_type") for e in cluster)),
                    }
                )

        logger.info(
            "event_clusters_detected",
            n_clusters=len(clusters),
            total_events=sum(c["size"] for c in clusters),
        )

        return clusters

    def adjust_car_for_clustering(
        self,
        events: list[dict[str, Any]],
        market_returns: np.ndarray,
        dates: np.ndarray,
    ) -> list[dict[str, Any]]:
        """Cluster'lı event'ler için CAR düzeltmesi.

        Cluster içindeki event'ler birbirini etkilediği için,
        CAR hesaplamasında clustering düzeltmesi uygulanır.

        Args:
            events: Event listesi
            market_returns: Piyasa getirileri
            dates: Tarih dizisi

        Returns:
            Düzeltilmiş event listesi
        """
        clusters = self.detect_clusters(events)
        adjusted_events = list(events)

        for cluster in clusters:
            cluster_events = cluster["events"]
            cluster_size = cluster["size"]

            # Cluster içindeki her event için
            for event in cluster_events:
                # CAR'ı cluster boyutuna göre düzelt
                if "car" in event:
                    # Basit düzeltme: CAR / √(cluster_size)
                    # Daha gelişmiş: overlapping window correction
                    adjustment_factor = 1.0 / np.sqrt(cluster_size)
                    event = dict(event)
                    event["car_adjusted"] = event["car"] * adjustment_factor
                    event["cluster_size"] = cluster_size
                    event["cluster_adjusted"] = True

                    logger.debug(
                        "car_cluster_adjustment",
                        ticker=event.get("ticker"),
                        original_car=event["car"],
                        adjusted_car=event["car_adjusted"],
                        cluster_size=cluster_size,
                    )

        return adjusted_events

    def get_cluster_statistics(self, clusters: list[dict[str, Any]]) -> dict[str, Any]:
        """Cluster istatistikleri.

        Returns:
            Dict with n_clusters, avg_size, max_size, size_distribution
        """
        if not clusters:
            return {"n_clusters": 0, "avg_size": 0, "max_size": 0}

        sizes = [c["size"] for c in clusters]
        return {
            "n_clusters": len(clusters),
            "avg_size": round(float(np.mean(sizes)), 1),
            "max_size": max(sizes),
            "min_size": min(sizes),
            "size_distribution": {f"size_{s}": sizes.count(s) for s in set(sizes)},
        }

    def _parse_date(self, date_val: Any) -> datetime | None:
        """Tarih parse et."""
        if isinstance(date_val, datetime):
            return date_val
        if isinstance(date_val, str):
            for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"]:
                try:
                    return datetime.strptime(date_val, fmt)
                except ValueError:
                    continue
        return None
