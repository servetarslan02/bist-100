"""ALPHA BIST — Kurumsal Seviye Portföy Simülatörü (Portfolio Simulator v3.0).

Finansal Doğruluk ve BIST Standartları:
- Pozisyon Yaşam Döngüsü: Açılış (Buy) → Kapanış (Sell) → Kar/Zarar Gerçekleşmesi.
- Aşırı Satış Engelleme (Oversell Prevention): Elde olmayan hisse satılamaz.
- Nakit Muhasebesi Değişmezliği (Cash Accounting Invariant): Nakit + Maliyet + Gerçekleşen K/Z = Başlangıç Sermayesi.
- Komisyon Modeli: BIST yapısı (Aracı Kurum + Borsa Payı + BSMV).
- Kayma (Slippage) Modeli: Sabit veya işlem hacmine duyarlı gerçekçi maliyet.
- Gerçekleşen (Realized) ve Gerçekleşmemiş (Unrealized) Kar/Zarar takibi.
- Günlük Özkaynak (Equity) Durum Fotoğrafı ve Drawdown Süresi Takibi.
- Denetim İzi (Audit Trail): Tüm alım, satım ve bakiye hareketlerinin kaydedilmesi.
- Deterministik Sonuç Garantisi.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import structlog

try:
    import polars as pl
except ImportError:
    pl = None

logger = structlog.get_logger(__name__)

DEFAULT_INITIAL_CAPITAL: float = 100_000.0
DEFAULT_MAX_POSITION_PCT: float = 0.10
DEFAULT_MAX_POSITIONS: int = 20
DEFAULT_SLIPPAGE_RATE: float = 0.001
DEFAULT_CASH_BUFFER_PCT: float = 0.05
MAX_HISTORY_ENTRIES: int = 5000

__all__ = [
    "DEFAULT_CASH_BUFFER_PCT",
    "DEFAULT_INITIAL_CAPITAL",
    "DEFAULT_MAX_POSITIONS",
    "DEFAULT_MAX_POSITION_PCT",
    "DEFAULT_SLIPPAGE_RATE",
    "MAX_HISTORY_ENTRIES",
    "AuditEntry",
    "BISTCommissionModel",
    "EquitySnapshot",
    "PortfolioSimulatorV3",
    "Position",
    "Trade",
]

# Dairesel bağımlılığı önlemek için lazy import edilen işlem maliyet motoru
_transaction_cost_engine: Any | None = None


def _get_cost_engine() -> Any | None:
    """İşlem maliyeti motorunu (TransactionCostEngine) lazy import yöntemiyle getirir.

    Returns:
        Any | None: Yüklü ise maliyet motoru örneği, aksi halde None.
    """
    global _transaction_cost_engine
    if _transaction_cost_engine is None:
        try:
            from .transaction_costs import bist_transaction_cost

            _transaction_cost_engine = bist_transaction_cost
        except ImportError:
            _transaction_cost_engine = None
    return _transaction_cost_engine


def _parse_date_to_str(d: Any) -> str:
    """Tarih veya datetime nesnesini YYYY-MM-DD string formatına dönüştürür."""
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, date):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, str):
        return d[:10]
    raise TypeError(f"Geçersiz tarih formatı: {type(d)} ({d})")


def _compute_days_between(start_str: str, end_str: str) -> int:
    """İki tarih string'i arasındaki gün farkını hesaplar."""
    try:
        d1 = datetime.strptime(start_str[:10], "%Y-%m-%d")
        d2 = datetime.strptime(end_str[:10], "%Y-%m-%d")
        return max(0, (d2 - d1).days)
    except Exception:
        return 0


# =====================================================
# VERİ MODELLERİ (DATA CLASSES)
# =====================================================


@dataclass
class Trade:
    """Gerçekleşen tek bir işlem (Trade) kaydı."""

    trade_id: int
    ticker: str
    side: str  # BUY | SELL
    date: str
    quantity: int
    price: float
    commission: float
    slippage: float
    pnl: float = 0.0  # Sadece SELL işlemlerinde hesaplanır
    pnl_pct: float = 0.0
    holding_days: int = 0

    def __repr__(self) -> str:
        """İşlem kaydı dize temsili."""
        return (
            f"Trade(id={self.trade_id}, {self.side} {self.quantity} {self.ticker} @ {self.price:.2f}, "
            f"date='{self.date}', pnl={self.pnl:.2f})"
        )

    def to_dict(self) -> dict[str, Any]:
        """İşlem verilerini sözlük formatına dönüştürür.

        Returns:
            dict[str, Any]: İşlem bilgileri sözlüğü.
        """
        return {
            "trade_id": self.trade_id,
            "ticker": self.ticker,
            "side": self.side,
            "date": self.date,
            "quantity": self.quantity,
            "price": round(float(self.price), 4),
            "commission": round(float(self.commission), 2),
            "slippage": round(float(self.slippage), 2),
            "pnl": round(float(self.pnl), 2),
            "pnl_pct": round(float(self.pnl_pct), 4),
            "holding_days": self.holding_days,
        }


