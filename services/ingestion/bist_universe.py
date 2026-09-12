"""
ALPHA BIST — BIST Universe v5.0 (Dinamik Otomatik Keşif)

Borsa İstanbul'daki TÜM hisseleri (600+ hisse) canlı kaynaklardan
dinamik olarak yönetir. Yeni halka arzlar ve değişiklikler otomatik
olarak keşfedilir.

Kullanım:
    from services.ingestion.bist_universe import bist_universe

    tickers = bist_universe.get_tickers()
    sector = bist_universe.get_ticker_sector("THYAO")
"""

from typing import Any

import structlog

from .providers.universe_provider import universe_updater

logger = structlog.get_logger()


class BISTUniverse:
    """BIST hisse evreni — dinamik canlı keşif yöneticisi.

    Canlı kaynaklardan (TradingView vb.) hisse listesini çeker.
    Sektör, endeks üyeliği ve şirket adı sorguları desteklenir.

    Raises:
        RuntimeError: Evren yüklenemediğinde (refresh sırasında).
    """

    def __init__(self) -> None:
        """BIST hisse evreni yöneticisini başlatır."""
        self.logger = structlog.get_logger()
        self._updater = universe_updater

    def __repr__(self) -> str:
        return f"<BISTUniverse(total_tickers={len(self.BIST_ALL_TICKERS)}, primary_source='tradingview')>"

    def refresh(self) -> None:
        """Hisse evrenini canlı kaynaklardan yeniden tarar.

        Raises:
            RuntimeError: Kaynak taraması başarısız olduğunda.
        """
        try:
            self._updater.refresh_universe()
        except Exception as exc:
            logger.error("Evren yenileme başarısız", error=str(exc))
            raise RuntimeError(f"Evren yenileme hatası: {exc}") from exc

    @property
    def BIST_ALL_TICKERS(self) -> list[str]:
        """TÜM BIST hisse sembolleri listesi (600+ hisse).

        Returns:
            Hisse sembollerinin listesi.
        """
        uni = self._updater.get_universe()
        return list(uni.keys())

    @property
    def BIST_100_TICKERS(self) -> list[str]:
        """BIST 100 endeksine üye hisseler.

        Returns:
            BIST 100 hisse sembollerinin listesi.
        """
        return self._updater.get_index_members("XU100")

    @property
    def BIST_30_TICKERS(self) -> list[str]:
        """BIST 30 endeksine üye hisseler.

        Returns:
            BIST 30 hisse sembollerinin listesi.
        """
        return self._updater.get_index_members("XU030")

    @property
    def BIST_50_TICKERS(self) -> list[str]:
        """BIST 50 endeksine üye hisseler.

        Returns:
            BIST 50 hisse sembollerinin listesi.
        """
        return self._updater.get_index_members("XU050")

    @property
    def SECTOR_MAP(self) -> dict[str, str]:
        """Tüm hisselerin sektör haritası.

        Returns:
            {ticker: sektör_adi} sözlüğü.
        """
        uni = self._updater.get_universe()
        return {t: info.sector for t, info in uni.items()}

    @property
    def COMPANY_NAMES(self) -> dict[str, str]:
        """Tüm hisselerin şirket isimleri.

        Returns:
            {ticker: şirket_adi} sözlüğü.
        """
        uni = self._updater.get_universe()
        return {t: getattr(info, "name", t) for t, info in uni.items()}

    def get_company_name(self, ticker: str) -> str:
        """Hissenin şirket adını döndürür.

        Args:
            ticker: Hisse sembolü (örn. "THYAO").

        Returns:
            Şirket adı veya bulunamazsa ticker sembolü.
        """
        uni = self._updater.get_universe()
        info = uni.get(ticker.upper())
        return getattr(info, "name", ticker) if info else ticker

    def get_ticker_sector(self, ticker: str) -> str:
        """Hissenin sektörünü döndürür.

        Args:
            ticker: Hisse sembolü (örn. "THYAO").

        Returns:
            Sektör adı veya bulunamazsa "DIGER".
        """
        uni = self._updater.get_universe()
        info = uni.get(ticker.upper())
        return info.sector if info else "DIGER"

    def get_tickers_by_sector(self, sector: str) -> list[str]:
        """Sektöre göre hisseleri getirir (alias destekli).

        Args:
            sector: Sektör adı veya alias'ı (örn. "BANK", "TECH").

        Returns:
            Sektöre ait hisse sembollerinin listesi.
        """
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
        """Tüm hisseleri getirir.

        Returns:
            Tüm BIST hisse sembollerinin listesi.
        """
        return self.BIST_ALL_TICKERS

    def get_index_members(self, index: str = "XU100") -> list[str]:
        """Belirli bir endeks üyelerini getirir.

        Args:
            index: Endeks kodu (örn. "XU100", "XU030", "XU050").

        Returns:
            Endeks üyesi hisse sembollerinin listesi.
        """
        return self._updater.get_index_members(index)

    def is_active(self, ticker: str) -> bool:
        """Hissenin aktif olup olmadığını kontrol eder.

        Args:
            ticker: Hisse sembolü.

        Returns:
            Hisse aktifse True, değilse False.
        """
        return self._updater.is_active(ticker.upper())


# Singleton instance
bist_universe = BISTUniverse()


def get_bist_universe() -> list[str]:
    """Tüm BIST hisse sembollerini döndürür.

    Returns:
        Hisse sembollerinin listesi.
    """
    return bist_universe.get_tickers()


def get_sector(ticker: str) -> str:
    """Hissenin sektörünü getirir.

    Args:
        ticker: Hisse sembolü.

    Returns:
        Sektör adı.
    """
    return bist_universe.get_ticker_sector(ticker)


def get_bist_stocks() -> list[str]:
    """Dinamik tüm hisseleri getirir.

    Returns:
        Tüm BIST hisse sembollerinin listesi.
    """
    return bist_universe.BIST_ALL_TICKERS


# Geriye dönük uyumluluk için modül özellikleri
BIST_INDICES: dict[str, str] = {
    "XU100": "BIST 100",
    "XU030": "BIST 30",
    "XU050": "BIST 50",
    "XUTUM": "BIST TÜM",
}  # BIST endeks kodları ve açıklamaları


def __getattr__(name: str) -> list[str]:
    """Modül seviyesinde eski isimlendirmeyle erişim sağlar.

    BIST_STOCKS veya BIST_ALL çağrıldığında canlı evreni döndürür.

    Args:
        name: Erişilmek istenen öznitelik adı.

    Returns:
        Hisse sembollerinin listesi.

    Raises:
        AttributeError: Bilinmeyen öznitelik adı verildiğinde.
    """
    if name in ("BIST_STOCKS", "BIST_ALL"):
        return bist_universe.BIST_ALL_TICKERS
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    "BISTUniverse",
    "bist_universe",
    "get_bist_universe",
    "get_sector",
    "get_bist_stocks",
    "BIST_INDICES",
]
