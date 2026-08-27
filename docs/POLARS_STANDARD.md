# 📊 ALPHA BIST — Polars DataFrame Standardı

> **Oluşturulma:** 2026-08-28  
> **Amaç:** DataFrame kullanımında tutarlılık sağlamak  
> **Kural:** Yeni yüksek hacimli data-processing kodu → Polars

---

## Temel Prensip

```
Polars (DataFrame) + DuckDB (SQL) birlikte kullanılır.
```

- **Polars**: DataFrame paradigm'ı için en hızlı (lazy evaluation, predicate pushdown, streaming)
- **DuckDB**: SQL paradigm'ı için en hızlı (columnar, vectorized, multi-threaded)
- **Pandas**: Sadece dış kütüphane zorunluluğu için (yfinance, eski API'ler)

---

## Ne Zaman Ne Kullanılır

| Durum | Araç | Gerekçe |
|---|---|---|
| Yeni data-processing kodu | **Polars** | Hız, bellek verimliliği, type safety |
| SQL aggregation/join | **DuckDB** | Native SQL, Parquet desteği |
| yfinance ile veri çekme | pandas → `pl.from_pandas()` | yfinance pandas döndürür |
| ClickHouse query_df | pandas → `pl.from_pandas()` | clickhouse-connect pandas döndürür |
| DuckDB'den okuma | `conn.execute(...).pl()` | Native Polars desteği |
| DuckDB'ye yazma | `conn.register()` + `CREATE TABLE` | Pandas dönüşümü gereksiz |
| Küçük utility/compat | pandas | Dış kütüphane zorunluluğu |

---

## Polars Lazy API Kullanımı

Yeni kodda mümkün olduğunca Lazy API kullanılmalı:

```python
# ❌ Eager (eski stil)
df = pl.read_parquet("data.parquet")
filtered = df.filter(pl.col("ticker") == "THYAO")
result = filtered.select(["date", "close"])

# ✅ Lazy (tercih edilen)
result = (
    pl.scan_parquet("data.parquet")
    .filter(pl.col("ticker") == "THYAO")
    .select(["date", "close"])
    .collect()
)
```

### Lazy API Avantajları
- **Predicate pushdown**: Filtreler dosya okuma aşamasında uygulanır
- **Projection pushdown**: Sadece gerekli sütunlar okunur
- **Query optimization**: Polars sorgu planını otomatik optimize eder
- **Streaming**: Bellek sığmayan veriler parçalar halinde işlenir

---

## Ortak Kalıplar

### 1. yfinance → Polars Dönüşümü

```python
import yfinance as yf
import polars as pl

raw = yf.download("THYAO.IS", start="2020-01-01")
# MultiIndex sütun düzleştirme
if isinstance(raw.columns, __import__("pandas").MultiIndex):
    raw.columns = [c[0] for c in raw.columns]
df = pl.from_pandas(raw.reset_index())
```

### 2. DuckDB → Polars (Native)

```python
import duckdb

with duckdb.connect("data.duckdb") as conn:
    # ✅ Doğrudan Polars
    df = conn.execute("SELECT * FROM table WHERE ticker = 'THYAO'").pl()
    
    # ❌ Eski yöntem (pandas ara adım)
    # pdf = conn.execute(...).fetchdf()
    # df = pl.from_pandas(pdf)
```

### 3. Polars → DuckDB (Native)

```python
import duckdb
import polars as pl

df = pl.DataFrame({"ticker": ["THYAO"], "price": [100.0]})

with duckdb.connect("data.duckdb") as conn:
    # ✅ Doğrudan Polars (register + create)
    conn.register("_tmp", df)
    conn.execute("CREATE TABLE IF NOT EXISTS stocks AS SELECT * FROM _tmp")
    conn.unregister("_tmp")
    
    # ❌ Eski yöntem (pandas ara adım)
    # df.to_pandas().to_sql("stocks", conn, if_exists="replace")
```

### 4. Feature Hesaplama

```python
import polars as pl

def compute_features(df: pl.DataFrame) -> dict[str, float]:
    """Polars-native feature hesaplama."""
    close = df["Close"].cast(pl.Float64)
    
    return {
        "roc_20d": float(close.pct_change(20)[-1]),
        "volatility": float(close.pct_change().rolling_std(20)[-1] * 252**0.5),
        "rsi_14": _compute_rsi(close, 14),
    }
```

---

## Kontrol Listesi

Yeni bir data-processing dosyası yazarken:

- [ ] `import pandas as pd` var mı? → Gerekli mi kontrol et
- [ ] `.to_pandas()` çağrısı var mı? → DuckDB native `.pl()` kullan
- [ ] `pl.from_pandas()` var mı? → Kaynak pandas mı kontrol et (yfinance → OK)
- [ ] Eager API mi? → Lazy API mümkün mü kontrol et
- [ ] `import polars as pl` var mı? → ✅ Doğru

---

## Performans Karşılaştırma (2026)

| İşlem | Polars | Pandas | Fark |
|---|---|---|---|
| 1M satır GROUP BY | ~0.1s | ~2.5s | 25x hızlı |
| Parquet okuma | ~0.05s | ~0.8s | 16x hızlı |
| Window function | ~0.2s | ~5.0s | 25x hızlı |
| Bellek kullanımı | ~1x | ~3-5x | 3-5x verimli |

---

*Bu standart, ALPHA BIST'in veri işleme pipeline'ının tutarlılığı için zorunludur.*
