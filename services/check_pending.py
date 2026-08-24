import sqlite3
conn = sqlite3.connect("data/paper_trading_state.db")
cur = conn.cursor()
cur.execute("SELECT * FROM pending_signals")
cols = [d[0] for d in cur.description]
print("pending_signals cols:", cols)
rows = cur.fetchall()
print("pending_signals count:", len(rows))
for r in rows[:5]:
    print(r)
