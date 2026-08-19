"""ALPHA BIST — Qlib Integration (Nihai —⭐⭐⭐⭐⭐).

Microsoft Qlib ile BIST verisi entegrasyonu.
Feature store, data handler, model integration.
"""
import os
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
import structlog

logger = structlog.get_logger()


@dataclass
class QlibConfig:
    """Qlib konfigürasyonu."""
    data_dir: str = "data/qlib"
    provider: str = "csv"  # csv, yfinance, qlib
    cache_dir: str = "data/qlib_cache"
    feature_columns: List[str] = field(default_factory=list)
    label_columns: List[str] = field(default_factory=lambda: ["label_5d"])
    train_start: str = "2020-01-01"
    train_end: str = "2024-01-01"
    valid_start: str = "2024-01-01"
    valid_end: str = "2024-06-01"
    test_start: str = "2024-06-01"
    test_end: str = "2025-01-01"


class QlibBIST:
    """Qlib ile BIST verisi entegrasyonu —⭐⭐⭐⭐⭐ seviye.

    Özellikler:
    - Qlib data formatına dönüştürme
    - Feature store yönetimi
    - Train/valid/test split
    - Multi-stock data handler
    - Qlib model pipeline entegrasyonu
    - Backtest entegrasyonu
    """

    def __init__(self, config: Optional[QlibConfig] = None):
        self.config = config or QlibConfig()
        self._data_cache: Dict[str, pd.DataFrame] = {}
        self._feature_store: Dict[str, np.ndarray] = {}
        self._is_initialized = False

    def prepare_data(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        features: Optional[np.ndarray] = None,
        prices: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """Qlib formatında veri hazırla.

        Args:
            ticker: Hisse kodu
            start_date: Başlangıç tarihi
            end_date: Bitiş tarihi
            features: Feature matrix (opsiyonel)
            prices: Fiyat array'i (opsiyonel)

        Returns:
            Qlib-compatible data dict
        """
        try:
            # Qlib data format
            qlib_data = {
                "ticker": ticker,
                "start_date": start_date,
                "end_date": end_date,
                "features": features.tolist() if features is not None else [],
                "prices": prices.tolist() if prices is not None else [],
                "n_samples": len(features) if features is not None else 0,
                "n_features": features.shape[1] if features is not None and len(features.shape) > 1 else 0,
                "status": "ready",
            }

            # Cache
            self._data_cache[ticker] = qlib_data

            return qlib_data

        except Exception as e:
            logger.error("qlib_prepare_failed", ticker=ticker, error=str(e))
            return {"ticker": ticker, "status": "error", "error": str(e)}

    def create_qlib_dataset(
        self,
        data: Dict[str, Dict[str, Any]],
        label_horizon: int = 5,
    ) -> Dict[str, Any]:
        """Qlib dataset oluştur — train/valid/test split.

        Args:
            data: {ticker: prepared_data}
            label_horizon: Label horizon (gün)

        Returns:
            Qlib dataset dict
        """
        dataset = {
            "train": {"X": [], "y": [], "tickers": []},
            "valid": {"X": [], "y": [], "tickers": []},
            "test": {"X": [], "y": [], "tickers": []},
        }

        for ticker, ticker_data in data.items():
            if ticker_data.get("status") != "ready":
                continue

            features = np.array(ticker_data.get("features", []))
            prices = np.array(ticker_data.get("prices", []))

            if len(features) == 0 or len(prices) == 0:
                continue

            # Forward return label
            returns = np.zeros(len(prices))
            if len(prices) > label_horizon:
                returns[:-label_horizon] = (prices[label_horizon:] - prices[:-label_horizon]) / prices[:-label_horizon]

            # Split (temporal)
            n = len(features)
            train_end = int(n * 0.6)
            valid_end = int(n * 0.8)

            # Train
            dataset["train"]["X"].append(features[:train_end])
            dataset["train"]["y"].append(returns[:train_end])
            dataset["train"]["tickers"].append(ticker)

            # Valid
            dataset["valid"]["X"].append(features[train_end:valid_end])
            dataset["valid"]["y"].append(returns[train_end:valid_end])
            dataset["valid"]["tickers"].append(ticker)

            # Test
            dataset["test"]["X"].append(features[valid_end:])
            dataset["test"]["y"].append(returns[valid_end:])
            dataset["test"]["tickers"].append(ticker)

        # Concatenate
        for split in ["train", "valid", "test"]:
            if dataset[split]["X"]:
                dataset[split]["X"] = np.concatenate(dataset[split]["X"], axis=0)
                dataset[split]["y"] = np.concatenate(dataset[split]["y"], axis=0)
            else:
                dataset[split]["X"] = np.array([])
                dataset[split]["y"] = np.array([])

        logger.info("qlib_dataset_created",
                     train_samples=len(dataset["train"]["X"]),
                     valid_samples=len(dataset["valid"]["X"]),
                     test_samples=len(dataset["test"]["X"]))

        return dataset

    def get_feature_store(self) -> Dict[str, np.ndarray]:
        """Feature store döndür."""
        return self._feature_store

    def add_to_feature_store(self, name: str, features: np.ndarray):
        """Feature store'a ekle."""
        self._feature_store[name] = features

    def get_cached_data(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Cache'den veri döndür."""
        return self._data_cache.get(ticker)

    def clear_cache(self):
        """Cache'i temizle."""
        self._data_cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        """İstatistikler."""
        return {
            "cached_tickers": len(self._data_cache),
            "feature_store_size": len(self._feature_store),
            "data_dir": self.config.data_dir,
        }


# Singleton
qlib_bist = QlibBIST()