@dataclass
class Position:
    """Portföyde tutulan açık pozisyon."""

    ticker: str
    quantity: int
    entry_price: float
    entry_date: str
    cost_basis: float  # Toplam alış maliyeti (Fiyat x Adet + Komisyon + Kayma)
    current_price: float = 0.0

    def __repr__(self) -> str:
        """Pozisyon dize temsili."""
        return (
            f"Position({self.ticker}: {self.quantity} adet @ {self.entry_price:.2f}, "
            f"maliyet={self.cost_basis:.2f}, güncel={self.current_price:.2f}, k/z={self.unrealized_pnl:.2f})"
        )

    @property
    def market_value(self) -> float:
        """Pozisyonun anlık piyasa değeri (Adet x Güncel Fiyat).

        Returns:
            float: Piyasa değeri.
        """
        return float(self.quantity * self.current_price)

    @property
    def unrealized_pnl(self) -> float:
        """Pozisyonun henüz gerçekleşmemiş net kar/zararı.

        Returns:
            float: Gerçekleşmemiş kar/zarar tutarı.
        """
        return float(self.market_value - self.cost_basis)

    @property
    def unrealized_pnl_pct(self) -> float:
        """Pozisyonun henüz gerçekleşmemiş yüzdesel kar/zararı.

        Returns:
            float: Gerçekleşmemiş kar/zarar yüzdesi.
        """
        if self.cost_basis <= 0:
            return 0.0
        return float((self.market_value / self.cost_basis - 1.0) * 100.0)

    def to_dict(self) -> dict[str, Any]:
        """Pozisyon verilerini sözlük formatına dönüştürür.

        Returns:
            dict[str, Any]: Pozisyon detayları.
        """
        return {
            "ticker": self.ticker,
            "quantity": self.quantity,
            "entry_price": round(float(self.entry_price), 4),
            "entry_date": self.entry_date,
            "cost_basis": round(float(self.cost_basis), 2),
            "current_price": round(float(self.current_price), 4),
            "market_value": round(float(self.market_value), 2),
            "unrealized_pnl": round(float(self.unrealized_pnl), 2),
            "unrealized_pnl_pct": round(float(self.unrealized_pnl_pct), 4),
        }


@dataclass
class EquitySnapshot:
    """Gün sonu özkaynak ve portföy durum fotoğrafı."""

    date: str
    equity: float
    cash: float
    market_value: float
    positions: int
    drawdown: float
    daily_return: float

    def __repr__(self) -> str:
        """Özkaynak durum fotoğrafı dize temsili."""
        return (
            f"EquitySnapshot(tarih='{self.date}', ozkaynak={self.equity:.2f}, "
            f"nakit={self.cash:.2f}, dd={self.drawdown * 100:.2f}%)"
        )

    def to_dict(self) -> dict[str, Any]:
        """Özkaynak durumunu sözlük formatına dönüştürür.

        Returns:
            dict[str, Any]: Günlük özkaynak bilgileri.
        """
        return {
            "date": self.date,
            "equity": round(float(self.equity), 2),
            "cash": round(float(self.cash), 2),
            "market_value": round(float(self.market_value), 2),
            "positions": self.positions,
            "drawdown": round(float(self.drawdown), 6),
            "daily_return": round(float(self.daily_return), 6),
        }


@dataclass
class AuditEntry:
    """Sistem denetim izi (audit trail) hareket kaydı."""

    timestamp: str
    date: str
    entry_type: str  # BUY | SELL | EQUITY | ERROR | INFO
    ticker: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        """Denetim kaydı dize temsili."""
        return f"AuditEntry({self.entry_type} {self.ticker} @ {self.date})"


# =====================================================
# BIST KOMİSYON MODELİ
# =====================================================


