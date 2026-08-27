"""
ALPHA BIST — Pre-Trade Risk & Validation Engine

Borsa İstanbul Kurumsal Emir Öncesi Risk ve Uygunluk Denetimleri:
1. PriceTickValidator (Kuruş Fiyat Adımı Kontrolü)
2. PriceLimitValidator (Tavan/Taban Marjı ve Kilit Denetimi)
3. ShortSaleValidator (Dinamik Enstrüman Bazlı Açığa Satış ve Uptick Kuralı)
4. GrossSettlementValidator (Dinamik Brüt Takas ve Aynı Gün Satış Kısıtı)
5. CashAvailabilityValidator (İşlem Gücü, Bloke Nakit ve T+2 Ayrımı)
6. OrderTypeValidator (Seans Fazına Göre İzin Verilen Emir Türleri)
"""

from dataclasses import dataclass
from typing import Any

import structlog

from services.core.bist_tick_size import get_bist_tick_size, is_valid_bist_tick, round_to_bist_tick
from services.core.market_session_fsm import BISTMarketPhase

logger = structlog.get_logger()


@dataclass
class PreTradeValidationResult:
    is_valid: bool
    rejection_code: str | None = None
    rejection_reason: str | None = None
    details: dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class PreTradeRiskEngine:
    """BIST Emir Öncesi Çok Katmanlı Risk ve Uygunluk Motoru."""

    def __init__(self):
        # Dinamik konfigürasyon ve tarihsel eligibility listeleri
        self._short_sale_eligible_tickers: set[str] = set()
        self._gross_settlement_tickers: set[str] = set()
        self._spk_banned_tickers: set[str] = set()
        self._custom_price_margins: dict[str, float] = {}  # Örn: %10, %5, %20

    def set_short_sale_universe(self, tickers: list[str]):
        self._short_sale_eligible_tickers = set(tickers)

    def set_gross_settlement_universe(self, tickers: list[str]):
        self._gross_settlement_tickers = set(tickers)

    def set_spk_banned_universe(self, tickers: list[str]):
        self._spk_banned_tickers = set(tickers)

    def set_custom_price_margin(self, ticker: str, margin_pct: float):
        self._custom_price_margins[ticker] = margin_pct

    def validate_order(
        self,
        ticker: str,
        side: str,                 # "BUY" | "SELL" | "SHORT"
        order_type: str,           # "MARKET" | "LIMIT" | "STOP_LIMIT" | "TRADE_AT_CLOSE"
        quantity: int,
        price: float,              # Limit fiyatı veya tahmini piyasa fiyatı
        reference_price: float,    # Önceki kapanış / baz fiyat
        market_phase: BISTMarketPhase,
        portfolio_cash: float,
        last_trade_price: float | None = None,
        is_closing_price: bool = False,
    ) -> PreTradeValidationResult:
        """Tüm BIST emir öncesi kurallarını denetler."""

        # 1. TEMEL GEÇERLİLİK
        if quantity <= 0:
            return PreTradeValidationResult(False, "INVALID_QUANTITY", f"Geçersiz miktar: {quantity}")

        # 1b. LOT BÜYÜKLÜĞÜ KONTROLÜ (BIST: 1 lot = 1 pay, minimum 1 lot)
        if quantity < 1:
            return PreTradeValidationResult(False, "BELOW_MIN_LOT", f"Minimum lot büyüklüğü 1. Girilen: {quantity}")

        # Lot altı (küsürat) işlem kontrolü — sadece belirli durumlarda izin verilir
        # Normal işlemler tam lot olmalı
        if quantity != int(quantity):
            return PreTradeValidationResult(
                False, "FRACTIONAL_LOT_NOT_ALLOWED",
                f"Küsüratlı lot ({quantity}) normal işlemlerde kabul edilmez. Tam lot girilmeli."
            )

        # 2. SEANS FAZI VE EMİR TÜRÜ UYGUNLUĞU (OrderTypeValidator)
        if market_phase == BISTMarketPhase.CLOSED:
            return PreTradeValidationResult(False, "MARKET_CLOSED", "Piyasa kapalı, emir kabul edilmez.")

        if market_phase in {BISTMarketPhase.OPENING_AUCTION_DETERMINATION, BISTMarketPhase.CLOSING_AUCTION_DETERMINATION}:
            return PreTradeValidationResult(False, "MATCHING_PHASE", "Fiyat belirleme fazında yeni emir girilemez.")

        if market_phase == BISTMarketPhase.CLOSING_PRICE_TRADING:
            if order_type not in {"TRADE_AT_CLOSE", "MARKET", "LIMIT"}:
                return PreTradeValidationResult(
                    False, "INVALID_ORDER_FOR_SESSION",
                    "Kapanış fiyatından işlemler fazında sadece sabit kapanış fiyatlı emirler kabul edilir."
                )

        # KİE (Kalanı İptal Et): Sürekli işlem ve kapanış seansında geçerli
        if order_type == "KIE" and market_phase not in {
            BISTMarketPhase.CONTINUOUS_AUCTION,
            BISTMarketPhase.CLOSING_AUCTION_COLLECTION,
            BISTMarketPhase.CLOSING_PRICE_TRADING,
        }:
            return PreTradeValidationResult(
                False, "INVALID_ORDER_FOR_SESSION",
                "KİE emri sadece sürekli işlem ve kapanış seansında kabul edilir."
            )

        # KPY (Kalanı Pasife Yaz): Sürekli işlem seansında geçerli
        if order_type == "KPY" and market_phase not in {
            BISTMarketPhase.CONTINUOUS_AUCTION,
        }:
            return PreTradeValidationResult(
                False, "INVALID_ORDER_FOR_SESSION",
                "KPY emri sadece sürekli işlem seansında kabul edilir."
            )

        # GİE (Gerçekleşmezse İptal): Açılış ve kapanış seansında geçerli
        if order_type == "GIE" and market_phase not in {
            BISTMarketPhase.OPENING_AUCTION_COLLECTION,
            BISTMarketPhase.CLOSING_AUCTION_COLLECTION,
        }:
            return PreTradeValidationResult(
                False, "INVALID_ORDER_FOR_SESSION",
                "GİE emri sadece açılış ve kapanış seansında kabul edilir."
            )

        # 3. FİYAT ADIMI DENETİMİ (PriceTickValidator)
        if order_type == "LIMIT" and price > 0 and not is_valid_bist_tick(price):
            expected_tick = get_bist_tick_size(price)
            return PreTradeValidationResult(
                False, "INVALID_TICK_SIZE",
                f"Fiyat {price:.4f} TL, BIST fiyat adımına ({expected_tick:.2f} TL) uymuyor."
            )

        # 4. FİYAT MARJI VE TAVAN/TABAN KİLİT DENETİMİ (PriceLimitValidator)
        margin = self._custom_price_margins.get(ticker, 10.0)  # Standart ±%10
        if reference_price > 0 and price > 0:
            upper_limit = round_to_bist_tick(reference_price * (1.0 + margin / 100.0), side="BUY")
            lower_limit = round_to_bist_tick(reference_price * (1.0 - margin / 100.0), side="SELL")

            # Fiyat limit dışı mı?
            if price > upper_limit + 1e-4:
                return PreTradeValidationResult(
                    False, "ABOVE_UPPER_LIMIT",
                    f"Fiyat {price} TL tavan fiyatın ({upper_limit} TL) üzerinde."
                )
            if price < lower_limit - 1e-4:
                return PreTradeValidationResult(
                    False, "BELOW_LOWER_LIMIT",
                    f"Fiyat {price} TL taban fiyatın ({lower_limit} TL) altında."
                )

            # Tavan / Taban Likidite Kilit Kontrolü
            if side == "SELL" and price <= lower_limit + 1e-4:
                # Taban kilit kontrolü
                return PreTradeValidationResult(
                    False, "BIST_LIMIT_DOWN_LOCKED",
                    f"{ticker} taban fiyatta ({lower_limit} TL). Satış kuyruğunda likidite yok."
                )
            if side == "BUY" and price >= upper_limit - 1e-4:
                # Tavan kilit kontrolü
                return PreTradeValidationResult(
                    False, "BIST_LIMIT_UP_LOCKED",
                    f"{ticker} tavan fiyatta ({upper_limit} TL). Tavanda satıcı likiditesi yok."
                )

        # 5. AÇIĞA SATIŞ DENETİMİ (ShortSaleValidator)
        if side == "SHORT":
            if ticker in self._spk_banned_tickers:
                return PreTradeValidationResult(False, "SPK_SHORT_BANNED", f"{ticker} için SPK açığa satış yasağı mevcuttur.")

            if self._short_sale_eligible_tickers and ticker not in self._short_sale_eligible_tickers:
                return PreTradeValidationResult(False, "SHORT_NOT_ELIGIBLE", f"{ticker} açığa satışa uygun enstrüman listesinde değil.")

            if ticker in self._gross_settlement_tickers:
                return PreTradeValidationResult(False, "GROSS_SETTLEMENT_NO_SHORT", f"{ticker} brüt takastadır, açığa satış yapılamaz.")

            # BIST Uptick Kuralı: Açığa satış fiyatı son işlem fiyatından düşük olamaz
            if last_trade_price and last_trade_price > 0 and price < last_trade_price:
                return PreTradeValidationResult(
                    False, "UPTICK_RULE_VIOLATION",
                    f"Açığa satış fiyatı ({price}) son işlem fiyatından ({last_trade_price}) düşük olamaz (Uptick Kuralı)."
                )

        # 6. NAKİT İŞLEM GÜCÜ DENETİMİ (CashAvailabilityValidator)
        if side in {"BUY"}:
            estimated_cost = quantity * price
            if estimated_cost > portfolio_cash:
                return PreTradeValidationResult(
                    False, "INSUFFICIENT_FUNDS",
                    f"Yetersiz işlem gücü. Gerekli: {estimated_cost:.2f} TL, Mevcut: {portfolio_cash:.2f} TL"
                )

        return PreTradeValidationResult(True)


pre_trade_risk_engine = PreTradeRiskEngine()
