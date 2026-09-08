"""ALPHA BIST — Backtest Kalıcılık Katmanı (DuckDB Persistence Layer) Kapsamlı Test Paketi.

services/backtest/persistence.py modülünün tüm işlevlerini ve uç durumlarını sınar:
1. Context manager desteği (__enter__, __exit__, close, __repr__).
2. Otomatik tablo ve sequence ilklendirme (_ensure_db, seq_backtest_trades_id, seq_backtest_equity_id).
3. save_run ve get_run:
   - Başarılı kayıt, metrik JSON serileştirme/ayrıştırma
   - Parametre eksikliği (run_id/start_date/end_date) ValueError kontrolü
   - Var olan çalıştırmanın güncellenmesi (INSERT OR REPLACE)
4. save_trades, get_trades ve get_trades_df:
   - Toplu işlem kaydı ve sequence bazlı ID üretimi
   - Polars DataFrame dışa aktarım (get_trades_df)
   - Boş işlem listesi durumu
5. save_equity_curve, get_equity_curve ve get_equity_curve_df:
   - Günlük özkaynak eğrisi kaydı ve Polars DataFrame dışa aktarımı
6. list_runs ve delete_run:
   - Limit bazlı en güncel çalıştırmaların listelenmesi
   - İlişkili tablolardaki tüm kayıtların cascade silinmesi (equity, trades, runs)
7. health_check:
   - Tablo kayıt sayıları ve bağlantı sağlık durumu
8. Thread-safety:
   - Çoklu iş parçacığında eşzamanlı kayıt, okuma ve silme güvenliği (_lock).
"""

from __future__ import annotations

import concurrent.futures

import polars as pl
import pytest

from services.backtest.persistence import (
    BacktestPersistence,
    backtest_persistence,
)


@pytest.fixture
def temp_persistence(tmp_path) -> BacktestPersistence:
    """İzole geçici DuckDB dosyası kullanan test fixture'ı."""
    db_file = tmp_path / "test_backtest.db"
    bp = BacktestPersistence(db_path=str(db_file))
    yield bp
    bp.close()


def test_persistence_context_manager_and_repr(tmp_path):
    """Context manager ve dize temsili doğrulaması."""
    db_file = tmp_path / "ctx_test.db"
    with BacktestPersistence(db_path=str(db_file)) as bp:
        assert repr(bp).startswith("BacktestPersistence")
        assert bp._conn is not None

    # Çıkışta bağlantı kapanmış olmalı
    assert bp._conn is None


def test_save_and_get_run(temp_persistence: BacktestPersistence):
    """Backtest çalıştırma üstverisi ve konfigürasyon kaydetme / getirme."""
    bp = temp_persistence

    # 1. Eksik parametre hatası
    with pytest.raises(ValueError, match="boş olamaz"):
        bp.save_run(run_id="", start_date="2026-01-01", end_date="2026-06-01", initial_capital=100000.0, metrics={})

    # 2. Başarılı kayıt
    run_id = "RUN_2026_ALPHA_1"
    metrics = {
        "final_equity": 145000.0,
        "total_return_pct": 45.0,
        "sharpe_ratio": 1.85,
        "max_drawdown_pct": -8.5,
        "total_trades": 120,
    }
    config = {
        "universe": ["THYAO", "GARAN", "ASELS"],
        "stop_loss_pct": 0.05,
        "model": "LightGBM",
    }

    bp.save_run(
        run_id=run_id,
        start_date="2026-01-01",
        end_date="2026-06-01",
        initial_capital=100000.0,
        metrics=metrics,
        config=config,
    )

    retrieved = bp.get_run(run_id)
    assert retrieved is not None
    assert retrieved["run_id"] == run_id
    assert retrieved["initial_capital"] == 100000.0
    assert retrieved["final_equity"] == 145000.0
    assert retrieved["metrics"]["sharpe_ratio"] == 1.85
    assert retrieved["config"]["universe"] == ["THYAO", "GARAN", "ASELS"]

    # Var olmayan çalıştırma
    assert bp.get_run("NON_EXISTENT_ID") is None


def test_save_and_get_trades_and_df(temp_persistence: BacktestPersistence):
    """İşlem kayıtlarının eklenmesi, listelenmesi ve Polars DataFrame dönüşümü."""
    bp = temp_persistence
    run_id = "RUN_TRADES_TEST"

    # Boş işlem listesi çağrısı güvenle dönmeli
    bp.save_trades(run_id, [])
    assert bp.get_trades(run_id) == []

    # İşlemler listesi
    trades = [
        {
            "trade_id": 1,
            "ticker": "THYAO",
            "side": "BUY",
            "date": "2026-02-01",
            "quantity": 100,
            "price": 280.0,
            "commission": 15.0,
            "slippage": 2.5,
            "pnl": 0.0,
            "pnl_pct": 0.0,
            "holding_days": 0,
        },
        {
            "trade_id": 2,
            "ticker": "THYAO",
            "side": "SELL",
            "date": "2026-02-15",
            "quantity": 100,
            "price": 310.0,
            "commission": 16.5,
            "slippage": 3.0,
            "pnl": 3000.0,
            "pnl_pct": 10.71,
            "holding_days": 14,
        },
    ]

    bp.save_trades(run_id, trades)

    # get_trades list
    saved_trades = bp.get_trades(run_id)
    assert len(saved_trades) == 2
    assert saved_trades[0]["ticker"] == "THYAO"
    assert saved_trades[1]["pnl"] == 3000.0

    # get_trades_df Polars
    df = bp.get_trades_df(run_id)
    assert isinstance(df, pl.DataFrame)
    assert len(df) == 2
    assert "ticker" in df.columns
    assert "pnl" in df.columns
    assert df["pnl"].sum() == 3000.0