class BISTCommissionModel:
    """Borsa İstanbul standart komisyon hesaplama modeli."""

    BROKER_RATE: float = 0.0003  # %0.03 Aracı Kurum Payı
    EXCHANGE_RATE: float = 0.000056  # %0.0056 Borsa Payı
    BSMV_RATE: float = 0.05  # BSMV (Komisyon toplamı üzerinden %5)
    MIN_COMMISSION: float = 1.0  # İşlem başına asgari 1 TL

    def __repr__(self) -> str:
        """Komisyon modeli dize temsili."""
        return (
            f"BISTCommissionModel(broker={self.BROKER_RATE}, exchange={self.EXCHANGE_RATE}, "
            f"bsmv={self.BSMV_RATE}, min={self.MIN_COMMISSION})"
        )

    @classmethod
    def compute(cls, amount: float) -> float:
        """İşlem tutarı üzerinden toplam BIST komisyon ve vergi kesintisini hesaplar.

        Args:
            amount: Toplam işlem hacmi tutarı (TL).

        Returns:
            float: Kesilecek komisyon tutarı (TL).
        """
        if amount <= 0 or not math.isfinite(amount):
            return 0.0

        broker = amount * cls.BROKER_RATE
        exchange = amount * cls.EXCHANGE_RATE
        base = broker + exchange
        bsmv = base * cls.BSMV_RATE
        total = base + bsmv
        return float(max(total, cls.MIN_COMMISSION))


# =====================================================
# PORTFÖY SİMÜLATÖRÜ v3.0
# =====================================================


