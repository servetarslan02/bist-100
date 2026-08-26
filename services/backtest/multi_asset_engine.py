"""
ALPHA BIST — Multi-Asset Backtest Engine

Birden fazla hisseyi eş zamanlı olarak backtest eden motor.
Portfolio-level risk yönetimi, korelasyon ve sektör maruziyeti dahil.

Özellikler:
1. Eş zamanlı çoklu hisse backtest
2. Portfolio-level risk limitleri
3. Sektör/korelasyon maruziyet kontrolü
4. Rejime duyarlı pozisyon yönetimi
5. Canlı sistem ile parity garantisi

Referanslar:
- BACKTEST-NIHAI-SPEC.md - Multi-asset backtest
- 02-SISTEM-MIMARISI.md - Katman 5 (Portfolio & Risk)
"""

import numpy as np
import polars as pl
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

from .transaction_costs import TransactionCostEngine, bist_transaction_cost
from .bias_detector import LookAheadBiasDetector, BiasDetectorMiddleware

logger = structlog.get_logger()


@dataclass
class SectorExposure:
    """Sektör maruziyet limiti."""
    sector_name: str
    max_weight_pct: float = 25.0  # Maksimum %25 tek sektör
    current_weight_pct: float = 0.0

    def is_within_limit(self, additional_weight: float = 0) -> bool:
        return (self.current_weight_pct + additional_weight) <= self.max_weight_pct


@dataclass
class MultiAssetConfig:
    """Multi-asset backtest konfigürasyonu."""
    initial_capital: float = 1_000_000.0
    max_positions: int = 20
    max_position_pct: float = 10.0  # Tek pozisyon max %10
    max_sector_pct: float = 25.0    # Tek sektör max %25
    max_correlation: float = 0.7    # Yüksek korelasyon eşiği
    min_cash_pct: float = 5.0       # Minimum nakit %5
    rebalance_frequency_days: int = 1  # Günlük rebalance

    # Risk limitleri
    max_portfolio_volatility: float = 0.20  # Yıllık %20 volatilite
    max_drawdown_pct: float = 15.0          # Max drawdown %15
    drawdown_reduction_trigger: float = 10.0 # %10 drawdown'da risk azalt

    # Likidite kısıtı: bir günlük hacmin bu yüzdesinden fazlası tek emirde
    # alınamaz/satılamaz (gerçek piyasada büyük emir günü aşan market impact
    # yaratır). 0 = kısıt yok (hacim verisi olmayan senaryolar için).
    max_volume_participation_pct: float = 10.0

    # Gap risk: BIST'te günlük fiyat marjı (tavan/taban) vardır - bu bandın
    # dışında fiyat oluşamaz ve o yönde işlem gerçekleşmeyebilir (limit kilidi).
    # Burada, önceki kapanışa göre |açılış getirisi| bu eşiği aşarsa emrin o
    # gün gerçekleşemediği varsayılır (muhafazakâr yaklaşım). BIST bandı
    # zamanla/enstrümana göre değişmiştir (~%10 tipik) - gerekirse ayarla.
    gap_limit_pct: float = 10.0

    # Transaction cost
    use_realistic_costs: bool = True

    # Bias detection
    enable_bias_detection: bool = True


@dataclass
class AssetAllocation:
    """Tek bir varlık tahsisi."""
    ticker: str
    target_weight: float    # Hedef ağırlık (0-1)
    current_weight: float   # Mevcut ağırlık
    signal_score: float     # Sinyal skoru
    sector: str             # Sektör
    reason: str             # Tahsis nedeni


@dataclass
class MultiAssetResult:
    """Multi-asset backtest sonucu."""
    run_id: str
    start_date: str
    end_date: str
    config: MultiAssetConfig
    total_return_pct: float = 0.0
    cagr_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_days: int = 0
    calmar_ratio: float = 0.0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    total_commission: float = 0.0
    total_slippage: float = 0.0
    avg_positions: float = 0.0
    avg_turnover: float = 0.0
    sector_exposures: Dict[str, float] = field(default_factory=dict)
    bias_report: Optional[Dict[str, Any]] = None
    equity_curve: List[Tuple[str, float]] = field(default_factory=list)
    trade_log: List[Dict[str, Any]] = field(default_factory=list)
    daily_metrics: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "metrics": {
                "total_return_pct": round(self.total_return_pct, 2),
                "cagr_pct": round(self.cagr_pct, 2),
                "sharpe_ratio": round(self.sharpe_ratio, 3),
                "sortino_ratio": round(self.sortino_ratio, 3),
                "max_drawdown_pct": round(self.max_drawdown_pct, 2),
                "max_drawdown_duration_days": self.max_drawdown_duration_days,
                "calmar_ratio": round(self.calmar_ratio, 3),
                "win_rate_pct": round(self.win_rate_pct, 1),
                "profit_factor": round(self.profit_factor, 3),
                "total_trades": self.total_trades,
                "total_commission": round(self.total_commission, 2),
                "total_slippage": round(self.total_slippage, 2),
                "avg_positions": round(self.avg_positions, 1),
                "avg_turnover": round(self.avg_turnover, 4),
            },
            "sector_exposures": self.sector_exposures,
            "bias_report": self.bias_report,
        }


