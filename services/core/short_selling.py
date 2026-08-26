"""
ALPHA BIST — Short Selling Monitor (Eylül 2025 Güncel)

BIST açığa satış kuralları:
- Sadece BIST-50 hisseleri açığa satılabilir
- Yukarı adım kuralı (uptick rule): BIST-100 %2 veya daha fazla düşerse seans sonuna kadar uygulanır
- Açığa satış fiyatı son işlem fiyatından yüksek veya eşit olmalı
- Brüt takaslı hisselerde açığa satış yasak
- SPK geçici yasak kontrolü

Kaynak: Borsa İstanbul resmi, Eylül 2025 duyurusu
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class ShortSellingDecision:
    allowed: bool
    reason: str = ""
    details: Dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class ShortSellingMonitor:
    """BIST açığa satış kuralları kontrolü (Eylül 2025 güncel)."""

    # Uptick rule tetikleme eşiği (Eylül 2025: %3 → %2)
    UPTICK_RULE_THRESHOLD_PCT = 2.0  # BIST-100 %2 düşünce uptick rule aktif

    def __init__(self):
        self._bist50_cache: Optional[List[str]] = None
        self._gross_settlement_tickers: set = set()
        self._spk_banned_tickers: set = set()
        self._uptick_rule_active: bool = False  # BIST-100 düşünce aktif olur

    def _get_bist50(self) -> List[str]:
        """BIST-50 hisselerini getir."""
        if self._bist50_cache is None:
            try:
                from services.ingestion.bist_universe import bist_universe
                self._bist50_cache = bist_universe.BIST_50_TICKERS if hasattr(bist_universe, 'BIST_50_TICKERS') else bist_universe.BIST_30_TICKERS
            except ImportError:
                self._bist50_cache = []
        return self._bist50_cache

    def refresh_bist50_cache(self):
        """BIST-50 listesini yenile (çeyrek dönemlerde güncellenir).

        BIST-50 listesi her yıl Mart, Haziran, Eylül, Aralık aylarında güncellenir.
        Bu metod otomatik olarak çağrılmalı.
        """
        self._bist50_cache = None
        self._get_bist50()
        logger.info("BIST-50 cache refreshed", count=len(self._bist50_cache) if self._bist50_cache else 0)

    def is_quarterly_rebalance_month(self) -> bool:
        """Bu ay BIST-50 yeniden dengeleme ayı mı? (Mart, Haziran, Eylül, Aralık)"""
        from datetime import datetime
        return datetime.now().month in {3, 6, 9, 12}

    def auto_refresh_if_needed(self):
        """Çeyrek dönemlerde otomatik yenile."""
        if self.is_quarterly_rebalance_month():
            self.refresh_bist50_cache()

    def set_gross_settlement(self, tickers: List[str]):
        """Brüt takaslı hisseleri güncelle."""
        self._gross_settlement_tickers = set(tickers)

    def set_spk_banned(self, tickers: List[str]):
        """SPK geçici yasaklı hisseleri güncelle."""
        self._spk_banned_tickers = set(tickers)

    def set_uptick_rule_active(self, active: bool):
        """Uptick rule durumunu güncelle.

        BIST-100 endeksi %2 veya daha fazla düşerse seans sonuna kadar aktif.
        """
        self._uptick_rule_active = active
        if active:
            logger.warning("BIST Uptick Rule AKTİF — BIST-100 %2+ düştü")

    def check_uptick_rule(self, bist100_change_pct: float):
        """BIST-100 değişim oranına göre uptick rule kontrolü.

        Args:
            bist100_change_pct: BIST-100 günlük değişim yüzdesi (negatif = düşüş)
        """
        if bist100_change_pct <= -self.UPTICK_RULE_THRESHOLD_PCT:
            self.set_uptick_rule_active(True)
        # Not: Seans sonunda otomatik sıfırlanmalı (scheduler tarafından)

    def reset_uptick_rule(self):
        """Seans sonunda uptick rule sıfırla."""
        self._uptick_rule_active = False

    def can_short_sell(
        self,
        ticker: str,
        current_price: float = 0,
        last_trade_price: float = 0,
        best_ask_price: float = 0,  # En iyi satış fiyatı (spread kontrolü için)
    ) -> ShortSellingDecision:
        """Açığa satış yapılabilir mi kontrol et.

        Args:
            ticker: Hisse kodu
            current_price: Güncel fiyat
            last_trade_price: Son işlem fiyatı (uptick rule için)
            best_ask_price: En iyi satış fiyatı (spread kontrolü için)
        """
        details = {"ticker": ticker}

        # 1. BIST-50 kontrolü
        bist50 = self._get_bist50()
        if ticker not in bist50:
            return ShortSellingDecision(
                allowed=False,
                reason=f"{ticker} BIST-50 listesinde değil — açığa satış sadece BIST-50",
                details=details,
            )

        # 2. Brüt takas kontrolü
        if ticker in self._gross_settlement_tickers:
            return ShortSellingDecision(
                allowed=False,
                reason=f"{ticker} brüt takasta — açığa satış yasak",
                details=details,
            )

        # 3. SPK geçici yasak kontrolü
        if ticker in self._spk_banned_tickers:
            return ShortSellingDecision(
                allowed=False,
                reason=f"{ticker} SPK geçici yasak listesinde",
                details=details,
            )

        # 4. Uptick rule (Ağustos 2025: BIST-100 %2 düşünce aktif)
        if self._uptick_rule_active:
            # Aktif uptick rule: fiyat son işlem fiyatından yüksek veya eşit olmalı
            if current_price > 0 and last_trade_price > 0:
                if current_price < last_trade_price:
                    return ShortSellingDecision(
                        allowed=False,
                        reason=f"Uptick Rule AKTİF (BIST-100 %2+ düştü): güncel ({current_price}) < son işlem ({last_trade_price})",
                        details={**details, "current_price": current_price, "last_trade_price": last_trade_price, "uptick_active": True},
                    )
            # Spread kontrolü: en iyi satış fiyatından da yüksek veya eşit olmalı
            if current_price > 0 and best_ask_price > 0:
                if current_price < best_ask_price:
                    return ShortSellingDecision(
                        allowed=False,
                        reason=f"Uptick Rule AKTİF: güncel ({current_price}) < en iyi satış ({best_ask_price})",
                        details={**details, "current_price": current_price, "best_ask_price": best_ask_price, "uptick_active": True},
                    )
        else:
            # Uptick rule pasifken de temel fiyat kontrolü
            if current_price > 0 and last_trade_price > 0:
                if current_price < last_trade_price:
                    return ShortSellingDecision(
                        allowed=False,
                        reason=f"Yukarı adım kuralı: güncel ({current_price}) < son işlem ({last_trade_price})",
                        details={**details, "current_price": current_price, "last_trade_price": last_trade_price},
                    )

        return ShortSellingDecision(
            allowed=True,
            reason="Açığa satış uygun",
            details=details,
        )


# Singleton
short_selling_monitor = ShortSellingMonitor()
