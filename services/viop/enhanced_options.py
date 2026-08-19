"""
ALPHA BIST — VIOP Enhanced Options System v3.0

Tüm VIOP opsiyon sistemi tek modülde:
- Black-Scholes fiyatlaması
- Greeks (Delta, Gamma, Theta, Vega, Rho)
- Implied Volatility (Newton-Raphson)
- Portfolio Greeks aggregation
- Options Chain veri modeli
- 9 strateji (Covered Call, Protective Put, Collar, Iron Condor, Straddle, Strangle, Bull Call Spread, Bear Put Spread, Butterfly)
- Dynamic Delta Hedging + Gamma Scalping
- SPAN Margin (16 senaryo)
- Futures-Spot Arbitrage
- VIOP Risk Integration
- Options Backtest Engine

Kaynaklar: Black-Scholes (1973), BIST SPAN, TradingBlock (2025), DaystoExpiry (2025)
"""

import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import date, datetime
from scipy.stats import norm
import structlog

logger = structlog.get_logger()


# =====================================================
# 1. BLACK-SCHOLES PRICING
# =====================================================

def black_scholes(S: float, K: float, T: float, r: float, sigma: float,
                  option_type: str = "call") -> float:
    """Black-Scholes opsiyon fiyatlaması.

    Args:
        S: Dayanak fiyat (spot)
        K: Kullanım fiyatı (strike)
        T: Vade (yıl cinsinden, ör. 0.25 = 3 ay)
        r: Risksiz faiz oranı (ondalık, ör. 0.15 = %15)
        sigma: Volatilite (ondalık, ör. 0.25 = %25)
        option_type: "call" veya "put"

    Returns:
        Opsiyon teorik fiyatı (TL)
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        # Vade dolmuş veya geçersiz parametre → intrinsic value
        if option_type == "call":
            return max(S - K, 0.0)
        else:
            return max(K - S, 0.0)

    d1 = (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    if option_type == "call":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


# =====================================================
# 2. GREEKS
# =====================================================

def calculate_greeks(S: float, K: float, T: float, r: float, sigma: float,
                     option_type: str = "call") -> Dict[str, float]:
    """Opsiyon Greeks hesaplama.

    Returns:
        {"delta", "gamma", "theta", "vega", "rho"}
        - delta: Fiyat hassasiyeti [-1, 1]
        - gamma: Delta değişimi [0, ∞)
        - theta: Günlük zaman aşımı (negatif)
        - vega: %1 volatilite değişimi etkisi
        - rho: %1 faiz değişimi etkisi
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        # Vade dolmuş → intrinsic Greeks
        if option_type == "call":
            delta = 1.0 if S > K else 0.0
        else:
            delta = -1.0 if S < K else 0.0
        return {"delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    d1 = (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    # Gamma ve Vega opsiyon type'dan bağımsız
    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
    vega = S * norm.pdf(d1) * np.sqrt(T) / 100  # %1 vol etkisi

    if option_type == "call":
        delta = norm.cdf(d1)
        theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T))
                 - r * K * np.exp(-r * T) * norm.cdf(d2)) / 365
        rho = K * T * np.exp(-r * T) * norm.cdf(d2) / 100
    else:
        delta = norm.cdf(d1) - 1
        theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T))
                 + r * K * np.exp(-r * T) * norm.cdf(-d2)) / 365
        rho = -K * T * np.exp(-r * T) * norm.cdf(-d2) / 100

    return {
        "delta": round(delta, 6),
        "gamma": round(gamma, 8),
        "theta": round(theta, 4),
        "vega": round(vega, 4),
        "rho": round(rho, 4),
    }


# =====================================================
# 3. IMPLIED VOLATILITY
# =====================================================

class ImpliedVolatility:
    """Implied volatility hesaplama (Newton-Raphson).

    Piyasa opsiyon fiyatından gizli volatiliteyi bulur.
    Konverjans garantisi: brent method fallback.
    """

    def calculate(
        self,
        market_price: float,
        S: float,
        K: float,
        T: float,
        r: float,
        option_type: str = "call",
        max_iterations: int = 200,
        tolerance: float = 1e-8,
    ) -> float:
        """Newton-Raphson + bisection fallback ile implied volatility.

        Args:
            market_price: Piyasa opsiyon fiyatı
            S: Dayanak fiyat
            K: Kullanım fiyatı
            T: Vade (yıl)
            r: Risksiz faiz
            option_type: call / put
            max_iterations: Maksimum iterasyon
            tolerance: Konverjans toleransı

        Returns:
            Implied volatility (ondalık, ör. 0.25 = %25)
        """
        if market_price <= 0 or S <= 0 or K <= 0 or T <= 0:
            return 0.0

        # Fiyat_bound_check: call için max(S - K*e^(-rT), 0), put için max(K*e^(-rT) - S, 0)
        if option_type == "call":
            intrinsic = max(S - K * np.exp(-r * T), 0)
        else:
            intrinsic = max(K * np.exp(-r * T) - S, 0)

        if market_price < intrinsic - 1e-6:
            # Arbitaj var, piyasa fiyatı intrinsic'in altında
            logger.warning("Market price below intrinsic", market=market_price, intrinsic=intrinsic)
            return 0.01  # Minimum vol

        # Newton-Raphson
        sigma = 0.30  # Başlangıç tahmini

        for i in range(max_iterations):
            price = black_scholes(S, K, T, r, sigma, option_type)
            diff = price - market_price

            if abs(diff) < tolerance:
                return round(sigma, 6)

            # Vega (türev)
            d1 = (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))
            vega = S * norm.pdf(d1) * np.sqrt(T)

            if abs(vega) < 1e-12:
                # Vega çok küçük → bisection'a geç
                break

            # Newton-Raphson güncelleme
            sigma_new = sigma - diff / vega

            # Sınır kontrolü
            if sigma_new <= 0 or sigma_new > 5.0:
                break  # Bisection'a geç

            sigma = sigma_new

        # Bisection fallback (her zaman konverjan)
        return self._bisection(market_price, S, K, T, r, option_type, tolerance, max_iterations)

    def _bisection(self, target_price: float, S: float, K: float, T: float,
                   r: float, option_type: str, tolerance: float, max_iter: int) -> float:
        """Bisection yöntemi — garantili konverjans."""
        sigma_low, sigma_high = 0.001, 5.0

        for _ in range(max_iter):
            sigma_mid = (sigma_low + sigma_high) / 2.0
            price_mid = black_scholes(S, K, T, r, sigma_mid, option_type)
            diff = price_mid - target_price

            if abs(diff) < tolerance:
                return round(sigma_mid, 6)

            if diff > 0:
                sigma_high = sigma_mid
            else:
                sigma_low = sigma_mid

        return round((sigma_low + sigma_high) / 2.0, 6)

    def calculate_batch(
        self,
        options: List[Dict[str, Any]],
        S: float,
        r: float,
    ) -> List[Dict[str, Any]]:
        """Toplu IV hesaplama.

        Args:
            options: [{"market_price", "K", "T", "option_type"}]
            S: Dayanak fiyat
            r: Risksiz faiz

        Returns:
            IV sonuçları listesi
        """
        results = []
        for opt in options:
            iv = self.calculate(
                market_price=opt.get("market_price", 0),
                S=S,
                K=opt.get("K", 0),
                T=opt.get("T", 0),
                r=r,
                option_type=opt.get("option_type", "call"),
            )
            results.append({
                "strike": opt.get("K"),
                "option_type": opt.get("option_type"),
                "market_price": opt.get("market_price"),
                "implied_vol": iv,
            })
        return results


