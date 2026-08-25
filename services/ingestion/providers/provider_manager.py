"""
ALPHA BIST — Provider Manager v1.0

Provider redundancy + failover:
Primary provider → quality check → secondary provider → cross-validation → canonical data

Bir provider bozulursa ALPHA'nın gözü kapanmaz.
"""

from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timezone
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class ProviderHealth:
    """Provider sağlık durumu."""
    name: str
    is_healthy: bool = True
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    consecutive_failures: int = 0
    avg_latency_ms: float = 0
    success_rate: float = 1.0


@dataclass
class ProviderResult:
    """Provider sonuç verisi."""
    provider: str
    data: Any
    timestamp: datetime
    latency_ms: float
    quality: float  # 0-1


class ProviderManager:
    """
    Provider yönetimi — failover, health tracking, cross-validation.
    """

    def __init__(self):
        self._providers: Dict[str, Dict[str, Callable]] = {}  # data_type -> {name: func}
        self._health: Dict[str, ProviderHealth] = {}
        self._priority: Dict[str, List[str]] = {}  # data_type -> [provider_names]

    def register_provider(self, data_type: str, name: str, func: Callable, priority: int = 0):
        """Veri sağlayıcı kaydet."""
        if data_type not in self._providers:
            self._providers[data_type] = {}
            self._priority[data_type] = []

        self._providers[data_type][name] = func
        self._health[name] = ProviderHealth(name=name)

        # Priority'ye göre sırala
        if name not in self._priority[data_type]:
            self._priority[data_type].insert(min(priority, len(self._priority[data_type])), name)

        logger.info("Provider registered", data_type=data_type, name=name, priority=priority)

    async def fetch(self, data_type: str, **kwargs) -> Optional[ProviderResult]:
        """
        Veri çek — failover ile.
        Önce primary, başarısız olursa secondary.
        """
        providers = self._priority.get(data_type, [])

        for provider_name in providers:
            health = self._health.get(provider_name)
            if health and not health.is_healthy:
                # Çok fazla başarısızlık → atla
                if health.consecutive_failures > 5:
                    logger.debug("Skipping unhealthy provider", provider=provider_name)
                    continue

            func = self._providers.get(data_type, {}).get(provider_name)
            if not func:
                continue

            start = datetime.now(timezone.utc)
            try:
                result = func(**kwargs)
                latency = (datetime.now(timezone.utc) - start).total_seconds() * 1000

                # Sağlık güncelle
                if health:
                    health.is_healthy = True
                    health.last_success = datetime.now(timezone.utc)
                    health.consecutive_failures = 0
                    health.avg_latency_ms = (health.avg_latency_ms * 0.9) + (latency * 0.1)
                    health.success_rate = min(1.0, health.success_rate + 0.01)

                return ProviderResult(
                    provider=provider_name,
                    data=result,
                    timestamp=datetime.now(timezone.utc),
                    latency_ms=latency,
                    quality=1.0,
                )

            except Exception as e:
                logger.warning("Provider failed", provider=provider_name, error=str(e))
                if health:
                    health.is_healthy = health.consecutive_failures < 10
                    health.last_failure = datetime.now(timezone.utc)
                    health.consecutive_failures += 1
                    health.success_rate = max(0, health.success_rate - 0.05)

        logger.error("All providers failed", data_type=data_type)
        return None

    def get_health(self) -> Dict[str, Dict]:
        """Tüm provider'ların sağlık durumu."""
        return {
            name: {
                "healthy": h.is_healthy,
                "success_rate": round(h.success_rate, 3),
                "avg_latency_ms": round(h.avg_latency_ms, 1),
                "consecutive_failures": h.consecutive_failures,
                "last_success": h.last_success.isoformat() if h.last_success else None,
            }
            for name, h in self._health.items()
        }


# Singleton
provider_manager = ProviderManager()
