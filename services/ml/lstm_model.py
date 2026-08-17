"""ALPHA BIST — LSTM Model."""
import numpy as np
from typing import Dict, Any, Optional, Tuple
import structlog
logger = structlog.get_logger()

try:
    import torch
    import torch.nn as nn
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

class StockLSTM:
    def __init__(self, input_size: int = 10, hidden_size: int = 64, num_layers: int = 2, dropout: float = 0.2):
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self._model = None
        if HAS_TORCH:
            self._model = self._build_model(dropout)

    def _build_model(self, dropout):
        import torch.nn as nn
        class _LSTM(nn.Module):
            def __init__(self, input_size, hidden_size, num_layers, dropout):
                super().__init__()
                self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True, dropout=dropout)
                self.fc = nn.Linear(hidden_size, 1)
                self.sigmoid = nn.Sigmoid()
            def forward(self, x):
                out, _ = self.lstm(x)
                out = self.fc(out[:, -1, :])
                return self.sigmoid(out)
        return _LSTM(self.input_size, self.hidden_size, self.num_layers, dropout)

    def train(self, X_train: np.ndarray, y_train: np.ndarray, epochs: int = 50, lr: float = 0.001):
        if not HAS_TORCH or self._model is None:
            logger.warning("torch not installed"); return None
        import torch
        optimizer = torch.optim.Adam(self._model.parameters(), lr=lr)
        criterion = torch.nn.BCELoss()
        X_t = torch.FloatTensor(X_train)
        y_t = torch.FloatTensor(y_train).unsqueeze(1)
        self._model.train()
        for epoch in range(epochs):
            optimizer.zero_grad()
            out = self._model(X_t)
            loss = criterion(out, y_t)
            loss.backward()
            optimizer.step()
        logger.info("LSTM trained", epochs=epochs, loss=float(loss))

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not HAS_TORCH or self._model is None: return np.zeros(len(X))
        import torch
        self._model.eval()
        with torch.no_grad():
            return self._model(torch.FloatTensor(X)).squeeze().numpy()

lstm_model = StockLSTM()