# =====================================================
# 4. OPTIONS CHAIN
# =====================================================

@dataclass
class OptionQuote:
    """Tek bir opsiyon kotasyonu."""
    strike: float
    expiry: date
    option_type: str  # "call" / "put"
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    volume: int = 0
    open_interest: int = 0
    implied_vol: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0

    @property
    def mid(self) -> float:
        """Orta fiyat (bid/ask ortalaması)."""
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2
        return self.last

    @property
    def spread(self) -> float:
        """Bid-ask spread."""
        if self.bid > 0 and self.ask > 0:
            return self.ask - self.bid
        return 0.0

    @property
    def spread_pct(self) -> float:
        """Spread yüzdesi."""
        mid = self.mid
        if mid > 0:
            return self.spread / mid * 100
        return 0.0


class OptionsChain:
    """Opsiyon zinciri — farklı strike ve vadelerde opsiyonlar.

    Bir dayanak varlık için tüm opsiyonları organize eder.
    """

    def __init__(self, underlying: str, spot_price: float, risk_free_rate: float = 0.15):
        self.underlying = underlying
        self.spot_price = spot_price
        self.risk_free_rate = risk_free_rate
        self._quotes: Dict[Tuple[float, date, str], OptionQuote] = {}

    def add_quote(self, quote: OptionQuote) -> None:
        """Opsiyon kotasyonu ekle."""
        key = (quote.strike, quote.expiry, quote.option_type)
        self._quotes[key] = quote

    def get_quote(self, strike: float, expiry: date, option_type: str) -> Optional[OptionQuote]:
        """Tek opsiyon kotasyonu getir."""
        return self._quotes.get((strike, expiry, option_type))

    def get_strikes(self, expiry: Optional[date] = None) -> List[float]:
        """Mevcut strike'ları sıralı döndür."""
        strikes = set()
        for (strike, exp, _) in self._quotes:
            if expiry is None or exp == expiry:
                strikes.add(strike)
        return sorted(strikes)

    def get_expiries(self) -> List[date]:
        """Mevcut vadeleri sıralı döndür."""
        expiries = set()
        for (_, exp, _) in self._quotes:
            expiries.add(exp)
        return sorted(expiries)

    def get_chain(self, expiry: date) -> Dict[str, List[OptionQuote]]:
        """Belirli bir vade için tüm opsiyonları döndür.

        Returns:
            {"calls": [...], "puts": [...]}
        """
        calls = []
        puts = []
        for (strike, exp, opt_type) in sorted(self._quotes.keys()):
            if exp == expiry:
                quote = self._quotes[(strike, exp, opt_type)]
                if opt_type == "call":
                    calls.append(quote)
                else:
                    puts.append(quote)
        return {"calls": calls, "puts": puts}

    def calculate_all_greeks(self, sigma: float = 0.25) -> None:
        """Tüm opsiyonlar için Greeks hesapla (fiyat yoksa Black-Scholes ile)."""
        for key, quote in self._quotes.items():
            T = (quote.expiry - date.today()).days / 365.0
            if T <= 0:
                continue

            # IV varsa onu kullan, yoksa verilen sigma
            vol = quote.implied_vol if quote.implied_vol > 0 else sigma

            # Fiyat yoksa BS ile hesapla
            if quote.last <= 0 and quote.mid <= 0:
                price = black_scholes(self.spot_price, quote.strike, T,
                                      self.risk_free_rate, vol, quote.option_type)
                quote.last = round(price, 2)

            # Greeks hesapla
            greeks = calculate_greeks(self.spot_price, quote.strike, T,
                                      self.risk_free_rate, vol, quote.option_type)
            quote.delta = greeks["delta"]
            quote.gamma = greeks["gamma"]
            quote.theta = greeks["theta"]
            quote.vega = greeks["vega"]

    def find_atm(self, expiry: date) -> Optional[OptionQuote]:
        """ATM (at-the-money) call opsiyonu bul."""
        strikes = self.get_strikes(expiry)
        if not strikes:
            return None

        # Spot'a en yakın strike
        closest = min(strikes, key=lambda k: abs(k - self.spot_price))
        return self.get_quote(closest, expiry, "call")

    def get_put_call_pairs(self, expiry: date) -> List[Dict[str, Any]]:
        """Put-Call çiftlerini döndür (parity check için)."""
        pairs = []
        strikes = self.get_strikes(expiry)
        for strike in strikes:
            call = self.get_quote(strike, expiry, "call")
            put = self.get_quote(strike, expiry, "put")
            if call and put:
                pairs.append({
                    "strike": strike,
                    "call": call,
                    "put": put,
                })
        return pairs


# =====================================================
# 5. PORTFOLIO GREEKS
# =====================================================

@dataclass
class PortfolioGreeksResult:
    """Portföy Greeks sonucu."""
    total_delta: float
    total_gamma: float
    total_theta: float
    total_vega: float
    total_rho: float
    n_positions: int
    delta_neutral: bool
    position_details: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_delta": self.total_delta,
            "total_gamma": self.total_gamma,
            "total_theta": self.total_theta,
            "total_vega": self.total_vega,
            "total_rho": self.total_rho,
            "n_positions": self.n_positions,
            "delta_neutral": self.delta_neutral,
            "position_details": self.position_details,
        }


