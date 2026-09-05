from typing import Any

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
        """BIST hisse evreni dinamik yöneticisini başlatır."""
        self.logger = structlog.get_logger()
        self._updater = universe_updater

    def __repr__(self) -> str:
        return f"<BISTUniverse(total_tickers={len(self.BIST_ALL_TICKERS)}, primary_source='tradingview')>"

    def refresh(self) -> Any:
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
        """Sektöre göre hisseleri getir (alias destekli)."""
        sec_u = sector.upper().strip()
        alias_map = {
            "BANK": "BANKACILIK",
            "BANKA": "BANKACILIK",
            "BANKS": "BANKACILIK",
            "GYO": "GAYRIMENKUL",
            "REAL_ESTATE": "GAYRIMENKUL",
            "TECH": "TEKNOLOJI",
            "TEKNO": "TEKNOLOJI",
            "ENERGY": "ENERJI",
            "IND": "SANAYI",
            "INDUSTRY": "SANAYI",
            "RETAIL": "PERAKENDE",
            "GIDA": "PERAKENDE",
            "AUTO": "OTOMOTIV",
            "INS": "SIGORTA",
            "TELCO": "TELEKOM",
            "DEFENSE": "SAVUNMA",
            "MINING": "MADENCILIK",
            "CHEM": "KIMYA",
        }
        target_sector = alias_map.get(sec_u, sec_u)
        stocks = self._updater.get_tickers_by_sector(target_sector)
        if not stocks and target_sector != sec_u:
            stocks = self._updater.get_tickers_by_sector(sec_u)
        return stocks

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


def get_bist_universe() -> list[str]:
    """Tüm BIST hisse sembolleri."""
    return bist_universe.get_tickers()


def get_sector(ticker: str) -> str:
    """Hissenin sektörünü getir."""
    return bist_universe.get_ticker_sector(ticker)


def get_bist_stocks() -> list[str]:
    """Dinamik tüm hisseler."""
    return bist_universe.BIST_ALL_TICKERS


# Geriye dönük uyumluluk için modül özellikleri
BIST_INDICES = {
    "XU100": "BIST 100",
    "XU030": "BIST 30",
    "XU050": "BIST 50",
    "XUTUM": "BIST TÜM",
}


def __getattr__(name: str) -> Any:
    """Modül seviyesinde BIST_STOCKS ve BIST_ALL çağrıldığında canlı evreni döndür."""
    if name in ("BIST_STOCKS", "BIST_ALL"):
        return bist_universe.BIST_ALL_TICKERS
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
