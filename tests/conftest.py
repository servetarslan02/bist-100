"""Test configuration and shared fixtures."""
import os
import pytest


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