class PortfolioGreeks:
    """Portföy bazlı Greeks aggregation.

    Tüm opsiyon pozisyonlarının Greeks'lerini toplar.
    """

    def aggregate(
        self,
        positions: List[Dict[str, Any]],
    ) -> PortfolioGreeksResult:
        """Portföy Greeks hesapla.

        Args:
            positions: Pozisyon listesi
                [{"option_type", "S", "K", "T", "r", "sigma", "quantity", "side"}]
                - side: "long" (alım) veya "short" (satım)
                - quantity: Sözleşme adedi

        Returns:
            PortfolioGreeksResult
        """
        total_delta = 0.0
        total_gamma = 0.0
        total_theta = 0.0
        total_vega = 0.0
        total_rho = 0.0
        details = []

        for pos in positions:
            S = pos.get("S", 0)
            K = pos.get("K", 0)
            T = pos.get("T", 0)
            r = pos.get("r", 0.15)
            sigma = pos.get("sigma", 0.25)
            option_type = pos.get("option_type", "call")
            quantity = pos.get("quantity", 1)
            side = pos.get("side", "long")

            greeks = calculate_greeks(S, K, T, r, sigma, option_type)

            # Long = pozitif, Short = negatif
            multiplier = quantity * (1 if side == "long" else -1)

            pos_delta = greeks["delta"] * multiplier
            pos_gamma = greeks["gamma"] * multiplier
            pos_theta = greeks["theta"] * multiplier
            pos_vega = greeks["vega"] * multiplier
            pos_rho = greeks["rho"] * multiplier

            total_delta += pos_delta
            total_gamma += pos_gamma
            total_theta += pos_theta
            total_vega += pos_vega
            total_rho += pos_rho

            details.append({
                "option_type": option_type,
                "strike": K,
                "side": side,
                "quantity": quantity,
                "delta": round(pos_delta, 6),
                "gamma": round(pos_gamma, 8),
                "theta": round(pos_theta, 4),
                "vega": round(pos_vega, 4),
            })

        return PortfolioGreeksResult(
            total_delta=round(total_delta, 6),
            total_gamma=round(total_gamma, 8),
            total_theta=round(total_theta, 4),
            total_vega=round(total_vega, 4),
            total_rho=round(total_rho, 4),
            n_positions=len(positions),
            delta_neutral=bool(abs(total_delta) < 0.05),
            position_details=details,
        )


# =====================================================
# 6. OPTIONS STRATEGIES
# =====================================================

@dataclass
class StrategyResult:
    """Strateji sonucu."""
    strategy: str
    max_profit: float
    max_loss: float
    breakeven: List[float]
    risk_reward: float
    description: str
    legs: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "max_profit": self.max_profit,
            "max_loss": self.max_loss,
            "breakeven": self.breakeven,
            "risk_reward": self.risk_reward,
            "description": self.description,
            "legs": self.legs,
        }


