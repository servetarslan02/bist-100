"""
ALPHA BIST — Market Session Manager (Wrapper)

Bu dosya market_session_fsm.py'ye yönlendirme yapar.
Tek kaynak: market_session_fsm.py

Geriye uyumluluk için korunmuştur.
"""

from datetime import datetime
import functools
import structlog
from opentelemetry import trace

from .auto_circuit_breaker import auto_circuit_breaker
from .market_session_fsm import (
    _TZ_ISTANBUL,
    BISTMarketPhase,
    bist_session_fsm,
)

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.market_session")

def otel_trace(span_name: str):
    """Decorator to wrap a method in an OTel span."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)
        return wrapper
    return decorator


# Eski API'ye uyumluluk için enum mapping
class MarketPhase:
    CLOSED = "closed"
    PRE_MARKET = "pre_market"
    ACTIVE = "active"
    POST_MARKET = "post_market"
    AFTER_HOURS = "after_hours"


class MarketSessionManager:
    """BIST piyasa session yönetimi — market_session_fsm.py wrapper.

    Tüm zaman hesaplamaları Europe/Istanbul timezone'da.
    """

    def __init__(self, holidays=None):
        if holidays:
            bist_session_fsm.set_holidays(holidays)

    def now_istanbul(self) -> datetime:
        return datetime.now(_TZ_ISTANBUL)

    @otel_trace("market_session.current_phase")
    def current_phase(self) -> str:
        """Piyasanın şu anki durumu (eski API uyumluluğu)."""
        phase = bist_session_fsm.get_phase()
        mapping = {
            BISTMarketPhase.CLOSED: MarketPhase.CLOSED,
            BISTMarketPhase.OPENING_AUCTION_COLLECTION: MarketPhase.PRE_MARKET,
            BISTMarketPhase.OPENING_AUCTION_DETERMINATION: MarketPhase.PRE_MARKET,
            BISTMarketPhase.CONTINUOUS_AUCTION: MarketPhase.ACTIVE,
            BISTMarketPhase.CIRCUIT_BREAKER_AUCTION: MarketPhase.ACTIVE,
            BISTMarketPhase.CLOSING_AUCTION_COLLECTION: MarketPhase.POST_MARKET,
            BISTMarketPhase.CLOSING_AUCTION_DETERMINATION: MarketPhase.POST_MARKET,
            BISTMarketPhase.CLOSING_PRICE_TRADING: MarketPhase.POST_MARKET,
        }
        return mapping.get(phase, MarketPhase.CLOSED)

    @otel_trace("market_session.is_trading_hours")
    def is_trading_hours(self) -> bool:
        return bist_session_fsm.is_trading_hours()

    @otel_trace("market_session.is_pre_market")
    def is_pre_market(self) -> bool:
        phase = bist_session_fsm.get_phase()
        return phase in (BISTMarketPhase.OPENING_AUCTION_COLLECTION, BISTMarketPhase.OPENING_AUCTION_DETERMINATION)

    @otel_trace("market_session.is_post_market")
    def is_post_market(self) -> bool:
        phase = bist_session_fsm.get_phase()
        return phase in (
            BISTMarketPhase.CLOSING_AUCTION_COLLECTION,
            BISTMarketPhase.CLOSING_AUCTION_DETERMINATION,
            BISTMarketPhase.CLOSING_PRICE_TRADING,
        )

    @otel_trace("market_session.is_closed")
    def is_closed(self) -> bool:
        return bist_session_fsm.is_closed()

    @otel_trace("market_session.should_run_trading_job")
    def should_run_trading_job(self) -> bool:
        """Trading job çalıştırılmalı mı?"""
        phase = bist_session_fsm.get_phase()
        return phase in (BISTMarketPhase.CONTINUOUS_AUCTION, BISTMarketPhase.OPENING_AUCTION_COLLECTION)

    @otel_trace("market_session.get_status")
    def get_status(self) -> dict:
        return bist_session_fsm.get_status()

    @otel_trace("market_session.update_price")
    def update_price(self, ticker: str, current_price: float, reference_price: float, market_type: str = "ana") -> dict:
        """Fiyat güncelle ve devre kesici kontrolü yap.

        Args:
            ticker: Hisse kodu ("BIST-100" için endeks)
            current_price: Güncel fiyat
            reference_price: Önceki kapanış
            market_type: Pazar tipi (yildiz, ana, alt)
        """
        if ticker == "BIST-100":
            event = auto_circuit_breaker.update_bist100_price(current_price)
        else:
            event = auto_circuit_breaker.check_pay_circuit_breaker(ticker, current_price, reference_price, market_type)
        return {
            "ticker": ticker,
            "event": event.to_dict() if event else None,
            "ebdks_active": bist_session_fsm.is_ebdks_active(),
            "ebdks_late_session": bist_session_fsm.is_ebdks_late_session(),
        }

    @otel_trace("market_session.reset_daily_circuit_breakers")
    def reset_daily_circuit_breakers(self):
        """Günlük devre kesici sayaçlarını sıfırla (seans sonunda)."""
        auto_circuit_breaker.reset_daily()


# Singleton (geriye uyumluluk)
market_session = MarketSessionManager()
