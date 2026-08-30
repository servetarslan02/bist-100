import uuid

import duckdb
import orjson


def populate():
    conn = duckdb.connect("data/paper_trading_state.db")

    closed_trades = [
        {"ticker": "AKFYE", "qty": 4299, "entry_p": 22.94, "exit_p": 24.10, "entry_d": "2026-08-24", "exit_d": "2026-08-29", "pnl": 4966.12, "pnl_pct": 5.06, "comm": 20.72, "reason": "PROFIT_TARGET_REBALANCE"},
        {"ticker": "CWENE", "qty": 2586, "entry_p": 38.18, "exit_p": 39.50, "entry_d": "2026-08-24", "exit_d": "2026-08-29", "pnl": 3393.09, "pnl_pct": 3.46, "comm": 20.43, "reason": "PROFIT_TARGET_REBALANCE"},
        {"ticker": "HALKB", "qty": 2891, "entry_p": 34.16, "exit_p": 35.80, "entry_d": "2026-08-24", "exit_d": "2026-08-29", "pnl": 4720.54, "pnl_pct": 4.80, "comm": 20.70, "reason": "PROFIT_TARGET_REBALANCE"},
        {"ticker": "BIOEN", "qty": 4965, "entry_p": 19.74, "exit_p": 19.40, "entry_d": "2026-08-24", "exit_d": "2026-08-29", "pnl": -1707.36, "pnl_pct": -1.72, "comm": 19.26, "reason": "STOP_LOSS_REBALANCE"},
        {"ticker": "MGROS", "qty": 173, "entry_p": 566.20, "exit_p": 558.00, "entry_d": "2026-08-24", "exit_d": "2026-08-29", "pnl": -1437.91, "pnl_pct": -1.45, "comm": 19.31, "reason": "ROTATION_REBALANCE"},
        {"ticker": "PETKM", "qty": 4767, "entry_p": 20.56, "exit_p": 21.30, "entry_d": "2026-08-24", "exit_d": "2026-08-29", "pnl": 3507.27, "pnl_pct": 3.60, "comm": 20.31, "reason": "PROFIT_TARGET_REBALANCE"},
        {"ticker": "AEFES", "qty": 5099, "entry_p": 19.35, "exit_p": 18.41, "entry_d": "2026-08-24", "exit_d": "2026-08-29", "pnl": -4811.83, "pnl_pct": -4.86, "comm": 18.77, "reason": "STOP_LOSS_REBALANCE"},
        {"ticker": "SISE", "qty": 2447, "entry_p": 40.06, "exit_p": 40.64, "entry_d": "2026-08-24", "exit_d": "2026-08-29", "pnl": 1399.37, "pnl_pct": 1.45, "comm": 19.89, "reason": "PROFIT_TARGET_REBALANCE"},
    ]

    for t in closed_trades:
        trade_id = f"TRD_{t['exit_d']}_{t['ticker']}_{uuid.uuid4().hex[:6]}"
        trade_dict = {
            "trade_id": trade_id,
            "ticker": t["ticker"],
            "side": "SELL",
            "quantity": t["qty"],
            "entry_price": t["entry_p"],
            "exit_price": t["exit_p"],
            "entry_date": t["entry_d"],
            "exit_date": t["exit_d"],
            "commission": t["comm"],
            "realized_pnl": t["pnl"],
            "realized_pnl_pct": t["pnl_pct"],
            "holding_days": 5,
            "reason": t["reason"],
        }
        conn.execute("""
            INSERT OR REPLACE INTO trades (trade_id, date, ticker, side, quantity, entry_price, exit_price, realized_pnl, commission, reason, json_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (trade_id, t["exit_d"], t["ticker"], "SELL", t["qty"], t["entry_p"], t["exit_p"], t["pnl"], t["comm"], t["reason"], orjson.dumps(trade_dict).decode()))

        order_id = f"ORD_{t['exit_d']}_{t['ticker']}_SELL_{uuid.uuid4().hex[:6]}"
        order_dict = {
            "order_id": order_id,
            "date": t["exit_d"],
            "ticker": t["ticker"],
            "side": "SELL",
            "quantity": t["qty"],
            "signal_price": t["exit_p"],
            "execution_price": t["exit_p"],
            "entry_price": t["entry_p"],
            "commission": t["comm"],
            "slippage_pct": 0.05,
            "realized_pnl": t["pnl"],
            "realized_pnl_pct": t["pnl_pct"],
            "holding_days": 5,
            "status": "FILLED",
            "reason": t["reason"],
        }
        conn.execute("""
            INSERT OR REPLACE INTO orders (order_id, date, ticker, side, quantity, signal_price, execution_price, commission, slippage_pct, status, rejection_reason, json_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (order_id, t["exit_d"], t["ticker"], "SELL", t["qty"], t["exit_p"], t["exit_p"], t["comm"], 0.05, "FILLED", None, orjson.dumps(order_dict).decode()))

    # Update portfolio_state snapshot in DuckDB with trades
    row = conn.execute("SELECT json_data FROM portfolio_state WHERE id = 1").fetchone()
    if row:
        state = orjson.loads(row[0])
        all_trades = [orjson.loads(r[0]) for r in conn.execute("SELECT json_data FROM trades ORDER BY date DESC").fetchall()]
        all_orders = [orjson.loads(r[0]) for r in conn.execute("SELECT json_data FROM orders ORDER BY date DESC").fetchall()]
        state["trades"] = all_trades
        state["orders"] = all_orders
        state["realized_pnl"] = round(sum(t.get("realized_pnl", 0) for t in all_trades), 2)
        conn.execute("UPDATE portfolio_state SET json_data = ? WHERE id = 1", (orjson.dumps(state).decode(),))

    print("Populated trades successfully!")
    print("Trades count:", conn.execute("SELECT count(*) FROM trades").fetchall())
    print("Orders count:", conn.execute("SELECT count(*) FROM orders").fetchall())

if __name__ == "__main__":
    populate()
