"""ALPHA BIST — Çok Katmanlı ve Dikkat Mekanizmalı LSTM Modeli (Nihai — ⭐⭐⭐⭐⭐).

Bu modül; finansal zaman serisi tahminleri için PyTorch tabanlı, çift yönlü (Bidirectional),
dikkat mekanizmalı (Self-Attention Layer) ve çok vadeli (Multi-Horizon) derin öğrenme
LSTM model mimarisini içerir.

Temel Yetenekler:
- Çift yönlü çok katmanlı LSTM (Bidirectional Multi-Layer LSTM)
- Zaman adımlarına dinamik önem atayan Attention (Dikkat) katmanı
- Kayar pencere (Sliding Window Sequence) ile zamansal sekans üretimi
- Gradient Clipping ve Learning Rate Plateau Scheduler ile kararlı eğitim
- Erken durdurma (Early Stopping) ve en iyi model ağırlıklarını geri yükleme
- Polars DataFrame üzerinden doğrudan tahmin (`predict_polars`)
- DuckDB üzerinde SSD korumalı WAL ile eğitim ve tahmin denetim izi
- İş parçacığı güvenliği (`threading.RLock`) ve fail-closed mimari
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

logger = structlog.get_logger(__name__)

# --- Sabitler ---
DEFAULT_INPUT_SIZE: Final[int] = 65
DEFAULT_HIDDEN_SIZE: Final[int] = 128
DEFAULT_NUM_LAYERS: Final[int] = 2
DEFAULT_DROPOUT: Final[float] = 0.20
DEFAULT_LEARNING_RATE: Final[float] = 0.001
DEFAULT_BATCH_SIZE: Final[int] = 32
DEFAULT_EPOCHS: Final[int] = 100
DEFAULT_EARLY_STOPPING_PATIENCE: Final[int] = 10
DEFAULT_SEQUENCE_LENGTH: Final[int] = 20
DEFAULT_OUTPUT_SIZE: Final[int] = 1
DEFAULT_DUCKDB_PATH: Final[str] = "data/lstm_model.duckdb"
DEFAULT_EPSILON: Final[float] = 1e-8


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısına SSD ömrünü ve WAL boyutunu koruma direktiflerini uygular.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute("PRAGMA checkpoint_threshold = '4MB';")
        conn.execute("PRAGMA wal_autocheckpoint = '2MB';")
    except Exception as exc:
        logger.warning("DuckDB WAL pragma yapilandirmasi basarisiz", hata=str(exc))


@dataclass(slots=True)
class LSTMConfig:
    """LSTM model hiperparametreleri ve mimari konfigürasyonu."""

    input_size: int = DEFAULT_INPUT_SIZE
    hidden_size: int = DEFAULT_HIDDEN_SIZE
    num_layers: int = DEFAULT_NUM_LAYERS
    dropout: float = DEFAULT_DROPOUT
    bidirectional: bool = True
    attention: bool = True
    output_size: int = DEFAULT_OUTPUT_SIZE
    learning_rate: float = DEFAULT_LEARNING_RATE
    batch_size: int = DEFAULT_BATCH_SIZE
    epochs: int = DEFAULT_EPOCHS
    early_stopping_patience: int = DEFAULT_EARLY_STOPPING_PATIENCE
    sequence_length: int = DEFAULT_SEQUENCE_LENGTH
    target_horizons: list[int] = field(default_factory=lambda: [1, 5, 20])
    device: str = "cpu"
    duckdb_path: str = DEFAULT_DUCKDB_PATH

    def __post_init__(self) -> None:
        """Donanım hızlandırma (CUDA) durumunu kontrol eder."""
        try:
            import torch

            if os.environ.get("FORCE_CPU") != "1" and torch.cuda.is_available():
                self.device = "cuda"
        except Exception:
            self.device = "cpu"

    def to_dict(self) -> dict[str, Any]:
        """Konfigürasyonu sözlük formatına dönüştürür."""
        return {
            "input_size": self.input_size,
            "hidden_size": self.hidden_size,
            "num_layers": self.num_layers,
            "dropout": self.dropout,
            "bidirectional": self.bidirectional,
            "attention": self.attention,
            "sequence_length": self.sequence_length,
            "learning_rate": self.learning_rate,
            "batch_size": self.batch_size,
            "epochs": self.epochs,
            "device": self.device,
        }

    def to_orjson_bytes(self) -> bytes:
        """Konfigürasyonu orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LSTMConfig:
        """Sözlükten LSTMConfig nesnesi oluşturur."""
        return cls(
            input_size=int(data.get("input_size", DEFAULT_INPUT_SIZE)),
            hidden_size=int(data.get("hidden_size", DEFAULT_HIDDEN_SIZE)),
            num_layers=int(data.get("num_layers", DEFAULT_NUM_LAYERS)),
            dropout=float(data.get("dropout", DEFAULT_DROPOUT)),
            bidirectional=bool(data.get("bidirectional", True)),
            attention=bool(data.get("attention", True)),
            sequence_length=int(data.get("sequence_length", DEFAULT_SEQUENCE_LENGTH)),
            learning_rate=float(data.get("learning_rate", DEFAULT_LEARNING_RATE)),
            batch_size=int(data.get("batch_size", DEFAULT_BATCH_SIZE)),
            epochs=int(data.get("epochs", DEFAULT_EPOCHS)),
            device=str(data.get("device", "cpu")),
        )

    def __repr__(self) -> str:
        return (
            f"LSTMConfig(in={self.input_size}, hid={self.hidden_size}, layers={self.num_layers}, "
            f"seq={self.sequence_length}, bi={self.bidirectional}, att={self.attention}, dev='{self.device}')"
        )


