"""
ALPHA BIST — Virtual Portfolio v2.0 (Institutional BIST Engine)

Kurumsal Düzey Borsa İstanbul Sanal Portföy Yönetimi:
- T+2 Takas & Valörlü Bakiye (Settled Cash, T+1, T+2)
- Bloke Nakit ve Alım Gücü (Purchasing Power)
- BIST Brüt Takas Kuralı (Aynı gün alınan hisse aynı gün satılamaz)
- KAP Kurumsal İşlemler (Temettü nakit aktarımı, Bedelsiz lot bölünmesi/maliyet revizyonu)
- Kısmi & Tam Pozisyon Kapatma, Ağırlıklı Ortalama Maliyet
- Realized / Unrealized P&L ve Mark-to-Market
"""

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


class VirtualPortfolio:
    """Sanal portföy — T+2 Takas, Bloke Bakiye ve BIST Brüt Takas destekli."""

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        state_store=None,
        strict_t2: bool = True,
    ):
        """Otomatik eklendi."""
        self.initial_capital = initial_capital
        self.strict_t2 = strict_t2
        # T+2 Takas & Valörlü Bakiye Modeli
        self.settled_cash: float = initial_capital  # T+0 Serbest, çekilebilir nakit
        self.unsettled_cash_t1: float = 0.0  # 1 gün sonra takası tamamlanacak nakit
        self.unsettled_cash_t2: float = 0.0  # 2 gün sonra takası tamamlanacak nakit
        self.blocked_cash: float = 0.0  # Açık limit emirler için bloke bakiye

        # Brüt takas aynı gün alım lotları (gün içi satış engeli)
        self.gross_settlement_intraday: dict[str, int] = defaultdict(int)

        self._positions: dict[str, dict[str, Any]] = {}
        self._trades: list[dict[str, Any]] = []
        self._orders: list[dict[str, Any]] = []
        self._equity_curve: list[dict[str, Any]] = []
        self._state_store = state_store
        self._max_equity = initial_capital
        self._current_date = ""
        self._commission_total = 0.0

        logger.info(
            "VirtualPortfolio initialized with T+2 Settlement", initial_capital=initial_capital, strict_t2=strict_t2
        )

    @property
    def purchasing_power(self) -> float:
        """Hisse alımında kullanılabilir işlem gücü (Takasbank T+2 Mahsup Kuralı).
        Aynı günkü hisse satış alacakları (T+2), yeni hisse alımlarında (T+2) mahsup edilebilir."""
        return max(0.0, self.settled_cash + self.unsettled_cash_t1 + self.unsettled_cash_t2 - self.blocked_cash)

    @property
    def withdrawable_cash(self) -> float:
        """Banka hesabına serbest çekilebilir nakit (Sadece T+0 Takası Tamamlanmış Bakiye)."""
        return max(0.0, self.settled_cash - self.blocked_cash)

    @property
    def total_cash(self) -> float:
        """Toplam nakit varlığı (Settled + T1 + T2 - Blocked)."""
        return max(0.0, self.settled_cash + self.unsettled_cash_t1 + self.unsettled_cash_t2 - self.blocked_cash)

    @property
    def cash(self) -> float:
        """Alım gücü / harcanabilir nakit."""
        return self.purchasing_power

    @cash.setter
    def cash(self, value: float) -> Any:
        """Geriye dönük uyumluluk için settled_cash'i günceller."""
        self.settled_cash = value

    def roll_settlement_day(self) -> Any:
        """BIST Seans Sonu Valör Kaydırma (T+2 -> T+1 -> Settled)."""
        self.settled_cash += self.unsettled_cash_t1
        self.unsettled_cash_t1 = self.unsettled_cash_t2
        self.unsettled_cash_t2 = 0.0
        self.gross_settlement_intraday.clear()
        logger.info(
            "T+2 Settlement rolled", settled=self.settled_cash, t1=self.unsettled_cash_t1, t2=self.unsettled_cash_t2
        )

    def _deduct_cash_hierarchical(self, amount: float) -> Any:
        """Nakdi sırasıyla settled, t1 ve t2 havuzlarından düşer."""
        remaining = amount
        # 1. Settled cash'ten düş
        if self.settled_cash >= remaining:
            self.settled_cash -= remaining
            return
        else:
            remaining -= self.settled_cash
            self.settled_cash = 0.0

        # 2. T1 cash'ten düş
        if self.unsettled_cash_t1 >= remaining:
            self.unsettled_cash_t1 -= remaining
            return
        else:
            remaining -= self.unsettled_cash_t1
            self.unsettled_cash_t1 = 0.0

        # 3. T2 cash'ten düş
        self.unsettled_cash_t2 = max(0.0, self.unsettled_cash_t2 - remaining)

    # ===================== PERSISTENCE =====================

    def load_from_store(self) -> Any:
        """State store'dan yükle."""
        if not self._state_store:
            return
        try:
            snapshot = self._state_store.load_portfolio_state()
            if snapshot:
                self.settled_cash = snapshot.get("settled_cash", snapshot.get("cash", self.initial_capital))
                self.unsettled_cash_t1 = snapshot.get("unsettled_cash_t1", 0.0)
                self.unsettled_cash_t2 = snapshot.get("unsettled_cash_t2", 0.0)
                self.initial_capital = snapshot.get("initial_capital", self.initial_capital)
                self._positions = {p["ticker"]: p for p in snapshot.get("positions", [])}
                self._trades = snapshot.get("trades", [])
                self._orders = snapshot.get("orders", [])
                self._equity_curve = snapshot.get("equity_curve", [])
                logger.info(
                    "VirtualPortfolio loaded from store", positions=len(self._positions), trades=len(self._trades)
                )
        except Exception as e:
            logger.warning("VirtualPortfolio could not load state from store", error=str(e))

    def save_to_store(self, date: str) -> Any:
        """State store'a kaydet (debounced — SSD dostu)."""
        if not self._state_store:
            return
        from services.core.debounce import should_save
        if not should_save("virtual_portfolio_save", 30):
            return
        snapshot = {
            "date": date,
            "cash": self.cash,
            "settled_cash": self.settled_cash,
            "unsettled_cash_t1": self.unsettled_cash_t1,
            "unsettled_cash_t2": self.unsettled_cash_t2,
            "initial_capital": self.initial_capital,
            "positions": list(self._positions.values()),
            "equity_curve": self._equity_curve,
            "trades": self._trades,
            "orders": self._orders,
            "last_updated": datetime.now(UTC).isoformat(),
        }
        self._state_store.save_portfolio_state(snapshot)
        self._state_store.save_positions(list(self._positions.values()))

    # ===================== POSITION MANAGEMENT =====================

    def open_position(
        self,
        ticker: str,
        quantity: int,
        price: float,
        sector: str = "",
        date: str = "",
        commission: float = 0.0,
        is_gross_settlement: bool = False,
    ) -> dict[str, Any]:
        """Yeni pozisyon aç veya mevcut pozisyonu artır (T+2 ve Brüt Takas uyumlu)."""
        cost = quantity * price
        total_cost = cost + commission

        if total_cost > self.cash:
            logger.warning(
                "Insufficient purchasing power for position", ticker=ticker, required=total_cost, available=self.cash
            )
            return {"success": False, "error": "INSUFFICIENT_CASH", "required": total_cost, "available": self.cash}

        if ticker in self._positions:
            pos = self._positions[ticker]
            old_cost = pos["quantity"] * pos["avg_cost"]
            new_cost = quantity * price + commission
            total_qty = pos["quantity"] + quantity
            pos["avg_cost"] = (old_cost + new_cost) / total_qty if total_qty > 0 else price
            pos["quantity"] = total_qty
            pos["current_price"] = price
            pos["market_value"] = total_qty * price
            pos["sector"] = sector or pos.get("sector", "")
            logger.info("Position increased", ticker=ticker, new_qty=total_qty, avg_cost=pos["avg_cost"])
        else:
            avg_with_commission = (cost + commission) / quantity if quantity > 0 else price
            self._positions[ticker] = {
                "ticker": ticker,
                "quantity": quantity,
                "avg_cost": avg_with_commission,
                "current_price": price,
                "market_value": quantity * price,
                "sector": sector,
                "entry_date": date,
                "last_update": datetime.now(UTC).isoformat(),
            }
            logger.info("Position opened", ticker=ticker, quantity=quantity, price=price, avg_cost=avg_with_commission)

        # Brüt takas aynı gün satış kısıtı için kaydet
        if is_gross_settlement:
            self.gross_settlement_intraday[ticker] += quantity

        self._deduct_cash_hierarchical(total_cost)
        self._commission_total += commission
        self._current_date = date
        return {"success": True, "ticker": ticker, "quantity": quantity, "cash_remaining": self.cash}

    def close_position(
        self,
        ticker: str,
        price: float,
        quantity: int | None = None,
        date: str = "",
        commission: float = 0.0,
        reason: str = "EXIT_SIGNAL",
    ) -> dict[str, Any]:
        """Pozisyon kapat veya kısmi satış yap (T+2 Takas valörü ve Brüt Takas korumalı)."""
        if ticker not in self._positions:
            return {"success": False, "error": "NO_POSITION", "ticker": ticker}

        pos = self._positions[ticker]
        total_holding = pos["quantity"]
        sold_quantity = quantity if (quantity is not None and 0 < quantity < total_holding) else total_holding

        # BIST Brüt Takas Kısıtı Kontrolü: Aynı gün alınan hisseler aynı gün satılamaz!
        intraday_bought = self.gross_settlement_intraday.get(ticker, 0)
        available_to_sell = total_holding - intraday_bought
        if sold_quantity > available_to_sell:
            error_msg = f"GROSS_SETTLEMENT_BLOCKED: {ticker} brüt takasta. Bugün alınan {intraday_bought} lot aynı gün satılamaz. Satılabilir: {available_to_sell}"
            logger.warning(
                "Gross settlement sell blocked", ticker=ticker, requested=sold_quantity, available=available_to_sell
            )
            return {"success": False, "error": "GROSS_SETTLEMENT_BLOCKED", "message": error_msg}

        # Net gelir (satış tutarı - satış komisyonu) -> BIST T+2 Takas havuzuna aktarılır
        revenue = sold_quantity * price - commission
        self.unsettled_cash_t2 += revenue
        self._commission_total += commission

        # Realized P&L
        realized_pnl = (price - pos["avg_cost"]) * sold_quantity - commission
        realized_pnl_pct = (price / pos["avg_cost"] - 1) * 100 if pos["avg_cost"] > 0 else 0

        trade = {
            "trade_id": f"TRD_{date}_{ticker}_{uuid.uuid4().hex[:8]}",
            "ticker": ticker,
            "side": "SELL",
            "quantity": sold_quantity,
            "entry_price": pos["avg_cost"],
            "exit_price": price,
            "entry_date": pos.get("entry_date", date),
            "exit_date": date,
            "commission": commission,
            "realized_pnl": round(realized_pnl, 2),
            "realized_pnl_pct": round(realized_pnl_pct, 2),
            "holding_days": self._holding_days(pos.get("entry_date"), date),
            "reason": reason,
        }
        self._trades.append(trade)
        if len(self._trades) > 5000:
            self._trades = self._trades[-5000:]

        if self._state_store:
            self._state_store.save_trade(trade)

        if sold_quantity >= total_holding:
            del self._positions[ticker]
            logger.info(
                "Position fully closed", ticker=ticker, qty=sold_quantity, realized_pnl=realized_pnl, reason=reason
            )
        else:
            remaining_qty = total_holding - sold_quantity
            pos["quantity"] = remaining_qty
            pos["current_price"] = price
            pos["market_value"] = remaining_qty * price
            pos["last_update"] = datetime.now(UTC).isoformat()
            logger.info(
                "Position partially sold",
                ticker=ticker,
                sold_qty=sold_quantity,
                remaining_qty=remaining_qty,
                realized_pnl=realized_pnl,
            )

        self._current_date = date
        return {
            "success": True,
            "ticker": ticker,
            "quantity_sold": sold_quantity,
            "realized_pnl": realized_pnl,
            "cash": self.cash,
            "trade": trade,
        }

    def mark_to_market(self, prices: dict[str, float], date: str, record_equity: bool = True) -> Any:
        """Mark-to-Market değerlemesi yap."""
        self.update_prices(prices, date, record_equity=record_equity)

    def update_prices(self, prices: dict[str, float], date: str, record_equity: bool = True) -> Any:
        """Fiyatları mark-to-market yap; istenirse gün sonu equity kaydı oluştur."""
        self._current_date = date
        for ticker, price in prices.items():
            if ticker in self._positions:
                self._positions[ticker]["current_price"] = price
                self._positions[ticker]["market_value"] = self._positions[ticker]["quantity"] * price

        total_value = self.get_total_value()
        if total_value > self._max_equity:
            self._max_equity = total_value

        if not record_equity:
            return

        self._equity_curve.append(
            {
                "date": date,
                "equity": total_value,
                "cash": self.cash,
                "settled_cash": self.settled_cash,
                "invested": total_value - self.cash,
            }
        )
        if len(self._equity_curve) > 5000:
            self._equity_curve = self._equity_curve[-5000:]

        if self._state_store:
            self._state_store.save_equity_point(date, total_value, self.cash, total_value - self.cash)

    def apply_corporate_action(
        self,
        ticker: str,
        action_type: str,  # "DIVIDEND", "BONUS_ISSUE", "RIGHTS_ISSUE"
        ratio: float = 0.0,
        cash_amount: float = 0.0,
        date: str = "",
    ) -> dict[str, Any]:
        """KAP Kurumsal İşlemlerini portföye uygula."""
        pos = self._positions.get(ticker)
        if not pos:
            return {"applied": False, "reason": "NO_POSITION"}

        if action_type == "DIVIDEND":
            # Net temettü (10% stopaj düşülerek serbest nakde eklenir)
            net_div_per_share = cash_amount * 0.90
            total_dividend = round(net_div_per_share * pos["quantity"], 2)
            self.settled_cash += total_dividend
            logger.info("Dividend credited", ticker=ticker, shares=pos["quantity"], amount=total_dividend)
            return {"applied": True, "type": "DIVIDEND", "net_amount": total_dividend}

        elif action_type == "BONUS_ISSUE":
            # Bedelsiz bölünme: Lot artar, birim maliyet aynı oranda düşer
            old_qty = pos["quantity"]
            new_qty = int(old_qty * (1.0 + ratio))
            pos["avg_cost"] = round(pos["avg_cost"] / (1.0 + ratio), 4)
            pos["quantity"] = new_qty
            pos["market_value"] = new_qty * pos.get("current_price", pos["avg_cost"])
            logger.info(
                "Bonus issue applied", ticker=ticker, old_qty=old_qty, new_qty=new_qty, new_avg_cost=pos["avg_cost"]
            )
            return {"applied": True, "type": "BONUS_ISSUE", "old_qty": old_qty, "new_qty": new_qty}

        return {"applied": False, "reason": "UNSUPPORTED_ACTION"}

    # ===================== QUERIES =====================

    _price_cache: dict[str, float] = {}
    _price_cache_ts: float = 0.0
    _PRICE_CACHE_TTL: float = 2.0  # saniye

    def _sync_live_prices(self) -> Any:
        """Açık pozisyonların güncel piyasa fiyatlarını Redis radarından eşitler.
        2 saniyelik cache ile Redis baskısını azaltır.
        """
        if not self._positions:
            return
        try:
            import time

            now = time.monotonic()
            if now - self._price_cache_ts < self._PRICE_CACHE_TTL and self._price_cache:
                price_map = self._price_cache
            else:
                from services.core.redis_helper import get_cached

                radar = get_cached("radar:data") or []
                if radar:
                    price_map = {
                        x["symbol"]: float(x["price"])
                        for x in radar
                        if x.get("symbol") and x.get("price") and float(x.get("price")) > 0
                    }
                    self._price_cache = price_map
                    self._price_cache_ts = now
                else:
                    price_map = self._price_cache
            for ticker, pos in self._positions.items():
                if ticker in price_map:
                    live_p = price_map[ticker]
                    pos["current_price"] = live_p
                    pos["market_value"] = pos["quantity"] * live_p
        except Exception:
            logger.warning("Caught Exception in _sync_live_prices", exc_info=True)

    def force_refresh_prices(self, date: str = "") -> dict[str, float]:
        """Açılışta tüm pozisyonların fiyatlarını zorla güncelle.

        Kaynak sırası:
        1. Redis radar cache
        2. PostgreSQL son kapanış fiyatları
        3. Mevcut fiyat (değişmez)

        Güncellenen fiyatları döner.
        """
        if not self._positions:
            return {}

        updated = {}

        # 1. Redis radar
        try:
            from services.core.redis_helper import get_cached

            radar = get_cached("radar:data") or []
            if radar:
                price_map = {
                    x["symbol"]: float(x["price"])
                    for x in radar
                    if x.get("symbol") and x.get("price") and float(x.get("price")) > 0
                }
                for ticker, pos in self._positions.items():
                    if ticker in price_map:
                        pos["current_price"] = price_map[ticker]
                        pos["market_value"] = pos["quantity"] * price_map[ticker]
                        updated[ticker] = price_map[ticker]
        except Exception:
            logger.warning("Caught Exception in force_refresh_prices", exc_info=True)

        # 2. PostgreSQL son kapanış (Redis'te olmayanlar için)
        try:
            missing = [t for t in self._positions if t not in updated]
            if missing:
                import asyncio

                from services.core.database import pg_fetch

                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Async ortamda — background task olarak çalıştır
                    async def _fetch_missing() -> Any:
                        """Otomatik eklendi."""
                        for ticker in missing:
                            rows = await pg_fetch(
                                "SELECT close FROM market_data WHERE ticker=$1 ORDER BY date DESC LIMIT 1", ticker
                            )
                            if rows:
                                price = float(rows[0]["close"])
                                self._positions[ticker]["current_price"] = price
                                self._positions[ticker]["market_value"] = self._positions[ticker]["quantity"] * price
                                updated[ticker] = price

                    # FIX: Task referansı saklandı
                    _fetch_task = asyncio.ensure_future(_fetch_missing())
                    _fetch_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
                else:
                    for ticker in missing:
                        rows = asyncio.run(
                            pg_fetch("SELECT close FROM market_data WHERE ticker=$1 ORDER BY date DESC LIMIT 1", ticker)
                        )
                        if rows:
                            price = float(rows[0]["close"])
                            self._positions[ticker]["current_price"] = price
                            self._positions[ticker]["market_value"] = self._positions[ticker]["quantity"] * price
                            updated[ticker] = price
        except Exception:
            logger.warning("Caught Exception in force_refresh_prices", exc_info=True)

        if updated and date:
            self.update_prices(updated, date, record_equity=True)

        logger.info(
            "Force price refresh completed",
            total_positions=len(self._positions),
            updated=len(updated),
            tickers=list(updated.keys()),
        )
        return updated

    def get_total_value(self) -> float:
        """Toplam portföy net aktif değeri (NAV = Toplam Nakit + Pozisyonlar)."""
        self._sync_live_prices()
        invested = sum(p.get("market_value", 0.0) for p in self._positions.values())
        return self.total_cash + invested

    def get_invested_value(self) -> float:
        """Otomatik eklendi."""
        self._sync_live_prices()
        return sum(p.get("market_value", 0.0) for p in self._positions.values())

    def get_unrealized_pnl(self) -> float:
        """Otomatik eklendi."""
        self._sync_live_prices()
        total = 0.0
        for pos in self._positions.values():
            cost = pos.get("avg_cost", 0.0)
            price = pos.get("current_price", cost)
            qty = pos.get("quantity", 0)
            if cost > 0:
                total += (price - cost) * qty
        return total

    def get_position(self, ticker: str) -> dict[str, Any] | None:
        """Otomatik eklendi."""
        self._sync_live_prices()
        return self._positions.get(ticker)

    def get_all_positions(self) -> list[dict[str, Any]]:
        """Açık pozisyonları şirket adı, anlık kâr/zarar ve portföy ağırlığıyla zenginleştirerek döner."""
        self._sync_live_prices()
        try:
            from services.ingestion.bist_universe import bist_universe

            company_names = getattr(bist_universe, "COMPANY_NAMES", {})
        except Exception:
            company_names = {}

        total_val = self.get_total_value()
        result = []

        for p in self._positions.values():
            pos = dict(p)
            ticker = pos.get("ticker", "")
            cost = float(pos.get("avg_cost", 0.0))
            price = float(pos.get("current_price", cost))
            qty = int(pos.get("quantity", 0))
            m_val = float(pos.get("market_value", qty * price))

            unrealized = (price - cost) * qty if cost > 0 else 0.0
            unrealized_pct = ((price / max(cost, 1e-6)) - 1.0) * 100.0 if cost > 0 else 0.0
            weight = (m_val / max(total_val, 1.0)) * 100.0 if total_val > 0 else 0.0

            c_name = company_names.get(ticker, ticker)
            pos["symbol"] = ticker
            pos["name"] = c_name
            pos["company_name"] = c_name
            pos["unrealized_pnl"] = round(unrealized, 2)
            pos["unrealized_pnl_pct"] = round(unrealized_pct, 2)
            pos["weight_pct"] = round(weight, 2)
            pos["market_value"] = round(m_val, 2)
            pos["avg_cost"] = round(cost, 2)
            pos["current_price"] = round(price, 2)
            pos["side"] = "LONG"
            pos["status"] = "ACTIVE"
            result.append(pos)

        # Portföy ağırlığına göre büyükten küçüğe sırala
        result.sort(key=lambda x: x.get("market_value", 0.0), reverse=True)
        return result

    def get_orders(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Emir geçmişini yükle."""
        orders = []
        if self._state_store:
            try:
                orders = self._state_store.load_orders()
            except Exception:
                orders = []
        if not orders and self._orders:
            orders = list(self._orders)
        elif not orders and self._positions:
            for pos in self._positions.values():
                orders.append(
                    {
                        "date": pos.get("entry_date", datetime.now(UTC).strftime("%Y-%m-%d")),
                        "order_id": f"ORD_{pos.get('ticker')}_1",
                        "ticker": pos.get("ticker"),
                        "side": "BUY",
                        "quantity": pos.get("quantity"),
                        "signal_price": round(float(pos.get("avg_cost", 0.0)) * 0.999, 2),
                        "execution_price": round(float(pos.get("avg_cost", 0.0)), 2),
                        "slippage_pct": 0.085,
                        "commission": round(float(pos.get("market_value", 0.0)) * 0.0002, 2),
                        "status": "FILLED",
                    }
                )

        if limit and orders:
            orders = orders[:limit]
        return orders

    def get_sector_weights(self) -> dict[str, float]:
        """Sektörel ağırlıklar."""
        total = self.get_total_value()
        if total <= 0:
            return {}
        sector_values = defaultdict(float)
        for pos in self._positions.values():
            sector_values[pos.get("sector", "UNKNOWN")] += pos["market_value"]
        return {s: round(v / total, 4) for s, v in sector_values.items()}

    def get_position_weights(self) -> dict[str, float]:
        """Hisse bazlı ağırlıklar."""
        total = self.get_total_value()
        if total <= 0:
            return {}
        return {t: round(p["market_value"] / total, 4) for t, p in self._positions.items()}

    def get_trades(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Otomatik eklendi."""
        if self._trades:
            trades = self._trades
        elif self._state_store:
            try:
                trades = self._state_store.load_trades()
            except Exception:
                trades = []
        else:
            trades = []

        if limit and trades:
            trades = trades[:limit]
        return trades

    def get_equity_curve(self) -> list[dict[str, Any]]:
        """Otomatik eklendi."""
        if self._equity_curve:
            return self._equity_curve
        if self._state_store:
            try:
                return self._state_store.load_equity_curve()
            except Exception:
                logger.warning("Caught Exception in get_equity_curve", exc_info=True)
        return []

    def get_position_history(self, ticker: str = "", limit: int | None = None) -> list[dict[str, Any]]:
        """Kapanmış veya devam eden tüm pozisyon değişikliklerini liste olarak döner."""
        trades = self.get_trades(limit=None)
        if ticker:
            trades = [t for t in trades if t.get("ticker") == ticker]
        if limit:
            trades = trades[:limit]
        return trades

    def get_equity_snapshots(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Zaman serisi olarak bakiye geçmişini döner."""
        curve = self.get_equity_curve()
        if limit:
            return curve[-limit:]
        return curve

    def deposit_cash(self, amount: float, description: str = "") -> float:
        """Portföye nakit ekler ve toplam bakiye/özsermayeyi günceller."""
        self.settled_cash += amount
        self.save_to_store(self._current_date or datetime.now(UTC).strftime("%Y-%m-%d"))
        logger.info("Cash deposited to portfolio", amount=amount, new_cash=self.cash, desc=description)
        return self.cash

    def get_portfolio(self) -> dict[str, Any]:
        """Geriye dönük uyumluluk için portföy özetini döner."""
        return self.get_summary()

    def get_max_drawdown(self) -> float:
        """Maksimum drawdown yüzdesi (0.0 - 100.0)."""
        if not self._equity_curve:
            return 0.0
        peak = self.initial_capital
        max_dd = 0.0
        for pt in self._equity_curve:
            eq = pt["equity"]
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (peak - eq) / peak
                if dd > max_dd:
                    max_dd = dd
        return max_dd * 100.0

    def get_current_drawdown(self) -> float:
        """Güncel portföy değerinin zirveye göre drawdown yüzdesi (0.0 - 100.0)."""
        if self._max_equity <= 0:
            return 0.0
        if self._equity_curve:
            tot = self._equity_curve[-1].get("equity", self.get_total_value())
        else:
            tot = self.get_total_value()
        return max(0.0, ((self._max_equity - tot) / self._max_equity) * 100.0)

    def get_summary(self) -> dict[str, Any]:
        """Portföy özet metrikleri."""
        total_val = self.get_total_value()
        unrealized = self.get_unrealized_pnl()
        realized = sum(t.get("realized_pnl", 0) for t in self._trades)
        total_pnl = total_val - self.initial_capital
        total_return_pct = (total_val / self.initial_capital - 1) * 100 if self.initial_capital > 0 else 0

        # Win rate
        closed_trades = [t for t in self._trades if "realized_pnl" in t]
        winning = [t for t in closed_trades if t["realized_pnl"] > 0]
        win_rate = len(winning) / len(closed_trades) if closed_trades else 0.0

        return {
            "initial_capital": self.initial_capital,
            "total_value": round(total_val, 2),
            "total_cash": round(self.total_cash, 2),
            "purchasing_power": round(self.purchasing_power, 2),
            "withdrawable_cash": round(self.withdrawable_cash, 2),
            "cash": round(self.cash, 2),
            "settled_cash": round(self.settled_cash, 2),
            "unsettled_cash_t1": round(self.unsettled_cash_t1, 2),
            "unsettled_cash_t2": round(self.unsettled_cash_t2, 2),
            "invested_value": round(self.get_invested_value(), 2),
            "unrealized_pnl": round(unrealized, 2),
            "realized_pnl": round(realized, 2),
            "total_pnl": round(total_pnl, 2),
            "total_return_pct": round(total_return_pct, 2),
            "max_drawdown_pct": round(self.get_max_drawdown(), 2),
            "num_positions": len(self._positions),
            "num_trades": len(self._trades),
            "win_rate": round(win_rate, 4),
            "sector_weights": self.get_sector_weights(),
            "last_date": self._current_date,
        }

    def _holding_days(self, entry_date: str | None, exit_date: str) -> int:
        """İki tarih arası gün sayısı."""
        if not entry_date or not exit_date:
            return 0
        try:
            d1 = datetime.fromisoformat(entry_date)
            d2 = datetime.fromisoformat(exit_date)
            return max(0, (d2 - d1).days)
        except (ValueError, TypeError):
            return 0

    get_portfolio_summary = get_summary


# Singleton
virtual_portfolio = VirtualPortfolio()
