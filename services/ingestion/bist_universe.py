"""
ALPHA BIST — BIST Universe v5.0 (Full Dynamic Auto-Discovery)
Borsa İstanbul'daki TÜM hisseleri (600+ hisse) canlı kaynaklardan dinamik olarak yönetir.
Yeni halka arzlar ve değişiklikler otomatik olarak keşfedilir.
"""

import structlog

from .providers.universe_provider import universe_updater

logger = structlog.get_logger()


class BISTUniverse:
    """BIST hisse evreni — 100% Dinamik Canlı Keşif."""

    def __init__(self, use_auto_discovery: bool = True):
        self.logger = structlog.get_logger()
        self._updater = universe_updater

    def refresh(self):
        """Hisse evrenini canlı kaynaklardan yeniden tara."""
        self._updater.refresh_universe()

    @property
    def BIST_ALL_TICKERS(self) -> list[str]:
        """TÜM BIST hisse sembolleri listesi (600+ hisse)."""
        uni = self._updater.get_universe()
        return list(uni.keys())

    @property
    def BIST_100_TICKERS(self) -> list[str]:
        """BIST 100 hisseleri."""
        return self._updater.get_index_members("XU100")

    @property
    def BIST_30_TICKERS(self) -> list[str]:
        """BIST 30 hisseleri."""
        return self._updater.get_index_members("XU030")

    @property
    def BIST_50_TICKERS(self) -> list[str]:
        """BIST 50 hisseleri."""
        return self._updater.get_index_members("XU050")

    @property
    def SECTOR_MAP(self) -> dict[str, str]:
        """Tüm hisselerin sektör haritası."""
        uni = self._updater.get_universe()
        return {t: info.sector for t, info in uni.items()}

    @property
    def COMPANY_NAMES(self) -> dict[str, str]:
        """Tüm hisselerin şirket isimleri."""
        uni = self._updater.get_universe()
        return {t: getattr(info, "name", t) for t, info in uni.items()}

    def get_company_name(self, ticker: str) -> str:
        """Hissenin şirket adını döndür."""
        uni = self._updater.get_universe()
        info = uni.get(ticker.upper())
        return getattr(info, "name", ticker) if info else ticker

    def get_ticker_sector(self, ticker: str) -> str:
        """Hissenin sektörünü döndür."""
        uni = self._updater.get_universe()
        info = uni.get(ticker.upper())
        return info.sector if info else "DIGER"

    def get_tickers_by_sector(self, sector: str) -> list[str]:
        """Sektöre göre hisseleri getir."""
        return self._updater.get_tickers_by_sector(sector)

    def get_tickers(self) -> list[str]:
        """Tüm hisseleri getir."""
        return self.BIST_ALL_TICKERS

    def get_index_members(self, index: str = "XU100") -> list[str]:
        """Endeks üyelerini getir."""
        return self._updater.get_index_members(index)

    def is_active(self, ticker: str) -> bool:
        """Hisse aktif mi?"""
        return self._updater.is_active(ticker.upper())


# Singleton instance
bist_universe = BISTUniverse()

BIST_STOCKS = bist_universe.BIST_100_TICKERS
BIST_ALL = bist_universe.BIST_ALL_TICKERS


def get_bist_universe() -> list[str]:
    return bist_universe.get_tickers()


def get_sector(ticker: str) -> str:
    return bist_universe.get_ticker_sector(ticker)


BIST_INDICES = {
    "XU100": "BIST 100",
    "XU030": "BIST 30",
    "XU050": "BIST 50",
    "XUTUM": "BIST TÜM",
}
