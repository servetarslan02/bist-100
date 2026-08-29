"""
ALPHA BIST — API v1 Router Package

Tüm v1 endpoint'leri.
"""

from fastapi import APIRouter

from .agents import router as agents_router
from .alternative import router as alternative_router
from .backtest import router as backtest_router
from .decisions import router as decisions_router
from .event_study import router as event_study_router
from .factors import router as factors_router
from .holidays import router as holidays_router
from .intelligence import router as intelligence_router
from .learning import router as learning_router
from .macro import router as macro_router
from .market import router as market_router
from .models import router as models_router
from .portfolio import router as portfolio_router
from .risk import router as risk_router
from .scanner import router as scanner_router
from .sse import router as sse_router
from .system import router as system_router
from .viop import router as viop_router
from .ws import router as ws_router

v1_router = APIRouter(prefix="/api/v1")

v1_router.include_router(market_router, prefix="/market", tags=["Market Data"])
v1_router.include_router(portfolio_router, prefix="/portfolio", tags=["Portfolio"])
v1_router.include_router(risk_router, prefix="/risk", tags=["Risk"])
v1_router.include_router(intelligence_router, prefix="/intelligence", tags=["Intelligence"])
v1_router.include_router(decisions_router, prefix="/decisions", tags=["Decisions"])
v1_router.include_router(backtest_router, prefix="/backtests", tags=["Backtest"])
v1_router.include_router(learning_router, prefix="/learning", tags=["Learning"])
v1_router.include_router(models_router, prefix="/models", tags=["Models"])
v1_router.include_router(agents_router, prefix="/agents", tags=["Agents"])
v1_router.include_router(scanner_router, prefix="/scanner", tags=["Scanner"])
v1_router.include_router(macro_router, prefix="/macro", tags=["Macro"])
v1_router.include_router(factors_router, prefix="/factors", tags=["Factors"])
v1_router.include_router(alternative_router, prefix="/alternative", tags=["Alternative Data"])
v1_router.include_router(viop_router, prefix="/viop", tags=["VIOP"])
v1_router.include_router(event_study_router, prefix="/event-study", tags=["Event Study"])
v1_router.include_router(system_router, prefix="/system", tags=["System"])
v1_router.include_router(ws_router, prefix="/ws", tags=["WebSockets"])
v1_router.include_router(sse_router, prefix="/sse", tags=["Server-Sent Events"])
v1_router.include_router(holidays_router, prefix="/holidays", tags=["Holidays"])

# Direct Frontend Route Aliases (Sıfır 404 Garantisi)
v1_router.include_router(scanner_router, prefix="", tags=["Scanner (Direct)"])
v1_router.include_router(system_router, prefix="", tags=["System (Direct)"])
v1_router.include_router(portfolio_router, prefix="/strategy", tags=["Strategy (Direct)"])
v1_router.include_router(holidays_router, prefix="/tatil", tags=["Tatil (Direct)"])

router = v1_router
