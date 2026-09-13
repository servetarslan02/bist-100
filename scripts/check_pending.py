import duckdb
import structlog

logger = structlog.get_logger(__name__)

# FIX: Connection leak — context manager kullan
with duckdb.connect("data/paper_trading_state.db") as conn:
    cur = conn.cursor()
    cur.execute("SELECT * FROM pending_signals")
    cols = [d[0] for d in cur.description]
    logger.debug("pending_signals cols:", cols)
    rows = cur.fetchall()
    logger.debug("pending_signals count:", len(rows))
    for r in rows[:5]:
        logger.debug(r)