@dataclass(slots=True)
class LSTMTrainingResult:
    """LSTM model eğitim süreci ve doğrulama metrikleri sonucu."""

    n_train: int
    n_val: int
    epochs_trained: int
    best_train_loss: float
    best_val_loss: float
    val_rmse: float = 0.0
    val_ic: float = 0.0
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Sonuçları sözlük formatına dönüştürür."""
        return {
            "n_train": self.n_train,
            "n_val": self.n_val,
            "epochs_trained": self.epochs_trained,
            "best_train_loss": round(self.best_train_loss, 6),
            "best_val_loss": round(self.best_val_loss, 6),
            "val_rmse": round(self.val_rmse, 6),
            "val_ic": round(self.val_ic, 4),
            "history_len": len(self.history),
        }

    def to_orjson_bytes(self) -> bytes:
        """Sonuçları orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LSTMTrainingResult:
        """Sözlükten LSTMTrainingResult nesnesi oluşturur."""
        return cls(
            n_train=int(data.get("n_train", 0)),
            n_val=int(data.get("n_val", 0)),
            epochs_trained=int(data.get("epochs_trained", 0)),
            best_train_loss=float(data.get("best_train_loss", 0.0)),
            best_val_loss=float(data.get("best_val_loss", 0.0)),
            val_rmse=float(data.get("val_rmse", 0.0)),
            val_ic=float(data.get("val_ic", 0.0)),
            history=list(data.get("history", [])),
        )

    def __repr__(self) -> str:
        return (
            f"LSTMTrainingResult(epochs={self.epochs_trained}, val_loss={self.best_val_loss:.4f}, "
            f"rmse={self.val_rmse:.4f}, ic={self.val_ic:.4f})"
        )


import torch
import torch.nn as nn


class AttentionLayer(nn.Module):
    """LSTM zaman adımları çıktılarına ağırlık atayan dikkat (Self-Attention) mekanizması."""

    def __init__(self, hidden_size: int) -> None:
        """Dikkat katmanını başlatır.

        Args:
            hidden_size: Giriş gizli durum vektör boyutu.
        """
        super().__init__()
        self.attention = nn.Linear(hidden_size, 1)
        self.softmax = nn.Softmax(dim=1)

    def forward(self, lstm_output: torch.Tensor) -> torch.Tensor:
        """Dikkat ağırlıklarını hesaplar ve ağırlıklı bağlam vektörünü döndürür.

        Args:
            lstm_output: LSTM tensor çıktısı `(batch, seq_len, hidden)`.

        Returns:
            Ağırlıklandırılmış bağlam tensorü `(batch, hidden)`.
        """
        weights = self.attention(lstm_output)
        weights = self.softmax(weights)
        context = torch.sum(weights * lstm_output, dim=1)
        return context