class OptionsStrategies:
    """Opsiyon strateji kütüphanesi — 9 strateji.

    Her strateji için:
    - max_profit: Maksimum kar (TL)
    - max_loss: Maksimum zarar (TL, negatif = zarar)
    - breakeven: Başabaş noktaları
    - risk_reward: Kar/zarar oranı
    - legs: Pozisyon bileşenleri
    """

    def covered_call(
        self,
        spot: float,
        call_strike: float,
        call_premium: float,
        shares: int = 100,
    ) -> StrategyResult:
        """Covered Call: hisse sahibi + call sat.

        Kullanım: Düşük volatilite, gelir elde etme.
        Risk: Hisse düşerse zarar (unlimited downside).
        Ödül: Prim + (strike - spot) kadar sınırlı upside.
        """
        max_profit = (call_strike - spot + call_premium) * shares
        # Max loss: hisse sıfıra düşerse = spot * shares - premium
        max_loss = -(spot * shares - call_premium * shares)
        breakeven = spot - call_premium
        rr = abs(max_profit / max_loss) if max_loss != 0 else 0

        return StrategyResult(
            strategy="COVERED_CALL",
            max_profit=round(max_profit, 2),
            max_loss=round(max_loss, 2),
            breakeven=[round(breakeven, 2)],
            risk_reward=round(rr, 2),
            description="Hisse sahibi + Call sat → gelir elde et, sınırlı upside, unlimited downside",
            legs=[
                {"action": "LONG", "instrument": "STOCK", "quantity": shares, "price": spot},
                {"action": "SHORT", "instrument": "CALL", "strike": call_strike, "premium": call_premium},
            ],
        )

    def protective_put(
        self,
        spot: float,
        put_strike: float,
        put_premium: float,
        shares: int = 100,
    ) -> StrategyResult:
        """Protective Put: hisse sahibi + put al.

        Kullanım: Düşüş koruması.
        Risk: Prim maliyeti.
        Ödül: Unlimited upside (prim düşülmüş).
        """
        max_loss = -(spot - put_strike + put_premium) * shares
        breakeven = spot + put_premium

        return StrategyResult(
            strategy="PROTECTIVE_PUT",
            max_profit=float("inf"),  # Unlimited upside
            max_loss=round(max_loss, 2),
            breakeven=[round(breakeven, 2)],
            risk_reward=0,  # Unlimited
            description="Hisse sahibi + Put al → düşüş koruması, unlimited upside",
            legs=[
                {"action": "LONG", "instrument": "STOCK", "quantity": shares, "price": spot},
                {"action": "LONG", "instrument": "PUT", "strike": put_strike, "premium": put_premium},
            ],
        )

    def collar(
        self,
        spot: float,
        put_strike: float,
        put_premium: float,
        call_strike: float,
        call_premium: float,
        shares: int = 100,
    ) -> StrategyResult:
        """Collar: protective put + covered call.

        Kullanım: Sınırlı risk, sınırlı ödül.
        Net maliyet = call_premium - put_premium (genellikle küçük veya negatif).
        """
        net_premium = call_premium - put_premium
        max_profit = (call_strike - spot + net_premium) * shares
        max_loss = -(spot - put_strike + net_premium) * shares
        breakeven = spot - net_premium
        rr = abs(max_profit / max_loss) if max_loss != 0 else 0

        return StrategyResult(
            strategy="COLLAR",
            max_profit=round(max_profit, 2),
            max_loss=round(max_loss, 2),
            breakeven=[round(breakeven, 2)],
            risk_reward=round(rr, 2),
            description="Protective Put + Covered Call → sınırlı risk, sınırlı ödül",
            legs=[
                {"action": "LONG", "instrument": "STOCK", "quantity": shares, "price": spot},
                {"action": "LONG", "instrument": "PUT", "strike": put_strike, "premium": put_premium},
                {"action": "SHORT", "instrument": "CALL", "strike": call_strike, "premium": call_premium},
            ],
        )

    def iron_condor(
        self,
        spot: float,
        put_sell_strike: float,
        put_buy_strike: float,
        call_sell_strike: float,
        call_buy_strike: float,
        put_sell_premium: float,
        put_buy_premium: float,
        call_sell_premium: float,
        call_buy_premium: float,
        contracts: int = 1,
        multiplier: int = 100,
    ) -> StrategyResult:
        """Iron Condor: düşük volatilite stratejisi.

        Kullanım: Dar aralıkta kalma beklentisi.
        4 bacak: short put spread + short call spread.
        Max profit = net credit. Max loss = spread width - net credit.
        """
        net_credit = ((put_sell_premium - put_buy_premium) +
                      (call_sell_premium - call_buy_premium)) * contracts * multiplier

        put_spread_width = (put_sell_strike - put_buy_strike) * contracts * multiplier
        call_spread_width = (call_buy_strike - call_sell_strike) * contracts * multiplier
        max_loss = max(put_spread_width, call_spread_width) - net_credit

        be_low = put_sell_strike - net_credit / (contracts * multiplier)
        be_high = call_sell_strike + net_credit / (contracts * multiplier)
        rr = abs(net_credit / max_loss) if max_loss > 0 else 0

        return StrategyResult(
            strategy="IRON_CONDOR",
            max_profit=round(net_credit, 2),
            max_loss=round(-max_loss, 2),
            breakeven=[round(be_low, 2), round(be_high, 2)],
            risk_reward=round(rr, 2),
            description="Düşük volatilite → dar aralıkta kalma beklentisi, 4 bacak",
            legs=[
                {"action": "LONG", "instrument": "PUT", "strike": put_buy_strike, "premium": put_buy_premium},
                {"action": "SHORT", "instrument": "PUT", "strike": put_sell_strike, "premium": put_sell_premium},
                {"action": "SHORT", "instrument": "CALL", "strike": call_sell_strike, "premium": call_sell_premium},
                {"action": "LONG", "instrument": "CALL", "strike": call_buy_strike, "premium": call_buy_premium},
            ],
        )

    def straddle(
        self,
        spot: float,
        strike: float,
        call_premium: float,
        put_premium: float,
        contracts: int = 1,
        multiplier: int = 100,
    ) -> StrategyResult:
        """Straddle: yüksek volatilite stratejisi.

        Kullanım: Büyük hareket beklentisi (yön belirsiz).
        Aynı strike'ta call + put al.
        """
        total_premium = (call_premium + put_premium) * contracts * multiplier
        breakeven_up = strike + call_premium + put_premium
        breakeven_down = strike - call_premium - put_premium

        return StrategyResult(
            strategy="STRADDLE",
            max_profit=float("inf"),  # Unlimited
            max_loss=round(-total_premium, 2),
            breakeven=[round(breakeven_down, 2), round(breakeven_up, 2)],
            risk_reward=0,  # Unlimited
            description="Yüksek volatilite → büyük hareket beklentisi (yön belirsiz)",
            legs=[
                {"action": "LONG", "instrument": "CALL", "strike": strike, "premium": call_premium},
                {"action": "LONG", "instrument": "PUT", "strike": strike, "premium": put_premium},
            ],
        )

    def strangle(
        self,
        spot: float,
        put_strike: float,
        call_strike: float,
        put_premium: float,
        call_premium: float,
        contracts: int = 1,
        multiplier: int = 100,
    ) -> StrategyResult:
        """Strangle: straddle'dan daha ucuz.

        Kullanım: Çok büyük hareket beklentisi.
        Farklı strike'larda call + put al.
        """
        total_premium = (call_premium + put_premium) * contracts * multiplier
        breakeven_up = call_strike + call_premium + put_premium
        breakeven_down = put_strike - call_premium - put_premium

        return StrategyResult(
            strategy="STRANGLE",
            max_profit=float("inf"),
            max_loss=round(-total_premium, 2),
            breakeven=[round(breakeven_down, 2), round(breakeven_up, 2)],
            risk_reward=0,
            description="Straddle'dan daha ucuz → çok büyük hareket beklentisi",
            legs=[
                {"action": "LONG", "instrument": "PUT", "strike": put_strike, "premium": put_premium},
                {"action": "LONG", "instrument": "CALL", "strike": call_strike, "premium": call_premium},
            ],
        )

    def bull_call_spread(
        self,
        buy_strike: float,
        sell_strike: float,
        buy_premium: float,
        sell_premium: float,
        contracts: int = 1,
        multiplier: int = 100,
    ) -> StrategyResult:
        """Bull Call Spread: yükseliş beklentisi.

        Kullanım: Orta düzey yükseliş beklentisi.
        Düşük strike'ta call al, yüksek strike'ta call sat.
        """
        net_debit = (buy_premium - sell_premium) * contracts * multiplier
        max_profit = (sell_strike - buy_strike) * contracts * multiplier - net_debit
        breakeven = buy_strike + net_debit / (contracts * multiplier)
        rr = abs(max_profit / net_debit) if net_debit > 0 else 0

        return StrategyResult(
            strategy="BULL_CALL_SPREAD",
            max_profit=round(max_profit, 2),
            max_loss=round(-net_debit, 2),
            breakeven=[round(breakeven, 2)],
            risk_reward=round(rr, 2),
            description="Yükseliş beklentisi → sınırlı risk, sınırlı ödül",
            legs=[
                {"action": "LONG", "instrument": "CALL", "strike": buy_strike, "premium": buy_premium},
                {"action": "SHORT", "instrument": "CALL", "strike": sell_strike, "premium": sell_premium},
            ],
        )

    def bear_put_spread(
        self,
        buy_strike: float,
        sell_strike: float,
        buy_premium: float,
        sell_premium: float,
        contracts: int = 1,
        multiplier: int = 100,
    ) -> StrategyResult:
        """Bear Put Spread: düşüş beklentisi.

        Kullanım: Orta düzey düşüş beklentisi.
        Yüksek strike'ta put al, düşük strike'ta put sat.
        """
        net_debit = (buy_premium - sell_premium) * contracts * multiplier
        max_profit = (buy_strike - sell_strike) * contracts * multiplier - net_debit
        breakeven = buy_strike - net_debit / (contracts * multiplier)
        rr = abs(max_profit / net_debit) if net_debit > 0 else 0

        return StrategyResult(
            strategy="BEAR_PUT_SPREAD",
            max_profit=round(max_profit, 2),
            max_loss=round(-net_debit, 2),
            breakeven=[round(breakeven, 2)],
            risk_reward=round(rr, 2),
            description="Düşüş beklentisi → sınırlı risk, sınırlı ödül",
            legs=[
                {"action": "LONG", "instrument": "PUT", "strike": buy_strike, "premium": buy_premium},
                {"action": "SHORT", "instrument": "PUT", "strike": sell_strike, "premium": sell_premium},
            ],
        )

    def butterfly(
        self,
        lower_strike: float,
        middle_strike: float,
        upper_strike: float,
        lower_premium: float,
        middle_premium: float,
        upper_premium: float,
        contracts: int = 1,
        multiplier: int = 100,
    ) -> StrategyResult:
        """Butterfly: dar aralık beklentisi.

        Kullanım: Fiyatın belirli bir seviyede kalma beklentisi.
        3 strike: low (1 long), mid (2 short), upper (1 long).
        """
        net_debit = (lower_premium - 2 * middle_premium + upper_premium) * contracts * multiplier
        max_profit = (middle_strike - lower_strike) * contracts * multiplier - net_debit
        be_low = lower_strike + net_debit / (contracts * multiplier)
        be_high = upper_strike - net_debit / (contracts * multiplier)
        rr = abs(max_profit / net_debit) if net_debit > 0 else 0

        return StrategyResult(
            strategy="BUTTERFLY",
            max_profit=round(max_profit, 2),
            max_loss=round(-net_debit, 2),
            breakeven=[round(be_low, 2), round(be_high, 2)],
            risk_reward=round(rr, 2),
            description="Dar aralık beklentisi → düşük risk, sınırlı ödül",
            legs=[
                {"action": "LONG", "instrument": "CALL", "strike": lower_strike, "premium": lower_premium},
                {"action": "SHORT", "instrument": "CALL", "strike": middle_strike, "premium": middle_premium, "quantity": 2},
                {"action": "LONG", "instrument": "CALL", "strike": upper_strike, "premium": upper_premium},
            ],
        )


