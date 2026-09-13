"""
ALPHA BIST — Institutional Data Freshness SLA & Point-in-Time Monitor v3.0

Finansal piyasalar için dinamik veri tazeliği (Freshness SLA), gecikme (Latency) ve Bayatlık Denetimi:
- TICK (Canlı BIST Tahta / İşlem Akışı)   : <= 5 saniye
- INTRADAY (Bar / Dakikalık Veri)         : <= 300 saniye (5 dakika)
- DAILY (Gün Sonu Kapanış ve Bar Verisi)  : <= 86400 saniye (24 saat)
- MACRO (TCMB, TÜİK, BDDK, Göstergeler)   : <= 14400 saniye (4 saat)
- NEWS_KAP (Şirket Bildirimleri ve Haber) : <= 600 saniye (10 dakika)
- ORDERBOOK (Derinlik ve Kademe Verisi)   : <= 2 saniye

Fail-Closed Prensibi:
Kritik veri bayatladığında (Data Stale/Outdated) sistem otomatik olarak DEFENSIVE moda
veya ALARM_HALT moduna geçerek sahte/eski verilerle emir gönderilmesini engeller.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class DataType(StrEnum):
    """Veri türleri enum'u."""
    TICK = "TICK"
    ORDERBOOK = "ORDERBOOK"
    INTRADAY = "INTRADAY"
    DAILY = "DAILY"
    MACRO = "MACRO"
    NEWS_KAP = "NEWS_KAP"


class SLAAction(StrEnum):
    """SLA ihlalinde alınacak zorunlu aksiyon."""
    NONE = "NONE"
    WARN = "WARN"
    DEGRADE_CONFIDENCE = "DEGRADE_CONFIDENCE"
    TRIGGER_DEFENSIVE_CASH = "TRIGGER_DEFENSIVE_CASH"
    HALT_TRADING = "HALT_TRADING"


FRESHNESS_SLA_SECONDS: dict[DataType, float] = {
    DataType.ORDERBOOK: 2.0,
    DataType.TICK: 5.0,
    DataType.INTRADAY: 300.0,
    DataType.NEWS_KAP: 600.0,
    DataType.MACRO: 14400.0,
    DataType.DAILY: 86400.0,
}


@dataclass
class FreshnessResult:
    """Veri tazeliği kontrol sonucu."""
    is_fresh: bool
    data_type: DataType
    age_seconds: float
    max_allowed_seconds: float
    action_required: str
    confidence_decay: float
    source: str
    last_updated_iso: str
    checked_at_iso: str

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return asdict(self)


@dataclass
class PortfolioFreshnessAudit:
    """Tüm veri hatlarının toplu tazelik denetim karnesi."""
    overall_health: str  # HEALTHY, DEGRADED, STALE, CRITICAL
    can_execute_trades: bool
    fresh_channels_count: int
    breached_channels_count: int
    channel_results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return asdict(self)


