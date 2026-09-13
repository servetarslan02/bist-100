"""
ALPHA BIST — VİOP Canlı Fiyat Akışı, Taşıma Maliyeti & Arbitraj Motoru

BIST VİOP endeks ve hisse vadeli kontratlarının anlık fiyat akışını yöneten,
spot vs vadeli teorik taşıma maliyetini (Cost of Carry), zımni repo faizini (Implied Repo Rate),
baz farkını (Basis) ve vadeler arası takvim spread (Calendar Spread) arbitraj fırsatlarını
tespit eden analitik motor.

Özellikler:
  - Spot vs Vadeli Teorik Değerleme: F = S * exp((r - q) * T)
  - Zımni Repo Oranı: Vadeli fiyata göre zımni risksiz faiz hesabı
  - Baz ve Prim/İskonto tespiti (Basis & Mispricing alert)
  - Takvim Spreadi (Calendar Spread): Vade geçişleri ve rollover analizi
  - Canlı veri önbelleği ve DuckDB zaman serisi kaydı
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

import duckdb
import structlog

logger = structlog.get_logger(__name__)

DB_TABLE_VIOP_PRICES = "viop_live_ticks"


@dataclass
class VIOPContractQuote:
    """Tek bir VİOP kontratının anlık kotasyon kaydı.

    Attributes:
        symbol: Kontrat kodu (örn: F_XU0301026, F_THYAO1026).
        underlying: Dayanak varlık kodu (XU030, THYAO vb.).
        expiry_date: Vade tarihi.
        days_to_expiry: Vadeye kalan gün sayısı.
        last_price: Son işlem fiyatı.
        bid: Alış kotasyonu.
        ask: Satış kotasyonu.
        volume: İşlem hacmi (lot).
        open_interest: Açık pozisyon sayısı (APS).
        timestamp: Fiyat zamanı.
    """

    symbol: str
    underlying: str
    expiry_date: str
    days_to_expiry: int
    last_price: float
    bid: float = 0.0
    ask: float = 0.0
    volume: int = 0
    open_interest: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def mid_price(self) -> float:
        """Alış-satış orta fiyatı."""
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.last_price

    def __repr__(self) -> str:
        """Kısa temsil."""
        return (
            f"VIOPQuote({self.symbol}: mid={self.mid_price:.2f}, "
            f"dte={self.days_to_expiry}d, OI={self.open_interest})"
        )


@dataclass
class ArbitrageSignal:
    """Spot-vadeli veya vadeler arası arbitraj sinyali.

    Attributes:
        symbol: İlgili vadeli kontrat.
        underlying: Dayanak hisse/endeks.
        spot_price: Spot piyasa fiyatı.
        future_price: Vadeli piyasa fiyatı.
        theoretical_price: Teorik taşıma maliyetli fiyat.
        mispricing_pct: Fiyatlama sapması yüzdesi ((Future - Theoretical) / Spot).
        implied_repo_rate: Yıllık zımni repo oranı.
        risk_free_rate: Mevcut piyasa faizi.
        action: Tavsiye (CASH_AND_CARRY, REVERSE_CASH_AND_CARRY, FAIR).
        timestamp: Sinyal üretim zamanı.
    """

    symbol: str
    underlying: str
    spot_price: float
    future_price: float
    theoretical_price: float
    mispricing_pct: float
    implied_repo_rate: float
    risk_free_rate: float
    action: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    def __repr__(self) -> str:
        """Kısa temsil."""
        return (
            f"ArbitrageSignal({self.symbol}: action={self.action}, "
            f"mispricing={self.mispricing_pct:+.2%}, implied_repo={self.implied_repo_rate:.2%})"
        )


class VIOPLiveFeedEngine:
    """VİOP Anlık Fiyat, Taşıma Maliyeti ve Arbitraj Motoru."""

    def __init__(
        self,
        db_path: str = "data/viop_live.duckdb",
        default_risk_free_rate: float = 0.45,  # %45 BIST politika/repo faizi
    ) -> None:
        """VIOPLiveFeedEngine başlatıcı.

        Args:
            db_path: DuckDB veritabanı yolu.
            default_risk_free_rate: Yıllık risksiz faiz oranı.
        """
        self.db_path = db_path
        self.risk_free_rate = default_risk_free_rate
        self._lock = threading.RLock()
        self._memory_con = duckdb.connect(":memory:") if self.db_path == ":memory:" else None
        self._quotes: dict[str, VIOPContractQuote] = {}
        self._spot_prices: dict[str, float] = {}
        self._init_db()

    def __repr__(self) -> str:
        """Engine temsili."""
        return (
            f"VIOPLiveFeedEngine(quotes={len(self._quotes)}, "
            f"spots={len(self._spot_prices)}, r={self.risk_free_rate:.1%})"
        )

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """DuckDB bağlantısı döndürür."""
        if self._memory_con is not None:
            return self._memory_con
        return duckdb.connect(self.db_path)

    def _init_db(self) -> None:
        """DuckDB tablosunu hazırlar."""
        try:
            con = self._get_connection()
            con.execute(f"""
                CREATE TABLE IF NOT EXISTS {DB_TABLE_VIOP_PRICES} (
                    symbol          VARCHAR NOT NULL,
                    underlying      VARCHAR NOT NULL,
                    days_to_expiry  INTEGER,
                    last_price      DOUBLE,
                    bid             DOUBLE,
                    ask             DOUBLE,
                    volume          BIGINT,
                    open_interest   BIGINT,
                    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            if self._memory_con is None:
                con.close()
            logger.info("VIOP live feed DuckDB hazır.", db=self.db_path)
        except Exception as exc:
            logger.warning("VIOP live feed DB başlatılamadı.", hata=str(exc))

    def update_spot_price(self, underlying: str, price: float) -> None:
        """Dayanak varlık spot fiyatını günceller.

        Args:
            underlying: Dayanak hisse/endeks kodu.
            price: Spot fiyat.
        """
        with self._lock:
            self._spot_prices[underlying] = price

    def update_quote(self, quote: VIOPContractQuote) -> None:
        """VİOP kontrat kotasyonunu günceller ve kaydeder.

        Args:
            quote: Yeni kotasyon verisi.
        """
        with self._lock:
            self._quotes[quote.symbol] = quote

        try:
            con = self._get_connection()
            con.execute(
                f"""
                INSERT INTO {DB_TABLE_VIOP_PRICES}
                    (symbol, underlying, days_to_expiry, last_price,
                     bid, ask, volume, open_interest)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    quote.symbol,
                    quote.underlying,
                    quote.days_to_expiry,
                    quote.last_price,
                    quote.bid,
                    quote.ask,
                    quote.volume,
                    quote.open_interest,
                ],
            )
            if self._memory_con is None:
                con.close()
        except Exception as exc:
            logger.warning("VİOP kotasyonu kaydedilemedi.", symbol=quote.symbol, hata=str(exc))

    def compute_cost_of_carry(
        self,
        spot: float,
        days_to_expiry: int,
        dividend_yield: float = 0.0,
    ) -> float:
        """Teorik vadeli fiyatı taşıma maliyeti (Cost of Carry) modeli ile hesaplar.

        F = S * exp((r - q) * T)

        Args:
            spot: Spot hisse/endeks fiyatı.
            days_to_expiry: Vadeye kalan gün.
            dividend_yield: Temettü verimi (yıllık, örn: 0.03).

        Returns:
            Teorik vadeli fiyat.
        """
        t = max(0.001, days_to_expiry / 365.0)
        cost = (self.risk_free_rate - dividend_yield) * t
        return float(spot * math.exp(cost))

    def analyze_arbitrage(
        self,
        symbol: str,
        dividend_yield: float = 0.0,
        threshold_pct: float = 0.015,  # %1.5 komisyon & işlem maliyeti eşiği
    ) -> ArbitrageSignal | None:
        """Belirtilen kontrat için Spot-Vadeli Arbitraj Analizi yapar.

        Args:
            symbol: Kontrat kodu.
            dividend_yield: Temettü verimi.
            threshold_pct: Arbitraj tetikleme marjı.

        Returns:
            ArbitrageSignal veya veri eksikse None.
        """
        with self._lock:
            quote = self._quotes.get(symbol)
            if not quote:
                return None
            spot = self._spot_prices.get(quote.underlying)
            if not spot or spot <= 0:
                return None

        t = max(0.001, quote.days_to_expiry / 365.0)
        future = quote.mid_price
        theo = self.compute_cost_of_carry(spot, quote.days_to_expiry, dividend_yield)

        mispricing = (future - theo) / spot

        # Zımni repo oranı: F = S * (1 + r * T) -> r = (F/S - 1) / T
        implied_repo = ((future / spot) - 1.0 + dividend_yield * t) / t

        action = "FAIR"
        if mispricing > threshold_pct:
            # Vadeli aşırı pahalı -> Vadeli SAT, Spot hisse AL, Repo borçlan (Cash and Carry)
            action = "CASH_AND_CARRY"
        elif mispricing < -threshold_pct:
            # Vadeli aşırı ucuz -> Vadeli AL, Spot hisse AÇIĞA SAT, Mevduata yatır (Reverse Cash and Carry)
            action = "REVERSE_CASH_AND_CARRY"

        return ArbitrageSignal(
            symbol=symbol,
            underlying=quote.underlying,
            spot_price=spot,
            future_price=future,
            theoretical_price=theo,
            mispricing_pct=float(mispricing),
            implied_repo_rate=float(implied_repo),
            risk_free_rate=self.risk_free_rate,
            action=action,
        )

    def scan_all_arbitrage(
        self,
        threshold_pct: float = 0.015,
    ) -> list[ArbitrageSignal]:
        """Tüm kayıtlı VİOP kontratlarında arbitraj taraması yapar.

        Args:
            threshold_pct: Tetikleme marjı.

        Returns:
            Aktif arbitraj fırsatları listesi.
        """
        with self._lock:
            symbols = list(self._quotes.keys())

        opportunities: list[ArbitrageSignal] = []
        for sym in symbols:
            sig = self.analyze_arbitrage(sym, threshold_pct=threshold_pct)
            if sig and sig.action != "FAIR":
                opportunities.append(sig)

        opportunities.sort(key=lambda x: abs(x.mispricing_pct), reverse=True)
        return opportunities


# Singleton
viop_live_feed = VIOPLiveFeedEngine()

__all__ = [
    "ArbitrageSignal",
    "VIOPContractQuote",
    "VIOPLiveFeedEngine",
    "viop_live_feed",
]
