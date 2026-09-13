"""
ALPHA BIST — Takasbank SPAN & Portföy Teminat Motoru v3.0

BIST VIOP ve Takasbank standartlarına uygun kurumsal portföy teminat mimarisi:
- 16 Farklı Fiyat ve Volatilite SPAN Risk Senaryosu (Scan Range Risk Array)
- Vadeler Arası (Inter-Month) ve Ürünler Arası (Inter-Commodity) Spread İndirimi
- Kısa Opsiyon Minimum Teminatı (Short Option Minimum Charge)
- Delta-Bazlı Netleştirme ve Aşırı Risk Senaryo Analizi (Extreme Move Scenarios)
- Nakit ve Teminat Karşılama Oranı (Margin Coverage Ratio & Margin Call Trigger)
"""

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np
import structlog

from .enhanced_options import SPANMarginCalculator, span_margin

logger = structlog.get_logger(__name__)


class PositionType(StrEnum):
    """Pozisyon yönü."""
    LONG = "LONG"
    SHORT = "SHORT"


class InstrumentType(StrEnum):
    """Finansal enstrüman tipi."""
    FUTURES = "FUTURES"
    OPTION_CALL = "OPTION_CALL"
    OPTION_PUT = "OPTION_PUT"
    EQUITY_SPOT = "EQUITY_SPOT"


@dataclass
class MarginScenarioSpec:
    """Tek bir SPAN senaryo tanımı."""
    scenario_id: int
    name: str
    price_change_pct: float
    vol_change_pts: float
    weight: float = 1.0


@dataclass
class PositionRiskDetail:
    """Pozisyon seviyesinde detaylı teminat ve senaryo dökümü."""
    symbol: str
    instrument_type: str
    position_type: str
    contracts: int
    notional_value: float
    spot_price: float
    delta: float
    gamma: float
    vega: float
    initial_margin_rate: float
    standalone_margin: float
    short_option_min_charge: float
    worst_scenario_loss: float
    scenario_pnls: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return asdict(self)


@dataclass
class PortfolioSpanMarginResult:
    """SPAN Portföy teminat hesaplama çıktısı."""
    total_margin_requirement: float
    gross_scan_risk: float
    inter_month_spread_charge: float
    inter_commodity_credit: float
    short_option_minimum_total: float
    cash_balance: float
    available_margin: float
    margin_call_triggered: bool
    scenarios_tested_count: int
    worst_scenario_id: int
    worst_scenario_name: str
    position_margins: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return asdict(self)


