"""
ALPHA BIST — Price Limits (Eylül 2025 Güncel)

BIST fiyat limitleri (Eylül 2025 sonrası — tüm pazarlarda standart):
- Yıldız Pazar: ±%10
- Ana Pazar: ±%10
- Alt Pazar: ±%10
- Devre kesici sonrası: Marj daraltılır

Kaynak: Borsa İstanbul resmi, Eylül 2025 duyurusu
"""

from typing import Dict, Any
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class PriceLimitResult:
    limit_hit: bool
    direction: str = ""       # "UP" veya "DOWN"
    change_pct: float = 0.0
    limit: float = 10.0       # Yüzde limit
    reference_price: float = 0.0
    current_price: float = 0.0
    upper_limit: float = 0.0
    lower_limit: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "limit_hit": self.limit_hit,
            "direction": self.direction,
            "change_pct": round(self.change_pct, 2),
            "limit": self.limit,
            "reference_price": self.reference_price,
            "current_price": self.current_price,
            "upper_limit": round(self.upper_limit, 2),
            "lower_limit": round(self.lower_limit, 2),
        }


class PriceLimitMonitor:
    """BIST fiyat limitleri kontrolü (Ağustos 2025 güncel).

    Pazar bazlı limitler:
    - Yıldız Pazar: ±%10
    - Ana Pazar: ±%10
    - Alt Pazar: ±%10
    - Halka arz günü: limit yok (serbest fiyat)
    - Bedelsiz/bölünme sonrası: baz fiyat yeniden hesaplanır
    - Devre kesici sonrası: marj daraltılır (%5)
    """

    # Eylül 2025 sonrası: Tüm pazarlarda standart ±%10
    DEFAULT_LIMIT = 10.0        # %10 (tüm pazarlar standart)
    YILDIZ_LIMIT = 10.0         # %10 (Yıldız Pazar)
    ANA_LIMIT = 10.0            # %10 (Ana Pazar)
    ALT_LIMIT = 10.0            # %10 (Alt Pazar)

    # Özel durum limitleri
    IPO_NO_LIMIT = True         # Halka arz günü limit yok
    POST_CB_LIMIT = 5.0         # Devre kesici sonrası daraltma
    POST_CORP_ACTION_LIMIT = 10.0  # Kurumsal işlem sonrası (bedelsiz/bölünme)

    # Pazar bazlı limit haritası
    MARKET_LIMITS = {
        "yildiz": 10.0,
        "ana": 10.0,
        "alt": 10.0,
        "fiyat": 10.0,       # Fiyat Pazarı
        "kesin": 10.0,       # Kesin Alım Satım Pazarı
        "gözaltı": 10.0,     # Gözaltı Pazarı
        "yakın": 10.0,       # Yakın İzleme Pazarı
        "kolektif": 10.0,    # Kolektif Yatırım Ürünleri
        "serbest": 0.0,      # Serbest İşlem (limit yok)
    }

    def __init__(self):
        self._custom_limits: Dict[str, float] = {}
        self._post_cb_tickers: Dict[str, float] = {}  # Devre kesici sonrası daraltılmış marj
        self._ipo_tickers: set = set()  # Halka arz günü (limit yok)
        self._corp_action_tickers: set = set()  # Kurumsal işlem sonrası (bedelsiz/bölünme)
        self._market_type: Dict[str, str] = {}  # Hisse → pazar tipi

    def set_custom_limit(self, ticker: str, limit_pct: float):
        """Özel limit ata (volatil hisseler)."""
        self._custom_limits[ticker] = limit_pct

    def set_market_type(self, ticker: str, market_type: str):
        """Hisse için pazar tipi ata (yildiz, ana, alt, vb.)."""
        self._market_type[ticker] = market_type

    def add_ipo_ticker(self, ticker: str):
        """Halka arz günü limit yok."""
        self._ipo_tickers.add(ticker)

    def remove_ipo_ticker(self, ticker: str):
        """Halka arz gününü kaldır."""
        self._ipo_tickers.discard(ticker)

    def add_corporate_action_ticker(self, ticker: str):
        """Kurumsal işlem sonrası (bedelsiz/bölünme) baz fiyat yeniden hesaplanır."""
        self._corp_action_tickers.add(ticker)

    def remove_corporate_action_ticker(self, ticker: str):
        """Kurumsal işlem sonrası takibi kaldır."""
        self._corp_action_tickers.discard(ticker)

    def set_post_circuit_breaker_limit(self, ticker: str):
        """Devre kesici sonrası marj daraltma uygula."""
        self._post_cb_tickers[ticker] = self.POST_CB_LIMIT
        logger.info("Post-CB margin tightened", ticker=ticker, new_limit=self.POST_CB_LIMIT)

    def clear_post_circuit_breaker_limit(self, ticker: str):
        """Devre kesici sonrası marj daraltmayı kaldır."""
        self._post_cb_tickers.pop(ticker, None)

    def get_effective_limit(self, ticker: str) -> float:
        """Hisseye uygulanan efektif limiti döndür."""
        # Halka arz günü → limit yok
        if ticker in self._ipo_tickers:
            return 0.0  # 0 = limit yok

        # Devre kesici sonrası daraltma kontrolü
        if ticker in self._post_cb_tickers:
            return self._post_cb_tickers[ticker]

        # Özel limit kontrolü
        if ticker in self._custom_limits:
            return self._custom_limits[ticker]

        # Pazar tipine göre limit
        market = self._market_type.get(ticker, "")
        if market in self.MARKET_LIMITS:
            return self.MARKET_LIMITS[market]

        return self.DEFAULT_LIMIT

    def check_price_limit(
        self,
        ticker: str,
        current_price: float,
        reference_price: float,
    ) -> PriceLimitResult:
        """Fiyat limiti kontrolü.

        Args:
            ticker: Hisse kodu
            current_price: Güncel fiyat
            reference_price: Referans fiyat (önceki kapanış)
        """
        if reference_price <= 0 or current_price <= 0:
            return PriceLimitResult(limit_hit=False)

        # Efektif limit belirle
        limit = self.get_effective_limit(ticker)

        # Değişim hesapla
        change_pct = ((current_price / reference_price) - 1) * 100

        # Limitler
        upper_limit = reference_price * (1 + limit / 100)
        lower_limit = reference_price * (1 - limit / 100)

        # Limit aşıldı mı?
        limit_hit = False
        direction = ""

        # Floating point toleransı ile kontrol
        tol = reference_price * 0.0001  # %0.01 tolerans
        if current_price >= upper_limit - tol:
            limit_hit = True
            direction = "UP"
        elif current_price <= lower_limit + tol:
            limit_hit = True
            direction = "DOWN"

        return PriceLimitResult(
            limit_hit=limit_hit,
            direction=direction,
            change_pct=change_pct,
            limit=limit,
            reference_price=reference_price,
            current_price=current_price,
            upper_limit=upper_limit,
            lower_limit=lower_limit,
        )


# Singleton
price_limit_monitor = PriceLimitMonitor()
