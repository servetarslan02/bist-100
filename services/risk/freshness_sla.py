"""ALPHA BIST — Dynamic Data Freshness SLA & Staleness Monitor (v2.0).

Veri türüne göre dinamik tazelik (freshness) SLA denetimleri:
- TICK      : <= 5 saniye
- INTRADAY  : <= 300 saniye (5 dakika)
- DAILY     : <= 86400 saniye (24 saat)
- MACRO/KAP : <= 14400 saniye (4 saat)

Fail-Closed Prensibi:
Kritik veri bayatladığında risk seviyesini otomatik DEFENSIVE moda çeker.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

import structlog

logger = structlog.get_logger(__name__)


class DataType(StrEnum):
    TICK = "TICK"
    INTRADAY = "INTRADAY"
    DAILY = "DAILY"
    MACRO = "MACRO"


FRESHNESS_SLA_SECONDS: dict[DataType, float] = {
    DataType.TICK: 5.0,
    DataType.INTRADAY: 300.0,
    DataType.DAILY: 86400.0,
    DataType.MACRO: 14400.0,
}


@dataclass
class FreshnessResult:
    is_fresh: bool
    data_type: DataType
    age_seconds: float
    max_allowed_seconds: float
    action_required: str  # "NONE", "WARN", "TRIGGER_DEFENSIVE_CASH"


class DataFreshnessSLAMonitor:
    """Veri türüne göre tazelik denetleyicisi."""

    def __init__(self, custom_slas: dict[DataType, float] | None = None) -> None:
        self.slas = custom_slas or FRESHNESS_SLA_SECONDS

    def evaluate_freshness(
        self,
        data_type: DataType,
        last_updated: datetime | float | str,
        current_time: datetime | None = None,
    ) -> FreshnessResult:
        """Verinin tazeliğini SLA sınırlarına göre değerlendirir."""
        now = current_time or datetime.now(UTC)

        # Parse last_updated
        if isinstance(last_updated, (int, float)):
            updated_dt = datetime.fromtimestamp(last_updated, tz=UTC)
        elif isinstance(last_updated, str):
            try:
                updated_dt = datetime.fromisoformat(last_updated)
                if updated_dt.tzinfo is None:
                    updated_dt = updated_dt.replace(tzinfo=UTC)
            except Exception:
                updated_dt = now
        elif isinstance(last_updated, datetime):
            updated_dt = last_updated if last_updated.tzinfo else last_updated.replace(tzinfo=UTC)
        else:
            updated_dt = now

        age_seconds = max(0.0, (now - updated_dt).total_seconds())
        max_sla = self.slas.get(data_type, 300.0)
        is_fresh = age_seconds <= max_sla

        if is_fresh:
            action = "NONE"
        elif age_seconds <= (max_sla * 2.0):
            action = "WARN"
            logger.warning("data_freshness_sla_warn", data_type=data_type, age_seconds=age_seconds, max_sla=max_sla)
        else:
            action = "TRIGGER_DEFENSIVE_CASH"
            logger.error("data_freshness_sla_breached", data_type=data_type, age_seconds=age_seconds, max_sla=max_sla)

        return FreshnessResult(
            is_fresh=is_fresh,
            data_type=data_type,
            age_seconds=round(age_seconds, 2),
            max_allowed_seconds=max_sla,
            action_required=action,
        )


# Singleton
data_freshness_monitor = DataFreshnessSLAMonitor()
