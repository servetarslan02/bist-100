import structlog
logger = structlog.get_logger(__name__)
import os

import duckdb

db_path = "data/alpha_dev.db"
if os.path.exists(db_path):
    conn = duckdb.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'")
    tables = [r[0] for r in cur.fetchall()]
    logger.info("Mevcut tablolar:", tables)
    for tbl in ["positions", "orders", "position_history", "cash_ledger", "equity_snapshots"]:
        if tbl in tables:
            cur.execute(f"DELETE FROM {tbl}")
            logger.info(f"Tablo temizlendi: {tbl}")
    if "portfolios" in tables:
        cur.execute(
            "UPDATE portfolios SET cash_balance = 10000000.0, current_capital = 10000000.0, initial_capital = 10000000.0, total_pnl = 0.0"
        )
        logger.info("Portföy sıfırlandı: ₺10,000,000 Nakit")
    conn.commit()
    conn.close()
    logger.info("Veritabanı sıfırlama işlemi tamamlandı.")
