"""ALPHA BIST — Manipülasyon Tespit Motoru v2.0 (SPK Uyumlu + İstatistiksel Testler).

Bu modül, SPK Piyasa Bozucu Eylemler Tebliği (VI-104.1) ve kurumsal quant standartlarına uygun
istatistiksel anomali ve manipülasyon tespit algoritmalarını içerir:
- Wash Trading: Kendinden kendine işlem (self-trade), ardışık ters taraf ve döngüsel hacim testleri
- Spoofing & Layering: Yüksek emir iptal oranı ve büyük emir sahte derinlik anomalileri
- Hacim Manipülasyonu: Z-Score ve 95. persentil sıçrama testleri
- Fiyat Kümeleme: Yuvarlak sayı ve yapay kademe yığılma anomalisi
- DuckDB Kalıcı Denetim Kaydı (İş parçacığı korumalı) ve Polars analitik dışa aktarımı
"""

from __future__ import annotations

import contextlib
import functools
import math
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog
from opentelemetry import trace

from services.core.debounce import configure_duckdb_wal

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.manipulation_detector")

DEFAULT_WASH_TRADING_WINDOW: Final[int] = 20
DEFAULT_SPOOFING_WINDOW: Final[int] = 50
DEFAULT_VOLUME_WINDOW: Final[int] = 20
DEFAULT_PRICE_CLUSTER_WINDOW: Final[int] = 50
DEFAULT_MANIPULATION_AUDIT_DB_PATH: Final[str] = "data/manipulation_audit.duckdb"

VALID_ALERT_TYPES: Final[set[str]] = {
    "WASH_TRADING",
    "SPOOFING",
    "LAYERING",
    "VOLUME_MANIP",
    "PRICE_CLUSTER",
}

VALID_SEVERITIES: Final[set[str]] = {
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
}

_duckdb_lock = threading.Lock()


