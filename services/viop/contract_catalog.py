"""
ALPHA BIST — VIOP Contract Catalog v1.0

VIOP sözleşme kataloğu:
- Sözleşme türleri (endeks, döviz, emtia)
- Sözleşme büyüklüğü
- Vade tarihleri
- Tick size
- Margin requirements

Kaynak: Borsa İstanbul resmi
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class VIOPContract:
    """VIOP sözleşmesi."""

    symbol: str  # Sözleşme kodu (XU030, DOL, GAU)
    name: str  # Sözleşme adı
    underlying: str  # Dayanak varlık
    contract_size: float  # Sözleşme büyüklüğü
    contract_size_unit: str  # Birim (TL, USD, EUR, gram, ton)
    tick_size: float  # Minimum fiyat adımı
    tick_value: float  # Tick değeri (TL)
    margin_rate: float  # Teminat oranı (%)
    settlement: str  # Takas yöntemi (nakdi/fiziki)
    expiry_months: list[int]  # Vade ayları
    exchange: str = "BIST"
    category: str = ""  # endeks, döviz, emtia


@dataclass
class OptionContract:
    """Opsiyon sözleşmesi."""

    symbol: str  # Opsiyon kodu
    underlying: str  # Dayanak varlık
    option_type: str  # call / put
    strike: float  # Kullanım fiyatı
    expiry: date  # Vade tarihi
    premium: float = 0.0  # Primi
    bid: float = 0.0  # Alış
    ask: float = 0.0  # Satış
    open_interest: int = 0  # Açık pozisyon
    volume: int = 0  # Hacim
    implied_vol: float = 0.0  # Implied volatility


class VIOPContractCatalog:
    """VIOP sözleşme kataloğu."""

    # BIST VIOP sözleşme tanımları
    CONTRACTS = {
        "XU030": VIOPContract(
            symbol="XU030",
            name="BIST 30 Endeks Vadeli İşlem",
            underlying="XU030",
            contract_size=10,
            contract_size_unit="TL",
            tick_size=0.25,
            tick_value=2.50,
            margin_rate=0.15,
            settlement="nakdi",
            expiry_months=[3, 6, 9, 12],  # Mart, Haziran, Eylül, Aralık
            category="endeks",
        ),
        "XU030D": VIOPContract(
            symbol="XU030D",
            name="BIST 30 Endeks Vadeli İşlem (Dolar)",
            underlying="XU030",
            contract_size=10,
            contract_size_unit="USD",
            tick_size=0.25,
            tick_value=2.50,
            margin_rate=0.15,
            settlement="nakdi",
            expiry_months=[3, 6, 9, 12],
            category="endeks",
        ),
        "DOL": VIOPContract(
            symbol="DOL",
            name="Dolar/TL Vadeli İşlem",
            underlying="USDTRY",
            contract_size=1000,
            contract_size_unit="USD",
            tick_size=0.0001,
            tick_value=0.10,
            margin_rate=0.10,
            settlement="nakdi",
            expiry_months=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            category="döviz",
        ),
        "EUR": VIOPContract(
            symbol="EUR",
            name="Euro/TL Vadeli İşlem",
            underlying="EURTRY",
            contract_size=1000,
            contract_size_unit="EUR",
            tick_size=0.0001,
            tick_value=0.10,
            margin_rate=0.10,
            settlement="nakdi",
            expiry_months=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            category="döviz",
        ),
        "GAU": VIOPContract(
            symbol="GAU",
            name="Gram Altın Vadeli İşlem",
            underlying="GAU",
            contract_size=1,
            contract_size_unit="gram",
            tick_size=0.10,
            tick_value=0.10,
            margin_rate=0.12,
            settlement="fiziki",
            expiry_months=[2, 4, 6, 8, 10, 12],
            category="emtia",
        ),
        "CAY": VIOPContract(
            symbol="CAY",
            name="Çeyrek Altın Vadeli İşlem",
            underlying="CAY",
            contract_size=1,
            contract_size_unit="çeyrek",
            tick_size=1.00,
            tick_value=1.00,
            margin_rate=0.12,
            settlement="fiziki",
            expiry_months=[2, 4, 6, 8, 10, 12],
            category="emtia",
        ),
        "BUD": VIOPContract(
            symbol="BUD",
            name="Buğday Vadeli İşlem",
            underlying="BUD",
            contract_size=5,
            contract_size_unit="ton",
            tick_size=0.25,
            tick_value=1.25,
            margin_rate=0.10,
            settlement="fiziki",
            expiry_months=[3, 5, 7, 9, 12],
            category="emtia",
        ),
        "PAM": VIOPContract(
            symbol="PAM",
            name="Pamuk Vadeli İşlem",
            underlying="PAM",
            contract_size=5,
            contract_size_unit="ton",
            tick_size=0.50,
            tick_value=2.50,
            margin_rate=0.10,
            settlement="fiziki",
            expiry_months=[3, 5, 7, 10, 12],
            category="emtia",
        ),
        "ELK": VIOPContract(
            symbol="ELK",
            name="Elektrik Vadeli İşlem",
            underlying="ELK",
            contract_size=1,
            contract_size_unit="MWh",
            tick_size=0.10,
            tick_value=0.10,
            margin_rate=0.15,
            settlement="nakdi",
            expiry_months=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            category="emtia",
        ),
    }

    def get_contract(self, symbol: str) -> VIOPContract | None:
        """Sözleşme bilgisi al.

        Args:
            symbol: Sözleşme kodu

        Returns:
            Sözleşme bilgisi veya None
        """
        return self.CONTRACTS.get(symbol)

    def get_all_contracts(self) -> dict[str, VIOPContract]:
        """Tüm sözleşmeleri al.

        Returns:
            Sözleşme sözlüğü
        """
        return self.CONTRACTS

    def get_contracts_by_category(self, category: str) -> list[VIOPContract]:
        """Kategoriye göre sözleşmeler.

        Args:
            category: Kategori (endeks, döviz, emtia)

        Returns:
            Sözleşme listesi
        """
        return [c for c in self.CONTRACTS.values() if c.category == category]

    def get_expiry_dates(self, symbol: str, year: int = 2026) -> list[date]:
        """Vade tarihlerini al.

        Args:
            symbol: Sözleşme kodu
            year: Yıl

        Returns:
            Vade tarihleri listesi
        """
        contract = self.CONTRACTS.get(symbol)
        if not contract:
            return []

        dates = []
        for month in contract.expiry_months:
            # Son iş günü (basitleştirilmiş — son Cuma)
            last_day = 28  # Minimum
            for day in range(31, 27, -1):
                try:
                    d = date(year, month, day)
                    if d.weekday() == 4:  # Cuma
                        last_day = day
                        break
                except ValueError:
                    continue
            dates.append(date(year, month, last_day))

        return sorted(dates)

    def get_next_expiry(self, symbol: str) -> date | None:
        """Bir sonrade vade tarihi.

        Args:
            symbol: Sözleşme kodu

        Returns:
            Bir sonraki vade tarihi
        """
        today = date.today()
        dates = self.get_expiry_dates(symbol, today.year)

        for d in dates:
            if d > today:
                return d

        # Gelecek yıl
        next_year_dates = self.get_expiry_dates(symbol, today.year + 1)
        return next_year_dates[0] if next_year_dates else None

    def calculate_margin(self, symbol: str, quantity: int, price: float) -> float:
        """Teminat hesapla.

        Args:
            symbol: Sözleşme kodu
            quantity: Pozisyon adedi
            price: Fiyat

        Returns:
            Teminat (TL)
        """
        contract = self.CONTRACTS.get(symbol)
        if not contract:
            return 0.0

        notional = quantity * price * contract.contract_size
        return notional * contract.margin_rate

    def calculate_pnl(self, symbol: str, quantity: int, entry_price: float, exit_price: float) -> float:
        """K/Z hesapla.

        Args:
            symbol: Sözleşme kodu
            quantity: Pozisyon adedi (pozitif: long, negatif: short)
            entry_price: Giriş fiyatı
            exit_price: Çıkış fiyatı

        Returns:
            K/Z (TL)
        """
        contract = self.CONTRACTS.get(symbol)
        if not contract:
            return 0.0

        return quantity * (exit_price - entry_price) * contract.contract_size

    def to_dict(self, symbol: str) -> dict[str, Any] | None:
        """Sözleşme bilgisini sözlüğe çevir.

        Args:
            symbol: Sözleşme kodu

        Returns:
            Sözleşme sözlüğü
        """
        contract = self.CONTRACTS.get(symbol)
        if not contract:
            return None

        return {
            "symbol": contract.symbol,
            "name": contract.name,
            "underlying": contract.underlying,
            "contract_size": contract.contract_size,
            "contract_size_unit": contract.contract_size_unit,
            "tick_size": contract.tick_size,
            "tick_value": contract.tick_value,
            "margin_rate": contract.margin_rate,
            "settlement": contract.settlement,
            "expiry_months": contract.expiry_months,
            "category": contract.category,
        }


# Singleton
viop_catalog = VIOPContractCatalog()