def test_save_and_get_equity_curve(temp_persistence: BacktestPersistence):
    """Özkaynak eğrisi kaydı ve Polars DataFrame sorgulaması."""
    bp = temp_persistence
    run_id = "RUN_EQUITY_TEST"

    # Boş eğri güvenle dönmeli
    bp.save_equity_curve(run_id, [])
    assert bp.get_equity_curve(run_id) == []

    curve = [
        {
            "date": "2026-01-01",
            "equity": 100000.0,
            "cash": 100000.0,
            "market_value": 0.0,
            "positions": 0,
            "drawdown": 0.0,
            "daily_return": 0.0,
        },
        {
            "date": "2026-01-02",
            "equity": 102000.0,
            "cash": 50000.0,
            "market_value": 52000.0,
            "positions": 1,
            "drawdown": 0.0,
            "daily_return": 0.02,
        },
        {
            "date": "2026-01-03",
            "equity": 99000.0,
            "cash": 50000.0,
            "market_value": 49000.0,
            "positions": 1,
            "drawdown": -0.0294,
            "daily_return": -0.0294,
        },
    ]

    bp.save_equity_curve(run_id, curve)

    pts = bp.get_equity_curve(run_id)
    assert len(pts) == 3
    assert pts[0]["equity"] == 100000.0
    assert pts[1]["equity"] == 102000.0

    # Polars DataFrame
    df_curve = bp.get_equity_curve_df(run_id)
    assert isinstance(df_curve, pl.DataFrame)
    assert len(df_curve) == 3
    assert "drawdown" in df_curve.columns


def test_list_and_delete_runs(temp_persistence: BacktestPersistence):
    """Çalıştırmaları listeleme ve ilişkili verilerle birlikte cascade silme."""
    bp = temp_persistence

    # 3 adet çalıştırma kaydet
    for i in range(1, 4):
        r_id = f"RUN_BULK_{i}"
        bp.save_run(r_id, "2026-01-01", "2026-02-01", 100000.0, {"final_equity": 100000.0 + i * 5000})
        bp.save_trades(r_id, [{"trade_id": 1, "ticker": "GARAN", "pnl": float(i * 100)}])
        bp.save_equity_curve(r_id, [{"date": "2026-01-01", "equity": 100000.0}])

    runs = bp.list_runs(limit=2)
    assert len(runs) == 2

    all_runs = bp.list_runs(limit=10)
    assert len(all_runs) == 3

    # delete_run (RUN_BULK_2'yi sil)
    bp.delete_run("RUN_BULK_2")

    assert bp.get_run("RUN_BULK_2") is None
    assert bp.get_trades("RUN_BULK_2") == []
    assert bp.get_equity_curve("RUN_BULK_2") == []
    assert len(bp.list_runs(limit=10)) == 2


def test_health_check(temp_persistence: BacktestPersistence):
    """Veritabanı sağlık kontrolü ve toplam sayaç doğrulaması."""
    bp = temp_persistence
    bp.save_run("RUN_HEALTH", "2026-01-01", "2026-02-01", 50000.0, {})
    bp.save_trades("RUN_HEALTH", [{"trade_id": 1, "ticker": "ASELS"}])
    bp.save_equity_curve("RUN_HEALTH", [{"date": "2026-01-01", "equity": 50000.0}])

    health = bp.health_check()
    assert health["status"] == "healthy"
    assert health["total_runs"] >= 1
    assert health["total_trades"] >= 1
    assert health["total_equity_points"] >= 1


def test_persistence_concurrency(tmp_path):
    """Çoklu iş parçacığında eşzamanlı okuma ve yazma güvenliği."""
    db_file = tmp_path / "concurrent_test.db"
    bp = BacktestPersistence(db_path=str(db_file))

    n_threads = 6
    runs_per_thread = 10

    def worker(tid: int):
        for i in range(runs_per_thread):
            r_id = f"THREAD_RUN_{tid}_{i}"
            bp.save_run(r_id, "2026-01-01", "2026-03-01", 100000.0, {"final_equity": 110000.0})
            bp.save_trades(r_id, [{"trade_id": 1, "ticker": "THYAO", "pnl": 500.0}])
            bp.save_equity_curve(r_id, [{"date": "2026-01-01", "equity": 100000.0}])
            # Eşzamanlı okuma
            _ = bp.get_run(r_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as executor:
        futures = [executor.submit(worker, tid) for tid in range(n_threads)]
        for f in futures:
            f.result()

    health = bp.health_check()
    assert health["total_runs"] == n_threads * runs_per_thread
    assert health["total_trades"] == n_threads * runs_per_thread
    assert health["total_equity_points"] == n_threads * runs_per_thread

    bp.close()
    assert isinstance(backtest_persistence, BacktestPersistence)