class PortfolioSimulatorV3:
    """Kurumsal seviye, deterministik ve muhasebe değişmezlik garantili portföy simülatörü.

    BIST piyasa mikro yapısına tam uyumlu emir eşleme, komisyon/kayma kesintisi,
    günlük özkaynak güncellemesi ve denetim izi sağlar.
    """

    def __init__(
        self,
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
        max_position_pct: float = DEFAULT_MAX_POSITION_PCT,
        max_positions: int = DEFAULT_MAX_POSITIONS,
        slippage_rate: float = DEFAULT_SLIPPAGE_RATE,
        use_realistic_costs: bool = False,
        avg_daily_volume: float = 0.0,
        volatility_ratio: float = 1.0,
    ) -> None:
        """PortfolioSimulatorV3 simülatörünü başlatır.

        Args:
            initial_capital: Başlangıç nakit sermayesi (varsayılan 100,000 TL).
            max_position_pct: Tek pozisyona ayrılabilecek azami portföy oranı (0-1).
            max_positions: Portföyde aynı anda tutulabilecek azami hisse adedi.
            slippage_rate: Sabit kayma (slippage) oranı.
            use_realistic_costs: İşlem maliyet motorunu aktif etme bayrağı.
            avg_daily_volume: Ortalama günlük işlem hacmi (varsayılan 0.0).
            volatility_ratio: Oynaklık çarpanı.

        Raises:
            ValueError: Sermaye veya pozisyon sınırları geçersizse.
        """
        if initial_capital <= 0 or not math.isfinite(initial_capital):
            raise ValueError("Başlangıç sermayesi pozitif ve sonlu bir sayı olmalıdır.")
        if not (0 < max_position_pct <= 1.0):
            raise ValueError("max_position_pct 0 ile 1 arasında olmalıdır.")
        if max_positions <= 0:
            raise ValueError("max_positions 0'dan büyük olmalıdır.")

        self._initial_capital: float = float(initial_capital)
        self._cash: float = float(initial_capital)
        self._max_position_pct: float = float(max_position_pct)
        self._max_positions: int = int(max_positions)
        self._slippage_rate: float = float(slippage_rate)
        self._use_realistic_costs: bool = bool(use_realistic_costs)
        self._avg_daily_volume: float = float(avg_daily_volume)
        self._volatility_ratio: float = float(volatility_ratio)

        self._positions: dict[str, Position] = {}
        self._trades: list[Trade] = []
        self._equity_curve: list[EquitySnapshot] = []
        self._audit_log: list[AuditEntry] = []

        self._high_water_mark: float = float(initial_capital)
        self._prev_equity: float = float(initial_capital)
        self._trade_counter: int = 0
        self._lock: threading.Lock = threading.Lock()

        # Benchmark karşılaştırma serisi
        self._benchmark_equity: list[tuple[str, float]] = []

        # Drawdown süresi takibi
        self._drawdown_start_date: str | None = None
        self._max_drawdown_duration_days: int = 0

    def __repr__(self) -> str:
        """Simülatörün mevcut durumunu gösteren dize temsili."""
        with self._lock:
            val = self._cash + sum(p.market_value for p in self._positions.values())
            return (
                f"PortfolioSimulatorV3(deger={val:.2f}, nakit={self._cash:.2f}, "
                f"pozisyonlar={len(self._positions)}/{self._max_positions}, trades={len(self._trades)})"
            )

    # ===================== EMİR YÜRÜTME OPERASYONLARI =====================

    def execute_buy(
        self,
        ticker: str,
        price: float,
        date: Any,
        quantity: int | None = None,
        avg_daily_volume: float | None = None,
        volatility_ratio: float | None = None,
    ) -> Trade | None:
        """Portföye alım emri iletir ve muhasebeleştirir.

        Args:
            ticker: Hisse senedi sembolü.
            price: Alış fiyatı.
            date: İşlem tarihi.
            quantity: Alınacak lot miktarı (None ise max_position_pct'ye göre hesaplanır).
            avg_daily_volume: Gerçekçi maliyet modeli için hisse günlük hacmi.
            volatility_ratio: Oynaklık oranı.

        Returns:
            Trade | None: İşlem başarılıysa Trade kaydı, yetersiz nakit veya limit durumunda None.
        """
        date_str = _parse_date_to_str(date)
        if not ticker or price <= 0 or not math.isfinite(price):
            self._audit(date_str, "ERROR", ticker, {"neden": "gecersiz_fiyat_veya_ticker", "fiyat": price})
            return None

        with self._lock:
            if ticker in self._positions:
                self._audit(date_str, "ERROR", ticker, {"neden": "zaten_portfoyde_var"})
                return None

            if len(self._positions) >= self._max_positions:
                self._audit(date_str, "ERROR", ticker, {"neden": "azami_pozisyon_sinirina_ulasildi"})
                return None

            # Otomatik adet hesabı
            if quantity is None:
                total_equity = self._cash + sum(p.market_value for p in self._positions.values())
                max_amount = min(
                    total_equity * self._max_position_pct,
                    self._cash * (1.0 - DEFAULT_CASH_BUFFER_PCT),
                )
                safe_div = price * (1.0 + self._slippage_rate + 0.001)
                quantity = int(max_amount / safe_div) if safe_div > 0 else 0
                if quantity <= 0:
                    return None

            # Maliyet hesaplama
            cost_engine = _get_cost_engine() if self._use_realistic_costs else None
            adv = avg_daily_volume if avg_daily_volume is not None else self._avg_daily_volume
            vol_r = volatility_ratio if volatility_ratio is not None else self._volatility_ratio

            if cost_engine is not None:
                try:
                    cost_detail = cost_engine.calculate_total_cost(
                        side="BUY",
                        price=price,
                        quantity=quantity,
                        ticker=ticker,
                        avg_daily_volume=adv,
                        volatility_ratio=vol_r,
                    )
                    fill_price = float(cost_detail["execution_price"])
                    commission = float(cost_detail["costs"]["commission"])
                    slippage_amount = float(cost_detail["costs"]["slippage"])
                except Exception as e:
                    logger.warning("Maliyet motoru hesaplama hatası, legacy moda geçildi: %s", e)
                    fill_price = price * (1.0 + self._slippage_rate)
                    commission = BISTCommissionModel.compute(quantity * fill_price)
                    slippage_amount = quantity * (fill_price - price)
            else:
                fill_price = price * (1.0 + self._slippage_rate)
                commission = BISTCommissionModel.compute(quantity * fill_price)
                slippage_amount = quantity * (fill_price - price)

            amount = quantity * fill_price
            total_cost = amount + commission

            # Nakit kontrolü ve gerekirse adet düşürme
            if total_cost > self._cash:
                denom = fill_price * 1.002
                quantity = int((self._cash - 1.0) / denom) if denom > 0 else 0
                if quantity <= 0:
                    self._audit(
                        date_str,
                        "ERROR",
                        ticker,
                        {"neden": "yetersiz_nakit", "gerekli": total_cost, "mevcut": self._cash},
                    )
                    return None

                fill_price = price * (1.0 + self._slippage_rate)
                amount = quantity * fill_price
                commission = BISTCommissionModel.compute(amount)
                slippage_amount = quantity * (fill_price - price)
                total_cost = amount + commission

            # Muhasebeleştirme
            self._cash -= total_cost
            self._positions[ticker] = Position(
                ticker=ticker,
                quantity=quantity,
                entry_price=fill_price,
                entry_date=date_str,
                cost_basis=total_cost,
                current_price=price,
            )

            self._trade_counter += 1
            trade = Trade(
                trade_id=self._trade_counter,
                ticker=ticker,
                side="BUY",
                date=date_str,
                quantity=quantity,
                price=fill_price,
                commission=commission,
                slippage=slippage_amount,
            )
            self._trades.append(trade)
            if len(self._trades) > MAX_HISTORY_ENTRIES:
                self._trades = self._trades[-MAX_HISTORY_ENTRIES:]

            self._audit(date_str, "BUY", ticker, trade.to_dict())
            return trade

    def execute_sell(
        self,
        ticker: str,
        price: float,
        date: Any,
        avg_daily_volume: float | None = None,
        volatility_ratio: float | None = None,
    ) -> Trade | None:
        """Portföydeki pozisyonu tamamen kapatır (Sell) ve kar/zararı muhasebeleştirir.

        Args:
            ticker: Satılacak hisse senedi sembolü.
            price: Satış fiyatı.
            date: İşlem tarihi.
            avg_daily_volume: Gerçekçi maliyet modeli hacim verisi.
            volatility_ratio: Oynaklık oranı.

        Returns:
            Trade | None: İşlem gerçekleştiyse Trade kaydı, pozisyon yoksa None.
        """
        date_str = _parse_date_to_str(date)
        if not ticker or price <= 0 or not math.isfinite(price):
            self._audit(date_str, "ERROR", ticker, {"neden": "gecersiz_satis_fiyati", "fiyat": price})
            return None

        with self._lock:
            if ticker not in self._positions:
                return None

            pos = self._positions[ticker]
            quantity = pos.quantity

            cost_engine = _get_cost_engine() if self._use_realistic_costs else None
            adv = avg_daily_volume if avg_daily_volume is not None else self._avg_daily_volume
            vol_r = volatility_ratio if volatility_ratio is not None else self._volatility_ratio

            if cost_engine is not None:
                try:
                    cost_detail = cost_engine.calculate_total_cost(
                        side="SELL",
                        price=price,
                        quantity=quantity,
                        ticker=ticker,
                        avg_daily_volume=adv,
                        volatility_ratio=vol_r,
                    )
                    fill_price = float(cost_detail["execution_price"])
                    commission = BISTCommissionModel.compute(quantity * price)
                    slippage_amount = float(cost_detail["costs"]["slippage"])
                except Exception as e:
                    logger.warning("Maliyet motoru satış hesaplama hatası, legacy moda geçildi: %s", e)
                    fill_price = price * (1.0 - self._slippage_rate)
                    commission = BISTCommissionModel.compute(quantity * price)
                    slippage_amount = quantity * (price - fill_price)
            else:
                fill_price = price * (1.0 - self._slippage_rate)
                commission = BISTCommissionModel.compute(quantity * price)
                slippage_amount = quantity * (price - fill_price)

            amount = quantity * fill_price
            net_revenue = amount - commission

            pnl = net_revenue - pos.cost_basis
            pnl_pct = (fill_price / pos.entry_price - 1.0) * 100.0 if pos.entry_price > 0 else 0.0
            holding_days = _compute_days_between(pos.entry_date, date_str)

            self._cash += net_revenue
            del self._positions[ticker]

            self._trade_counter += 1
            trade = Trade(
                trade_id=self._trade_counter,
                ticker=ticker,
                side="SELL",
                date=date_str,
                quantity=quantity,
                price=fill_price,
                commission=commission,
                slippage=slippage_amount,
                pnl=pnl,
                pnl_pct=pnl_pct,
                holding_days=holding_days,
            )
            self._trades.append(trade)
            if len(self._trades) > MAX_HISTORY_ENTRIES:
                self._trades = self._trades[-MAX_HISTORY_ENTRIES:]

            self._audit(date_str, "SELL", ticker, trade.to_dict())
            return trade

    def update_equity(
        self,
        prices: dict[str, float],
        date: Any,
        benchmark_price: float | None = None,
    ) -> EquitySnapshot:
        """Gün sonu kapanış fiyatlarına göre portföy değerini ve özkaynak durumunu günceller.

        Args:
            prices: Hisse kapanış fiyatları sözlüğü ({'THYAO': 250.0, ...}).
            date: Güncelleme tarihi.
            benchmark_price: BIST100 endeks kapanış değeri (opsiyonel).

        Returns:
            EquitySnapshot: Güncellenen günlük durum kaydı.
        """
        date_str = _parse_date_to_str(date)

        with self._lock:
            # Açık pozisyonların güncel piyasa fiyatlarını tazele
            for ticker, pos in self._positions.items():
                if ticker in prices and prices[ticker] > 0 and math.isfinite(prices[ticker]):
                    pos.current_price = float(prices[ticker])

            market_value = float(sum(p.market_value for p in self._positions.values()))
            equity = float(self._cash + market_value)

            # Değişmezlik denetimi (Invariant check)
            if abs(equity - (self._cash + market_value)) > 0.01:
                self._audit(
                    date_str,
                    "ERROR",
                    "",
                    {"neden": "ozkaynak_degismezlik_ihlali", "ozkaynak": equity, "nakit": self._cash},
                )

            # Zirve değer (High Water Mark) takibi
            if equity > self._high_water_mark:
                self._high_water_mark = equity
                self._drawdown_start_date = None

            # Drawdown hesabı
            drawdown = max(0.0, (self._high_water_mark - equity) / self._high_water_mark) if self._high_water_mark > 0 else 0.0

            # Drawdown süresi takibi
            if drawdown > 0 and self._drawdown_start_date is None:
                self._drawdown_start_date = date_str
            if drawdown > 0 and self._drawdown_start_date is not None:
                dd_duration = _compute_days_between(self._drawdown_start_date, date_str)
                if dd_duration > self._max_drawdown_duration_days:
                    self._max_drawdown_duration_days = dd_duration

            # Günlük getiri hesabı
            daily_return = (equity / self._prev_equity - 1.0) if self._prev_equity > 0 else 0.0

            snapshot = EquitySnapshot(
                date=date_str,
                equity=equity,
                cash=self._cash,
                market_value=market_value,
                positions=len(self._positions),
                drawdown=drawdown,
                daily_return=daily_return,
            )
            self._equity_curve.append(snapshot)
            if len(self._equity_curve) > MAX_HISTORY_ENTRIES:
                self._equity_curve = self._equity_curve[-MAX_HISTORY_ENTRIES:]

            self._prev_equity = equity

            # Benchmark takibi
            if benchmark_price is not None and benchmark_price > 0:
                self._benchmark_equity.append((date_str, float(benchmark_price)))
                if len(self._benchmark_equity) > MAX_HISTORY_ENTRIES:
                    self._benchmark_equity = self._benchmark_equity[-MAX_HISTORY_ENTRIES:]

            return snapshot

    # ===================== SORGULAR VE GETTER METOTLARI =====================

    def get_total_value(self) -> float:
        """Portföyün toplam net aktif değerini (Nakit + Pozisyonlar) döndürür.

        Returns:
            float: Toplam portföy değeri.
        """
        with self._lock:
            return float(self._cash + sum(p.market_value for p in self._positions.values()))

    def get_realized_pnl(self) -> float:
        """Kapatılan işlemlerden gerçekleşmiş toplam net kar/zararı döndürür.

        Returns:
            float: Gerçekleşmiş kar/zarar toplamı (TL).
        """
        with self._lock:
            return float(sum(t.pnl for t in self._trades if t.side == "SELL"))

    def get_unrealized_pnl(self) -> float:
        """Açık pozisyonlardaki gerçekleşmemiş kar/zarar toplamını döndürür.

        Returns:
            float: Gerçekleşmemiş kar/zarar toplamı (TL).
        """
        with self._lock:
            return float(sum(p.unrealized_pnl for p in self._positions.values()))

    def can_buy(self) -> bool:
        """Portföyün yeni bir alım işlemi yapmaya uygun olup olmadığını denetler.

        Returns:
            bool: Pozisyon limiti aşılmamışsa ve pozitif nakit varsa True.
        """
        with self._lock:
            return len(self._positions) < self._max_positions and self._cash > 1.0

    def get_position_count(self) -> int:
        """Portföyde tutulan açık hisse pozisyonu sayısını döndürür.

        Returns:
            int: Açık pozisyon adedi.
        """
        with self._lock:
            return len(self._positions)

    def has_position(self, ticker: str) -> bool:
        """Belirtilen hisse senedinin portföyde bulunup bulunmadığını kontrol eder.

        Args:
            ticker: Hisse sembolü.

        Returns:
            bool: Portföyde mevcut ise True.
        """
        with self._lock:
            return ticker in self._positions

    def get_trades(self) -> list[Trade]:
        """Gerçekleşen tüm alım ve satım işlemlerinin kopyasını döndürür.

        Returns:
            list[Trade]: İşlem nesneleri listesi.
        """
        with self._lock:
            return list(self._trades)

    def get_trades_df(self) -> pl.DataFrame:
        """İşlem geçmişini doğrudan Polars DataFrame olarak döndürür.

        Returns:
            pl.DataFrame: İşlem kayıtlarını içeren Polars DataFrame.
        """
        trades = self.get_trades()
        if pl is not None:
            return pl.DataFrame([t.to_dict() for t in trades]) if trades else pl.DataFrame()
        logger.warning("Polars ortamda bulunamadı, boş DataFrame yerine sözlük listesi tercih edilmeli.")
        raise RuntimeError("Polars kütüphanesi ortamda yüklü değil.")

    def get_equity_curve(self) -> list[EquitySnapshot]:
        """Günlük özkaynak geçmişi kayıtlarının kopyasını döndürür.

        Returns:
            list[EquitySnapshot]: Özkaynak durum kayıtları.
        """
        with self._lock:
            return list(self._equity_curve)

    def get_equity_curve_df(self) -> pl.DataFrame:
        """Günlük özkaynak eğrisini doğrudan Polars DataFrame olarak döndürür.

        Returns:
            pl.DataFrame: Özkaynak eğrisi Polars DataFrame.
        """
        curve = self.get_equity_curve()
        if pl is not None:
            return pl.DataFrame([s.to_dict() for s in curve]) if curve else pl.DataFrame()
        logger.warning("Polars ortamda bulunamadı, boş DataFrame yerine sözlük listesi tercih edilmeli.")
        raise RuntimeError("Polars kütüphanesi ortamda yüklü değil.")

    def get_audit_log(self) -> list[AuditEntry]:
        """Sistemin kaydettiği tüm denetim izi (audit log) kayıtlarını döndürür.

        Returns:
            list[AuditEntry]: Denetim kayıtları listesi.
        """
        with self._lock:
            return list(self._audit_log)

    # ===================== PERFORMANS METRİKLERİ =====================

    def compute_metrics(self) -> dict[str, Any]:
        """Kapsamlı portföy ve backtest performans metriklerini hesaplar.

        Returns:
            dict[str, Any]: Sharpe, Sortino, Calmar, VaR, Win Rate, Alpha vb. metrikler.
        """
        with self._lock:
            sell_trades = [t for t in self._trades if t.side == "SELL"]
            sell_pnls = np.array([t.pnl for t in sell_trades], dtype=float) if sell_trades else np.array([], dtype=float)

            winning = int(np.sum(sell_pnls > 0)) if len(sell_pnls) > 0 else 0
            win_rate = (winning / len(sell_pnls) * 100.0) if len(sell_pnls) > 0 else 0.0
            gross_profit = float(np.sum(sell_pnls[sell_pnls > 0])) if len(sell_pnls) > 0 else 0.0
            gross_loss = float(np.abs(np.sum(sell_pnls[sell_pnls < 0]))) if len(sell_pnls) > 0 else 0.0

            if gross_loss > 0:
                profit_factor = gross_profit / gross_loss
            elif gross_profit > 0:
                profit_factor = 999.0
            else:
                profit_factor = 0.0

            expectancy = float(np.mean(sell_pnls)) if len(sell_pnls) > 0 else 0.0
            total_commission = float(sum(t.commission for t in self._trades))
            total_slippage = float(sum(t.slippage for t in self._trades))

            if not self._equity_curve:
                total_val = self._cash + sum(p.market_value for p in self._positions.values())
                return {
                    "initial_capital": self._initial_capital,
                    "final_equity": round(total_val, 2),
                    "total_return_pct": 0.0,
                    "cagr_pct": 0.0,
                    "sharpe_ratio": 0.0,
                    "sortino_ratio": 0.0,
                    "calmar_ratio": 0.0,
                    "max_drawdown_pct": 0.0,
                    "win_rate_pct": round(win_rate, 1),
                    "profit_factor": round(profit_factor, 4),
                    "expectancy": round(expectancy, 2),
                    "total_trades": len(self._trades),
                    "sell_trades": len(sell_trades),
                    "total_commission": round(total_commission, 2),
                    "total_slippage": round(total_slippage, 2),
                    "open_positions": len(self._positions),
                    "benchmark_return_pct": 0.0,
                    "alpha_pct": 0.0,
                    "daily_returns_count": 0,
                    "var_95": 0.0,
                    "cvar_95": 0.0,
                    "max_drawdown_duration_days": 0,
                }

            final_equity = self._equity_curve[-1].equity
            total_return_pct = ((final_equity / self._initial_capital) - 1.0) * 100.0 if self._initial_capital > 0 else 0.0

            returns = np.array([s.daily_return for s in self._equity_curve], dtype=float)

            # Sharpe Oranı
            ret_std = float(np.std(returns)) if len(returns) > 1 else 0.0
            if ret_std > 0 and math.isfinite(ret_std):
                sharpe = float(np.mean(returns) / ret_std * np.sqrt(252))
            else:
                sharpe = 0.0

            # Sortino Oranı
            downside_returns = np.minimum(returns, 0.0)
            downside_std = float(np.sqrt(np.mean(downside_returns**2)))
            if math.isfinite(downside_std) and downside_std > 0:
                sortino = float(np.mean(returns) / downside_std * np.sqrt(252))
            else:
                sortino = 0.0

            # VaR ve CVaR 95%
            var_95 = float(np.percentile(returns, 5)) if len(returns) >= 20 else 0.0
            var_tail = returns[returns <= var_95]
            cvar_95 = float(np.mean(var_tail)) if len(var_tail) > 0 else var_95

            # Maksimum Drawdown ve Calmar Oranı
            max_dd = max((s.drawdown for s in self._equity_curve), default=0.0) * 100.0
            calmar = (total_return_pct / max_dd) if max_dd > 0 and math.isfinite(max_dd) else 0.0

            # Benchmark ve Alfa
            benchmark_return = 0.0
            if len(self._benchmark_equity) >= 2:
                b_start = self._benchmark_equity[0][1]
                b_end = self._benchmark_equity[-1][1]
                if b_start > 0:
                    benchmark_return = ((b_end / b_start) - 1.0) * 100.0
            alpha = total_return_pct - benchmark_return

            # Bileşik Yıllık Büyüme Oranı (CAGR)
            n_days = len(self._equity_curve)
            n_years = n_days / 252.0 if n_days > 0 else 1.0
            if n_years > 0 and final_equity > 0 and self._initial_capital > 0:
                cagr = ((final_equity / self._initial_capital) ** (1.0 / n_years) - 1.0) * 100.0
            else:
                cagr = 0.0

            return {
                "initial_capital": self._initial_capital,
                "final_equity": round(final_equity, 2),
                "total_return_pct": round(total_return_pct, 2),
                "cagr_pct": round(cagr, 2),
                "sharpe_ratio": round(sharpe, 4),
                "sortino_ratio": round(sortino, 4),
                "calmar_ratio": round(calmar, 4),
                "max_drawdown_pct": round(max_dd, 2),
                "win_rate_pct": round(win_rate, 1),
                "profit_factor": round(profit_factor, 4),
                "expectancy": round(expectancy, 2),
                "total_trades": len(self._trades),
                "sell_trades": len(sell_trades),
                "total_commission": round(total_commission, 2),
                "total_slippage": round(total_slippage, 2),
                "open_positions": len(self._positions),
                "benchmark_return_pct": round(benchmark_return, 2),
                "alpha_pct": round(alpha, 2),
                "daily_returns_count": len(returns),
                "var_95": round(var_95, 6),
                "cvar_95": round(cvar_95, 6),
                "max_drawdown_duration_days": self._max_drawdown_duration_days,
            }

    # ===================== DEĞİŞMEZLİK DENETİMİ (INVARIANTS) =====================

    def check_invariants(self) -> tuple[bool, list[str]]:
        """Portföy muhasebesi ve finansal değişmezlik kurallarını denetler.

        Returns:
            tuple[bool, list[str]]: Tüm kurallar sağlandıysa (True, []), ihlal varsa (False, hata_listesi).
        """
        with self._lock:
            errors: list[str] = []

            # 1. Nakit negatif olamaz
            if self._cash < -0.01:
                errors.append(f"Negatif nakit bakiyesi: {self._cash:.2f}")

            # 2. Özkaynak tutarlılığı: Özkaynak = Nakit + Pozisyon Değeri
            market_value = sum(p.market_value for p in self._positions.values())
            computed_equity = self._cash + market_value
            if self._equity_curve:
                actual_equity = self._equity_curve[-1].equity
                if abs(actual_equity - computed_equity) > 0.05:
                    errors.append(f"Özkaynak uyuşmazlığı: Gerçek={actual_equity:.2f} != Hesaplanan={computed_equity:.2f}")

            # 3. Pozisyon adet ve alış fiyatı geçerliliği
            for ticker, pos in self._positions.items():
                if pos.quantity <= 0:
                    errors.append(f"Geçersiz pozisyon adedi ({ticker}): {pos.quantity}")
                if pos.entry_price <= 0 or not math.isfinite(pos.entry_price):
                    errors.append(f"Geçersiz giriş fiyatı ({ticker}): {pos.entry_price}")

            # 4. Satış işlemlerinde negatif komisyon kontrolü
            for t in self._trades:
                if t.side == "SELL" and t.commission < 0:
                    errors.append(f"Satışta negatif komisyon hatası (Trade ID: {t.trade_id})")

            return len(errors) == 0, errors

    # ===================== YARDIMCI VE SIFIRLAMA METOTLARI =====================

    def _audit(self, date_str: str, entry_type: str, ticker: str, details: dict[str, Any]) -> None:
        """Denetim izi kütüğüne yeni bir hareket kaydeder."""
        self._audit_log.append(
            AuditEntry(
                timestamp=datetime.now(UTC).isoformat(),
                date=date_str,
                entry_type=entry_type,
                ticker=ticker,
                details=details,
            )
        )
        if len(self._audit_log) > MAX_HISTORY_ENTRIES:
            self._audit_log = self._audit_log[-MAX_HISTORY_ENTRIES:]

    def reset(self) -> None:
        """Simülatörü ilk başlangıç durumuna sıfırlar."""
        with self._lock:
            self._cash = self._initial_capital
            self._positions.clear()
            self._trades.clear()
            self._equity_curve.clear()
            self._audit_log.clear()
            self._benchmark_equity.clear()
            self._high_water_mark = self._initial_capital
            self._prev_equity = self._initial_capital
            self._trade_counter = 0
            self._drawdown_start_date = None
            self._max_drawdown_duration_days = 0
            logger.info("PortfolioSimulatorV3 başlangıç durumuna sıfırlandı.")