# =====================================================
# 7. DYNAMIC DELTA HEDGING
# =====================================================

@dataclass
class DeltaHedgeResult:
    """Delta hedge sonucu."""
    current_delta: float
    target_delta: float
    delta_gap: float
    contracts_needed: int
    hedge_instrument: str
    action: str  # "BUY", "SELL", "NONE"
    estimated_cost: float
    contract_multiplier: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_delta": self.current_delta,
            "target_delta": self.target_delta,
            "delta_gap": self.delta_gap,
            "contracts_needed": self.contracts_needed,
            "hedge_instrument": self.hedge_instrument,
            "action": self.action,
            "estimated_cost": self.estimated_cost,
        }


class DeltaHedger:
    """Dynamic delta hedging.

    Options pozisyonlarında delta riskini yönetir.
    BIST-30 futures için contract_multiplier = endeks * 10.
    """

    def hedge(
        self,
        portfolio_delta: float,
        spot_price: float,
        futures_price: float = 0,
        contract_multiplier: float = 100,
        hedge_instrument: str = "futures",
    ) -> DeltaHedgeResult:
        """Delta hedge pozisyonu öner.

        Args:
            portfolio_delta: Mevcut portföy delta (hisse cinsinden, ör. 150 = 150 hisse delta)
            spot_price: Dayanak fiyat
            futures_price: Futures fiyatı (komisyon hesabı için)
            contract_multiplier: Sözleşme çarpanı (BIST-30: endeks * 10)
            hedge_instrument: "futures" veya "options"

        Returns:
            DeltaHedgeResult
        """
        target_delta = 0.0  # Delta neutral
        delta_gap = target_delta - portfolio_delta

        if hedge_instrument == "futures":
            # Futures delta = 1, gap'i sözleşme sayısına çevir
            contracts_needed = int(round(delta_gap / contract_multiplier))
        else:
            # ATM call delta ≈ 0.5
            contracts_needed = int(round(delta_gap / (0.5 * contract_multiplier)))

        if contracts_needed > 0:
            action = "BUY"
        elif contracts_needed < 0:
            action = "SELL"
        else:
            action = "NONE"

        # Komisyon tahmini: %0.1
        cost = abs(contracts_needed) * abs(futures_price or spot_price) * contract_multiplier * 0.001

        return DeltaHedgeResult(
            current_delta=round(portfolio_delta, 4),
            target_delta=target_delta,
            delta_gap=round(delta_gap, 4),
            contracts_needed=contracts_needed,
            hedge_instrument=hedge_instrument,
            action=action,
            estimated_cost=round(cost, 2),
            contract_multiplier=contract_multiplier,
        )

    def gamma_scalp(
        self,
        portfolio_gamma: float,
        spot_price: float,
        price_move_pct: float,
        contract_multiplier: float = 100,
    ) -> Dict[str, Any]:
        """Gamma scalping — delta hedge P&L hesabı.

        Gamma pozitif portföyde (long options), fiyat hareketinden kar edilir.
        P&L = 0.5 × Γ × (ΔS)² × multiplier

        Args:
            portfolio_gamma: Portföy toplam gamma
            spot_price: Dayanak fiyat
            price_move_pct: Fiyat hareketi yüzdesi (ör. 3.0 = %3)
            contract_multiplier: Sözleşme çarpanı

        Returns:
            {"gamma_pnl", "price_move_pct", "delta_s"}
        """
        delta_s = spot_price * price_move_pct / 100.0
        # Gamma P&L = 0.5 × Γ × (ΔS)²
        gamma_pnl = 0.5 * portfolio_gamma * (delta_s ** 2)

        return {
            "gamma_pnl": round(gamma_pnl, 2),
            "price_move_pct": price_move_pct,
            "delta_s": round(delta_s, 2),
            "description": "Long gamma: fiyat hareketinden delta hedge P&L",
        }


# =====================================================
# 8. SPAN MARGIN CALCULATOR
# =====================================================

