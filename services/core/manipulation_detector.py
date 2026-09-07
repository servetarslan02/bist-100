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

try:
    from services.core.otel import otel_trace
except ImportError:
    try:
        from opentelemetry import trace
        tracer = trace.get_tracer("alpha-bist.manipulation_detector")

        def otel_trace(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
                @functools.wraps(func)
                def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
                    with tracer.start_as_current_span(span_name):
                        return func(self, *args, **kwargs)
                return wrapper
            return decorator
    except ImportError:
        def otel_trace(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
                @functools.wraps(func)
                def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
                    return func(self, *args, **kwargs)
                return wrapper
            return decorator

logger = structlog.get_logger(__name__)


def configure_duckdb_wal(conn: Any) -> None:
    """DuckDB WAL boyut ve checkpoint ayarlarını SSD koruması için yapılandırır."""
    with contextlib.suppress(Exception):
        conn.execute("PRAGMA checkpoint_threshold='4MB'")
        conn.execute("PRAGMA wal_autocheckpoint='2MB'")


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

_duckdb_lock: Final[threading.RLock] = threading.RLock()


@dataclass(slots=True)
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

    def to_dict(self) -> dict[str, Any]:
        """Alarm nesnesini sözlük formatına dönüştürür."""
        return {
            "alert_type": self.alert_type,
            "severity": self.severity,
            "description": self.description,
            "details": self.details,
        }

    def to_orjson_bytes(self) -> bytes:
        """Alarm verisini orjson bayt dizisine serileştirir (GEMINI.md Kural 5)."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        """Alarm özetini Türkçe anahtar alanlarla döndürür."""
        return (
            f"ManipulationAlert(tur={self.alert_type!r}, "
            f"onem={self.severity!r}, aciklama={self.description!r})"
        )


class ManipulationDetector:
    """SPK VI-104.1 uyumlu piyasa dolandırıcılığı ve manipülasyon tespit motoru."""

    def __init__(self) -> None:
        """İş parçacığı güvenli manipülasyon tespit motorunu ilklendirir."""
        self._lock: threading.RLock = threading.RLock()

    def __repr__(self) -> str:
        """Motor yapılandırma ve durum özetini döndürür."""
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
            window: Döngüsel frekans analizi için incelenecek pencere boyutu (minimum 1).

        Returns:
            Üretilen ManipulationAlert nesneleri listesi.
        """
        alerts: list[ManipulationAlert] = []
        if not trades or len(trades) < 1:
            return alerts

        effective_window = max(1, window)

        with self._lock:
            # 1. Aşama: Doğrudan Kendinden Kendine İşlem (Direct Self-Trade: Alıcı == Satıcı)
            for i, t in enumerate(trades):
                if not isinstance(t, dict):
                    continue
                raw_b, raw_s = t.get("buyer"), t.get("seller")
                b = str(raw_b).strip() if raw_b is not None else ""
                s = str(raw_s).strip() if raw_s is not None else ""

                # Boş veya anonim kimlikler hariç, alıcı ve satıcı birebir aynıysa
                if b and s and b == s:
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
                curr, prev = trades[i], trades[i - 1]
                if not isinstance(curr, dict) or not isinstance(prev, dict):
                    continue

                try:
                    p_curr = float(curr.get("price") or 0.0)
                    p_prev = float(prev.get("price") or 0.0)
                    v_curr = float(curr.get("volume") or 0.0)
                    v_prev = float(prev.get("volume") or 0.0)
                except (ValueError, TypeError):
                    continue

                raw_bc, raw_sc = curr.get("buyer"), curr.get("seller")
                raw_bp, raw_sp = prev.get("buyer"), prev.get("seller")
                bc = str(raw_bc).strip() if raw_bc is not None else ""
                sc = str(raw_sc).strip() if raw_sc is not None else ""
                bp = str(raw_bp).strip() if raw_bp is not None else ""
                sp = str(raw_sp).strip() if raw_sp is not None else ""

                # Fiyat ve hacim eşleşmesi, tarafların yer değiştirmesi
                price_match = abs(p_curr - p_prev) < 1e-6 and p_curr > 0.0
                volume_match = abs(v_curr - v_prev) < 1e-6 and v_curr > 0.0
                parties_swapped = bool(bc and sc and bp and sp and bc == sp and sc == bp)

                if price_match and volume_match and parties_swapped:
                    alerts.append(
                        ManipulationAlert(
                            alert_type="WASH_TRADING",
                            severity="HIGH",
                            description=f"Olası ardışık wash trading tespit edildi (İşlem #{i})",
                            details={"index": i, "price": p_curr, "volume": v_curr, "buyer": bc, "seller": sc},
                        )
                    )

            # 3. Aşama: Pencere bazlı tekrarlayan fiyat/hacim kombinasyonu anomalisi
            effective_trades = trades[-effective_window:] if len(trades) >= effective_window else trades
            if len(effective_trades) >= 5:
                price_vol_pairs: list[tuple[float, float]] = []
                for t in effective_trades:
                    if not isinstance(t, dict):
                        continue
                    try:
                        p = float(t.get("price") or 0.0)
                        v = float(t.get("volume") or 0.0)
                        if p > 0.0 and v > 0.0 and math.isfinite(p) and math.isfinite(v):
                            price_vol_pairs.append((round(p, 4), round(v, 4)))
                    except (ValueError, TypeError):
                        continue

                pair_counts = Counter(price_vol_pairs)
                denom = len(effective_trades)
                for pair, count in pair_counts.items():
                    if count >= 3 and (count / denom) > 0.30:  # %30'dan fazla özdeş fiyat/hacim
                        alerts.append(
                            ManipulationAlert(
                                alert_type="WASH_TRADING",
                                severity="MEDIUM",
                                description=f"Pencere içinde aşırı tekrarlayan işlem çifti: {count}/{denom}",
                                details={
                                    "fiyat": pair[0],
                                    "hacim": pair[1],
                                    "adet": count,
                                    "pencere": denom,
                                },
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
            window: İncelenecek emir penceresi boyutu (minimum 5).

        Returns:
            Üretilen ManipulationAlert listesi.
        """
        alerts: list[ManipulationAlert] = []
        if not orders or len(orders) < 5:
            return alerts

        effective_window = max(5, window)
        recent_orders = orders[-effective_window:]
        total_count = len(recent_orders)
        cancel_count = 0
        large_new_order_count = 0
        large_cancel_count = 0

        with self._lock:
            for order in recent_orders:
                if not isinstance(order, dict):
                    continue
                try:
                    size = float(order.get("size") or 0.0)
                    avg_size = float(order.get("avg_size") or 1.0)
                except (ValueError, TypeError):
                    size = 0.0
                    avg_size = 1.0

                is_large = size > (avg_size * 3.0) if avg_size > 0.0 else False
                action = str(order.get("action") or "").upper()

                if action in {"CANCEL", "IPTAL", "DELETE", "AMEND_DOWN", "REDUCE"}:
                    cancel_count += 1
                    if is_large:
                        large_cancel_count += 1
                else:
                    if is_large:
                        large_new_order_count += 1

            # Genel iptal oranı kontrolü
            if total_count >= 10:
                cancel_rate = cancel_count / total_count
                if cancel_rate > 0.70:  # %70+ iptal oranı
                    alerts.append(
                        ManipulationAlert(
                            alert_type="SPOOFING",
                            severity="HIGH",
                            description=f"Anormal yüksek emir iptal oranı: %{cancel_rate * 100:.1f}",
                            details={
                                "iptal_orani": round(cancel_rate, 3),
                                "toplam_emir": total_count,
                                "iptal": cancel_count,
                            },
                        )
                    )

            # Büyük emir iptal anomalisi (Layering / Spoofing)
            total_large_orders = large_new_order_count + large_cancel_count
            if total_large_orders >= 3:
                large_cancel_rate = large_cancel_count / total_large_orders
                if large_cancel_rate > 0.60:
                    alerts.append(
                        ManipulationAlert(
                            alert_type="SPOOFING",
                            severity="CRITICAL",
                            description=(
                                f"Büyük emir sahte derinlik anomalisi (Spoofing): "
                                f"{large_cancel_count}/{total_large_orders} büyük emir iptal edildi"
                            ),
                            details={
                                "buyuk_iptal_orani": round(large_cancel_rate, 3),
                                "buyuk_emirler": total_large_orders,
                            },
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
            window: İstatistiksel temel oluşturacak pencere boyutu (minimum 3).

        Returns:
            Üretilen ManipulationAlert listesi.
        """
        alerts: list[ManipulationAlert] = []
        min_required = max(3, window)
        if not volumes or len(volumes) < min_required:
            return alerts

        # NaN ve sonsuz değer filtrelemesi
        cleaned: list[float] = []
        for v in volumes[-min_required:]:
            try:
                fv = float(v)
                if math.isfinite(fv) and fv >= 0.0:
                    cleaned.append(fv)
            except (ValueError, TypeError):
                continue

        if len(cleaned) < 3:
            return alerts

        with self._lock:
            arr = np.array(cleaned, dtype=float)
            history = arr[:-1]
            latest = float(arr[-1])

            if len(history) < 2:
                return alerts

            mean_vol = float(np.mean(history))
            raw_std = float(np.std(history)) if len(history) >= 2 else 1.0
            std_vol = max(raw_std, mean_vol * 0.01, 1.0)

            if mean_vol < 0.0 or not math.isfinite(mean_vol) or not math.isfinite(std_vol):
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
            window: İncelenecek fiyat geçmişi boyutu (minimum 5).

        Returns:
            Üretilen ManipulationAlert listesi.
        """
        alerts: list[ManipulationAlert] = []
        min_required = max(5, window)
        if not prices or len(prices) < min_required:
            return alerts

        valid_prices: list[float] = []
        for p in prices[-min_required:]:
            try:
                fp = float(p)
                if math.isfinite(fp) and fp > 0.0:
                    valid_prices.append(fp)
            except (ValueError, TypeError):
                continue

        if len(valid_prices) < max(3, min_required // 2):
            return alerts

        round_count = 0
        with self._lock:
            for p in valid_prices:
                if p <= 0.0:
                    continue
                # Kuruş basamağında .00 veya .50 kümelenmesi
                cents = round(p % 1.0, 2)
                if cents in {0.0, 0.5}:
                    round_count += 1
                else:
                    # 10 TL, 50 TL veya 100 TL üstü yuvarlak kademeler
                    for round_val in [100.0, 50.0, 10.0]:
                        if p >= round_val:
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

    def evaluate_trading_safety(self, alerts: list[ManipulationAlert]) -> tuple[bool, str]:
        """Manipülasyon alarmlarını değerlendirerek emir iletiminin güvenli olup olmadığını belirler (Self-Healing / Kural 6).

        Args:
            alerts: İncelenecek manipülasyon alarmları listesi.

        Returns:
            (guvenli_mi, gerekce) ikilisi. CRITICAL veya çoklu HIGH alarm durumunda False döner.
        """
        criticals = [a for a in alerts if a.severity == "CRITICAL"]
        if criticals:
            return False, f"Piyasa Güvenlik Kilidi: Kritik manipülasyon tespit edildi ({criticals[0].description})"

        highs = [a for a in alerts if a.severity == "HIGH"]
        if len(highs) >= 2:
            return False, f"Piyasa Güvenlik Kilidi: Çoklu yüksek manipülasyon riski ({len(highs)} adet alarm)"

        return True, "Piyasa koşulları işlem için güvenli"

    def get_risk_multiplier(self, alerts: list[ManipulationAlert]) -> float:
        """Alarmların ciddiyetine göre pozisyon büyüklüğü katsayısı (haircut) hesaplar (Tam Otomasyon).

        Args:
            alerts: Aktif manipülasyon alarmları listesi.

        Returns:
            0.0 (tam durdurma) ile 1.0 (tam limit) arasında pozisyon çarpanı.
        """
        if any(a.severity == "CRITICAL" for a in alerts):
            return 0.0
        if any(a.severity == "HIGH" for a in alerts):
            return 0.20
        if any(a.severity == "MEDIUM" for a in alerts):
            return 0.50
        if any(a.severity == "LOW" for a in alerts):
            return 0.85
        return 1.0

    def detect_from_polars(
        self,
        df_trades: pl.DataFrame | None = None,
        df_orders: pl.DataFrame | None = None,
    ) -> list[ManipulationAlert]:
        """Polars DataFrame verilerinden sıfır kopyalı manipülasyon taraması yapar (GEMINI.md Kural 2).

        Args:
            df_trades: Fiyat, hacim, buyer, seller sütunları içeren işlemler DataFrame'i.
            df_orders: Action, size, avg_size sütunları içeren emirler DataFrame'i.

        Returns:
            Tespit edilen ManipulationAlert nesneleri listesi.
        """
        alerts: list[ManipulationAlert] = []
        if df_trades is not None and not df_trades.is_empty():
            trades_list = df_trades.to_dicts()
            alerts.extend(self.detect_wash_trading(trades_list))
            if "volume" in df_trades.columns:
                vols = [float(v) for v in df_trades["volume"].to_list() if v is not None]
                alerts.extend(self.detect_volume_manipulation(vols))
            if "price" in df_trades.columns:
                prices = [float(p) for p in df_trades["price"].to_list() if p is not None]
                alerts.extend(self.detect_price_clustering(prices))

        if df_orders is not None and not df_orders.is_empty():
            orders_list = df_orders.to_dicts()
            alerts.extend(self.detect_spoofing(orders_list))

        return alerts


def alerts_to_polars(alerts: list[ManipulationAlert]) -> pl.DataFrame:
    """Manipülasyon alarmlarını Polars DataFrame yapısına dönüştürür (GEMINI.md Kural 2).

    Args:
        alerts: ManipulationAlert nesneleri listesi.

    Returns:
        Yapılandırılmış Polars DataFrame.
    """
    empty_schema = {
        "alert_type": pl.String,
        "severity": pl.String,
        "description": pl.String,
        "details_json": pl.String,
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

    İş parçacığı kilidi (threading.RLock) ile Windows dosya kilitleme çatışmaları engellenir.

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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_manipulation_audit_ts ON manipulation_audit_ledger (detected_at);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_manipulation_audit_type ON manipulation_audit_ledger (alert_type);")
        conn.register("df_alerts_view", df.to_arrow())
        try:
            conn.execute(
                "INSERT INTO manipulation_audit_ledger "
                "SELECT alert_type, severity, description, details_json, CURRENT_TIMESTAMP FROM df_alerts_view"
            )
        finally:
            with contextlib.suppress(Exception):
                conn.unregister("df_alerts_view")

    return df.height


def query_manipulation_audit_duckdb(
    db_path: str = DEFAULT_MANIPULATION_AUDIT_DB_PATH,
    limit: int = 100,
    alert_type: str | None = None,
) -> list[dict[str, Any]]:
    """DuckDB manipülasyon denetim defterinden geçmiş alarmları sorgular.

    Args:
        db_path: DuckDB veritabanı yolu.
        limit: Döndürülecek maksimum kayıt adedi.
        alert_type: İsteğe bağlı filtre kategori ('WASH_TRADING', 'SPOOFING' vb.).

    Returns:
        Sözlük formatında alarm kayıtları listesi.
    """
    target = Path(db_path)
    if not target.exists() or target.stat().st_size == 0:
        return []

    with _duckdb_lock, duckdb.connect(db_path, read_only=True) as conn:
        configure_duckdb_wal(conn)
        query = (
            "SELECT alert_type, severity, description, details_json, detected_at "
            "FROM manipulation_audit_ledger "
        )
        params: list[Any] = []
        if alert_type:
            query += "WHERE alert_type = ? "
            params.append(alert_type)
        query += "ORDER BY detected_at DESC LIMIT ?"
        params.append(max(1, limit))

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]

    results: list[dict[str, Any]] = []
    for r in rows:
        row_dict = dict(zip(cols, r, strict=False))
        if "details_json" in row_dict and row_dict["details_json"]:
            with contextlib.suppress(Exception):
                row_dict["details"] = orjson.loads(row_dict["details_json"])
        results.append(row_dict)

    return results


def export_manipulation_audit_to_polars(
    db_path: str = DEFAULT_MANIPULATION_AUDIT_DB_PATH,
    limit: int = 1000,
) -> pl.DataFrame:
    """DuckDB manipülasyon denetim defterini Polars DataFrame olarak dışa aktarır (GEMINI.md Kural 2).

    Args:
        db_path: DuckDB veritabanı yolu.
        limit: Dışa aktarılacak maksimum kayıt adedi.

    Returns:
        Sıfır kopyalı Polars DataFrame.
    """
    target = Path(db_path)
    if not target.exists() or target.stat().st_size == 0:
        return alerts_to_polars([])

    with _duckdb_lock, duckdb.connect(db_path, read_only=True) as conn:
        configure_duckdb_wal(conn)
        arrow_table = conn.execute(
            "SELECT alert_type, severity, description, details_json, detected_at "
            "FROM manipulation_audit_ledger ORDER BY detected_at DESC LIMIT ?",
            [max(1, limit)],
        ).fetch_arrow_table()

    return pl.from_arrow(arrow_table)  # type: ignore[return-value]


def export_alerts_to_orjson_bytes(alerts: list[ManipulationAlert]) -> bytes:
    """Manipülasyon alarmlarını orjson serileştirilmiş ikili bayt olarak döndürür."""
    records = [a.to_dict() for a in alerts]
    return orjson.dumps(records, default=str)


def clear_manipulation_audit_duckdb(
    db_path: str = DEFAULT_MANIPULATION_AUDIT_DB_PATH,
) -> None:
    """DuckDB manipülasyon denetim defterindeki tüm kayıtları siler."""
    target = Path(db_path)
    if not target.exists():
        return

    with _duckdb_lock, duckdb.connect(db_path) as conn:
        configure_duckdb_wal(conn)
        conn.execute("DROP TABLE IF EXISTS manipulation_audit_ledger")


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
    "clear_manipulation_audit_duckdb",
    "configure_duckdb_wal",
    "export_alerts_to_duckdb",
    "export_alerts_to_orjson_bytes",
    "export_manipulation_audit_to_polars",
    "manipulation_detector",
    "otel_trace",
    "query_manipulation_audit_duckdb",
]
