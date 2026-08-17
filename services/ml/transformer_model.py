"""ALPHA BIST — Transformer Model."""
import numpy as np
from typing import Dict, Any, Optional
import structlog
logger = structlog.get_logger()

try:
    import torch
    import torch.nn as nn
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

class StockTransformer:
    def __init__(self, input_size: int = 10, d_model: int = 64, nhead: int = 4, num_layers: int = 2, dropout: float = 0.1):
        self._model = None
        if HAS_TORCH:
            class _Transformer(nn.Module):
                def __init__(self, input_size, d_model, nhead, num_layers, dropout):
                    super().__init__()
                    self.input_proj = nn.Linear(input_size, d_model)
                    encoder_layer = nn.TransformerEncoderLayer(d_model=d_model, nhead=nhead, dropout=dropout, batch_first=True)
                    self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
                    self.fc = nn.Linear(d_model, 1)
                    self.sigmoid = nn.Sigmoid()
                def forward(self, x):
                    x = self.input_proj(x)
                    x = self.transformer(x)
                    x = self.fc(x[:, -1, :])
                    return self.sigmoid(x)
            self._model = _Transformer(input_size, d_model, nhead, num_layers, dropout)

    def train(self, X_train: np.ndarray, y_train: np.ndarray, epochs: int = 50, lr: float = 0.001):
        if not HAS_TORCH or self._model is None: return None
        import torch
        optimizer = torch.optim.Adam(self._model.parameters(), lr=lr)
        criterion = torch.nn.BCELoss()
        X_t = torch.FloatTensor(X_train); y_t = torch.FloatTensor(y_train).unsqueeze(1)
        self._model.train()
        for _ in range(epochs):
            optimizer.zero_grad()
            loss = criterion(self._model(X_t), y_t)
            loss.backward(); optimizer.step()
        logger.info("Transformer trained", epochs=epochs)

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not HAS_TORCH or self._model is None: return np.zeros(len(X))
        import torch
        self._model.eval()
        with torch.no_grad(): return self._model(torch.FloatTensor(X)).squeeze().numpy()

transformer_model = StockTransformer()