class SPANMarginCalculator:
    """SPAN teminat hesaplama (16 senaryo).

    BIST SPAN modeline uygun senaryo bazlı teminat hesabı.
    Her senaryo için fiyat ve volatilite kombinasyonu ile P&L hesaplanır,
    en kötü senaryo teminat olarak alınır.
    """

    # 16 SPAN senaryosu (fiyat değişimi, volatilite değişimi)
    SCENARIOS = [
        {"price_change": 0.0, "vol_change": 0.0},       # 1: Base
        {"price_change": 0.03, "vol_change": 0.0},       # 2: +3%
        {"price_change": -0.03, "vol_change": 0.0},      # 3: -3%
        {"price_change": 0.03, "vol_change": 0.02},      # 4: +3% + vol up
        {"price_change": -0.03, "vol_change": 0.02},     # 5: -3% + vol up
        {"price_change": 0.06, "vol_change": 0.0},       # 6: +6%
        {"price_change": -0.06, "vol_change": 0.0},      # 7: -6%
        {"price_change": 0.06, "vol_change": 0.04},      # 8: +6% + vol up
        {"price_change": -0.06, "vol_change": 0.04},     # 9: -6% + vol up
        {"price_change": 0.10, "vol_change": 0.0},       # 10: +10%
        {"price_change": -0.10, "vol_change": 0.0},      # 11: -10%
        {"price_change": 0.10, "vol_change": 0.06},      # 12: +10% + vol up
        {"price_change": -0.10, "vol_change": 0.06},     # 13: -10% + vol up
        {"price_change": 0.15, "vol_change": 0.0},       # 14: +15%
        {"price_change": -0.15, "vol_change": 0.0},      # 15: -15%
        {"price_change": 0.0, "vol_change": 0.08},       # 16: Vol up only
    ]

    def calculate(self, positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """SPAN teminat hesapla.

        Args:
            positions: Pozisyon listesi
                [{"ticker", "value", "delta", "gamma", "vega", "sigma", "spot_price"}]
                - value: Pozisyonun notional değeri
                - delta: Pozisyon delta (1.0 = long futures)
                - gamma: Pozisyon gamma (opsiyon)
                - vega: Pozisyon vega (opsiyon)
                - sigma: Volatilite (opsiyon)
                - spot_price: Dayanak fiyat (gamma/vega için)

        Returns:
            {"total_margin", "position_margins", "scenarios_tested"}
        """
        total_margin = 0.0
        position_margins = []

        for pos in positions:
            worst_loss = 0.0
            scenario_pnls = []

            for scenario in self.SCENARIOS:
                pnl = self._calculate_scenario_pnl(pos, scenario)
                worst_loss = min(worst_loss, pnl)
                scenario_pnls.append(round(pnl, 2))

            margin = abs(worst_loss)
            total_margin += margin

            position_margins.append({
                "ticker": pos.get("ticker", ""),
                "margin": round(margin, 2),
                "worst_scenario_loss": round(worst_loss, 2),
                "scenario_pnls": scenario_pnls,
            })

        return {
            "total_margin": round(total_margin, 2),
            "position_margins": position_margins,
            "scenarios_tested": len(self.SCENARIOS),
        }

    def _calculate_scenario_pnl(self, position: Dict, scenario: Dict) -> float:
        """Tek senaryo için P&L hesaplama.

        Delta P&L: value × delta × price_change
        Gamma P&L: 0.5 × gamma × (ΔS)²  [ΔS = price_change × spot_price]
        Vega P&L:  vega × vol_change      [vega zaten %1 cinsinden]
        """
        value = position.get("value", 0)
        delta = position.get("delta", 1.0)
        gamma = position.get("gamma", 0)
        vega = position.get("vega", 0)
        spot_price = position.get("spot_price", value)  # Spot yoksa value kullan

        # Delta P&L
        delta_pnl = value * delta * scenario["price_change"]

        # Gamma P&L: 0.5 × Γ × (ΔS)²
        delta_s = spot_price * scenario["price_change"]
        gamma_pnl = 0.5 * gamma * (delta_s ** 2)

        # Vega P&L: vega × vol_change (vega zaten /100 cinsinden)
        vega_pnl = vega * scenario["vol_change"] * 100

        return delta_pnl + gamma_pnl + vega_pnl


# =====================================================
# 9. FUTURES-SPOT ARBITRAGE
# =====================================================

@dataclass
class ArbitrageResult:
    """Arbitrage sonucu."""
    spot_price: float
    futures_price: float
    theoretical_futures: float
    basis: float
    fair_basis: float
    basis_diff: float
    basis_pct: float
    arbitrage_opportunity: bool
    strategy: str
    estimated_profit: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "spot_price": self.spot_price,
            "futures_price": self.futures_price,
            "theoretical_futures": self.theoretical_futures,
            "basis": self.basis,
            "fair_basis": self.fair_basis,
            "basis_diff": self.basis_diff,
            "basis_pct": self.basis_pct,
            "arbitrage_opportunity": self.arbitrage_opportunity,
            "strategy": self.strategy,
            "estimated_profit": self.estimated_profit,
        }


class FuturesSpotArbitrage:
    """Futures-spot arbitraj tespiti.

    Cost-of-carry modeli: F = S × e^((r-q)×T)
    Basis = F - S, Fair Basis = S × (e^((r-q)×T) - 1)
    """

    def analyze(
        self,
        spot_price: float,
        futures_price: float,
        risk_free_rate: float = 0.15,
        dividend_yield: float = 0.02,
        time_to_expiry: float = 0.25,
        contract_multiplier: float = 100,
        threshold_pct: float = 0.5,
    ) -> ArbitrageResult:
        """Futures-spot basis analizi.

        Args:
            spot_price: Spot fiyat
            futures_price: Futures fiyatı
            risk_free_rate: Risksiz faiz
            dividend_yield: Temettü verimi
            time_to_expiry: Vadeye kalan süre (yıl)
            contract_multiplier: Sözleşme çarpanı
            threshold_pct: Arbitraj eşiği (%)

        Returns:
            ArbitrageResult
        """
        # Teorik futures = S × e^((r-q)×T)
        theoretical = spot_price * np.exp((risk_free_rate - dividend_yield) * time_to_expiry)

        basis = futures_price - spot_price
        fair_basis = theoretical - spot_price
        basis_diff = basis - fair_basis
        basis_pct = (basis_diff / spot_price * 100) if spot_price > 0 else 0

        arbitrage_opportunity = abs(basis_pct) > threshold_pct

        if basis_diff > threshold_pct / 100 * spot_price:
            strategy = "SELL_FUTURES_BUY_SPOT"
            estimated_profit = abs(basis_diff) * contract_multiplier
        elif basis_diff < -threshold_pct / 100 * spot_price:
            strategy = "BUY_FUTURES_SELL_SPOT"
            estimated_profit = abs(basis_diff) * contract_multiplier
        else:
            strategy = "NO_ARBITRAGE"
            estimated_profit = 0.0

        return ArbitrageResult(
            spot_price=spot_price,
            futures_price=futures_price,
            theoretical_futures=round(theoretical, 2),
            basis=round(basis, 2),
            fair_basis=round(fair_basis, 2),
            basis_diff=round(basis_diff, 2),
            basis_pct=round(basis_pct, 4),
            arbitrage_opportunity=arbitrage_opportunity,
            strategy=strategy,
            estimated_profit=round(estimated_profit, 2),
        )


# =====================================================
# 10. PUT-CALL PARITY
# =====================================================