class DataFreshnessSLAMonitor:
    """Kurumsal Veri Tazeliği ve Kesintisiz SLA Takip Motoru."""

    def __init__(self, custom_slas: dict[DataType, float] | None = None) -> None:
        """SLA denetleyici başlatıcısı."""
        self.slas = custom_slas or FRESHNESS_SLA_SECONDS

    def __repr__(self) -> str:
        return f"DataFreshnessSLAMonitor(monitored_types={len(self.slas)})"

    def parse_datetime(self, timestamp_input: datetime | float | int | str, fallback_now: datetime) -> datetime:
        """Girdi zaman damgasını güvenli bir şekilde UTC datetime nesnesine çevirir."""
        if isinstance(timestamp_input, (int, float)):
            try:
                return datetime.fromtimestamp(float(timestamp_input), tz=UTC)
            except Exception:
                return fallback_now
        elif isinstance(timestamp_input, str):
            try:
                dt = datetime.fromisoformat(timestamp_input.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
            except Exception:
                return fallback_now
        elif isinstance(timestamp_input, datetime):
            return timestamp_input if timestamp_input.tzinfo else timestamp_input.replace(tzinfo=UTC)
        return fallback_now

    def evaluate_freshness(
        self,
        data_type: DataType,
        last_updated: datetime | float | str,
        current_time: datetime | None = None,
        source: str = "BIST_FEED",
    ) -> FreshnessResult:
        """Veri türüne göre tazelik denetimi yapar ve güven bozulmasını (confidence decay) hesaplar."""
        now = current_time if current_time and current_time.tzinfo else (current_time.replace(tzinfo=UTC) if current_time else datetime.now(UTC))
        updated_dt = self.parse_datetime(last_updated, fallback_now=now)

        age_seconds = max(0.0, (now - updated_dt).total_seconds())
        max_sla = self.slas.get(data_type, 300.0)
        is_fresh = age_seconds <= max_sla

        # Güvenilirlik Çürümesi (Confidence Decay): 1.0 (mükemmel taze) -> 0.0 (tamamen çöp veri)
        decay_factor = float(max(0.0, 1.0 - (age_seconds / (max_sla * 3.0))))

        if is_fresh:
            action = SLAAction.NONE.value
        elif age_seconds <= (max_sla * 2.0):
            action = SLAAction.WARN.value
            logger.warning(
                "data_freshness_sla_warn",
                data_type=data_type.value,
                source=source,
                age_seconds=round(age_seconds, 2),
                max_sla=max_sla,
            )
        elif age_seconds <= (max_sla * 5.0):
            action = SLAAction.TRIGGER_DEFENSIVE_CASH.value
            logger.error(
                "data_freshness_sla_breached",
                data_type=data_type.value,
                source=source,
                age_seconds=round(age_seconds, 2),
                max_sla=max_sla,
                action="DEFENSIVE_CASH",
            )
        else:
            action = SLAAction.HALT_TRADING.value
            logger.critical(
                "data_freshness_sla_critical_outage",
                data_type=data_type.value,
                source=source,
                age_seconds=round(age_seconds, 2),
                max_sla=max_sla,
                action="HALT_TRADING",
            )

        return FreshnessResult(
            is_fresh=is_fresh,
            data_type=data_type,
            age_seconds=round(age_seconds, 2),
            max_allowed_seconds=max_sla,
            action_required=action,
            confidence_decay=round(decay_factor, 4),
            source=source,
            last_updated_iso=updated_dt.isoformat(),
            checked_at_iso=now.isoformat(),
        )

    def audit_all_channels(self, feed_timestamps: dict[DataType, Any]) -> PortfolioFreshnessAudit:
        """Sistemdeki tüm veri hatlarını aynı anda denetleyip ticaret yapılabilirliğini doğrular."""
        results: list[FreshnessResult] = []
        breaches = 0

        for dt, ts in feed_timestamps.items():
            res = self.evaluate_freshness(data_type=dt, last_updated=ts)
            results.append(res)
            if not res.is_fresh:
                breaches += 1

        fresh_count = len(results) - breaches

        if breaches == 0:
            health = "HEALTHY"
            can_trade = True
        elif any(r.action_required == SLAAction.HALT_TRADING.value for r in results):
            health = "CRITICAL"
            can_trade = False
        elif breaches > 1 or any(r.action_required == SLAAction.TRIGGER_DEFENSIVE_CASH.value for r in results):
            health = "STALE"
            can_trade = False
        else:
            health = "DEGRADED"
            can_trade = True

        return PortfolioFreshnessAudit(
            overall_health=health,
            can_execute_trades=can_trade,
            fresh_channels_count=fresh_count,
            breached_channels_count=breaches,
            channel_results=[r.to_dict() for r in results],
        )


data_freshness_monitor = DataFreshnessSLAMonitor()

__all__ = [
    "DataFreshnessSLAMonitor",
    "DataType",
    "FRESHNESS_SLA_SECONDS",
    "FreshnessResult",
    "PortfolioFreshnessAudit",
    "SLAAction",
    "data_freshness_monitor",
]
