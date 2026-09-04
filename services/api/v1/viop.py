"""
VIOP API — Vadeli İşlem ve Opsiyon Piyasası endpoint'leri.

Gerçek veriyle çalışan opsiyon fiyatlaması, Greeks, strateji analizi,
delta hedging, SPAN teminat, arbitraj ve put-call parity kontrolleri.

Kullanım:
    GET  /api/v1/viop/options?symbol=XU030
    POST /api/v1/viop/options/price
    POST /api/v1/viop/options/implied-vol
    POST /api/v1/viop/greeks
    GET  /api/v1/viop/strategies
    POST /api/v1/viop/strategies/analyze
    POST /api/v1/viop/hedge
    POST /api/v1/viop/hedge/gamma-scalp
    POST /api/v1/viop/margin
    POST /api/v1/viop/arbitrage
    POST /api/v1/viop/parity
    POST /api/v1/viop/risk
    GET  /api/v1/viop/contracts
    GET  /api/v1/viop/contracts/{symbol}
"""

import logging
from typing import Any

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

logger = logging.getLogger(__name__)
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
    """Opsiyon sözleşme bilgisi ve Greeks.

    Args:
        symbol: Sözleşme kodu (ör. XU030, USDTRY).

    Returns:
        Sözleşme detayları, son vade tarihi ve kategori.

    Raises:
        HTTPException(404): Sözleşme bulunamazsa.
        HTTPException(500): Dahili hata oluşursa.
    """
    try:
        contract = viop_catalog.get_contract(symbol)
        if not contract:
            raise HTTPException(status_code=404, detail=f"Sözleşme bulunamadı: {symbol}")

        next_expiry = viop_catalog.get_next_expiry(symbol)

        return {
            "contract": viop_catalog.to_dict(symbol),
            "next_expiry": next_expiry.isoformat() if next_expiry else None,
            "category": contract.category,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("viop_options_hatasi: symbol=%s hata=%s", symbol, str(e))
        raise HTTPException(status_code=500, detail="Opsiyon bilgisi alınamadı.") from e


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
    """Black-Scholes opsiyon fiyatlaması.

    Args:
        S: Dayanak varlık fiyatı.
        K: Kullanım (strike) fiyatı.
        T: Vadeye kalan süre (yıl).
        r: Risksiz faiz oranı.
        sigma: Volatilite.
        option_type: Opsiyon tipi (call/put).

    Returns:
        Opsiyon fiyatı, Greeks ve giriş parametreleri.

    Raises:
        HTTPException(500): Hesaplama hatası oluşursa.
    """
    try:
        price = black_scholes(S, K, T, r, sigma, option_type)
        greeks = calculate_greeks(S, K, T, r, sigma, option_type)

        return {
            "price": round(price, 4),
            "greeks": greeks,
            "inputs": {"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "type": option_type},
        }
    except Exception as e:
        logger.error("viop_fiyat_hatasi: S=%s K=%s hata=%s", S, K, str(e))
        raise HTTPException(status_code=500, detail="Opsiyon fiyatlaması başarısız.") from e


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
    """Implied volatility hesapla (Newton-Raphson).

    Args:
        market_price: Piyasada gözlenen opsiyon fiyatı.
        S: Dayanak varlık fiyatı.
        K: Kullanım (strike) fiyatı.
        T: Vadeye kalan süre (yıl).
        r: Risksiz faiz oranı.
        option_type: Opsiyon tipi (call/put).

    Returns:
        Implied volatilite (ondalık ve yüzde olarak), piyasa fiyatı ve giriş parametreleri.

    Raises:
        HTTPException(500): IV hesaplama yakınsamazsa.
    """
    try:
        iv = implied_volatility.calculate(market_price, S, K, T, r, option_type)

        return {
            "implied_vol": iv,
            "implied_vol_pct": round(iv * 100, 2),
            "market_price": market_price,
            "inputs": {"S": S, "K": K, "T": T, "r": r, "type": option_type},
        }
    except Exception as e:
        logger.error("viop_iv_hatasi: market_price=%s S=%s hata=%s", market_price, S, str(e))
        raise HTTPException(status_code=500, detail="Implied volatility hesaplanamadı.") from e


# =====================================================
# PORTFOLIO GREEKS
# =====================================================


@router.post("/greeks")
async def get_portfolio_greeks(
    positions: list[dict[str, Any]],
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Portföy bazlı Greeks aggregation.

    Args:
        positions: Pozisyon listesi. Her eleman: {option_type, S, K, T, r, sigma, quantity, side}.

    Returns:
        Toplam Greeks değerleri (delta, gamma, vega, theta, rho).

    Raises:
        HTTPException(400): Pozisyon listesi boşsa.
        HTTPException(500): Hesaplama hatası oluşursa.
    """
    if not positions:
        raise HTTPException(status_code=400, detail="Pozisyon listesi boş")

    try:
        result = portfolio_greeks.aggregate(positions)
        return result.to_dict()
    except Exception as e:
        logger.error("viop_greeks_hatasi: pozisyon_sayisi=%d hata=%s", len(positions), str(e))
        raise HTTPException(status_code=500, detail="Greeks hesaplanamadı.") from e


# =====================================================
# STRATEGIES
# =====================================================


@router.get("/strategies")
async def list_strategies(
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Mevcut opsiyon stratejilerini listele.

    Returns:
        Strateji adları ve açıklamaları.

    Raises:
        HTTPException(500): Dahili hata oluşursa.
    """
    try:
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
    except Exception as e:
        logger.error("viop_strateji_listesi_hatasi: hata=%s", str(e))
        raise HTTPException(status_code=500, detail="Strateji listesi alınamadı.") from e


@router.post("/strategies/analyze")
async def analyze_strategy(
    strategy: str = Query(..., description="Strateji adı"),
    spot: float = Query(..., description="Spot fiyat"),
    params: dict[str, Any] | None = None,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Strateji analizi yap.

    Args:
        strategy: Strateji adı (COVERED_CALL, IRON_CONDOR vb.).
        spot: Dayanak varlık spot fiyatı.
        params: Stratejiye özel parametreler (opsiyonel).

    Returns:
        Strateji P&L profili ve detayları.

    Raises:
        HTTPException(400): Bilinmeyen strateji adı.
        HTTPException(500): Hesaplama hatası oluşursa.
    """
    if params is None:
        params = {}

    try:
        strat = options_strategies

        strategy_map: dict[str, Any] = {
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error("viop_strateji_hatasi: strateji=%s hata=%s", strategy, str(e))
        raise HTTPException(status_code=500, detail="Strateji analizi başarısız.") from e


# =====================================================
# HEDGING
# =====================================================


@router.post("/hedge")
async def calculate_hedge(
    portfolio_delta: float = Query(..., description="Portföy delta"),
    spot_price: float = Query(..., description="Spot fiyat"),
    futures_price: float = Query(..., description="Futures fiyatı"),
    contract_multiplier: float = Query(100, description="Sözleşme çarpanı"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Delta hedge pozisyonu öner.

    Args:
        portfolio_delta: Portföyün toplam deltası.
        spot_price: Dayanak varlık spot fiyatı.
        futures_price: Futures sözleşme fiyatı.
        contract_multiplier: Sözleşme çarpanı (VIOP standart: 100).

    Returns:
        Hedge pozisyonu, sözleşme adedi ve maliyet.

    Raises:
        HTTPException(500): Hesaplama hatası oluşursa.
    """
    try:
        result = delta_hedger.hedge(portfolio_delta, spot_price, futures_price, contract_multiplier)
        return result.to_dict()
    except Exception as e:
        logger.error("viop_hedge_hatasi: delta=%s hata=%s", portfolio_delta, str(e))
        raise HTTPException(status_code=500, detail="Delta hedge hesaplanamadı.") from e


@router.post("/hedge/gamma-scalp")
async def gamma_scalp(
    portfolio_gamma: float = Query(..., description="Portföy gamma"),
    spot_price: float = Query(..., description="Spot fiyat"),
    price_move_pct: float = Query(..., description="Fiyat hareketi (%)"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Gamma scalping P&L hesabı.

    Args:
        portfolio_gamma: Portföyün toplam gamması.
        spot_price: Dayanak varlık spot fiyatı.
        price_move_pct: Fiyat hareketi yüzdesi.

    Returns:
        Gamma scalping P&L ve pozisyon detayları.

    Raises:
        HTTPException(500): Hesaplama hatası oluşursa.
    """
    try:
        return delta_hedger.gamma_scalp(portfolio_gamma, spot_price, price_move_pct)
    except Exception as e:
        logger.error("viop_gamma_scalp_hatasi: gamma=%s hata=%s", portfolio_gamma, str(e))
        raise HTTPException(status_code=500, detail="Gamma scalping hesaplanamadı.") from e


# =====================================================
# MARGIN
# =====================================================


@router.post("/margin")
async def calculate_margin(
    positions: list[dict[str, Any]],
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """SPAN teminat hesapla.

    Args:
        positions: Pozisyon listesi. Her eleman: {ticker, value, delta, gamma, vega, spot_price}.

    Returns:
        SPAN teminat gereksinimi ve detayları.

    Raises:
        HTTPException(500): Hesaplama hatası oluşursa.
    """
    try:
        result = span_margin.calculate(positions)
        return result
    except Exception as e:
        logger.error("viop_teminat_hatasi: pozisyon_sayisi=%d hata=%s", len(positions), str(e))
        raise HTTPException(status_code=500, detail="SPAN teminat hesaplanamadı.") from e


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
    """Futures-spot arbitraj kontrolü.

    Args:
        spot_price: Spot fiyat.
        futures_price: Futures fiyatı.
        risk_free_rate: Risksiz faiz oranı.
        dividend_yield: Temettü verimi.
        time_to_expiry: Vadeye kalan süre (yıl).

    Returns:
        Arbitraj fırsatı varsa detaylar, yoksa "arbitraj yok" sonucu.

    Raises:
        HTTPException(500): Hesaplama hatası oluşursa.
    """
    try:
        result = futures_spot_arbitrage.analyze(
            spot_price, futures_price, risk_free_rate, dividend_yield, time_to_expiry
        )
        return result.to_dict()
    except Exception as e:
        logger.error("viop_arbitraj_hatasi: spot=%s futures=%s hata=%s", spot_price, futures_price, str(e))
        raise HTTPException(status_code=500, detail="Arbitraj analizi başarısız.") from e


# =====================================================
# PARITY
# =====================================================


@router.post("/parity")
async def check_parity(
    call_price: float = Query(..., description="Call opsiyon fiyatı"),
    put_price: float = Query(..., description="Put opsiyon fiyatı"),
    spot_price: float = Query(..., description="Dayanak spot fiyatı"),
    strike: float = Query(..., description="Kullanım (strike) fiyatı"),
    r: float = Query(0.15, description="Risksiz faiz oranı"),
    T: float = Query(0.25, description="Vadeye kalan süre (yıl)"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Put-Call Parity kontrolü.

    Args:
        call_price: Call opsiyon fiyatı.
        put_price: Put opsiyon fiyatı.
        spot_price: Dayanak spot fiyatı.
        strike: Kullanım fiyatı.
        r: Risksiz faiz oranı.
        T: Vadeye kalan süre (yıl).

    Returns:
        Parite durumu ve sapma miktarı.

    Raises:
        HTTPException(500): Hesaplama hatası oluşursa.
    """
    try:
        return check_put_call_parity(call_price, put_price, spot_price, strike, r, T)
    except Exception as e:
        logger.error("viop_parite_hatasi: call=%s put=%s hata=%s", call_price, put_price, str(e))
        raise HTTPException(status_code=500, detail="Put-Call parity hesaplanamadı.") from e


# =====================================================
# RISK
# =====================================================


@router.post("/risk")
async def calculate_viop_risk(
    viop_positions: list[dict[str, Any]],
    portfolio_value: float = Query(..., description="Portföy değeri"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """VIOP pozisyon risk hesabı.

    Args:
        viop_positions: VIOP pozisyon listesi.
        portfolio_value: Toplam portföy değeri.

    Returns:
        Risk metrikleri (VaR, stress test, Greeks bazlı risk).

    Raises:
        HTTPException(500): Hesaplama hatası oluşursa.
    """
    try:
        return viop_risk.calculate_portfolio_viop_risk(viop_positions, portfolio_value)
    except Exception as e:
        logger.error("viop_risk_hatasi: deger=%s hata=%s", portfolio_value, str(e))
        raise HTTPException(status_code=500, detail="VIOP risk hesabı başarısız.") from e


# =====================================================
# CONTRACT CATALOG
# =====================================================


@router.get("/contracts")
async def list_contracts(
    category: str | None = Query(None, description="Kategori filtresi (endeks/döviz/emtia)"),
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """VIOP sözleşmelerini listele.

    Args:
        category: Kategori filtresi (endeks/döviz/emtia). None ise tümü.

    Returns:
        Sözleşme listesi.
    """
    try:
        if category:
            contracts = viop_catalog.get_contracts_by_category(category)
            return {"contracts": [viop_catalog.to_dict(c.symbol) for c in contracts]}
        return {"contracts": [viop_catalog.to_dict(s) for s in viop_catalog.get_all_contracts()]}
    except Exception as e:
        logger.error("viop_sozlesme_listesi_hatasi: hata=%s", str(e))
        raise HTTPException(status_code=500, detail="Sözleşme listesi alınamadı.") from e


@router.get("/contracts/{symbol}")
async def get_contract(
    symbol: str,
    user=Depends(get_current_user),
    _=Depends(check_rate_limit),
) -> Any:
    """Tek sözleşme detayı.

    Args:
        symbol: Sözleşme kodu.

    Returns:
        Sözleşme detay bilgileri.

    Raises:
        HTTPException(404): Sözleşme bulunamazsa.
        HTTPException(500): Dahili hata oluşursa.
    """
    try:
        contract = viop_catalog.get_contract(symbol)
        if not contract:
            raise HTTPException(status_code=404, detail=f"Sözleşme bulunamadı: {symbol}")
        return viop_catalog.to_dict(symbol)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("viop_sozlesme_hatasi: symbol=%s hata=%s", symbol, str(e))
        raise HTTPException(status_code=500, detail="Sözleşme bilgisi alınamadı.") from e
