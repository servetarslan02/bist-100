from typing import Any
"""VIOP API — Gerçek veriyle çalışan endpoint'ler."""

from fastapi import APIRouter, Depends, HTTPException, Query

from ...viop.contract_catalog import viop_catalog
from ...viop.enhanced_options import (
    black_scholes,
    calculate_greeks,
    check_put_call_parity,
    delta_hedger,
    futures_spot_arbitrage,
    implied_volatility,
    options_strategies,
    portfolio_greeks,
    span_margin,
    viop_risk,
)
from ..dependencies import check_rate_limit, get_current_user

router = APIRouter()


# =====================================================
# OPTIONS PRICING & GREEKS
# =====================================================


@router.get("/options")
async def get_options(
    symbol: str = Query(..., description="Sözleşme kodu (ör. XU030)"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Opsiyon sözleşme bilgisi ve Greeks."""
    contract = viop_catalog.get_contract(symbol)
    if not contract:
        raise HTTPException(status_code=404, detail=f"Sözleşme bulunamadı: {symbol}")

    next_expiry = viop_catalog.get_next_expiry(symbol)

    return {
        "contract": viop_catalog.to_dict(symbol),
        "next_expiry": next_expiry.isoformat() if next_expiry else None,
        "category": contract.category,
    }


@router.post("/options/price")
async def price_option(
    S: float = Query(..., description="Dayanak fiyat"),
    K: float = Query(..., description="Kullanım fiyatı"),
    T: float = Query(..., description="Vade (yıl)"),
    r: float = Query(0.15, description="Risksiz faiz"),
    sigma: float = Query(0.25, description="Volatilite"),
    option_type: str = Query("call", description="call/put"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Black-Scholes opsiyon fiyatlaması."""
    price = black_scholes(S, K, T, r, sigma, option_type)
    greeks = calculate_greeks(S, K, T, r, sigma, option_type)

    return {
        "price": round(price, 4),
        "greeks": greeks,
        "inputs": {"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "type": option_type},
    }


@router.post("/options/implied-vol")
async def calculate_iv(
    market_price: float = Query(..., description="Piyasa opsiyon fiyatı"),
    S: float = Query(..., description="Dayanak fiyat"),
    K: float = Query(..., description="Kullanım fiyatı"),
    T: float = Query(..., description="Vade (yıl)"),
    r: float = Query(0.15, description="Risksiz faiz"),
    option_type: str = Query("call", description="call/put"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Implied volatility hesapla (Newton-Raphson)."""
    iv = implied_volatility.calculate(market_price, S, K, T, r, option_type)

    return {
        "implied_vol": iv,
        "implied_vol_pct": round(iv * 100, 2),
        "market_price": market_price,
        "inputs": {"S": S, "K": K, "T": T, "r": r, "type": option_type},
    }


# =====================================================
# PORTFOLIO GREEKS
# =====================================================


@router.post("/greeks")
async def get_portfolio_greeks(
    positions: list[dict],
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Portföy bazlı Greeks aggregation.

    positions: [{"option_type", "S", "K", "T", "r", "sigma", "quantity", "side"}]
    """
    if not positions:
        raise HTTPException(status_code=400, detail="Pozisyon listesi boş")

    result = portfolio_greeks.aggregate(positions)
    return result.to_dict()


# =====================================================
# STRATEGIES
# =====================================================


@router.get("/strategies")
async def list_strategies(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Mevcut opsiyon stratejilerini listele."""
    return {
        "strategies": [
            {"name": "COVERED_CALL", "description": "Hisse + Call sat → gelir"},
            {"name": "PROTECTIVE_PUT", "description": "Hisse + Put al → koruma"},
            {"name": "COLLAR", "description": "Put al + Call sat → sınırlı risk"},
            {"name": "IRON_CONDOR", "description": "4 bacak, düşük vol beklentisi"},
            {"name": "STRADDLE", "description": "Call + Put al, yön belirsiz"},
            {"name": "STRANGLE", "description": "OTM Call + Put al, büyük hareket"},
            {"name": "BULL_CALL_SPREAD", "description": "Yükseliş beklentisi"},
            {"name": "BEAR_PUT_SPREAD", "description": "Düşüş beklentisi"},
            {"name": "BUTTERFLY", "description": "Dar aralık beklentisi"},
        ]
    }


@router.post("/strategies/analyze")
async def analyze_strategy(
    strategy: str = Query(..., description="Strateji adı"),
    spot: float = Query(..., description="Spot fiyat"),
    params: dict = None,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Strateji analizi yap."""
    if params is None:
        params = {}
    strat = options_strategies

    strategy_map = {
        "COVERED_CALL": lambda: strat.covered_call(
            spot,
            params.get("call_strike", spot * 1.05),
            params.get("call_premium", spot * 0.02),
            params.get("shares", 100),
        ),
        "PROTECTIVE_PUT": lambda: strat.protective_put(
            spot,
            params.get("put_strike", spot * 0.95),
            params.get("put_premium", spot * 0.02),
            params.get("shares", 100),
        ),
        "COLLAR": lambda: strat.collar(
            spot,
            params.get("put_strike", spot * 0.95),
            params.get("put_premium", spot * 0.02),
            params.get("call_strike", spot * 1.05),
            params.get("call_premium", spot * 0.02),
            params.get("shares", 100),
        ),
        "IRON_CONDOR": lambda: strat.iron_condor(
            spot,
            params.get("put_sell", spot * 0.95),
            params.get("put_buy", spot * 0.90),
            params.get("call_sell", spot * 1.05),
            params.get("call_buy", spot * 1.10),
            params.get("put_sell_prem", spot * 0.02),
            params.get("put_buy_prem", spot * 0.01),
            params.get("call_sell_prem", spot * 0.02),
            params.get("call_buy_prem", spot * 0.01),
        ),
        "STRADDLE": lambda: strat.straddle(
            spot, spot, params.get("call_premium", spot * 0.03), params.get("put_premium", spot * 0.03)
        ),
        "STRANGLE": lambda: strat.strangle(
            spot,
            params.get("put_strike", spot * 0.95),
            params.get("call_strike", spot * 1.05),
            params.get("put_premium", spot * 0.02),
            params.get("call_premium", spot * 0.02),
        ),
        "BULL_CALL_SPREAD": lambda: strat.bull_call_spread(
            params.get("buy_strike", spot),
            params.get("sell_strike", spot * 1.10),
            params.get("buy_premium", spot * 0.05),
            params.get("sell_premium", spot * 0.02),
        ),
        "BEAR_PUT_SPREAD": lambda: strat.bear_put_spread(
            params.get("buy_strike", spot * 1.10),
            params.get("sell_strike", spot),
            params.get("buy_premium", spot * 0.05),
            params.get("sell_premium", spot * 0.02),
        ),
        "BUTTERFLY": lambda: strat.butterfly(
            params.get("lower", spot * 0.95),
            params.get("middle", spot),
            params.get("upper", spot * 1.05),
            params.get("lower_prem", spot * 0.06),
            params.get("middle_prem", spot * 0.03),
            params.get("upper_prem", spot * 0.01),
        ),
    }

    factory = strategy_map.get(strategy.upper())
    if not factory:
        raise HTTPException(status_code=400, detail=f"Bilinmeyen strateji: {strategy}")

    result = factory()
    return result.to_dict()


# =====================================================
# HEDGING
# =====================================================


@router.post("/hedge")
async def calculate_hedge(
    portfolio_delta: float = Query(..., description="Portföy delta"),
    spot_price: float = Query(..., description="Spot fiyat"),
    futures_price: float = Query(0, description="Futures fiyatı"),
    contract_multiplier: float = Query(100, description="Sözleşme çarpanı"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Delta hedge pozisyonu öner."""
    result = delta_hedger.hedge(portfolio_delta, spot_price, futures_price, contract_multiplier)
    return result.to_dict()


@router.post("/hedge/gamma-scalp")
async def gamma_scalp(
    portfolio_gamma: float = Query(..., description="Portföy gamma"),
    spot_price: float = Query(..., description="Spot fiyat"),
    price_move_pct: float = Query(..., description="Fiyat hareketi (%)"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Gamma scalping P&L hesabı."""
    return delta_hedger.gamma_scalp(portfolio_gamma, spot_price, price_move_pct)


# =====================================================
# MARGIN
# =====================================================


@router.post("/margin")
async def calculate_margin(
    positions: list[dict],
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """SPAN teminat hesapla.

    positions: [{"ticker", "value", "delta", "gamma", "vega", "spot_price"}]
    """
    result = span_margin.calculate(positions)
    return result


# =====================================================
# ARBITRAGE
# =====================================================


@router.post("/arbitrage")
async def check_arbitrage(
    spot_price: float = Query(..., description="Spot fiyat"),
    futures_price: float = Query(..., description="Futures fiyatı"),
    risk_free_rate: float = Query(0.15, description="Risksiz faiz"),
    dividend_yield: float = Query(0.02, description="Temettü verimi"),
    time_to_expiry: float = Query(0.25, description="Vade (yıl)"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Futures-spot arbitraj kontrolü."""
    result = futures_spot_arbitrage.analyze(spot_price, futures_price, risk_free_rate, dividend_yield, time_to_expiry)
    return result.to_dict()


# =====================================================
# PARITY
# =====================================================


@router.post("/parity")
async def check_parity(
    call_price: float = Query(...),
    put_price: float = Query(...),
    spot_price: float = Query(...),
    strike: float = Query(...),
    r: float = Query(0.15),
    T: float = Query(0.25),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Put-Call Parity kontrolü."""
    return check_put_call_parity(call_price, put_price, spot_price, strike, r, T)


# =====================================================
# RISK
# =====================================================


@router.post("/risk")
async def calculate_viop_risk(
    viop_positions: list[dict],
    portfolio_value: float = Query(..., description="Portföy değeri"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """VIOP pozisyon risk hesabı."""
    return viop_risk.calculate_portfolio_viop_risk(viop_positions, portfolio_value)


# =====================================================
# CONTRACT CATALOG
# =====================================================


@router.get("/contracts")
async def list_contracts(
    category: str | None = Query(None, description="Kategori filtresi (endeks/döviz/emtia)"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """VIOP sözleşmelerini listele."""
    if category:
        contracts = viop_catalog.get_contracts_by_category(category)
        return {"contracts": [viop_catalog.to_dict(c.symbol) for c in contracts]}
    return {"contracts": [viop_catalog.to_dict(s) for s in viop_catalog.get_all_contracts()]}


@router.get("/contracts/{symbol}")
async def get_contract(
    symbol: str,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Tek sözleşme detayı."""
    contract = viop_catalog.get_contract(symbol)
    if not contract:
        raise HTTPException(status_code=404, detail=f"Sözleşme bulunamadı: {symbol}")
    return viop_catalog.to_dict(symbol)
