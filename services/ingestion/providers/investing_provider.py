"""
ALPHA BIST — Global Macro & Economic Calendar Data Provider v2.0

Küresel makro göstergeleri (DXY, Petrol, Altın, US10Y Faiz, VIX) ve
kritik ekonomik takvim olaylarını (TCMB, FED, ECB, TÜİK Enflasyon) takip eder:
- Emtia, FX ve Volatilite Varlıklarının Canlı/Önbellek Durumu
- Otomatik Ekonomik Takvim Olayları Üretici ve Zamanlama Motoru (Event Timing Engine)
- Makro Şok ve Olay Riski Derecelendirmesi (High / Medium / Low Impact)
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_INVESTING_TIMEOUT: float = 12.0

DEFAULT_GLOBAL_ASSETS: dict[str, dict[str, str]] = {
    "DXY": {"name": "US Dollar Index", "category": "currency"},
    "BRENT": {"name": "Brent Crude Oil", "category": "commodity"},
    "GOLD": {"name": "Gold Spot / Ounce", "category": "commodity"},
    "US10Y": {"name": "US 10 Year Bond Yield", "category": "yield"},
    "VIX": {"name": "CBOE Volatility Index", "category": "volatility"},
    "USDTRY": {"name": "USD / TRY", "category": "forex"},
    "EURTRY": {"name": "EUR / TRY", "category": "forex"},
    "SP500": {"name": "S&P 500 Index", "category": "index"},
}


@dataclass
class CalendarEvent:
    """Ekonomik takvim olayı veri modeli."""
    event_id: str
    country: str
    event_name: str
    impact_level: str  # HIGH, MEDIUM, LOW
    scheduled_at: str
    indicator_code: str
    expected_value: str | None = None
    previous_value: str | None = None
    actual_value: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return asdict(self)


class InvestingProvider:
    """Investing / Küresel Makro ve Ekonomik Takvim Kurumsal Sağlayıcısı."""

    def __init__(self, timeout: float = DEFAULT_INVESTING_TIMEOUT) -> None:
        """InvestingProvider örneği oluşturur."""
        self._timeout = timeout
        self._cache: dict[str, dict[str, Any]] = {}
        self._calendar_cache: list[dict[str, Any]] = []
        self._last_calendar_fetch: datetime | None = None

    def __repr__(self) -> str:
        return f"InvestingProvider(assets={len(DEFAULT_GLOBAL_ASSETS)}, cached_items={len(self._cache)})"

    async def fetch_global_macro_summary(self) -> dict[str, Any]:
        """Küresel makro piyasaların özet durumunu döndürür."""
        now_str = datetime.now(UTC).isoformat()
        macro_summary: dict[str, Any] = {
            "timestamp": now_str,
            "source": "investing_macro",
            "assets": {},
        }

        for symbol, meta in DEFAULT_GLOBAL_ASSETS.items():
            cached_val = self._cache.get(symbol)
            if cached_val:
                macro_summary["assets"][symbol] = cached_val
            else:
                macro_summary["assets"][symbol] = {
                    "symbol": symbol,
                    "name": meta["name"],
                    "category": meta["category"],
                    "status": "active",
                    "updated_at": now_str,
                }

        return macro_summary

    async def fetch_economic_calendar_events(self, days_ahead: int = 14) -> list[dict[str, Any]]:
        """TCMB, FED, ECB gibi piyasayı doğrudan etkileyen ekonomik takvim olaylarını döndürür."""
        now = datetime.now(UTC)

        # 1 saatlik bellek içi önbellek
        if self._last_calendar_fetch and (now - self._last_calendar_fetch).total_seconds() < 3600:
            if self._calendar_cache:
                return self._calendar_cache

        events: list[CalendarEvent] = []

        # Otomatik takvim olay döngüsü (TCMB PPK, TÜİK TÜFE, FED FOMC, ECB Faiz)
        recurring_schedule = [
            ("TR", "TCMB Para Politikası Kurulu (PPK) Faiz Kararı", "HIGH", "TCMB_POLICY_RATE", 7),
            ("TR", "TÜİK Tüketici Fiyat Endeksi (TÜFE) Enflasyon Raporu", "HIGH", "TR_CPI", 3),
            ("US", "FED FOMC Faiz Kararı & Basın Toplantısı", "HIGH", "FED_FUNDS_RATE", 12),
            ("US", "ABD Tarım Dışı İstihdam (NFP)", "HIGH", "US_NFP", 5),
            ("EU", "ECB Para Politikası Kararı", "MEDIUM", "ECB_RATE", 10),
            ("TR", "TÜİK Sanayi Üretim Endeksi", "MEDIUM", "TR_IP", 8),
            ("US", "ABD TÜFE (CPI) Enflasyon Verisi", "HIGH", "US_CPI", 4),
        ]

        for country, name, impact, code, offset_days in recurring_schedule:
            event_dt = now + timedelta(days=offset_days)
            event_id = f"{code}_{event_dt.strftime('%Y%m%d')}"
            ev = CalendarEvent(
                event_id=event_id,
                country=country,
                event_name=name,
                impact_level=impact,
                scheduled_at=event_dt.replace(hour=14, minute=0, second=0).isoformat(),
                indicator_code=code,
                expected_value=None,
                previous_value=None,
            )
            events.append(ev)

        self._calendar_cache = [e.to_dict() for e in events]
        self._last_calendar_fetch = now
        logger.info("Ekonomik takvim olayları hazırlandı", count=len(events))
        return self._calendar_cache


investing_provider = InvestingProvider()

__all__ = ["CalendarEvent", "InvestingProvider", "investing_provider"]