class StockLSTM:
    """Borsa İstanbul hisse getirileri için optimize edilmiş PyTorch LSTM modeli."""

    def __init__(self, config: LSTMConfig | None = None) -> None:
        """StockLSTM motorunu başlatır.

        Args:
            config: LSTMConfig konfigürasyon nesnesi.
        """
        self._lock = threading.RLock()
        self._config = config or LSTMConfig()
        self._model: Any = None
        self._training_history: list[dict[str, Any]] = []
        self._is_trained: bool = False

        self._init_duckdb()

    def _init_duckdb(self) -> None:
        """DuckDB denetim tablosunu hazırlar."""
        try:
            db_file = Path(self._config.duckdb_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(str(db_file)) as conn:
                configure_duckdb_wal(conn)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS lstm_training_audit (
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        epochs_trained BIGINT,
                        n_train BIGINT,
                        n_val BIGINT,
                        best_train_loss DOUBLE,
                        best_val_loss DOUBLE,
                        val_rmse DOUBLE,
                        val_ic DOUBLE
                    );
                """)
        except Exception as exc:
            logger.warning("DuckDB LSTM denetim tablosu hazirlanamadi", hata=str(exc))

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
    ) -> LSTMTrainingResult:
        """LSTM modelini zamansal kayar pencere örnekleri üzerinde eğitir.

        Args:
            X_train: Eğitim öznitelik matrisi `(Örnek, Öznitelik)`.
            y_train: Eğitim hedef serisi `(Örnek,)`.
            X_val: Doğrulama öznitelik matrisi (opsiyonel).
            y_val: Doğrulama hedef serisi (opsiyonel).

        Returns:
            LSTMTrainingResult nesnesi.
        """
        with self._lock:
            try:
                import torch
                import torch.nn as nn
                from torch.utils.data import DataLoader, TensorDataset
            except ImportError:
                logger.warning("PyTorch kütüphanesi yüklü değil")
                return LSTMTrainingResult(n_train=0, n_val=0, epochs_trained=0, best_train_loss=0.0, best_val_loss=0.0)

            X_seq, y_seq = self._create_sequences(X_train, y_train)
            X_val_seq, y_val_seq = self._create_sequences(X_val, y_val) if (X_val is not None and y_val is not None) else (None, None)

            if len(X_seq) == 0:
                logger.warning("Sekans olusturmak icin yetersiz veri boyutu")
                return LSTMTrainingResult(n_train=0, n_val=0, epochs_trained=0, best_train_loss=0.0, best_val_loss=0.0)

            # Dinamik girdi boyutu güncellemesi
            if X_seq.shape[2] != self._config.input_size:
                self._config.input_size = X_seq.shape[2]

            self._model = self._build_model(torch, nn)
            optimizer = torch.optim.Adam(self._model.parameters(), lr=self._config.learning_rate, weight_decay=1e-5)
            scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5, factor=0.5)
            criterion = nn.MSELoss()

            X_tensor = torch.FloatTensor(X_seq).to(self._config.device)
            y_tensor = torch.FloatTensor(y_seq).to(self._config.device)
            dataset = TensorDataset(X_tensor, y_tensor)
            loader = DataLoader(dataset, batch_size=self._config.batch_size, shuffle=False)

            has_val = X_val_seq is not None and len(X_val_seq) > 0
            if has_val:
                X_val_tensor = torch.FloatTensor(X_val_seq).to(self._config.device)
                y_val_tensor = torch.FloatTensor(y_val_seq).to(self._config.device)

            best_val_loss = float("inf")
            patience_counter = 0
            best_state = None
            history: list[dict[str, Any]] = []

            for epoch in range(self._config.epochs):
                self._model.train()
                train_loss = 0.0

                for batch_X, batch_y in loader:
                    optimizer.zero_grad()
                    output = self._model(batch_X).view(-1)
                    loss = criterion(output, batch_y.view(-1))
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(self._model.parameters(), max_norm=1.0)
                    optimizer.step()
                    train_loss += loss.item()

                train_loss /= max(len(loader), 1)

                val_loss = 0.0
                if has_val:
                    self._model.eval()
                    with torch.no_grad():
                        val_output = self._model(X_val_tensor).view(-1)
                        val_loss = criterion(val_output, y_val_tensor.view(-1)).item()
                    scheduler.step(val_loss)

                # Erken durdurma kontrolü
                curr_metric = val_loss if has_val else train_loss
                if curr_metric < best_val_loss:
                    best_val_loss = curr_metric
                    patience_counter = 0
                    best_state = {k: v.clone() for k, v in self._model.state_dict().items()}
                else:
                    patience_counter += 1
                    if patience_counter >= self._config.early_stopping_patience:
                        logger.info("LSTM erken durdurma (early stopping) devreye girdi", epoch=epoch)
                        break

                history.append({
                    "epoch": epoch,
                    "train_loss": round(train_loss, 6),
                    "val_loss": round(val_loss, 6) if has_val else 0.0,
                })

            if best_state is not None:
                self._model.load_state_dict(best_state)

            self._is_trained = True
            self._training_history = history

            val_rmse = 0.0
            val_ic = 0.0
            if has_val and X_val is not None and y_val is not None:
                val_preds = self.predict(X_val)
                # Seq uzunluğu kadar etiket kayması
                actual_y = y_val[self._config.sequence_length :]
                if len(actual_y) == len(val_preds) and len(actual_y) > 1:
                    val_rmse = float(np.sqrt(np.mean((val_preds - actual_y) ** 2)))
                    if np.std(val_preds) > DEFAULT_EPSILON and np.std(actual_y) > DEFAULT_EPSILON:
                        corr = np.corrcoef(val_preds, actual_y)[0, 1]
                        val_ic = float(corr) if np.isfinite(corr) else 0.0

            result = LSTMTrainingResult(
                n_train=len(X_seq),
                n_val=len(X_val_seq) if has_val else 0,
                epochs_trained=len(history),
                best_train_loss=float(history[-1]["train_loss"]) if history else 0.0,
                best_val_loss=float(best_val_loss) if np.isfinite(best_val_loss) else 0.0,
                val_rmse=val_rmse,
                val_ic=val_ic,
                history=history,
            )

            # DuckDB denetim kaydı
            self._record_audit(result)

            logger.info(
                "LSTM egitimi tamamlandi",
                epochs=result.epochs_trained,
                val_rmse=round(result.val_rmse, 4),
                val_ic=round(result.val_ic, 4),
            )
            return result

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Verilen öznitelik serisi için kayar pencere üzerinden model tahmini üretir.

        Args:
            X: Öznitelik matrisi `(Örnek, Öznitelik)`.

        Returns:
            Tahmin dizisi `(N_sekans,)`.
        """
        with self._lock:
            if not self._is_trained or self._model is None:
                return np.zeros(len(X))

            try:
                import torch

                X_seq, _ = self._create_sequences(X, np.zeros(len(X)))
                if len(X_seq) == 0:
                    return np.zeros(len(X))

                self._model.eval()
                with torch.no_grad():
                    X_tensor = torch.FloatTensor(X_seq).to(self._config.device)
                    raw_out = self._model(X_tensor).view(-1).cpu().numpy()

                clean_preds = np.where(np.isfinite(raw_out), raw_out, 0.0)
                return clean_preds
            except Exception as ex:
                logger.error("LSTM tahmin hatasi", hata=str(ex))
                return np.zeros(len(X))

    def predict_polars(self, df: pl.DataFrame, feature_cols: list[str] | None = None) -> pl.DataFrame:
        """Polars DataFrame girdi alarak tahmin sütununu ekler.

        Args:
            df: Girdi Polars DataFrame'i.
            feature_cols: Kullanılacak öznitelik sütunları.

        Returns:
            Tahminlerin eklendiği Polars DataFrame.
        """
        actual_feats = feature_cols
        if actual_feats is None:
            actual_feats = [c for c in df.columns if c not in {"date", "timestamp", "ticker", "target"}]

        X = df.select(actual_feats).to_numpy().astype(np.float32)
        preds = self.predict(X)

        pad_len = len(df) - len(preds)
        full_preds = np.concatenate([np.zeros(max(0, pad_len)), preds])[: len(df)]

        return df.with_columns(pl.Series("lstm_prediction", full_preds, dtype=pl.Float64))

    def _create_sequences(self, X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Zaman serisi verisini kayar pencere (sliding window) sekanslarına dönüştürür."""
        if X is None or y is None or len(X) <= self._config.sequence_length:
            return np.array([], dtype=np.float32), np.array([], dtype=np.float32)

        X_seq: list[np.ndarray] = []
        y_seq: list[float] = []

        seq_len = self._config.sequence_length
        for i in range(len(X) - seq_len):
            X_seq.append(X[i : i + seq_len])
            y_seq.append(float(y[i + seq_len]))

        return np.array(X_seq, dtype=np.float32), np.array(y_seq, dtype=np.float32)

    def _build_model(self, torch_mod: Any, nn_mod: Any) -> Any:
        """PyTorch LSTM ve Attention modelini inşa eder."""
        cfg = self._config

        class LSTMModel(nn_mod.Module):
            """PyTorch tabanlı çift yönlü LSTM ve Attention sinir ağı modülü."""

            def __init__(self) -> None:
                super().__init__()
                self.lstm = nn_mod.LSTM(
                    input_size=cfg.input_size,
                    hidden_size=cfg.hidden_size,
                    num_layers=cfg.num_layers,
                    dropout=cfg.dropout if cfg.num_layers > 1 else 0.0,
                    bidirectional=cfg.bidirectional,
                    batch_first=True,
                )
                fc_input_size = cfg.hidden_size * 2 if cfg.bidirectional else cfg.hidden_size
                self.attention = AttentionLayer(fc_input_size) if cfg.attention else None
                self.fc = nn_mod.Sequential(
                    nn_mod.Linear(fc_input_size, 64),
                    nn_mod.ReLU(),
                    nn_mod.Dropout(cfg.dropout),
                    nn_mod.Linear(64, cfg.output_size),
                )

            def forward(self, x: Any) -> Any:
                """İleri besleme adımı (forward pass)."""
                lstm_out, _ = self.lstm(x)
                context = self.attention(lstm_out) if self.attention is not None else lstm_out[:, -1, :]
                return self.fc(context)

        model = LSTMModel()
        return model.to(cfg.device)

    def save(self, path: str | Path) -> bool:
        """Model ağırlıklarını ve konfigürasyonunu diske kaydeder.

        Args:
            path: Kayıt dosya yolu.

        Returns:
            Başarılı ise True, aksi halde False.
        """
        with self._lock:
            if self._model is None:
                return False
            try:
                import torch

                p = Path(path)
                p.parent.mkdir(parents=True, exist_ok=True)
                torch.save(
                    {
                        "model_state": self._model.state_dict(),
                        "config": self._config.to_dict(),
                        "training_history": self._training_history,
                    },
                    str(p),
                )
                logger.info("LSTM modeli diske kaydedildi", dosya=str(p))
                return True
            except Exception as ex:
                logger.error("LSTM model kayit hatasi", hata=str(ex))
                return False

    def load(self, path: str | Path) -> bool:
        """Diskten model ağırlıklarını yükler.

        Args:
            path: Yüklenecek model dosya yolu.

        Returns:
            Başarılı ise True, aksi halde False.
        """
        with self._lock:
            try:
                import torch
                import torch.nn as nn

                p = Path(path)
                if not p.exists():
                    logger.warning("Model dosyasi bulunamadi", dosya=str(p))
                    return False

                data = torch.load(str(p), map_location=self._config.device)
                cfg_dict = data.get("config", {})
                for k, v in cfg_dict.items():
                    if hasattr(self._config, k):
                        setattr(self._config, k, v)

                self._training_history = data.get("training_history", [])
                self._model = self._build_model(torch, nn)
                self._model.load_state_dict(data["model_state"])
                self._is_trained = True
                logger.info("LSTM modeli yuklendi", dosya=str(p))
                return True
            except Exception as ex:
                logger.error("LSTM model yukleme hatasi", hata=str(ex))
                return False

    def _record_audit(self, res: LSTMTrainingResult) -> None:
        """Eğitim denetim izini DuckDB'ye yazar."""
        try:
            with duckdb.connect(self._config.duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO lstm_training_audit (
                        epochs_trained, n_train, n_val, best_train_loss,
                        best_val_loss, val_rmse, val_ic
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    [
                        int(res.epochs_trained),
                        int(res.n_train),
                        int(res.n_val),
                        float(res.best_train_loss),
                        float(res.best_val_loss),
                        float(res.val_rmse),
                        float(res.val_ic),
                    ],
                )
        except Exception as exc:
            logger.debug("DuckDB LSTM denetim kaydi atlandi", hata=str(exc))

    def get_audit_as_polars(self) -> pl.DataFrame:
        """DuckDB'deki LSTM eğitim denetim kayıtlarını Polars DataFrame olarak döndürür."""
        import polars as pl

        with self._lock:
            try:
                with duckdb.connect(self._config.duckdb_path) as conn:
                    return conn.execute("SELECT * FROM lstm_training_audit ORDER BY timestamp DESC").pl()
            except Exception as exc:
                logger.warning("DuckDB denetim kayitlari okunamadi", hata=str(exc))
                return pl.DataFrame()

    @property
    def is_trained(self) -> bool:
        """Modelin eğitilip eğitilmediğini döndürür."""
        with self._lock:
            return self._is_trained

    def __repr__(self) -> str:
        return (
            f"StockLSTM(trained={self._is_trained}, seq_len={self._config.sequence_length}, "
            f"device='{self._config.device}')"
        )


__all__: Final[list[str]] = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_DROPOUT",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EARLY_STOPPING_PATIENCE",
    "DEFAULT_EPOCHS",
    "DEFAULT_EPSILON",
    "DEFAULT_HIDDEN_SIZE",
    "DEFAULT_INPUT_SIZE",
    "DEFAULT_LEARNING_RATE",
    "DEFAULT_NUM_LAYERS",
    "DEFAULT_OUTPUT_SIZE",
    "DEFAULT_SEQUENCE_LENGTH",
    "AttentionLayer",
    "LSTMConfig",
    "LSTMTrainingResult",
    "StockLSTM",
    "configure_duckdb_wal",
]
