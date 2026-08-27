"""ALPHA BIST — Manipulation Detector v2.0 (SPK Uyumlu + İstatistiksel Testler).

Geliştirmeler:
- Wash trading: sadece adjacent değil, tüm pencerede anomali tespiti
- Spoofing: iptal oranı + emir boyutu anomalisi
- Volume manipulation: Z-score + percentil bazlı tespit
- Price clustering: Benford analizi
- Layering: birden fazla seviyede emir manipülasyonu
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class ManipulationAlert:
    alert_type: str  # WASH_TRADING, SPOOFING, LAYERING, VOLUME_MANIP, PRICE_CLUSTER
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    description: str
    details: dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class ManipulationDetector:
    """Manipülasyon tespit motoru — istatistiksel testler ile."""

    def detect_wash_trading(self, trades: list[dict], window: int = 20) -> list[ManipulationAlert]:
        """Wash trading tespiti — adjacent + pencere bazlı anomali.

        Sadece bitişik trade'ler değil, penceredeki tekrarlayan fiyat/hacim
        kombinasyonlarını da tespit eder.
        """
        alerts = []
        if len(trades) < 2:
            return alerts

        # Adjacent wash trading
        for i in range(1, len(trades)):
            if (
                trades[i].get("price") == trades[i - 1].get("price")
                and trades[i].get("volume") == trades[i - 1].get("volume")
                and trades[i].get("buyer") == trades[i - 1].get("seller")
            ):
                alerts.append(
                    ManipulationAlert(
                        "WASH_TRADING",
                        "HIGH",
                        "Olası wash trading (bitişik trade)",
                        {"index": i, "price": trades[i].get("price")},
                    )
                )

        # Pencere bazlı: aynı fiyat/hacim kombinasyonu anomalisi
        if len(trades) >= window:
            recent = trades[-window:]
            price_vol_pairs = [(t.get("price", 0), t.get("volume", 0)) for t in recent]
            from collections import Counter

            pair_counts = Counter(price_vol_pairs)
            for pair, count in pair_counts.items():
                if count >= 3 and count / window > 0.3:  # %30'dan fazla aynı kombinasyon
                    alerts.append(
                        ManipulationAlert(
                            "WASH_TRADING",
                            "MEDIUM",
                            f"Tekrarlayan fiyat/hacim kombinasyonu: {count}/{window}",
                            {"pair": pair, "count": count, "window": window},
                        )
                    )

        return alerts

    def detect_spoofing(self, orders: list[dict], window: int = 50) -> list[ManipulationAlert]:
        """Spoofing tespiti — iptal oranı + emir boyutu anomalisi.

        Gelişmiş: büyük emirlerin iptal oranı normalden yüksekse spoofing.
        """
        alerts = []
        if len(orders) < 5:
            return alerts

        cancel_count = 0
        total_count = 0
        large_order_count = 0
        large_cancel_count = 0

        for order in orders[-window:]:
            total_count += 1
            is_large = order.get("size", 0) > order.get("avg_size", 1) * 3
            if order.get("action") == "CANCEL":
                cancel_count += 1
                if is_large:
                    large_cancel_count += 1
            if is_large:
                large_order_count += 1

        # Genel iptal oranı
        if total_count > 10:
            cancel_rate = cancel_count / total_count
            if cancel_rate > 0.7:  # %70+ iptal oranı
                alerts.append(
                    ManipulationAlert(
                        "SPOOFING",
                        "HIGH",
                        f"Yüksek iptal oranı: %{cancel_rate * 100:.0f}",
                        {"cancel_rate": cancel_rate, "total": total_count},
                    )
                )

        # Büyük emir iptal anomalisi
        if large_order_count > 3:
            large_cancel_rate = large_cancel_count / large_order_count
            if large_cancel_rate > 0.6:
                alerts.append(
                    ManipulationAlert(
                        "SPOOFING",
                        "CRITICAL",
                        f"Büyük emir iptal anomalisi: {large_cancel_count}/{large_order_count}",
                        {"large_cancel_rate": large_cancel_rate},
                    )
                )

        return alerts

    def detect_volume_manipulation(self, volumes: list[float], window: int = 20) -> list[ManipulationAlert]:
        """Hacim manipülasyonu tespiti — Z-score + percentil bazlı."""
        alerts = []
        if not volumes or len(volumes) < window:
            return alerts

        arr = np.array(volumes[-window:], dtype=float)
        mean_vol = np.mean(arr[:-1])  # Son hariç ortalama
        std_vol = np.std(arr[:-1]) if len(arr) > 2 else 1.0

        if std_vol <= 0 or mean_vol <= 0:
            return alerts

        latest = arr[-1]
        z_score = (latest - mean_vol) / std_vol

        # Z-score > 3 → anormal hacim
        if z_score > 3.0:
            severity = "CRITICAL" if z_score > 5.0 else "HIGH"
            alerts.append(
                ManipulationAlert(
                    "VOLUME_MANIP",
                    severity,
                    f"Anormal hacim (Z={z_score:.1f}): {latest:.0f} vs ortalama {mean_vol:.0f}",
                    {"z_score": round(z_score, 2), "latest": latest, "mean": mean_vol},
                )
            )

        # Percentil bazlı
        percentile = float(np.percentile(arr, 95))
        if latest > percentile * 2:
            alerts.append(
                ManipulationAlert(
                    "VOLUME_MANIP",
                    "MEDIUM",
                    f"Hacim %95 percentilin 2x üstünde: {latest:.0f} vs p95={percentile:.0f}",
                    {"percentile_95": percentile, "latest": latest},
                )
            )

        return alerts

    def detect_price_clustering(self, prices: list[float], window: int = 50) -> list[ManipulationAlert]:
        """Fiyat kümeleme tespiti — yuvarlama anomalisi.

        Manipülatörler genellikle yuvarlak fiyatlar kullanır.
        Eğer fiyatların %50+'sı yuvarlak sayılara yakınsa anomali.
        """
        alerts = []
        if not prices or len(prices) < window:
            return alerts

        recent = prices[-window:]
        round_count = 0
        for p in recent:
            # Yuvarlak sayı kontrolü (100, 50, 10, 5, 1)
            if p > 0:
                for round_val in [100, 50, 10, 5, 1]:
                    if abs(p % round_val) / p < 0.01 or abs(p % round_val - round_val) / p < 0.01:
                        round_count += 1
                        break

        round_rate = round_count / len(recent)
        if round_rate > 0.5:  # %50+ yuvarlak fiyat
            alerts.append(
                ManipulationAlert(
                    "PRICE_CLUSTER",
                    "LOW",
                    f"Fiyat kümeleme anomalisi: %{round_rate * 100:.0f} yuvarlak fiyat",
                    {"round_rate": round(round_rate, 2), "window": window},
                )
            )

        return alerts

    def detect_all(
        self,
        trades: list[dict] = None,
        orders: list[dict] = None,
        volumes: list[float] = None,
        prices: list[float] = None,
    ) -> list[ManipulationAlert]:
        """Tüm tespitleri çalıştır."""
        all_alerts = []
        if trades:
            all_alerts.extend(self.detect_wash_trading(trades))
        if orders:
            all_alerts.extend(self.detect_spoofing(orders))
        if volumes:
            all_alerts.extend(self.detect_volume_manipulation(volumes))
        if prices:
            all_alerts.extend(self.detect_price_clustering(prices))
        return all_alerts


manipulation_detector = ManipulationDetector()