def check_put_call_parity(
    call_price: float,
    put_price: float,
    spot_price: float,
    strike: float,
    r: float,
    T: float,
    tolerance: float = 0.01,
    arbitrage_threshold: float = 0.05,
) -> Dict[str, Any]:
    """Put-Call Parity kontrolü.

    C - P = S - K × e^(-rT)

    Args:
        call_price: Call opsiyon fiyatı
        put_price: Put opsiyon fiyatı
        spot_price: Dayanak fiyat
        strike: Kullanım fiyatı
        r: Risksiz faiz
        T: Vade (yıl)
        tolerance: Parity toleransı
        arbitrage_threshold: Arbitraj eşiği

    Returns:
        {"parity_holds", "deviation", "arbitrage_opportunity", "theoretical_diff", "actual_diff"}
    """
    theoretical_diff = spot_price - strike * np.exp(-r * T)
    actual_diff = call_price - put_price
    deviation = actual_diff - theoretical_diff

    return {
        "parity_holds": bool(abs(deviation) < tolerance),
        "deviation": round(deviation, 4),
        "arbitrage_opportunity": bool(abs(deviation) > arbitrage_threshold),
        "theoretical_diff": round(theoretical_diff, 4),
        "actual_diff": round(actual_diff, 4),
        "strategy": "BUY_PUT_SELL_CALL" if deviation > arbitrage_threshold else
                    "BUY_CALL_SELL_PUT" if deviation < -arbitrage_threshold else "NONE",
    }


# =====================================================
# 11. VIOP RISK INTEGRATION
# =====================================================

class VIOPRiskCalculator:
    """VIOP pozisyonları için risk hesaplama.

    Portföydeki VIOP pozisyonlarının risk metriklerini hesaplar.
    """

    def calculate_portfolio_viop_risk(
        self,
        viop_positions: List[Dict[str, Any]],
        portfolio_value: float,
    ) -> Dict[str, Any]:
        """VIOP pozisyonları için toplam risk hesabı.

        Args:
            viop_positions: VIOP pozisyon listesi
                [{"ticker", "type" (futures/options), "side" (long/short),
                  "quantity", "entry_price", "current_price", "delta", "gamma",
                  "vega", "contract_multiplier"}]
            portfolio_value: Toplam portföy değeri

        Returns:
            Risk metrikleri
        """
        total_delta_exposure = 0.0
        total_gamma_exposure = 0.0
        total_vega_exposure = 0.0
        total_notional = 0.0
        total_pnl = 0.0
        position_risks = []

        for pos in viop_positions:
            ticker = pos.get("ticker", "")
            pos_type = pos.get("type", "futures")
            side = pos.get("side", "long")
            quantity = pos.get("quantity", 0)
            entry_price = pos.get("entry_price", 0)
            current_price = pos.get("current_price", 0)
            delta = pos.get("delta", 1.0 if pos_type == "futures" else 0.5)
            gamma = pos.get("gamma", 0)
            vega = pos.get("vega", 0)
            multiplier = pos.get("contract_multiplier", 100)

            # Side'a göre yön
            direction = 1 if side == "long" else -1

            # Notional
            notional = quantity * current_price * multiplier
            total_notional += notional * direction

            # P&L
            pnl = quantity * (current_price - entry_price) * multiplier * direction
            total_pnl += pnl

            # Delta exposure (hisse eşdeğeri)
            delta_exposure = quantity * delta * multiplier * direction
            total_delta_exposure += delta_exposure

            # Gamma exposure
            gamma_exposure = quantity * gamma * multiplier * direction
            total_gamma_exposure += gamma_exposure

            # Vega exposure
            vega_exposure = quantity * vega * multiplier * direction
            total_vega_exposure += vega_exposure

            position_risks.append({
                "ticker": ticker,
                "type": pos_type,
                "side": side,
                "quantity": quantity,
                "notional": round(notional, 2),
                "pnl": round(pnl, 2),
                "delta_exposure": round(delta_exposure, 2),
            })

        # Portföy bazlı risk metrikleri
        delta_pct = (total_delta_exposure / portfolio_value * 100) if portfolio_value > 0 else 0
        notional_pct = (abs(total_notional) / portfolio_value * 100) if portfolio_value > 0 else 0

        return {
            "total_delta_exposure": round(total_delta_exposure, 2),
            "total_gamma_exposure": round(total_gamma_exposure, 4),
            "total_vega_exposure": round(total_vega_exposure, 2),
            "total_notional": round(total_notional, 2),
            "total_pnl": round(total_pnl, 2),
            "delta_exposure_pct": round(delta_pct, 2),
            "notional_exposure_pct": round(notional_pct, 2),
            "n_positions": len(viop_positions),
            "position_risks": position_risks,
            "risk_flags": self._generate_risk_flags(delta_pct, notional_pct, total_gamma_exposure),
        }

    def _generate_risk_flags(self, delta_pct: float, notional_pct: float,
                              gamma_exposure: float) -> List[str]:
        """Risk bayrakları üret."""
        flags = []

        if abs(delta_pct) > 20:
            flags.append(f"HIGH_DELTA_EXPOSURE: {delta_pct:.1f}%")
        if notional_pct > 50:
            flags.append(f"HIGH_NOTIONAL_EXPOSURE: {notional_pct:.1f}%")
        if abs(gamma_exposure) > 1000:
            flags.append(f"HIGH_GAMMA_EXPOSURE: {gamma_exposure:.0f}")

        return flags

    def calculate_margin_requirement(
        self,
        viop_positions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """VIOP pozisyonları için toplam teminat hesabı.

        Args:
            viop_positions: VIOP pozisyon listesi

        Returns:
            {"total_margin", "position_margins"}
        """
        margin_calc = SPANMarginCalculator()

        span_positions = []
        for pos in viop_positions:
            multiplier = pos.get("contract_multiplier", 100)
            notional = pos.get("quantity", 0) * pos.get("current_price", 0) * multiplier

            span_positions.append({
                "ticker": pos.get("ticker", ""),
                "value": notional,
                "delta": pos.get("delta", 1.0),
                "gamma": pos.get("gamma", 0),
                "vega": pos.get("vega", 0),
                "spot_price": pos.get("current_price", 0),
            })

        return margin_calc.calculate(span_positions)


# =====================================================
# 12. OPTIONS BACKTEST ENGINE
# =====================================================

@dataclass
class BacktestTrade:
    """Tek backtest işlemi."""
    entry_date: date
    exit_date: Optional[date]
    strategy: str
    spot_price: float
    entry_premium: float
    exit_premium: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    holding_days: int = 0
    legs: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class BacktestResult:
    """Backtest sonucu."""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    avg_pnl: float
    max_profit: float
    max_loss: float
    avg_holding_days: float
    profit_factor: float
    trades: List[BacktestTrade]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "total_pnl": round(self.total_pnl, 2),
            "avg_pnl": round(self.avg_pnl, 2),
            "max_profit": round(self.max_profit, 2),
            "max_loss": round(self.max_loss, 2),
            "avg_holding_days": round(self.avg_holding_days, 1),
            "profit_factor": round(self.profit_factor, 2),
        }