def otel_trace(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Metotları OpenTelemetry span'i ile sarmalayan kurumsal izleme dekoratörü.

    Args:
        span_name: Üretilecek span için benzersiz izleme adı.

    Returns:
        Dekoratör fonksiyonu.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


@dataclass
class ManipulationAlert:
    """Manipülasyon ve piyasa bozucu eylem alarm modeli.

    Attributes:
        alert_type: Alarm kategorisi ('WASH_TRADING', 'SPOOFING', 'LAYERING', 'VOLUME_MANIP', 'PRICE_CLUSTER').
        severity: Önem derecesi ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL').
        description: Açıklayıcı Türkçe ihlal metni.
        details: İhlale ilişkin istatistiksel ve bağlamsal detaylar.
    """

    alert_type: str
    severity: str
    description: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Kategori ve önem derecesi doğrulaması gerçekleştirir."""
        if self.alert_type not in VALID_ALERT_TYPES:
            self.alert_type = "VOLUME_MANIP"
        if self.severity not in VALID_SEVERITIES:
            self.severity = "MEDIUM"

    def __repr__(self) -> str:
        return (
            f"ManipulationAlert(tur={self.alert_type!r}, "
            f"onem={self.severity!r}, aciklama={self.description!r})"
        )


class ManipulationDetector:
    """Manipülasyon ve piyasa suistimali tespit motoru."""

    def __repr__(self) -> str:
        return "ManipulationDetector(spk_uyumlu=True, pencereler=[20, 50])"

    @otel_trace("manipulation_detector.detect_wash_trading")
    def detect_wash_trading(
        self,
        trades: list[dict[str, Any]],
        window: int = DEFAULT_WASH_TRADING_WINDOW,
    ) -> list[ManipulationAlert]:
        """Wash trading tespiti — doğrudan kendinden kendine işlem, ardışık ters taraf ve döngüsel işlemler.

        Args:
            trades: İşlem sözlükleri listesi (fiyat, hacim, alıcı, satıcı alanları).
            window: Döngüsel frekans analizi için incelenecek pencere boyutu.

        Returns:
            Üretilen ManipulationAlert nesneleri listesi.
        """
        alerts: list[ManipulationAlert] = []
        if len(trades) < 1:
            return alerts

        # 1. Aşama: Doğrudan Kendinden Kendine İşlem (Direct Self-Trade: Alıcı == Satıcı)
        for i, t in enumerate(trades):
            b, s = t.get("buyer"), t.get("seller")
            if b is not None and s is not None and b == s:
                alerts.append(
                    ManipulationAlert(
                        alert_type="WASH_TRADING",
                        severity="CRITICAL",
                        description=f"Doğrudan kendinden kendine işlem (Self-Trade) tespit edildi (İşlem #{i})",
                        details={"index": i, "price": t.get("price"), "volume": t.get("volume"), "hesap": b},
                    )
                )

        # 2. Aşama: Ardışık (Adjacent) Wash Trading — aynı fiyat, hacim ve ters taraf
        for i in range(1, len(trades)):
            curr = trades[i]
            prev = trades[i - 1]

            p_curr, p_prev = curr.get("price"), prev.get("price")
            v_curr, v_prev = curr.get("volume"), prev.get("volume")
            b_curr, s_curr = curr.get("buyer"), curr.get("seller")
            b_prev, s_prev = prev.get("buyer"), prev.get("seller")

            if (
                p_curr is not None
                and p_curr == p_prev
                and v_curr is not None
                and float(v_curr or 0.0) > 0
                and v_curr == v_prev
                and b_curr is not None
                and s_curr is not None
                and b_curr == s_prev
                and s_curr == b_prev
            ):
                alerts.append(
                    ManipulationAlert(
                        alert_type="WASH_TRADING",
                        severity="HIGH",
                        description=f"Olası ardışık wash trading tespit edildi (İşlem #{i})",
                        details={"index": i, "price": p_curr, "volume": v_curr, "buyer": b_curr, "seller": s_curr},
                    )
                )

        # 3. Aşama: Pencere bazlı tekrarlayan fiyat/hacim kombinasyonu anomalisi
        if len(trades) >= window:
            recent = trades[-window:]
            price_vol_pairs: list[tuple[float, float]] = []
            for t in recent:
                try:
                    p = float(t.get("price") or 0.0)
                    v = float(t.get("volume") or 0.0)
                    if p > 0 and v > 0:
                        price_vol_pairs.append((p, v))
                except (ValueError, TypeError):
                    continue

            pair_counts = Counter(price_vol_pairs)
            for pair, count in pair_counts.items():
                if count >= 3 and (count / window) > 0.3:  # %30'dan fazla özdeş fiyat/hacim
                    alerts.append(
                        ManipulationAlert(
                            alert_type="WASH_TRADING",
                            severity="MEDIUM",
                            description=f"Pencere içinde aşırı tekrarlayan işlem çifti: {count}/{window}",
                            details={"fiyat": pair[0], "hacim": pair[1], "adet": count, "pencere": window},
                        )
                    )

        return alerts

    @otel_trace("manipulation_detector.detect_spoofing")
    def detect_spoofing(
        self,
        orders: list[dict[str, Any]],
        window: int = DEFAULT_SPOOFING_WINDOW,
    ) -> list[ManipulationAlert]:
        """Spoofing ve sahte derinlik tespiti — emir iptal oranı ve büyük emir iptal anomalileri.

        Args:
            orders: Emir kayıtları listesi ('action', 'size', 'avg_size' alanları).
            window: İncelenecek emir penceresi boyutu.

        Returns:
            Üretilen ManipulationAlert listesi.
        """
        alerts: list[ManipulationAlert] = []
        if len(orders) < 5:
            return alerts

        recent_orders = orders[-window:]
        total_count = len(recent_orders)
        cancel_count = 0
        large_order_count = 0
        large_cancel_count = 0

        for order in recent_orders:
            try:
                size = float(order.get("size") or 0.0)
                avg_size = float(order.get("avg_size") or 1.0)
            except (ValueError, TypeError):
                size = 0.0
                avg_size = 1.0

            is_large = size > (avg_size * 3.0) if avg_size > 0 else False

            action = str(order.get("action") or "").upper()
            if action in {"CANCEL", "IPTAL", "DELETE"}:
                cancel_count += 1
                if is_large:
                    large_cancel_count += 1
            if is_large:
                large_order_count += 1

        # Genel iptal oranı kontrolü
        if total_count >= 10:
            cancel_rate = cancel_count / total_count
            if cancel_rate > 0.70:  # %70+ iptal oranı
                alerts.append(
                    ManipulationAlert(
                        alert_type="SPOOFING",
                        severity="HIGH",
                        description=f"Anormal yüksek emir iptal oranı: %{cancel_rate * 100:.1f}",
                        details={"iptal_orani": round(cancel_rate, 3), "toplam_emir": total_count, "iptal": cancel_count},
                    )
                )

        # Büyük emir iptal anomalisi (Layering/Spoofing)
        if large_order_count >= 3:
            large_cancel_rate = large_cancel_count / large_order_count
            if large_cancel_rate > 0.60:
                alerts.append(
                    ManipulationAlert(
                        alert_type="SPOOFING",
                        severity="CRITICAL",
                        description=(
                            f"Büyük emir sahte derinlik anomalisi (Spoofing): "
                            f"{large_cancel_count}/{large_order_count} büyük emir iptal edildi"
                        ),
                        details={"buyuk_iptal_orani": round(large_cancel_rate, 3), "buyuk_emirler": large_order_count},
                    )
                )

        return alerts

    @otel_trace("manipulation_detector.detect_volume_manipulation")
    def detect_volume_manipulation(
        self,
        volumes: list[float],
        window: int = DEFAULT_VOLUME_WINDOW,
    ) -> list[ManipulationAlert]:
        """Hacim sıçraması ve manipülasyon tespiti — Z-score ve 95. yüzdelik testleri.

        Args:
            volumes: Kayan noktalı işlem hacimleri dizisi.
            window: İstatistiksel temel oluşturacak pencere boyutu.

        Returns:
            Üretilen ManipulationAlert listesi.
        """
        alerts: list[ManipulationAlert] = []
        if not volumes or len(volumes) < window:
            return alerts

        # NaN ve sonsuz değer filtrelemesi
        cleaned: list[float] = []
        for v in volumes[-window:]:
            try:
                fv = float(v)
                if math.isfinite(fv) and fv >= 0.0:
                    cleaned.append(fv)
            except (ValueError, TypeError):
                continue

        if len(cleaned) < window:
            return alerts

        arr = np.array(cleaned, dtype=float)
        history = arr[:-1]
        latest = float(arr[-1])

        mean_vol = float(np.mean(history))
        raw_std = float(np.std(history)) if len(history) > 2 else 1.0
        std_vol = max(raw_std, mean_vol * 0.01, 1.0)

        if mean_vol < 0.0:
            return alerts

        z_score = (latest - mean_vol) / std_vol
        p95 = float(np.percentile(history, 95))

        # Z-score > 3.0 ise istatistiksel 3-sigma dışı aşırı hacim
        if z_score > 3.0:
            severity = "CRITICAL" if z_score > 5.0 else "HIGH"
            alerts.append(
                ManipulationAlert(
                    alert_type="VOLUME_MANIP",
                    severity=severity,
                    description=f"Anormal hacim sıçraması (Z={z_score:.2f}): {latest:,.0f} vs ortalama {mean_vol:,.0f}",
                    details={
                        "z_score": round(z_score, 2),
                        "son_hacim": latest,
                        "ortalama": mean_vol,
                        "p95": round(p95, 2),
                    },
                )
            )
        elif latest > (p95 * 2.0) and p95 > 0.0:
            # 95. yüzdelik sıçrama kontrolü (Z-score aşılmamışsa ikinci derece uyarı)
            alerts.append(
                ManipulationAlert(
                    alert_type="VOLUME_MANIP",
                    severity="MEDIUM",
                    description=f"Hacim %95 persentilinin 2 katını aştı: {latest:,.0f} vs p95={p95:,.0f}",
                    details={"p95": round(p95, 2), "son_hacim": latest, "ortalama": mean_vol},
                )
            )

        return alerts

    @otel_trace("manipulation_detector.detect_price_clustering")
    def detect_price_clustering(
        self,
        prices: list[float],
        window: int = DEFAULT_PRICE_CLUSTER_WINDOW,
    ) -> list[ManipulationAlert]:
        """Fiyat kümeleme (Price Clustering) ve yapay yuvarlama anomalisi tespiti.

        Args:
            prices: Kayan noktalı fiyatlar listesi.
            window: İncelenecek fiyat geçmişi boyutu.

        Returns:
            Üretilen ManipulationAlert listesi.
        """
        alerts: list[ManipulationAlert] = []
        if not prices or len(prices) < window:
            return alerts

        valid_prices: list[float] = []
        for p in prices[-window:]:
            try:
                fp = float(p)
                if math.isfinite(fp) and fp > 0.0:
                    valid_prices.append(fp)
            except (ValueError, TypeError):
                continue

        if len(valid_prices) < (window // 2):
            return alerts

        round_count = 0
        for p in valid_prices:
            # Kuruş basamağında .00 veya .50 kümelenmesi
            cents = round(p % 1.0, 2)
            if cents in {0.0, 0.5}:
                round_count += 1
            else:
                # 10 TL veya 50 TL üstü yuvarlak kademeler
                for round_val in [100.0, 50.0, 10.0]:
                    rem = p % round_val
                    if (rem / p < 0.002) or (abs(rem - round_val) / p < 0.002):
                        round_count += 1
                        break

        round_rate = round_count / len(valid_prices)
        if round_rate > 0.60:  # Fiyatların %60'ından fazlası yapay yuvarlak kümelenmiş
            alerts.append(
                ManipulationAlert(
                    alert_type="PRICE_CLUSTER",
                    severity="LOW",
                    description=f"Fiyat kümeleme anomalisi: %{round_rate * 100:.1f} yuvarlak fiyat oranı",
                    details={"yuvarlak_orani": round(round_rate, 3), "orneklem": len(valid_prices)},
                )
            )

        return alerts

    @otel_trace("manipulation_detector.detect_all")
    def detect_all(
        self,
        trades: list[dict[str, Any]] | None = None,
        orders: list[dict[str, Any]] | None = None,
        volumes: list[float] | None = None,
        prices: list[float] | None = None,
    ) -> list[ManipulationAlert]:
        """Tüm manipülasyon tarama modüllerini tek çağrıda yürütür.

        Args:
            trades: İşlem kayıtları.
            orders: Emir akışı kayıtları.
            volumes: Hacim zaman serisi.
            prices: Fiyat zaman serisi.

        Returns:
            Tüm tespit edilen alarmların birleşik listesi.
        """
        all_alerts: list[ManipulationAlert] = []
        if trades:
            all_alerts.extend(self.detect_wash_trading(trades))
        if orders:
            all_alerts.extend(self.detect_spoofing(orders))
        if volumes:
            all_alerts.extend(self.detect_volume_manipulation(volumes))
        if prices:
            all_alerts.extend(self.detect_price_clustering(prices))
        return all_alerts


def alerts_to_polars(alerts: list[ManipulationAlert]) -> pl.DataFrame:
    """Manipülasyon alarmlarını Polars DataFrame yapısına dönüştürür (GEMINI.md Kural 2).

    Args:
        alerts: ManipulationAlert nesneleri listesi.

    Returns:
        Yapılandırılmış Polars DataFrame.
    """
    empty_schema = {
        "alert_type": pl.Utf8,
        "severity": pl.Utf8,
        "description": pl.Utf8,
        "details_json": pl.Utf8,
    }
    if not alerts:
        return pl.DataFrame(schema=empty_schema)

    records: list[dict[str, Any]] = []
    for a in alerts:
        records.append({
            "alert_type": a.alert_type,
            "severity": a.severity,
            "description": a.description,
            "details_json": orjson.dumps(a.details, default=str).decode("utf-8"),
        })

    return pl.DataFrame(records, schema=empty_schema)


def export_alerts_to_duckdb(
    alerts: list[ManipulationAlert],
    db_path: str = DEFAULT_MANIPULATION_AUDIT_DB_PATH,
) -> int:
    """Tespit edilen manipülasyon alarmlarını SPK denetim izi için DuckDB tablosuna kaydeder.

    İş parçacığı kilidi (threading.Lock) ile Windows dosya kilitleme çatışmaları engellenir.

    Args:
        alerts: Kaydedilecek alarmlar listesi.
        db_path: DuckDB dosya yolu.

    Returns:
        Eklenen toplam alarm adedi.
    """
    if not alerts:
        return 0

    df = alerts_to_polars(alerts)
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size == 0:
        with contextlib.suppress(OSError):
            target.unlink()

    with _duckdb_lock, duckdb.connect(db_path) as conn:
        configure_duckdb_wal(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS manipulation_audit_ledger (
                alert_type VARCHAR NOT NULL,
                severity VARCHAR NOT NULL,
                description VARCHAR NOT NULL,
                details_json VARCHAR,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.register("df_alerts_view", df.to_arrow())
        conn.execute(
            "INSERT INTO manipulation_audit_ledger "
            "SELECT alert_type, severity, description, details_json, CURRENT_TIMESTAMP FROM df_alerts_view"
        )

    return df.height


# Global tekil nesne
manipulation_detector: Final[ManipulationDetector] = ManipulationDetector()

__all__: Final[list[str]] = [
    "DEFAULT_MANIPULATION_AUDIT_DB_PATH",
    "DEFAULT_PRICE_CLUSTER_WINDOW",
    "DEFAULT_SPOOFING_WINDOW",
    "DEFAULT_VOLUME_WINDOW",
    "DEFAULT_WASH_TRADING_WINDOW",
    "ManipulationAlert",
    "ManipulationDetector",
    "VALID_ALERT_TYPES",
    "VALID_SEVERITIES",
    "alerts_to_polars",
    "export_alerts_to_duckdb",
    "manipulation_detector",
    "otel_trace",
]
