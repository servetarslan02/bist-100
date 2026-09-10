"""ALPHA BIST — Event Clustering Detection.

Yakın tarihli event'lerin etkileşimini tespit etme ve düzeltme.
MacKinlay (1997) — clustered events problem.
"""

from datetime import datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# --- Sabitler ---
DEFAULT_WINDOW_DAYS: int = 5
DEFAULT_MIN_CLUSTER_SIZE: int = 2
MIN_WINDOW_DAYS: int = 1
MAX_WINDOW_DAYS: int = 30
MIN_CLUSTER_SIZE: int = 2
DATE_FORMATS: tuple[str, ...] = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y")


def _validate_positive_int(value: int, name: str, min_val: int = 1, max_val: int = 100) -> int:
    """Pozitif tamsayı doğrulama.

    Args:
        value: Kontrol edilecek değer
        name: Parametre adı
        min_val: Minimum değer
        max_val: Maximum değer

    Returns:
        Doğrulanmış integer

    Raises:
        TypeError: Tamsayı değilse
        ValueError: Aralık dışındaysa
    """
    if not isinstance(value, (int, np.integer)):
        raise TypeError(f"{name} tamsayı olmalı, alınan: {type(value).__name__}")
    if not (min_val <= value <= max_val):
        raise ValueError(f"{name} [{min_val}, {max_val}] aralığında olmalı, alınan: {value}")
    return int(value)


def _validate_events_list(events: Any) -> list:
    """Events listesi doğrulama.

    Args:
        events: Kontrol edilecek liste

    Returns:
        Doğrulanmış liste

    Raises:
        TypeError: Liste değilse
    """
    if not isinstance(events, list):
        raise TypeError(f"events liste olmalı, alınan: {type(events).__name__}")
    return events


class EventClusteringDetector:
    """Event clustering tespiti ve düzeltmesi."""

    def __init__(
        self,
        window_days: int = DEFAULT_WINDOW_DAYS,
        min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    ) -> None:
        """Event clustering dedektörü başlat.

        Args:
            window_days: Cluster oluşturma penceresi (gün)
            min_cluster_size: Minimum cluster boyutu

        Raises:
            TypeError: Parametre tipleri uygun değilse
            ValueError: Parametreler aralık dışındaysa
        """
        self.window_days = _validate_positive_int(window_days, "window_days", MIN_WINDOW_DAYS, MAX_WINDOW_DAYS)
        self.min_cluster_size = _validate_positive_int(min_cluster_size, "min_cluster_size", MIN_CLUSTER_SIZE)

    def detect_clusters(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Event'leri tarihe göre cluster'lara ayır.

        Args:
            events: [{date, ticker, event_type, car, ...}]

        Returns:
            Cluster listesi — her cluster bir event grubu

        Raises:
            TypeError: events liste değilse
        """
        events = _validate_events_list(events)
        if not events:
            return []

        # Tarihe göre sırala
        sorted_events = sorted(events, key=lambda e: e.get("date", ""))

        clusters: list[dict[str, Any]] = []
        used: set[int] = set()

        for i, event in enumerate(sorted_events):
            if i in used:
                continue

            cluster: list[dict[str, Any]] = [event]
            used.add(i)

            for j in range(i + 1, len(sorted_events)):
                if j in used:
                    continue

                # Tarih farkı kontrolü
                date_i = self._parse_date(event.get("date"))
                date_j = self._parse_date(sorted_events[j].get("date"))

                if date_i is not None and date_j is not None:
                    diff_days = (date_j - date_i).days
                    if diff_days <= self.window_days:
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

        logger.debug(
            "event_kümeleri_tespit_edildi",
            kume_sayisi=len(clusters),
            toplam_event=sum(c["size"] for c in clusters),
        )

        return clusters

    def adjust_car_for_clustering(
        self,
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Cluster'lı event'ler için CAR düzeltmesi.

        Cluster içindeki event'ler birbirini etkilediği için,
        CAR hesaplamasında clustering düzeltmesi uygulanır.

        Args:
            events: Event listesi

        Returns:
            Düzeltilmiş event listesi (orijinal listeyi değiştirmez)

        Raises:
            TypeError: events liste değilse
        """
        events = _validate_events_list(events)

        clusters = self.detect_clusters(events)

        # Orijinal listeyi kopyala (değiştirmemek için)
        adjusted_events: list[dict[str, Any]] = [dict(e) for e in events]

        # Event → index mapping (hızlı lookup)
        event_to_idx: dict[int, int] = {id(e): i for i, e in enumerate(events)}

        for cluster in clusters:
            cluster_size = cluster["size"]
            adjustment_factor = 1.0 / np.sqrt(cluster_size)

            for event in cluster["events"]:
                # Orijinal listedeki indeksi bul
                orig_id = id(event)
                if orig_id in event_to_idx:
                    idx = event_to_idx[orig_id]
                    orig_car = adjusted_events[idx].get("car")
                    if orig_car is not None:
                        adjusted_events[idx]["car_adjusted"] = orig_car * adjustment_factor
                        adjusted_events[idx]["cluster_size"] = cluster_size
                        adjusted_events[idx]["cluster_adjusted"] = True

                        logger.debug(
                            "car_kume_ayarlama",
                            ticker=adjusted_events[idx].get("ticker"),
                            orijinal_car=round(orig_car, 4),
                            duzeltilmis_car=round(orig_car * adjustment_factor, 4),
                            kume_boyutu=cluster_size,
                        )

        return adjusted_events

    def get_cluster_statistics(self, clusters: list[dict[str, Any]]) -> dict[str, Any]:
        """Cluster istatistikleri.

        Args:
            clusters: Cluster listesi

        Returns:
            Dict with n_clusters, avg_size, max_size, size_distribution

        Raises:
            TypeError: clusters liste değilse
        """
        if not isinstance(clusters, list):
            raise TypeError(f"clusters liste olmalı, alınan: {type(clusters).__name__}")
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
        """Tarih parse et.

        Args:
            date_val: Parse edilecek değer (datetime, str veya None)

        Returns:
            datetime veya None (parse edilemezse)
        """
        if isinstance(date_val, datetime):
            return date_val
        if isinstance(date_val, str):
            for fmt in DATE_FORMATS:
                try:
                    return datetime.strptime(date_val, fmt)
                except ValueError:
                    continue
        return None