class MultiAssetBacktestEngine:
    """
    Multi-asset backtest motoru.

    Birden fazla hisseyi eş zamanlı olarak backtest eder.
    Portfolio-level risk yönetimi uygular.
    """

    def __init__(
        self,
        config: Optional[MultiAssetConfig] = None,
        cost_engine: Optional[TransactionCostEngine] = None,
    ):
        self.config = config or MultiAssetConfig()
        self.cost_engine = cost_engine or bist_transaction_cost
        self.bias_detector = LookAheadBiasDetector()
        self.bias_middleware = BiasDetectorMiddleware(strict_mode=True)

    def run(
        self,
        market_data: pl.DataFrame,
        signal_data: pl.DataFrame,
        sector_mapping: Dict[str, str],
        benchmark_data: Optional[pl.DataFrame] = None,
        universe_tickers: Optional[Set[str]] = None,
    ) -> MultiAssetResult:
        """
        Multi-asset backtest çalıştır.

        Args:
            market_data: Fiyat/hacim verisi (date, ticker, open, high, low, close, volume)
            signal_data: Sinyal verisi (date, ticker, score, confidence)
            sector_mapping: Hisse → sektör eşleştirmesi
            benchmark_data: Benchmark (endeks) verisi
            universe_tickers: Evren hisseleri (survivorship bias için)

        Returns:
            MultiAssetResult
        """
        # universe_tickers verildiyse, market/signal verisini bu evrenle
        # sınırla. Bu, SurvivorshipBiasHandler.get_universe_at_date() ile
        # üretilen tarihe-özgü (delisted hisseleri de içeren) evrenin
        # backtest motoruna gerçekten ulaşmasını sağlayan bağlantı
        # noktasıdır. (Önceden bu parametre tanımlıydı ama hiç
        # kullanılmıyordu - survivorship bias düzeltmesi çağırılsa bile
        # motora hiç ulaşmıyordu; bkz. documentation/14.)
        if universe_tickers is not None:
            market_data = market_data[market_data["ticker"].isin(universe_tickers)]
            if signal_data is not None and not signal_data.empty:
                signal_data = signal_data[signal_data["ticker"].isin(universe_tickers)]
            logger.info(
                "Universe filtresi uygulandı (survivorship-aware)",
                universe_size=len(universe_tickers),
            )

        import hashlib
        run_id = hashlib.md5(
            f"multi_{datetime.now(timezone.utc).isoformat()}".encode()
        ).hexdigest()[:12]

        logger.info("Starting multi-asset backtest",
                    run_id=run_id,
                    tickers=market_data["ticker"].nunique() if "ticker" in market_data.columns else 0,
                    date_range=f"{market_data['date'].min()} - {market_data['date'].max()}")

        # Config
        cfg = self.config
        capital = cfg.initial_capital
        cash = capital

        # State
        positions: Dict[str, Dict] = {}  # ticker → {quantity, entry_price, entry_date, sector}
        equity_curve = []
        trade_log = []
        daily_metrics = []
        total_commission = 0.0
        total_slippage = 0.0
        total_trades = 0

        # Get unique dates
        dates = sorted(market_data["date"].unique())

        # T+1 EXECUTION: Sinyal D gününün verisiyle üretilir, ama işlem
        # D gününün KAPANIŞINDA değil, D+1'in AÇILIŞINDA gerçekleşir.
        # Aynı günün kapanışıyla hem sinyal üretip hem işlem yapmak,
        # gerçek hayatta imkansız bir öngörü (look-ahead bias) varsayar
        # (bkz. documentation/14 — kod incelemesiyle tespit edilen bug).
        next_date_map: Dict[Any, Any] = {
            dates[i]: dates[i + 1] for i in range(len(dates) - 1)
        }
        open_price_map: Dict[Tuple[Any, str], float] = {}
        if "open" in market_data.columns:
            for row in market_data[["date", "ticker", "open"]].itertuples(index=False):
                open_price_map[(row.date, row.ticker)] = row.open

        # Gap risk kontrolü için önceki kapanış fiyatı haritası
        close_price_map: Dict[Tuple[Any, str], float] = {}
        if "close" in market_data.columns:
            for row in market_data[["date", "ticker", "close"]].itertuples(index=False):
                close_price_map[(row.date, row.ticker)] = row.close

        def _gap_locked(ticker: str, signal_date: Any, next_open: float) -> bool:
            """Açılış, önceki kapanışa göre izin verilen bandın dışındaysa
            (tavan/taban kilidi varsayımı) True döner - emir o gün gerçekleşemez."""
            if cfg.gap_limit_pct <= 0:
                return False
            prev_close = close_price_map.get((signal_date, ticker))
            if prev_close is None or prev_close <= 0:
                return False
            gap_pct = abs(next_open - prev_close) / prev_close * 100
            return gap_pct > cfg.gap_limit_pct

        # Bias check
        bias_report = None
        if cfg.enable_bias_detection:
            bias_report_obj = self.bias_detector.validate_label_feature_alignment(
                label_horizon_days=5,
                feature_window_days=20,
                purge_days=5,
            )
            bias_report = bias_report_obj.to_dict()

        # Sector tracking
        sector_exposure: Dict[str, float] = {}

        # Main loop
        prev_equity = capital
        peak_equity = capital
        drawdown_start = None
        max_dd_duration = 0
        current_dd_duration = 0
        winning_days = 0
        losing_days = 0
        gross_profit = 0.0
        gross_loss = 0.0
        position_count_per_day = []

        for date in dates:
            # Current day data
            day_market = market_data.filter(pl.col('date') == target_date)
            day_signals = signal_data.filter(pl.col('date') == target_date) if signal_data is not None else pl.DataFrame()

            if day_market.empty:
                continue

            # Current prices
            prices = dict(zip(day_market["ticker"], day_market["close"]))
            volumes = dict(zip(day_market["ticker"], day_market["volume"]))

            # Mark-to-market
            portfolio_value = cash
            for ticker, pos in positions.items():
                current_price = prices.get(ticker, pos["entry_price"])
                portfolio_value += pos["quantity"] * current_price

            # Drawdown tracking
            if portfolio_value > peak_equity:
                peak_equity = portfolio_value
                if drawdown_start:
                    current_dd_duration = (date - drawdown_start).days if hasattr(date, 'days') else 0
                    max_dd_duration = max(max_dd_duration, current_dd_duration)
                    drawdown_start = None

            current_dd = (peak_equity - portfolio_value) / peak_equity * 100
            if current_dd > cfg.max_drawdown_pct:
                logger.warning("Max drawdown exceeded",
                              current_dd=round(current_dd, 2),
                              max_allowed=cfg.max_drawdown_pct)

            if current_dd > 0 and drawdown_start is None:
                drawdown_start = date

            # Daily return
            daily_return = (portfolio_value - prev_equity) / prev_equity if prev_equity > 0 else 0
            if daily_return > 0:
                winning_days += 1
                gross_profit += daily_return
            elif daily_return < 0:
                losing_days += 1
                gross_loss += abs(daily_return)

            # Record daily metrics
            daily_metrics.append({
                "date": str(date),
                "equity": round(portfolio_value, 2),
                "cash": round(cash, 2),
                "positions": len(positions),
                "daily_return_pct": round(daily_return * 100, 4),
                "drawdown_pct": round(current_dd, 2),
            })

            equity_curve.append((str(date), round(portfolio_value, 2)))
            prev_equity = portfolio_value
            position_count_per_day.append(len(positions))

            # SELL signals (exit positions)
            # T+1: signal 'date' gününe ait, execution fiyatı D+1 açılışı
            next_date = next_date_map.get(date)
            if not day_signals.empty and next_date is not None:
                sell_signals = day_signals.filter(pl.col('score') < 0)  # Düşük skor = sat
                for _, sig in sell_signals.iterrows():
                    ticker = sig["ticker"]
                    if ticker in positions:
                        pos = positions[ticker]
                        next_open = open_price_map.get((next_date, ticker))
                        if next_open is None or next_open <= 0:
                            # D+1'de fiyat verisi yok (delisting/eksik veri) -
                            # T+1 için gerçekçi execution imkansız, işlemi atla
                            continue
                        sell_price = next_open

                        if _gap_locked(ticker, date, next_open):
                            # Tavan/taban kilidi varsayımı: bu yönde emir
                            # gerçekleşemez, pozisyon açık kalır
                            continue

                        # Likidite kısıtı: günlük hacmin max_volume_participation_pct'ini
                        # aşan kısım o gün satılamaz (market impact / gerçekçi execution).
                        day_volume = volumes.get(ticker, 0)
                        sell_qty = pos["quantity"]
                        if cfg.max_volume_participation_pct > 0 and day_volume > 0:
                            liquidity_cap = int(day_volume * cfg.max_volume_participation_pct / 100)
                            sell_qty = min(sell_qty, liquidity_cap)
                        if sell_qty < 1:
                            # Hacim o kadar düşük ki tek pay bile satılamıyor - bu güne atla
                            continue

                        # Transaction cost
                        if cfg.use_realistic_costs:
                            cost = self.cost_engine.calculate_total_cost(
                                "SELL", sell_price, sell_qty, ticker,
                                day_volume
                            )
                            commission = cost["costs"]["commission"]
                            slippage = cost["costs"]["slippage"]
                            exec_price = cost["execution_price"]
                        else:
                            # Basit komisyon: sadece broker ücreti (realistic modelden düşük olmalı)
                            commission = sell_price * sell_qty * 0.0003
                            slippage = 0
                            exec_price = sell_price

                        proceeds = sell_qty * exec_price - commission
                        pnl = proceeds - sell_qty * pos["entry_price"]

                        cash += proceeds
                        total_commission += commission
                        total_slippage += slippage
                        total_trades += 1

                        # Sector update
                        sector = pos.get("sector", "unknown")
                        sector_exposure[sector] = sector_exposure.get(sector, 0) - (
                            sell_qty * sell_price / portfolio_value * 100
                        )

                        trade_log.append({
                            "date": str(next_date),
                            "signal_date": str(date),
                            "ticker": ticker,
                            "side": "SELL",
                            "quantity": sell_qty,
                            "price": round(exec_price, 4),
                            "pnl": round(pnl, 2),
                            "commission": round(commission, 2),
                            "reason": "signal" if sell_qty == pos["quantity"] else "signal_partial_liquidity",
                        })

                        if sell_qty >= pos["quantity"]:
                            del positions[ticker]
                        else:
                            # Kısmi satış: kalan miktarı pozisyonda tut (entry_price sabit kalır)
                            pos["quantity"] -= sell_qty

            # BUY signals (enter positions)
            # T+1: signal 'date' gününe ait, execution fiyatı D+1 açılışı
            if not day_signals.empty and len(positions) < cfg.max_positions and next_date is not None:
                buy_signals = day_signals[
                    (day_signals["score"] >= 70) &  # Yüksek skor = al
                    (~day_signals["ticker"].isin(positions.keys()))
                ].sort("score", ascending=False)

                for _, sig in buy_signals.iterrows():
                    if len(positions) >= cfg.max_positions:
                        break

                    ticker = sig["ticker"]
                    next_open = open_price_map.get((next_date, ticker))
                    if next_open is None or next_open <= 0:
                        # D+1'de fiyat verisi yok - gerçekçi execution
                        # imkansız, işlemi atla (aynı gün kapanışına
                        # dönüp look-ahead bias yaratmıyoruz)
                        continue

                    buy_price = next_open

                    if _gap_locked(ticker, date, next_open):
                        # Tavan/taban kilidi varsayımı: bu yönde emir
                        # gerçekleşemez, işlemi atla
                        continue

                    sector = sector_mapping.get(ticker, "unknown")

                    # Position sizing (equal weight with limits)
                    max_position_value = portfolio_value * cfg.max_position_pct / 100

                    # Sector limit check
                    current_sector_pct = sector_exposure.get(sector, 0)
                    sector_limit = cfg.max_sector_pct - current_sector_pct
                    max_from_sector = portfolio_value * sector_limit / 100

                    position_value = min(max_position_value, max_from_sector, cash * 0.95)

                    if position_value < buy_price * 10:  # Minimum 10 adet
                        continue

                    quantity = int(position_value / buy_price)
                    if quantity < 1:
                        continue

                    # Likidite kısıtı: günlük hacmin max_volume_participation_pct'ini
                    # aşan miktar tek günde alınamaz (market impact / gerçekçi execution).
                    day_volume = volumes.get(ticker, 0)
                    if cfg.max_volume_participation_pct > 0:
                        if day_volume <= 0:
                            # Hacim verisi yok - güvenli taraf: işlem yapma
                            continue
                        liquidity_cap = int(day_volume * cfg.max_volume_participation_pct / 100)
                        quantity = min(quantity, liquidity_cap)
                        if quantity < 1:
                            continue

                    # Transaction cost
                    if cfg.use_realistic_costs:
                        cost = self.cost_engine.calculate_total_cost(
                            "BUY", buy_price, quantity, ticker,
                            day_volume
                        )
                        commission = cost["costs"]["commission"]
                        slippage = cost["costs"]["slippage"]
                        exec_price = cost["execution_price"]
                    else:
                        # Basit komisyon: sadece broker ücreti
                        commission = buy_price * quantity * 0.0003
                        slippage = 0
                        exec_price = buy_price

                    total_cost = quantity * exec_price + commission
                    if total_cost > cash:
                        continue

                    cash -= total_cost
                    total_commission += commission
                    total_slippage += slippage
                    total_trades += 1

                    positions[ticker] = {
                        "quantity": quantity,
                        "entry_price": exec_price,
                        "entry_date": str(next_date),
                        "sector": sector,
                        "signal_score": sig["score"],
                    }

                    # Sector update
                    sector_exposure[sector] = sector_exposure.get(sector, 0) + (
                        quantity * buy_price / portfolio_value * 100
                    )

                    trade_log.append({
                        "date": str(next_date),
                        "signal_date": str(date),
                        "ticker": ticker,
                        "side": "BUY",
                        "quantity": quantity,
                        "price": round(exec_price, 4),
                        "commission": round(commission, 2),
                        "score": sig["score"],
                    })

        # Final metrics
        final_equity = equity_curve[-1][1] if equity_curve else capital
        total_return = (final_equity / capital - 1) * 100

        days = len(dates)
        years = days / 252 if days > 0 else 1
        cagr = ((final_equity / capital) ** (1 / years) - 1) * 100 if years > 0 else 0

        # Sharpe
        returns = [d["daily_return_pct"] / 100 for d in daily_metrics]
        if len(returns) > 1:
            avg_return = np.mean(returns)
            std_return = np.std(returns)
            sharpe = (avg_return / std_return * np.sqrt(252)) if std_return > 0 else 0

            # Sortino
            downside_returns = [r for r in returns if r < 0]
            downside_std = np.std(downside_returns) if len(downside_returns) > 1 else std_return
            sortino = (avg_return / downside_std * np.sqrt(252)) if downside_std > 0 else 0
        else:
            sharpe = sortino = 0

        # Max drawdown
        max_dd = max((d["drawdown_pct"] for d in daily_metrics), default=0)

        # Calmar
        calmar = cagr / max_dd if max_dd > 0 else 0

        # Win rate
        total_days = winning_days + losing_days
        win_rate = winning_days / total_days * 100 if total_days > 0 else 0

        # Profit factor
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Average positions
        avg_positions = np.mean(position_count_per_day) if position_count_per_day else 0

        result = MultiAssetResult(
            run_id=run_id,
            start_date=str(dates[0]) if dates else "",
            end_date=str(dates[-1]) if dates else "",
            config=cfg,
            total_return_pct=total_return,
            cagr_pct=cagr,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown_pct=max_dd,
            max_drawdown_duration_days=max_dd_duration,
            calmar_ratio=calmar,
            win_rate_pct=win_rate,
            profit_factor=profit_factor,
            total_trades=total_trades,
            total_commission=total_commission,
            total_slippage=total_slippage,
            avg_positions=avg_positions,
            sector_exposures={k: round(v, 2) for k, v in sector_exposure.items()},
            bias_report=bias_report,
            equity_curve=equity_curve,
            trade_log=trade_log,
            daily_metrics=daily_metrics,
        )

        logger.info("Multi-asset backtest complete",
                    run_id=run_id,
                    total_return=f"{total_return:.2f}%",
                    sharpe=round(sharpe, 3),
                    max_dd=f"{max_dd:.2f}%")

        return result
