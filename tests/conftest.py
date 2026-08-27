"""Test configuration and shared fixtures."""
import logging
import os

import pytest

logger = logging.getLogger(__name__)

# Test veritabanı tabloları — temizlik sırasında kullanılacak
TEST_TABLES = [
    'daily_pnl', 'equity_snapshots', 'position_history',
    'cash_ledger', 'positions', 'portfolios',
]


async def safe_cleanup_tables(dev_db):
    """Test DB tablolarını temizle — tablo yoksa sessizce geç, diğer hataları raporla.

    except Exception: pass yerine kullanılır.
    """
    _TABLE_NOT_FOUND = ('does not exist', 'undefined table', 'no such table')
    for t in TEST_TABLES:
        try:
            await dev_db.pg_execute(f"DELETE FROM {t}")
        except Exception as e:
            err_str = str(e).lower()
            if any(kw in err_str for kw in _TABLE_NOT_FOUND):
                logger.debug("Tablo mevcut değil, atlanıyor: %s (%s)", t, e)
            else:
                logger.warning("Tablo temizlenirken hata: %s — %s", t, e)
                raise


@pytest.fixture(autouse=True)
def clean_env():
    """Her test sonrası env değişkenlerini temizle."""
    original = os.environ.copy()
    yield
    # Test sırasında eklenen env değişkenlerini temizle
    for key in list(os.environ.keys()):
        if key not in original:
            del os.environ[key]
    os.environ.update(original)


@pytest.fixture
def tmp_data_path(tmp_path):
    """Geçici veri dizini."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def sample_ohlcv():
    """Örnek OHLCV verisi."""
    import numpy as np
    n = 100
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.abs(np.random.randn(n) * 0.3)
    low = close - np.abs(np.random.randn(n) * 0.3)
    open_ = close + np.random.randn(n) * 0.2
    volume = np.random.randint(1000000, 10000000, n).astype(float)
    return {
        "Open": open_,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    }
