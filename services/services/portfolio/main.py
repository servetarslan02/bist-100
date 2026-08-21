"""ALPHA BIST - Portfolio Service v2.0

v2.0: PortfolioManager v2.0 muhasebe altyapısıyla uyumlu.
- Cash ledger, position history, equity snapshots DB'ye persist edilir.
- Realized P&L, commission, weighted average cost doğru hesaplanır.
- EQUITY = CASH + MARKET_VALUE invariant korunur.
- Tek gerçek muhasebe kaynağı: PortfolioManager v2.0 + DB.
"""

import asyncio
import os
import json
from datetime import datetime, timezone, date
from typing import Dict, List, Any, Optional
import structlog

from ..core.config import settings
from ..core.database_dev import dev_db
from ..core.db_lock import CoordinatedLock, get_lock_metrics, get_all_metrics, get_health_report, portfolio_trade_lock
from ..core.config_watcher import ConfigWatcher
from ..portfolio.portfolio_manager import (
    PortfolioManager, CommissionModel,
)

logger = structlog.get_logger()


class PortfolioService:
    """Async DB-backed portfolio service — v2.0 muhasebe ile uyumlu.

    Thread-safety:
    - _trade_lock: Aynı anda yalnızca tek alım/satım işlemi
    - Her kritik işlem sonrası invariant doğrulama
    - DB transaction içinde atomik işlemler
    """

    def __init__(self, initial_capital: float = 100000.0):
        self._running = False
        self._portfolio_id: Optional[int] = None
        self._pm = PortfolioManager(initial_capital=initial_capital)
        self._commission_model = CommissionModel()
        self._position_cache: Dict[str, Dict] = {}
        self._last_snapshot_date: str = ""
        self._daily_realized_pnl: float = 0.0
        self._daily_commission: float = 0.0
        self._trade_lock = asyncio.Lock()  # Fallback in-process lock
        self._coordinated_lock: Optional[CoordinatedLock] = None  # Initialized in start()

    # =====================================================
    # LIFECYCLE
    # =====================================================

    async def start(self):
        """Servisi başlat (state lock ile)."""
        logger.info("Starting Portfolio Service v2.0")
        if dev_db._db is None:
            await dev_db.init()

        # Coordinated lock (asyncio + DB) oluştur
        dialect = "sqlite" if hasattr(dev_db._db, 'execute') else "postgresql"
        self._coordinated_lock = CoordinatedLock(
            dev_db._db, dialect=dialect, key="portfolio_trade", timeout_ms=10000
        )

        # Portfolio initialization lock (multi-instance safety)
        async with self._trade_lock:
            self._portfolio_id = await dev_db.ensure_default_portfolio()
            await self._load_state()
            self._running = True

        # Config watcher başlat
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "..", "config", "alpha_config.json")
        if os.path.exists(config_path):
            self._config_watcher = ConfigWatcher(
                config_path, reload_fn=self._on_config_change, watch_interval_s=5.0
            )
            self._config_watcher.start()

        logger.info("Portfolio Service v2.0 started", portfolio_id=self._portfolio_id)

    async def stop(self):
        """Servisi durdur."""
        self._running = False
        if self._config_watcher:
            self._config_watcher.stop()
        if self._portfolio_id:
            try:
                await self._save_equity_snapshot()
            except Exception as e:
                logger.debug("Handled exception", error=str(e), context="main.py:90")
                pass
        logger.info("Portfolio Service v2.0 stopped")

    def _on_config_change(self, new_config: Dict[str, Any]):
        """Config değişikliğinde çağrılır."""
        try:
            # Risk limitlerini güncelle
            risk = new_config.get("risk", {})
            if risk:
                logger.info("Risk config updated", risk=risk)
            # Portfolio ayarlarını güncelle
            pf_config = new_config.get("portfolio", {})
            if pf_config:
                logger.info("Portfolio config updated", portfolio=pf_config)
        except Exception as e:
            logger.warning("Config change handler failed", error=str(e))

    # =====================================================
    # STATE LOAD / SAVE
    # =====================================================

    @staticmethod
    def _safe_parse_ts(raw) -> datetime:
        """Timestamp'i güvenli şekilde datetime'a çevir."""
        if not raw:
            return datetime.now(timezone.utc)
        if isinstance(raw, datetime):
            return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
        try:
            s = str(raw).strip()
            # ISO format: 2026-08-17T04:00:00+00:00 veya 2026-08-17 04:00:00
            if '+' in s or s.endswith('Z'):
                return datetime.fromisoformat(s.replace('Z', '+00:00'))
            # Naive timestamp → UTC varsay
            dt = datetime.fromisoformat(s)
            return dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return datetime.now(timezone.utc)

    async def _load_state(self):
        """DB'den portföy durumunu eksiksiz yükle.

        Restore edilen alanlar:
        - Pozisyonlar (quantity, avg_cost, entry_commission, current_price)
        - Cash balance
        - Realized P&L total
        - Commission total (position_history'den)
        - Trade geçmişi (position_history'den)
        - High-water mark (equity_snapshots'dan)
        - Equity curve (equity_snapshots'dan)
        - Daily P&L (daily_pnl tablosundan)
        - Position cache
        """
        from ..portfolio.portfolio_manager import Position, Trade

        # 1. Portfolio bilgisi
        pf = await dev_db.pg_fetchrow(
            "SELECT * FROM portfolios WHERE id = ?", self._portfolio_id
        )
        if pf:
            self._pm._cash = float(pf["cash_balance"])
            self._pm._initial_capital = float(pf["initial_capital"])
            self._pm._realized_pnl_total = float(pf.get("total_pnl") or 0)

        # 2. Pozisyonları yükle (entry_commission dahil)
        rows = await dev_db.pg_fetch("""
            SELECT p.*, i.symbol as ticker
            FROM positions p
            JOIN instruments i ON p.instrument_id = i.id
            WHERE p.portfolio_id = ? AND p.status = 'OPEN'
        """, self._portfolio_id)

        for row in rows:
            ticker = row["ticker"]
            qty = int(row["quantity"])
            avg_cost = float(row["avg_cost"])
            entry_comm = float(row.get("entry_commission") or 0)
            current_price = float(row.get("current_price") or avg_cost)

            self._pm._positions[ticker] = Position(
                ticker=ticker,
                direction="LONG",
                quantity=qty,
                entry_price=avg_cost,
                entry_commission=entry_comm,
                current_price=current_price,
            )

            self._position_cache[ticker] = {
                "id": row["id"],
                "instrument_id": row["instrument_id"],
                "quantity": qty,
                "avg_cost": avg_cost,
                "current_price": current_price,
            }

        # 3. Commission total (position_history SUM'dan)
        comm_hist = await dev_db.pg_fetch(
            "SELECT SUM(commission) as total FROM position_history WHERE portfolio_id = ?",
            self._portfolio_id
        )
        if comm_hist and comm_hist[0].get("total"):
            self._pm._commission_total = float(comm_hist[0]["total"])

        # 4. Trade geçmişini position_history'den restore et
        closed_trades = await dev_db.pg_fetch("""
            SELECT ph.*, i.symbol as ticker
            FROM position_history ph
            LEFT JOIN instruments i ON i.symbol = ph.ticker
            WHERE ph.portfolio_id = ? AND ph.action IN ('CLOSE', 'REDUCE')
            ORDER BY ph.id ASC
        """, self._portfolio_id)

        for ct in closed_trades:
            trade = Trade(
                trade_id=ct.get("reference_id") or f"RESTORE_{ct['id']}",
                ticker=ct["ticker"],
                direction=ct["direction"],
                entry_price=float(ct.get("avg_cost_before") or 0),
                exit_price=float(ct["price"]),
                quantity=int(ct["quantity"]),
                entry_time=self._safe_parse_ts(ct.get("created_at")),
                exit_time=self._safe_parse_ts(ct.get("created_at")),
                commission=float(ct.get("commission") or 0),
                realized_pnl=float(ct.get("realized_pnl") or 0),
            )
            self._pm._trades.append(trade)

        # 5. High-water mark + equity snapshots
        all_snapshots = await dev_db.pg_fetch(
            "SELECT * FROM equity_snapshots WHERE portfolio_id = ? ORDER BY id ASC",
            self._portfolio_id
        )
        for snap in all_snapshots:
            self._pm._equity_curve.append({
                "timestamp": snap.get("created_at", ""),
                "equity": float(snap["total_equity"]),
                "cash": float(snap["cash"]),
                "invested": float(snap["invested"]),
            })
        if all_snapshots:
            last = all_snapshots[-1]
            self._pm._high_water_mark = float(last["high_water_mark"])
            self._last_snapshot_date = last["snapshot_date"]

        # 6. Daily P&L restore
        try:
            daily_rows = await dev_db.pg_fetch(
                "SELECT * FROM daily_pnl WHERE portfolio_id = ? ORDER BY pnl_date ASC",
                self._portfolio_id
            )
            for dr in daily_rows:
                self._pm._daily_pnl.append({
                    "date": dr["pnl_date"],
                    "realized": float(dr.get("realized_pnl") or 0),
                    "unrealized": float(dr.get("unrealized_pnl") or 0),
                    "commission": float(dr.get("commission") or 0),
                    "net": float(dr.get("net_pnl") or 0),
                    "equity_start": float(dr.get("equity_start") or 0),
                    "equity_end": float(dr.get("equity_end") or 0),
                })
        except Exception as e:
            pass  # daily_pnl tablosu yoksa atla

        # 7. Invariant doğrula
        acc = self._pm.get_accounting_summary()
        if not acc["invariant_check"]:
            logger.warning("INVARIANT VIOLATION after load",
                         equity=acc["total_equity"],
                         cash=acc["cash"],
                         mv=acc["market_value"])

        logger.info("State fully restored",
                   positions=len(self._pm._positions),
                   trades=len(self._pm._trades),
                   cash=self._pm._cash,
                   realized_pnl=self._pm._realized_pnl_total,
                   commission_total=self._pm._commission_total,
                   hwm=self._pm._high_water_mark,
                   equity_curve_points=len(self._pm._equity_curve),
                   daily_pnl_points=len(self._pm._daily_pnl))

    async def get_closed_positions(self, limit: int = 50) -> List[Dict]:
        """Kapalı pozisyonların tarihsel kayıtları.

        ticker doğrudan position_history'den alınır (instruments JOIN yok).
        Böylece instrument silinse bile kayıtlar korunur.
        """
        rows = await dev_db.pg_fetch("""
            SELECT * FROM position_history
            WHERE portfolio_id = ? AND action = 'CLOSE'
            ORDER BY id DESC LIMIT ?
        """, self._portfolio_id, limit)
        return rows

    async def get_daily_pnl_history(self, limit: int = 252) -> List[Dict]:
        """Günlük P&L geçmişi."""
        try:
            rows = await dev_db.pg_fetch(
                "SELECT * FROM daily_pnl WHERE portfolio_id = ? ORDER BY pnl_date DESC LIMIT ?",
                self._portfolio_id, limit
            )
            return rows
        except Exception as e:
            return []

    async def _update_daily_pnl(self, realized_pnl: float, commission: float):
        """İşlem sonrası daily_pnl tablosunu güncelle.

        Aynı gün için INSERT OR UPDATE yapar (UPSERT mantığı).
        """
        today = date.today().isoformat()
        try:
            pf = self._pm.get_portfolio()
            net = realized_pnl - commission

            # Mevcut gün kaydı var mı?
            existing = await dev_db.pg_fetchrow(
                "SELECT id, realized_pnl, commission, net_pnl FROM daily_pnl WHERE portfolio_id = ? AND pnl_date = ?",
                self._portfolio_id, today
            )

            if existing:
                # Güncelle
                new_realized = float(existing["realized_pnl"]) + realized_pnl
                new_commission = float(existing["commission"]) + commission
                new_net = new_realized - new_commission
                await dev_db.pg_execute(
                    "UPDATE daily_pnl SET realized_pnl = ?, commission = ?, net_pnl = ?, equity_end = ? WHERE id = ?",
                    round(new_realized, 2), round(new_commission, 2), round(new_net, 2),
                    round(pf["total_value"], 2), existing["id"]
                )
            else:
                # Yeni gün kaydı
                await dev_db.pg_execute(
                    "INSERT INTO daily_pnl (portfolio_id, pnl_date, realized_pnl, unrealized_pnl, commission, net_pnl, equity_start, equity_end) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    self._portfolio_id, today,
                    round(realized_pnl, 2),
                    round(pf["unrealized_pnl"], 2),
                    round(commission, 2),
                    round(net, 2),
                    round(pf["total_value"] - net, 2),
                    round(pf["total_value"], 2)
                )
        except Exception as e:
            logger.warning("Daily P&L update failed", error=str(e))

    # =====================================================
    # TRADE EXECUTION — v2.0 Muhasebe
    # =====================================================

    def _verify_invariant(self, context: str):
        """EQUITY = CASH + MARKET_VALUE invariant doğrula."""
        acc = self._pm.get_accounting_summary()
        if not acc["invariant_check"]:
            logger.critical("INVARIANT VIOLATION",
                         context=context,
                         equity=acc["total_equity"],
                         cash=acc["cash"],
                         mv=acc["market_value"])
            raise RuntimeError(
                f"Portfolio invariant ihlali ({context}): "
                f"EQUITY={acc['total_equity']} != CASH={acc['cash']} + MV={acc['market_value']}"
            )



    async def execute_buy(
        self,
        ticker: str,
        quantity: int,
        price: float,
        instrument_id: int = 0,
        stop_price: float = 0.0,
        target_price: float = 0.0,
        sector: str = "",
    ) -> Dict[str, Any]:
        """Alım işlemi — v2.0 muhasebe ile (race-safe)."""
        if not self._running:
            return {"success": False, "error": "Servis çalışmıyor"}

        lock = self._coordinated_lock or self._trade_lock
        try:
            if isinstance(lock, CoordinatedLock):
                async with lock:
                    return await self._execute_buy_atomic(
                        ticker, quantity, price, instrument_id,
                        stop_price, target_price, sector
                    )
            else:
                async with lock:
                    return await self._execute_buy_atomic(
                        ticker, quantity, price, instrument_id,
                        stop_price, target_price, sector
                    )
        except RuntimeError as e:
            return {"success": False, "error": str(e)}

    async def execute_sell(
        self,
        ticker: str,
        quantity: int,
        price: float,
        instrument_id: int = 0,
    ) -> Dict[str, Any]:
        """Satış işlemi — v2.0 muhasebe ile (race-safe)."""
        if not self._running:
            return {"success": False, "error": "Servis çalışmıyor"}

        lock = self._coordinated_lock or self._trade_lock
        try:
            if isinstance(lock, CoordinatedLock):
                async with lock:
                    return await self._execute_sell_atomic(
                        ticker, quantity, price, instrument_id
                    )
            else:
                async with lock:
                    return await self._execute_sell_atomic(
                        ticker, quantity, price, instrument_id
                    )
        except RuntimeError as e:
            return {"success": False, "error": str(e)}

    async def update_prices(self, prices: Dict[str, float]):
        """Fiyat güncelle + equity snapshot."""
        self._pm.update_prices(prices)

        # Cache güncelle
        for ticker, price in prices.items():
            if ticker in self._position_cache:
                self._position_cache[ticker]["current_price"] = price

        # DB pozisyon fiyatlarını güncelle
        try:
            for ticker, price in prices.items():
                if ticker in self._position_cache:
                    await dev_db.pg_execute(
                        "UPDATE positions SET current_price = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        price, self._position_cache[ticker]["id"]
                    )
        except Exception as e:
            logger.debug("Handled exception", error=str(e), context="main.py:432")
            pass

        # Portfolio totals güncelle
        try:
            await self._update_portfolio_totals()
        except Exception as e:
            logger.debug("Handled exception", error=str(e), context="main.py:438")
            pass

        # Günlük snapshot
        try:
            await self._save_equity_snapshot()
        except Exception as e:
            logger.debug("Handled exception", error=str(e), context="main.py:444")
            pass

    # =====================================================
    # DB PERSISTENCE
    # =====================================================

    async def _execute_buy_atomic(
        self, ticker, quantity, price, instrument_id,
        stop_price, target_price, sector
    ) -> Dict[str, Any]:
        """Atomik alım işlemi (lock altında çağrılır)."""
        commission = self._commission_model.calculate(quantity * price)

        # In-process cash kontrolü
        if self._pm._cash < quantity * price + commission:
            return {"success": False, "error": "Yetersiz nakit"}

        # DB'den güncel cash oku (multi-instance tutarlılığı)
        try:
            pf_row = await dev_db.pg_fetchrow(
                "SELECT cash_balance FROM portfolios WHERE id = ?", self._portfolio_id
            )
            db_cash = float(pf_row["cash_balance"]) if pf_row else self._pm._cash
            if db_cash < quantity * price + commission:
                return {"success": False, "error": "Yetersiz nakit (DB)"}
        except Exception as e:
            logger.warning("DB cash read failed — using in-memory", error=str(e), ticker=ticker)

        result = self._pm.open_position(
            ticker=ticker, direction="LONG", quantity=quantity,
            price=price, stop_price=stop_price, target_price=target_price,
            sector=sector, commission=commission,
        )

        if not result.get("success"):
            return result

        await self._persist_buy(ticker, quantity, price, commission, instrument_id)
        self._verify_invariant(f"BUY {ticker}")
        return result

    async def _execute_sell_atomic(
        self, ticker, quantity, price, instrument_id
    ) -> Dict[str, Any]:
        """Atomik satış işlemi (lock altında çağrılır)."""
        if ticker not in self._pm._positions:
            return {"success": False, "error": f"{ticker} pozisyonu yok"}

        pos = self._pm._positions[ticker]

        # Oversell kontrolü
        if quantity > pos.quantity:
            return {"success": False, "error": f"Oversell: {quantity} > mevcut {pos.quantity}"}

        # Atomik pozisyon azaltma (DB-level)
        if quantity >= pos.quantity:
            update_result = await dev_db.pg_execute(
                "UPDATE positions SET quantity = 0, status = 'CLOSED', entry_commission = 0, updated_at = CURRENT_TIMESTAMP WHERE portfolio_id = ? AND instrument_id = ? AND status = 'OPEN' AND quantity >= ?",
                self._portfolio_id, instrument_id, quantity
            )
            if "OK 0" in str(update_result):
                return {"success": False, "error": "Oversell (DB atomic): yeterli pozisyon yok"}
        else:
            update_result = await dev_db.pg_execute(
                "UPDATE positions SET quantity = quantity - ?, updated_at = CURRENT_TIMESTAMP WHERE portfolio_id = ? AND instrument_id = ? AND status = 'OPEN' AND quantity >= ?",
                quantity, self._portfolio_id, instrument_id, quantity
            )
            if "OK 0" in str(update_result):
                return {"success": False, "error": "Oversell (DB atomic): yeterli pozisyon yok"}

        if quantity >= pos.quantity:
            commission = self._commission_model.calculate(quantity * price)
            result = self._pm.close_position(ticker, price, commission)
        else:
            commission = self._commission_model.calculate(quantity * price)
            result = self._pm._reduce_position(ticker, "SHORT", quantity, price, commission)

        if result.get("success"):
            realized = result.get("realized_pnl", 0)
            await self._persist_sell(ticker, quantity, price, commission, result, instrument_id)
            await self._update_daily_pnl(realized, commission)
            self._verify_invariant(f"SELL {ticker}")

        return result

    def get_lock_metrics(self) -> Dict[str, Any]:
        """Lock performans metrikleri."""
        return get_all_metrics()

    def get_health_status(self) -> Dict[str, Any]:
        """Portfolio servis sağlık durumu (lock durumu dahil)."""
        lock_health = get_health_report()
        pf = self._pm.get_portfolio()
        acc = self._pm.get_accounting_summary()

        issues = []
        if lock_health["overall_status"] != "HEALTHY":
            issues.append(f"lock_status:{lock_health['overall_status']}")
        if not acc.get("invariant_check", True):
            issues.append("invariant_violation")
        if pf.get("cash", 0) < 0:
            issues.append("negative_cash")

        status = "HEALTHY" if not issues else "DEGRADED" if len(issues) <= 1 else "UNHEALTHY"
        return {
            "status": status,
            "issues": issues,
            "portfolio": {
                "cash": pf.get("cash", 0),
                "total_value": pf.get("total_value", 0),
                "positions_count": pf.get("positions_count", 0),
                "invariant_check": acc.get("invariant_check", True),
            },
            "locks": lock_health,
        }

    async def _persist_buy(self, ticker: str, quantity: int, price: float, commission: float, instrument_id: int):
        """Alımı DB'ye kaydet."""
        cost = quantity * price

        # Portfolio cash güncelle
        await dev_db.pg_execute(
            "UPDATE portfolios SET cash_balance = cash_balance - ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            cost + commission, self._portfolio_id
        )

        # Pozisyon güncelle/oluştur
        existing = await dev_db.pg_fetchrow(
            "SELECT id, quantity, avg_cost FROM positions WHERE portfolio_id = ? AND instrument_id = ? AND status = 'OPEN'",
            self._portfolio_id, instrument_id
        )

        if existing:
            old_qty = int(existing["quantity"])
            old_avg = float(existing["avg_cost"])
            old_comm = float(existing.get("entry_commission") or 0)
            new_qty = old_qty + quantity
            new_avg = (old_avg * old_qty + price * quantity) / new_qty
            new_comm = old_comm + commission
            await dev_db.pg_execute(
                "UPDATE positions SET quantity = ?, avg_cost = ?, entry_commission = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                new_qty, round(new_avg, 4), round(new_comm, 4), existing["id"]
            )
            pos_id = existing["id"]
        else:
            await dev_db.pg_execute(
                "INSERT INTO positions (portfolio_id, instrument_id, quantity, avg_cost, entry_commission, current_price, entry_date, status) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 'OPEN')",
                self._portfolio_id, instrument_id, quantity, round(price, 4), round(commission, 4), price
            )
            row = await dev_db.pg_fetchrow("SELECT id FROM positions WHERE portfolio_id = ? AND instrument_id = ? AND status = 'OPEN' ORDER BY id DESC LIMIT 1", self._portfolio_id, instrument_id)
            pos_id = row["id"] if row else 0

        # Cash ledger kaydet
        balance = self._pm._cash
        await dev_db.pg_execute(
            "INSERT INTO cash_ledger (portfolio_id, amount, balance_after, entry_type, description, ticker) VALUES (?, ?, ?, 'BUY', ?, ?)",
            self._portfolio_id, -(cost + commission), round(balance, 2),
            f"BUY {quantity} {ticker} @ {price:.4f} (komisyon: {commission:.2f})", ticker
        )

        # Position history kaydet
        pos = self._pm._positions.get(ticker)
        await dev_db.pg_execute(
            "INSERT INTO position_history (portfolio_id, ticker, action, direction, quantity, price, commission, avg_cost_before, avg_cost_after, quantity_before, quantity_after, realized_pnl) VALUES (?, ?, 'OPEN', 'LONG', ?, ?, ?, 0, ?, 0, ?, 0)",
            self._portfolio_id, ticker, quantity, price, commission,
            round(pos.entry_price, 4) if pos else price, quantity
        )

        # Cache güncelle
        self._position_cache[ticker] = {
            "id": pos_id,
            "instrument_id": instrument_id,
            "quantity": self._pm._positions[ticker].quantity if ticker in self._pm._positions else quantity,
            "avg_cost": self._pm._positions[ticker].entry_price if ticker in self._pm._positions else price,
            "current_price": price,
        }

    async def _persist_sell(self, ticker: str, quantity: int, price: float, commission: float, result: Dict, instrument_id: int = 0):
        """Satışı DB'ye kaydet."""
        realized_pnl = result.get("realized_pnl", 0)

        # Instrument ID bul (instruments tablosundaki ID)
        if not instrument_id:
            cached = self._position_cache.get(ticker)
            if cached:
                instrument_id = cached.get("instrument_id", 0)

        # Portfolio cash güncelle
        revenue = quantity * price - commission
        await dev_db.pg_execute(
            "UPDATE portfolios SET cash_balance = cash_balance + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            revenue, self._portfolio_id
        )

        # Pozisyon zaten atomik olarak güncellendi (execute_sell'de)
        # Burada sadece entry_commission güncelle
        if ticker in self._pm._positions:
            pos = self._pm._positions[ticker]
            await dev_db.pg_execute(
                "UPDATE positions SET entry_commission = ?, updated_at = CURRENT_TIMESTAMP WHERE portfolio_id = ? AND instrument_id = ? AND status = 'OPEN'",
                round(pos.entry_commission, 4), self._portfolio_id, instrument_id
            )
        else:
            # Pozisyon zaten kapatıldı — cache temizle
            self._position_cache.pop(ticker, None)

        # Cash ledger
        balance = self._pm._cash
        await dev_db.pg_execute(
            "INSERT INTO cash_ledger (portfolio_id, amount, balance_after, entry_type, description, ticker) VALUES (?, ?, ?, 'SELL', ?, ?)",
            self._portfolio_id, revenue, round(balance, 2),
            f"SELL {quantity} {ticker} @ {price:.4f} (P&L: {realized_pnl:.2f}, komisyon: {commission:.2f})", ticker
        )

        # Position history
        action = "CLOSE" if ticker not in self._pm._positions else "REDUCE"
        pos_before = self._pm._positions.get(ticker)
        await dev_db.pg_execute(
            "INSERT INTO position_history (portfolio_id, ticker, action, direction, quantity, price, commission, avg_cost_before, avg_cost_after, quantity_before, quantity_after, realized_pnl) VALUES (?, ?, ?, 'LONG', ?, ?, ?, ?, ?, ?, ?, ?)",
            self._portfolio_id, ticker, action, quantity, price, commission,
            0, round(pos_before.entry_price, 4) if pos_before else 0,
            quantity + (pos_before.quantity if pos_before else 0),
            pos_before.quantity if pos_before else 0, realized_pnl
        )

        # Toplam P&L güncelle
        await dev_db.pg_execute(
            "UPDATE portfolios SET total_pnl = total_pnl + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            realized_pnl, self._portfolio_id
        )

    async def _update_portfolio_totals(self):
        """Portfolio toplamlarını DB'ye yaz."""
        if not self._portfolio_id:
            return
        pf = self._pm.get_portfolio()
        acc = self._pm.get_accounting_summary()

        await dev_db.pg_execute(
            "UPDATE portfolios SET cash_balance = ?, invested_value = ?, current_capital = ?, total_return_pct = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            pf["cash"], pf["invested_value"], pf["total_value"],
            acc["return_on_equity_pct"], self._portfolio_id
        )

    async def _save_equity_snapshot(self):
        """Günlük equity snapshot + daily_pnl DB'ye kaydet."""
        if not self._portfolio_id:
            return
        today = date.today().isoformat()
        if today == self._last_snapshot_date:
            return

        try:
            pf = self._pm.get_portfolio()
            acc = self._pm.get_accounting_summary()

            # Equity snapshot
            await dev_db.pg_execute(
                "INSERT INTO equity_snapshots (portfolio_id, snapshot_date, total_equity, cash, invested, unrealized_pnl, realized_pnl_today, commission_today, positions_count, high_water_mark, drawdown_from_hwm) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._portfolio_id, today,
                pf["total_value"], pf["cash"], pf["invested_value"],
                pf["unrealized_pnl"], self._daily_realized_pnl, self._daily_commission,
                pf["positions_count"], acc["high_water_mark"], acc["drawdown_pct"]
            )

            # Daily P&L
            net_pnl = self._daily_realized_pnl - self._daily_commission
            await dev_db.pg_execute(
                "INSERT OR IGNORE INTO daily_pnl (portfolio_id, pnl_date, realized_pnl, unrealized_pnl, commission, net_pnl, equity_start, equity_end) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                self._portfolio_id, today,
                round(self._daily_realized_pnl, 2),
                round(pf["unrealized_pnl"], 2),
                round(self._daily_commission, 2),
                round(net_pnl, 2),
                round(pf["total_value"] - net_pnl, 2),
                round(pf["total_value"], 2)
            )

            self._last_snapshot_date = today
            self._daily_realized_pnl = 0.0
            self._daily_commission = 0.0
        except Exception as e:
            logger.warning("Equity snapshot save failed", error=str(e))

    # =====================================================
    # QUERIES — DB-backed
    # =====================================================

    async def get_portfolio(self) -> Dict[str, Any]:
        """Portföy durumu (in-memory + DB doğrulama)."""
        return self._pm.get_portfolio()

    async def get_accounting(self) -> Dict[str, Any]:
        """Muhasebe özeti."""
        return self._pm.get_accounting_summary()

    async def get_cash_ledger(self, limit: int = 100) -> List[Dict]:
        """DB'den nakit hareket geçmişi."""
        rows = await dev_db.pg_fetch(
            "SELECT * FROM cash_ledger WHERE portfolio_id = ? ORDER BY id DESC LIMIT ?",
            self._portfolio_id, limit
        )
        return rows

    async def get_position_history(self, ticker: str = "", limit: int = 100) -> List[Dict]:
        """DB'den pozisyon geçmişi."""
        if ticker:
            rows = await dev_db.pg_fetch(
                "SELECT * FROM position_history WHERE portfolio_id = ? AND ticker = ? ORDER BY id DESC LIMIT ?",
                self._portfolio_id, ticker, limit
            )
        else:
            rows = await dev_db.pg_fetch(
                "SELECT * FROM position_history WHERE portfolio_id = ? ORDER BY id DESC LIMIT ?",
                self._portfolio_id, limit
            )
        return rows

    async def get_equity_snapshots(self, limit: int = 252) -> List[Dict]:
        """DB'den equity snapshot'ları."""
        rows = await dev_db.pg_fetch(
            "SELECT * FROM equity_snapshots WHERE portfolio_id = ? ORDER BY id DESC LIMIT ?",
            self._portfolio_id, limit
        )
        return rows

    async def get_metrics(self) -> Dict[str, Any]:
        """Performans metrikleri."""
        return self._pm.get_metrics()

    async def get_risk_metrics(self) -> Dict[str, Any]:
        """Risk metrikleri."""
        return self._pm.get_risk_metrics()

    async def get_trade_history(self, limit: int = 100) -> List[Dict]:
        """Trade geçmişi."""
        return self._pm.get_trade_history(limit)


# Singleton
portfolio_service = PortfolioService()


# =====================================================
# Portfolio Enhancements Entegrasyonu
# =====================================================
def get_portfolio_enhancements() -> Dict[str, Any]:
    """Portfolio enhancement servislerini getir."""
    result = {}
    try:
        from .enhancements import TaxModel, DividendHandler, BenchmarkEngine, PerformanceAttribution, MultiCurrencyHandler
        result["tax_model"] = TaxModel()
        result["dividend_handler"] = DividendHandler()
        result["benchmark_engine"] = BenchmarkEngine()
        result["performance_attribution"] = PerformanceAttribution()
        result["multi_currency"] = MultiCurrencyHandler()
    except ImportError:
        pass
    except Exception:
        pass
    return result

async def main():
    try:
        await portfolio_service.start()
        while portfolio_service._running:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await portfolio_service.stop()

if __name__ == '__main__':
    asyncio.run(main())