class BISTSPANMarginEngine:
    """Takasbank SPAN Portföy Teminat Motoru."""

    # Takasbank ve Borsa İstanbul için 16 senaryo dizilimi
    DEFAULT_SPAN_SCENARIOS: list[MarginScenarioSpec] = [
        MarginScenarioSpec(1, "Temel Durum (Nötr)", 0.0, 0.0, weight=1.0),
        MarginScenarioSpec(2, "Fiyat +%3, Vol Sabit", 0.03, 0.0, weight=1.0),
        MarginScenarioSpec(3, "Fiyat -%3, Vol Sabit", -0.03, 0.0, weight=1.0),
        MarginScenarioSpec(4, "Fiyat +%3, Vol +2 Puan", 0.03, 0.02, weight=1.0),
        MarginScenarioSpec(5, "Fiyat -%3, Vol +2 Puan", -0.03, 0.02, weight=1.0),
        MarginScenarioSpec(6, "Fiyat +%6, Vol Sabit", 0.06, 0.0, weight=1.0),
        MarginScenarioSpec(7, "Fiyat -%6, Vol Sabit", -0.06, 0.0, weight=1.0),
        MarginScenarioSpec(8, "Fiyat +%6, Vol +4 Puan", 0.06, 0.04, weight=1.0),
        MarginScenarioSpec(9, "Fiyat -%6, Vol +4 Puan", -0.06, 0.04, weight=1.0),
        MarginScenarioSpec(10, "Fiyat +%10, Vol Sabit", 0.10, 0.0, weight=1.0),
        MarginScenarioSpec(11, "Fiyat -%10, Vol Sabit", -0.10, 0.0, weight=1.0),
        MarginScenarioSpec(12, "Fiyat +%10, Vol +6 Puan", 0.10, 0.06, weight=1.0),
        MarginScenarioSpec(13, "Fiyat -%10, Vol +6 Puan", -0.10, 0.06, weight=1.0),
        MarginScenarioSpec(14, "Ekstrem Şok Yukarı (+%15)", 0.15, 0.0, weight=0.35),
        MarginScenarioSpec(15, "Ekstrem Şok Aşağı (-%15)", -0.15, 0.0, weight=0.35),
        MarginScenarioSpec(16, "Volatilite Şoku (Vol +8 Puan)", 0.0, 0.08, weight=1.0),
    ]

    def __init__(
        self,
        scenarios: list[MarginScenarioSpec] | None = None,
        inter_commodity_offset_rate: float = 0.40,
        inter_month_spread_rate: float = 0.05,
    ) -> None:
        """Motor başlatıcısı."""
        self.scenarios = scenarios or self.DEFAULT_SPAN_SCENARIOS
        self.inter_commodity_offset_rate = inter_commodity_offset_rate
        self.inter_month_spread_rate = inter_month_spread_rate

    def __repr__(self) -> str:
        return f"BISTSPANMarginEngine(scenarios={len(self.scenarios)}, offset={self.inter_commodity_offset_rate})"

    def calculate_margin(
        self,
        positions: list[dict[str, Any]],
        cash_balance: float = 0.0,
    ) -> PortfolioSpanMarginResult:
        """Tüm portföyün Takasbank SPAN 16 senaryolu teminat yükümlülüğünü hesaplar.

        Args:
            positions: Pozisyon sözlükleri listesi.
            cash_balance: Mevcut nakit/teminat tutarı (TL).

        Returns:
            PortfolioSpanMarginResult: Detaylı teminat gereksinimi ve margin call raporu.
        """
        if not positions:
            return PortfolioSpanMarginResult(
                total_margin_requirement=0.0,
                gross_scan_risk=0.0,
                inter_month_spread_charge=0.0,
                inter_commodity_credit=0.0,
                short_option_minimum_total=0.0,
                cash_balance=cash_balance,
                available_margin=cash_balance,
                margin_call_triggered=False,
                scenarios_tested_count=len(self.scenarios),
                worst_scenario_id=1,
                worst_scenario_name="Temel Durum",
                position_margins=[],
            )

        position_details: list[PositionRiskDetail] = []
        portfolio_scenario_pnls = [0.0] * len(self.scenarios)
        short_option_min_total = 0.0

        for pos in positions:
            symbol = str(pos.get("ticker") or pos.get("symbol") or "BIST_INSTRUMENT")
            value = float(pos.get("value", 0.0))
            spot = float(pos.get("spot_price", pos.get("underlying_value", value)))
            pos_type = str(pos.get("position_type", "LONG")).upper()
            is_opt = bool(pos.get("is_option", False))
            contracts = int(pos.get("contracts", 1))
            margin_rate = float(pos.get("margin_rate", 0.15))
            opt_type = str(pos.get("option_type") or "").upper()

            if is_opt:
                inst_type = InstrumentType.OPTION_CALL if "CALL" in opt_type else InstrumentType.OPTION_PUT
                delta = float(pos.get("delta", 0.5 if "CALL" in opt_type else -0.5))
            else:
                inst_type = InstrumentType.FUTURES
                delta = 1.0 if pos_type == "LONG" else -1.0

            gamma = float(pos.get("gamma", 0.0))
            vega = float(pos.get("vega", 0.0))

            # Pozisyon bazında 16 senaryoyu test et
            pnl_series: list[float] = []
            for sc in self.scenarios:
                p_chg = sc.price_change_pct
                v_chg = sc.vol_change_pts

                # Delta P&L: Value * Delta * Price Change
                delta_pnl = value * delta * p_chg
                # Gamma P&L: 0.5 * Gamma * (Delta S)^2
                delta_s = spot * p_chg
                gamma_pnl = 0.5 * gamma * (delta_s**2)
                # Vega P&L: Vega * Volatility Change Points * 100
                vega_pnl = vega * v_chg * 100.0

                pnl = (delta_pnl + gamma_pnl + vega_pnl) * sc.weight
                pnl_series.append(pnl)

            worst_pnl = min(pnl_series)
            worst_loss = abs(min(0.0, worst_pnl))

            # Kısa opsiyon minimum koruma marjı
            short_opt_charge = 0.0
            if is_opt and pos_type == "SHORT":
                premium = float(pos.get("premium", value))
                short_opt_charge = max(0.0, premium + (0.15 * spot * abs(contracts)))
                short_option_min_total += short_opt_charge

            # Standart vadeli / opsiyon standalone margin
            standalone = max(worst_loss, value * margin_rate)

            pos_detail = PositionRiskDetail(
                symbol=symbol,
                instrument_type=inst_type.value,
                position_type=pos_type,
                contracts=contracts,
                notional_value=round(value, 2),
                spot_price=round(spot, 2),
                delta=round(delta, 4),
                gamma=round(gamma, 6),
                vega=round(vega, 4),
                initial_margin_rate=margin_rate,
                standalone_margin=round(standalone, 2),
                short_option_min_charge=round(short_opt_charge, 2),
                worst_scenario_loss=round(worst_loss, 2),
                scenario_pnls=[round(p, 2) for p in pnl_series],
            )
            position_details.append(pos_detail)

            # Portföy seviyesinde senaryo toplamı
            for i, p in enumerate(pnl_series):
                portfolio_scenario_pnls[i] += p

        # Portföyün en kötü senaryosu (Scanning Risk)
        min_portfolio_pnl = min(portfolio_scenario_pnls)
        worst_idx = int(np.argmin(portfolio_scenario_pnls))
        worst_scenario = self.scenarios[worst_idx]
        gross_scan_risk = abs(min(0.0, min_portfolio_pnl))

        # Portföy bazında netleşme kredisi (Inter-commodity / long-short delta offset)
        long_notional = sum(p.notional_value for p in position_details if p.position_type == "LONG")
        short_notional = sum(p.notional_value for p in position_details if p.position_type == "SHORT")
        hedge_overlap = min(long_notional, short_notional)
        inter_commodity_credit = hedge_overlap * self.inter_commodity_offset_rate * 0.15

        # Vadeler arası spread ek yükümlülüğü
        distinct_symbols = {p.symbol for p in position_details}
        inter_month_charge = (
            gross_scan_risk * self.inter_month_spread_rate if len(distinct_symbols) > 1 else 0.0
        )

        # Nihai toplam teminat gereksinimi
        total_req = max(
            short_option_min_total,
            gross_scan_risk - inter_commodity_credit + inter_month_charge,
        )

        available = cash_balance - total_req
        margin_call = available < 0.0

        logger.info(
            "SPAN margin calculated",
            total_req=round(total_req, 2),
            gross_risk=round(gross_scan_risk, 2),
            worst_sc=worst_scenario.name,
            margin_call=margin_call,
        )

        return PortfolioSpanMarginResult(
            total_margin_requirement=round(total_req, 2),
            gross_scan_risk=round(gross_scan_risk, 2),
            inter_month_spread_charge=round(inter_month_charge, 2),
            inter_commodity_credit=round(inter_commodity_credit, 2),
            short_option_minimum_total=round(short_option_min_total, 2),
            cash_balance=round(cash_balance, 2),
            available_margin=round(available, 2),
            margin_call_triggered=margin_call,
            scenarios_tested_count=len(self.scenarios),
            worst_scenario_id=worst_scenario.scenario_id,
            worst_scenario_name=worst_scenario.name,
            position_margins=[p.to_dict() for p in position_details],
        )


# Singleton motor örneği
span_margin_engine = BISTSPANMarginEngine()


def calculate_span_margin(
    positions: list[dict[str, Any]],
    cash_balance: float = 0.0,
) -> dict[str, Any]:
    """Geriye dönük tam uyumlu ve gelişmiş SPAN teminat fonksiyonu."""
    result = span_margin_engine.calculate_margin(positions, cash_balance=cash_balance)
    res_dict = result.to_dict()
    # API uyumu için "total_margin" ve "scenarios_tested" anahtarlarını sağla
    res_dict["total_margin"] = result.total_margin_requirement
    res_dict["scenarios_tested"] = result.scenarios_tested_count
    return res_dict


__all__ = [
    "BISTSPANMarginEngine",
    "InstrumentType",
    "MarginScenarioSpec",
    "PortfolioSpanMarginResult",
    "PositionRiskDetail",
    "PositionType",
    "SPANMarginCalculator",
    "calculate_span_margin",
    "span_margin",
    "span_margin_engine",
]
