"""DLQ test kayıtlarını temizle."""
import duckdb

con = duckdb.connect("data/dlq.db")

# Test kayıtlarını sil
before = con.execute("SELECT COUNT(*) FROM dlq_entries").fetchone()[0]
con.execute(
    "DELETE FROM dlq_entries WHERE event_type = 'TEST_ALERT' OR entry_id LIKE 'dlq_e1_%'"
)
remaining = con.execute("SELECT COUNT(*) FROM dlq_entries").fetchone()[0]
deleted = before - remaining

print(f"Silinen DLQ kayit: {deleted}")
print(f"Kalan DLQ kaydi: {remaining}")
con.close()