class OptionsBacktestEngine:
    """Opsiyon strateji backtest motoru.

    Basit ama doğru backtest:
    - Strateji seçimi
    - Entry/exit kuralları
    - Greeks-based P&L
    """

    def __init__(self, strategies: OptionsStrategies = None):
        self.strategies = strategies or OptionsStrategies()

    def backtest_covered_call(
        self,
        price_series: List[Dict[str, Any]],
        strike_pct: float = 1.05,  # %5 OTM
        premium_pct: float = 0.02,  # Spot'un %2'si premium
        holding_days: int = 30,
    ) -> BacktestResult:
        """Covered call backtest.

        Args:
            price_series: [{"date", "close"}]
            strike_pct: Strike = spot × strike_pct
            premium_pct: Premium = spot × premium_pct
            holding_days: Pozisyon süresi

        Returns:
            BacktestResult
        """
        trades = []
        i = 0

        while i < len(price_series):
            entry = price_series[i]
            entry_price = entry["close"]
            entry_date = entry["date"]

            # Strike ve premium
            strike = entry_price * strike_pct
            premium = entry_price * premium_pct

            # Exit bul
            exit_idx = min(i + holding_days, len(price_series) - 1)
            exit_price = price_series[exit_idx]["close"]
            exit_date = price_series[exit_idx]["date"]

            # Covered call P&L
            # Hisse P&L = exit - entry
            # Call P&L = premium - max(exit - strike, 0)
            stock_pnl = exit_price - entry_price
            call_pnl = premium - max(exit_price - strike, 0)
            total_pnl = stock_pnl + call_pnl
            pnl_pct = (total_pnl / entry_price) * 100

            trades.append(BacktestTrade(
                entry_date=entry_date,
                exit_date=exit_date,
                strategy="COVERED_CALL",
                spot_price=entry_price,
                entry_premium=premium,
                exit_premium=0,
                pnl=round(total_pnl, 2),
                pnl_pct=round(pnl_pct, 2),
                holding_days=(exit_date - entry_date).days if isinstance(exit_date, date) else holding_days,
            ))

            i = exit_idx + 1

        return self._summarize_trades(trades)

    def backtest_iron_condor(
        self,
        price_series: List[Dict[str, Any]],
        width_pct: float = 0.05,  # %5 spread width
        premium_pct: float = 0.015,  # %1.5 net credit
        holding_days: int = 30,
    ) -> BacktestResult:
        """Iron condor backtest.

        Args:
            price_series: [{"date", "close"}]
            width_pct: Spread genişliği (spot'un %'si)
            premium_pct: Net credit (spot'un %'si)
            holding_days: Pozisyon süresi

        Returns:
            BacktestResult
        """
        trades = []
        i = 0

        while i < len(price_series):
            entry = price_series[i]
            entry_price = entry["close"]
            entry_date = entry["date"]

            # Iron condor parametreleri
            put_sell = entry_price * (1 - width_pct)
            put_buy = entry_price * (1 - 2 * width_pct)
            call_sell = entry_price * (1 + width_pct)
            call_buy = entry_price * (1 + 2 * width_pct)
            net_credit = entry_price * premium_pct

            # Exit
            exit_idx = min(i + holding_days, len(price_series) - 1)
            exit_price = price_series[exit_idx]["close"]
            exit_date = price_series[exit_idx]["date"]

            # Iron condor P&L
            # Max profit = net_credit (fiyat aralıkta kalırsa)
            # Max loss = spread_width - net_credit
            if put_buy <= exit_price <= call_buy:
                # Aralıkta → max profit
                pnl = net_credit
            elif exit_price < put_buy or exit_price > call_buy:
                # Aralığın dışında → max loss
                spread_width = entry_price * width_pct
                pnl = -(spread_width - net_credit)
            elif exit_price < put_sell:
                # Put spread'te kısmi kayıp
                pnl = net_credit - (put_sell - exit_price)
            elif exit_price > call_sell:
                # Call spread'te kısmi kayıp
                pnl = net_credit - (exit_price - call_sell)
            else:
                pnl = net_credit

            pnl_pct = (pnl / entry_price) * 100

            trades.append(BacktestTrade(
                entry_date=entry_date,
                exit_date=exit_date,
                strategy="IRON_CONDOR",
                spot_price=entry_price,
                entry_premium=net_credit,
                pnl=round(pnl, 2),
                pnl_pct=round(pnl_pct, 2),
                holding_days=(exit_date - entry_date).days if isinstance(exit_date, date) else holding_days,
            ))

            i = exit_idx + 1

        return self._summarize_trades(trades)

    def _summarize_trades(self, trades: List[BacktestTrade]) -> BacktestResult:
        """İşlemleri özetle."""
        if not trades:
            return BacktestResult(
                total_trades=0, winning_trades=0, losing_trades=0,
                win_rate=0, total_pnl=0, avg_pnl=0,
                max_profit=0, max_loss=0, avg_holding_days=0,
                profit_factor=0, trades=[],
            )

        winning = [t for t in trades if t.pnl > 0]
        losing = [t for t in trades if t.pnl < 0]

        total_pnl = sum(t.pnl for t in trades)
        gross_profit = sum(t.pnl for t in winning) if winning else 0
        gross_loss = abs(sum(t.pnl for t in losing)) if losing else 1
        avg_holding = sum(t.holding_days for t in trades) / len(trades)

        return BacktestResult(
            total_trades=len(trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate=round(len(winning) / len(trades) * 100, 1) if trades else 0,
            total_pnl=round(total_pnl, 2),
            avg_pnl=round(total_pnl / len(trades), 2) if trades else 0,
            max_profit=round(max(t.pnl for t in trades), 2) if trades else 0,
            max_loss=round(min(t.pnl for t in trades), 2) if trades else 0,
            avg_holding_days=round(avg_holding, 1),
            profit_factor=round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf"),
            trades=trades,
        )


# =====================================================
# 13. SINGLETON INSTANCES
# =====================================================

implied_volatility = ImpliedVolatility()
portfolio_greeks = PortfolioGreeks()
options_strategies = OptionsStrategies()
delta_hedger = DeltaHedger()
span_margin = SPANMarginCalculator()
futures_spot_arbitrage = FuturesSpotArbitrage()
viop_risk = VIOPRiskCalculator()
options_backtest = OptionsBacktestEngine()
