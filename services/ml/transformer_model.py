"""ALPHA BIST — Çok Başlı Dikkat Tabanlı Zaman Serisi Modeli (Stock Transformer v3.0) (Nihai — ⭐⭐⭐⭐⭐).

Bu modül; BIST hisse senetlerinin zaman serisi özniteliklerini işlemek üzere
PyTorch çok başlı öz-dikkat (Multi-Head Self-Attention), sinüzoidal pozisyonel kodlama
(Positional Encoding) ve çok katmanlı Transformer kodlayıcı (Encoder) mimarisini uygular.

Temel Yetenekler:
- Sinüzoidal Pozisyonel Kodlama ve Katman Normalizasyonu
- Cosine Annealing Öğrenme Oranı Zamanlayıcısı ve Gradient Kırpma (Norm Clipping)
- Erken Durdurma (Early Stopping) ve En İyi Ağırlık Kurtarma
- Sıfır Veri Sızıntılı Zamansal Dizi Üretimi (`_create_sequences`)
- Polars DataFrame Desteği (`train_polars`, `predict_polars`)
- DuckDB SSD Korumalı WAL ile Model Eğitimi ve Tahmin Denetim İzi
- İş Parçacığı Eşzamanlılık Güvenliği (`threading.RLock`)
- Fail-Closed Hata Yönetimi ve Kapsamlı Tip Belirteçleri
"""

from __future__ import annotations

import os
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import duckdb
import numpy as np
import orjson
import structlog

if TYPE_CHECKING:
    import polars as pl

logger = structlog.get_logger(__name__)

# --- Sabitler ---
DEFAULT_INPUT_SIZE: Final[int] = 65
DEFAULT_D_MODEL: Final[int] = 128
DEFAULT_NHEAD: Final[int] = 8
DEFAULT_NUM_ENCODER_LAYERS: Final[int] = 3
DEFAULT_DIM_FEEDFORWARD: Final[int] = 256
DEFAULT_DROPOUT: Final[float] = 0.1
DEFAULT_OUTPUT_SIZE: Final[int] = 1
DEFAULT_LEARNING_RATE: Final[float] = 1e-4
DEFAULT_BATCH_SIZE: Final[int] = 32
DEFAULT_SEQUENCE_LENGTH: Final[int] = 20
DEFAULT_MAX_POSITION_ENCODING: Final[int] = 500
DEFAULT_WARMUP_STEPS: Final[int] = 100
DEFAULT_EPOCHS: Final[int] = 50
DEFAULT_EARLY_STOPPING_PATIENCE: Final[int] = 10
DEFAULT_WEIGHT_DECAY: Final[float] = 1e-4
DEFAULT_DUCKDB_PATH: Final[str] = "data/transformer_model.duckdb"
DEFAULT_EPSILON: Final[float] = 1e-8


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısına SSD korumalı WAL pragma direktiflerini uygular.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute("PRAGMA checkpoint_threshold = '4MB';")
        conn.execute("PRAGMA wal_autocheckpoint = '2MB';")
    except Exception as exc:
        logger.warning("DuckDB WAL pragma yapilandirmasi basarisiz", hata=str(exc))


@dataclass(slots=True)
class TransformerConfig:
    """StockTransformer mimarisi ve eğitim hiperparametreleri konfigürasyonu."""

    input_size: int = DEFAULT_INPUT_SIZE
    d_model: int = DEFAULT_D_MODEL
    nhead: int = DEFAULT_NHEAD
    num_encoder_layers: int = DEFAULT_NUM_ENCODER_LAYERS
    dim_feedforward: int = DEFAULT_DIM_FEEDFORWARD
    dropout: float = DEFAULT_DROPOUT
    output_size: int = DEFAULT_OUTPUT_SIZE
    learning_rate: float = DEFAULT_LEARNING_RATE
    batch_size: int = DEFAULT_BATCH_SIZE
    sequence_length: int = DEFAULT_SEQUENCE_LENGTH
    max_position_encoding: int = DEFAULT_MAX_POSITION_ENCODING
    warmup_steps: int = DEFAULT_WARMUP_STEPS
    epochs: int = DEFAULT_EPOCHS
    early_stopping_patience: int = DEFAULT_EARLY_STOPPING_PATIENCE
    weight_decay: float = DEFAULT_WEIGHT_DECAY
    device: str = "cpu"

    def __post_init__(self) -> None:
        """Cihaz tespiti (CUDA / CPU) ve tutarlılık doğrulaması yapar."""
        try:
            import torch

            if os.environ.get("FORCE_CPU") != "1" and torch.cuda.is_available():
                self.device = "cuda"
            else:
                self.device = "cpu"
        except Exception as exc:
            logger.debug("Torch cihaz kontrol bildirimi", hata=str(exc))
            self.device = "cpu"

    def to_dict(self) -> dict[str, Any]:
        """Konfigürasyonu sözlük formatına dönüştürür."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransformerConfig:
        """Sözlükten TransformerConfig nesnesi oluşturur."""
        return cls(
            input_size=int(data.get("input_size", DEFAULT_INPUT_SIZE)),
            d_model=int(data.get("d_model", DEFAULT_D_MODEL)),
            nhead=int(data.get("nhead", DEFAULT_NHEAD)),
            num_encoder_layers=int(data.get("num_encoder_layers", DEFAULT_NUM_ENCODER_LAYERS)),
            dim_feedforward=int(data.get("dim_feedforward", DEFAULT_DIM_FEEDFORWARD)),
            dropout=float(data.get("dropout", DEFAULT_DROPOUT)),
            output_size=int(data.get("output_size", DEFAULT_OUTPUT_SIZE)),
            learning_rate=float(data.get("learning_rate", DEFAULT_LEARNING_RATE)),
            batch_size=int(data.get("batch_size", DEFAULT_BATCH_SIZE)),
            sequence_length=int(data.get("sequence_length", DEFAULT_SEQUENCE_LENGTH)),
            max_position_encoding=int(data.get("max_position_encoding", DEFAULT_MAX_POSITION_ENCODING)),
            warmup_steps=int(data.get("warmup_steps", DEFAULT_WARMUP_STEPS)),
            epochs=int(data.get("epochs", DEFAULT_EPOCHS)),
            early_stopping_patience=int(data.get("early_stopping_patience", DEFAULT_EARLY_STOPPING_PATIENCE)),
            weight_decay=float(data.get("weight_decay", DEFAULT_WEIGHT_DECAY)),
            device=str(data.get("device", "cpu")),
        )

    def to_orjson_bytes(self) -> bytes:
        """Konfigürasyonu orjson serileştirilmiş byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Özet metin gösterimini üretir."""
        return (
            f"TransformerConfig(input_dim={self.input_size}, d_model={self.d_model}, "
            f"heads={self.nhead}, layers={self.num_encoder_layers}, seq_len={self.sequence_length}, device='{self.device}')"
        )


class PositionalEncoding:
    """Zaman serisi adımları için sinüzoidal pozisyon kodlaması (Sinusoidal PE)."""

    def __init__(self, d_model: int, max_len: int = DEFAULT_MAX_POSITION_ENCODING) -> None:
        """Pozisyon matrisini önceden hesaplar ve ilklendirir.

        Args:
            d_model: Model gizli boyut genişliği.
            max_len: Maksimum dizi uzunluğu sınırı.
        """
        self.pe: Any = None
        try:
            import torch

            pe = torch.zeros(max_len, d_model)
            position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
            div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-np.log(10000.0) / d_model))
            pe[:, 0::2] = torch.sin(position * div_term)
            pe[:, 1::2] = torch.cos(position * div_term)
            self.pe = pe.unsqueeze(0)  # (1, max_len, d_model)
        except ImportError:
            self.pe = None

    def __call__(self, x: Any) -> Any:
        """Girdi tensörüne pozisyonel kodlama değerlerini ekler.

        Args:
            x: Şekli (batch, seq_len, d_model) olan girdi tensörü.

        Returns:
            Pozisyon kodlaması eklenmiş tensör.
        """
        if self.pe is None:
            return x
        seq_len = x.size(1)
        return x + self.pe[:, :seq_len, :].to(x.device)

    def __repr__(self) -> str:
        """Pozisyonel kodlayıcı metin gösterimi."""
        return f"PositionalEncoding(initialized={self.pe is not None})"


class StockTransformer:
    """BIST Hisse Senetleri için Derin Transformer Tahmin Motoru."""

    def __init__(
        self,
        config: TransformerConfig | None = None,
        duckdb_path: str = DEFAULT_DUCKDB_PATH,
    ) -> None:
        """StockTransformer bileşenini başlatır.

        Args:
            config: Model ve eğitim konfigürasyonu.
            duckdb_path: Denetim kaydı için DuckDB veritabanı yolu.
        """
        self._config: TransformerConfig = config or TransformerConfig()
        self._duckdb_path: str = duckdb_path
        self._lock: threading.RLock = threading.RLock()

        self._model: Any = None
        self._training_history: list[dict[str, Any]] = []
        self._is_trained: bool = False

        self._init_duckdb()
        logger.info(
            "StockTransformer v3.0 baslatildi",
            d_model=self._config.d_model,
            heads=self._config.nhead,
            device=self._config.device,
        )

    def _init_duckdb(self) -> None:
        """DuckDB denetim tablosunu güvenle oluşturur."""
        try:
            db_dir = Path(self._duckdb_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS transformer_audit (
                        timestamp TIMESTAMPTZ NOT NULL,
                        operation VARCHAR NOT NULL,
                        epochs_trained BIGINT NOT NULL,
                        best_val_loss DOUBLE NOT NULL,
                        val_ic DOUBLE NOT NULL,
                        details VARCHAR NOT NULL
                    );
                    """
                )
        except Exception as exc:
            logger.warning("DuckDB transformer_audit tablosu ilklendirilemedi", hata=str(exc))

    def _record_audit_event(
        self,
        operation: str,
        epochs_trained: int,
        best_val_loss: float,
        val_ic: float,
        details: dict[str, Any],
    ) -> None:
        """Denetim olayını DuckDB tablosuna kaydeder."""
        try:
            now_iso = datetime.now(UTC).isoformat()
            details_json = orjson.dumps(details).decode()
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO transformer_audit
                    (timestamp, operation, epochs_trained, best_val_loss, val_ic, details)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    [now_iso, operation, epochs_trained, best_val_loss, val_ic, details_json],
                )
        except Exception as exc:
            logger.warning("DuckDB transformer denetim kaydi basarisiz", hata=str(exc))

    def get_audit_as_polars(self) -> pl.DataFrame:
        """DuckDB denetim kayıtlarını Polars DataFrame olarak döndürür."""
        import polars as pl

        with self._lock:
            try:
                with duckdb.connect(self._duckdb_path) as conn:
                    configure_duckdb_wal(conn)
                    arrow_table = conn.execute(
                        "SELECT * FROM transformer_audit ORDER BY timestamp DESC;"
                    ).arrow()
                    return pl.from_arrow(arrow_table)  # type: ignore[return-value]
            except Exception as exc:
                logger.warning("DuckDB transformer denetim tablosu okunamadi", hata=str(exc))
                return pl.DataFrame()

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
    ) -> dict[str, Any]:
        """Transformer modelini tam denetimli eğitim döngüsü ile eğitir.

        Args:
            X_train: Eğitim öznitelik matrisi (N, F).
            y_train: Eğitim hedef serisi (N,).
            X_val: Doğrulama öznitelik matrisi (M, F) (opsiyonel).
            y_val: Doğrulama hedef serisi (M,) (opsiyonel).

        Returns:
            Eğitim ve doğrulama metriklerini içeren sözlük.
        """
        with self._lock:
            try:
                import torch
                import torch.nn as nn
                from torch.utils.data import DataLoader, TensorDataset
            except ImportError:
                logger.warning("PyTorch kurulu degil, egitim atlandi")
                return {"error": "PyTorch kurulu degil"}

            # Dizi dizilimi oluştur (TimeSeries Sequences)
            X_seq, y_seq = self._create_sequences(X_train, y_train)
            if len(X_seq) == 0:
                logger.error("Dizi uretimi icin yetersiz ornek", mevcut_satir=len(X_train))
                return {"error": "Dizi uretimi icin yetersiz veri"}

            X_val_seq: np.ndarray | None = None
            y_val_seq: np.ndarray | None = None
            if X_val is not None and y_val is not None and len(X_val) >= self._config.sequence_length:
                X_val_seq, y_val_seq = self._create_sequences(X_val, y_val)

            # Modeli inşa et
            self._model = self._build_model(torch, nn)
            optimizer = torch.optim.AdamW(
                self._model.parameters(),
                lr=self._config.learning_rate,
                weight_decay=self._config.weight_decay,
            )
            scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(optimizer, T_0=10, T_mult=2)
            criterion = nn.MSELoss()

            # Veri yükleyicisi
            X_tensor = torch.FloatTensor(X_seq).to(self._config.device)
            y_tensor = torch.FloatTensor(y_seq).to(self._config.device)
            dataset = TensorDataset(X_tensor, y_tensor)
            loader = DataLoader(dataset, batch_size=self._config.batch_size, shuffle=False)

            X_val_tensor: Any = None
            y_val_tensor: Any = None
            if X_val_seq is not None and y_val_seq is not None and len(X_val_seq) > 0:
                X_val_tensor = torch.FloatTensor(X_val_seq).to(self._config.device)
                y_val_tensor = torch.FloatTensor(y_val_seq).to(self._config.device)

            # Eğitim döngüsü
            best_val_loss = float("inf")
            patience_counter = 0
            best_state: dict[str, Any] | None = None
            history: list[dict[str, Any]] = []

            for epoch in range(self._config.epochs):
                self._model.train()
                train_loss = 0.0

                for batch_X, batch_y in loader:
                    optimizer.zero_grad()
                    output = self._model(batch_X).squeeze(-1)
                    loss = criterion(output, batch_y)
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(self._model.parameters(), max_norm=1.0)
                    optimizer.step()
                    train_loss += loss.item()

                train_loss /= max(len(loader), 1)
                scheduler.step()

                val_loss = 0.0
                if X_val_tensor is not None and y_val_tensor is not None:
                    self._model.eval()
                    with torch.no_grad():
                        val_output = self._model(X_val_tensor).squeeze(-1)
                        val_loss = criterion(val_output, y_val_tensor).item()

                    if val_loss < best_val_loss:
                        best_val_loss = val_loss
                        patience_counter = 0
                        best_state = {k: v.clone() for k, v in self._model.state_dict().items()}
                    else:
                        patience_counter += 1
                        if patience_counter >= self._config.early_stopping_patience:
                            logger.info("Transformer erken durdurma tetiklendi", epoch=epoch)
                            break

                history.append(
                    {
                        "epoch": epoch,
                        "train_loss": round(float(train_loss), 6),
                        "val_loss": round(float(val_loss), 6),
                    }
                )

            if best_state is not None:
                self._model.load_state_dict(best_state)

            self._is_trained = True
            self._training_history = history

            metrics: dict[str, Any] = {
                "n_train": len(X_seq),
                "n_val": len(X_val_seq) if X_val_seq is not None else 0,
                "epochs_trained": len(history),
                "best_val_loss": round(float(best_val_loss), 6) if best_val_loss != float("inf") else 0.0,
            }

            if X_val is not None and y_val is not None and len(X_val) > self._config.sequence_length:
                val_pred = self.predict(X_val)
                y_val_target = y_val[self._config.sequence_length :]

                # Güvenli RMSE
                mse = float(np.mean((val_pred - y_val_target) ** 2))
                metrics["val_rmse"] = round(float(np.sqrt(mse)), 6)

                # Bilgi Katsayısı (IC)
                std_pred = np.std(val_pred)
                std_true = np.std(y_val_target)
                if std_pred > DEFAULT_EPSILON and std_true > DEFAULT_EPSILON:
                    corr = np.corrcoef(val_pred, y_val_target)[0, 1]
                    metrics["val_ic"] = round(float(corr), 4) if np.isfinite(corr) else 0.0
                else:
                    metrics["val_ic"] = 0.0

            self._record_audit_event(
                operation="TRAIN",
                epochs_trained=metrics["epochs_trained"],
                best_val_loss=metrics["best_val_loss"],
                val_ic=metrics.get("val_ic", 0.0),
                details=metrics,
            )

            logger.info("Transformer egitimi tamamlandi", **metrics)
            return metrics

    def train_polars(
        self,
        df_train: pl.DataFrame,
        target_col: str,
        feature_cols: list[str],
        df_val: pl.DataFrame | None = None,
    ) -> dict[str, Any]:
        """Polars DataFrame girdisi ile modeli eğitir.

        Args:
            df_train: Eğitim Polars DataFrame'i.
            target_col: Hedef serisi sütun adı.
            feature_cols: Girdi öznitelik sütunları listesi.
            df_val: Doğrulama Polars DataFrame'i (opsiyonel).

        Returns:
            Eğitim metrikleri sözlüğü.
        """
        X_train = df_train.select(feature_cols).fill_null(0.0).to_numpy()
        y_train = df_train.select(target_col).fill_null(0.0).to_numpy().squeeze()

        X_val: np.ndarray | None = None
        y_val: np.ndarray | None = None
        if df_val is not None and not df_val.is_empty():
            X_val = df_val.select(feature_cols).fill_null(0.0).to_numpy()
            y_val = df_val.select(target_col).fill_null(0.0).to_numpy().squeeze()

        return self.train(X_train, y_train, X_val, y_val)

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Eğitilmiş model ile girdi matrisi üzerinde çıkarım yapar.

        Args:
            X: Öznitelik matrisi (N, F).

        Returns:
            Dizi tahmin dizisi (N - sequence_length,). Yetersiz veri durumunda sıfır dizisi.
        """
        with self._lock:
            if not self._is_trained or self._model is None:
                return np.zeros(max(0, len(X) - self._config.sequence_length), dtype=np.float64)

            try:
                import torch

                X_seq, _ = self._create_sequences(X, np.zeros(len(X)))
                if len(X_seq) == 0:
                    return np.zeros(0, dtype=np.float64)

                self._model.eval()
                with torch.no_grad():
                    X_tensor = torch.FloatTensor(X_seq).to(self._config.device)
                    raw_preds = self._model(X_tensor).squeeze(-1).cpu().numpy()

                preds = np.asarray(raw_preds, dtype=np.float64)
                return preds if preds.ndim > 0 else np.array([preds], dtype=np.float64)
            except Exception as exc:
                logger.error("Transformer cikarim hatasi", hata=str(exc))
                return np.zeros(max(0, len(X) - self._config.sequence_length), dtype=np.float64)

    def predict_polars(
        self,
        df: pl.DataFrame,
        feature_cols: list[str],
    ) -> pl.DataFrame:
        """Polars DataFrame girdisi üzerinde tahmin yürüterek sonuç sütununu ekler.

        Args:
            df: Veri satırlarını içeren Polars DataFrame.
            feature_cols: Model girdi öznitelik sütunları.

        Returns:
            'transformer_pred' sütunu eklenmiş Polars DataFrame.
        """
        import polars as pl

        n_rows = len(df)
        if n_rows < self._config.sequence_length:
            return df.with_columns(pl.lit(0.0).alias("transformer_pred"))

        X = df.select(feature_cols).fill_null(0.0).to_numpy()
        preds = self.predict(X)

        # İlk sequence_length kadar adıma sıfır doldurarak boyut hizalaması sağla
        pad_size = n_rows - len(preds)
        if pad_size > 0:
            full_preds = np.concatenate([np.zeros(pad_size, dtype=np.float64), preds])
        else:
            full_preds = preds

        return df.with_columns(pl.Series("transformer_pred", full_preds[:n_rows]))

    def predict_with_confidence(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Tahmin ve Monte Carlo Dropout tabanlı belirsizlik güven skorunu üretir.

        Args:
            X: Öznitelik matrisi.

        Returns:
            (predictions, confidence) demeti.
        """
        with self._lock:
            if not self._is_trained or self._model is None:
                n_out = max(0, len(X) - self._config.sequence_length)
                return np.zeros(n_out, dtype=np.float64), np.zeros(n_out, dtype=np.float64)

            try:
                import torch

                X_seq, _ = self._create_sequences(X, np.zeros(len(X)))
                if len(X_seq) == 0:
                    return np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float64)

                # Monte Carlo Dropout ile 5 çıkarım
                self._model.train()  # Dropout'u aktif tut
                mc_preds: list[np.ndarray] = []
                X_tensor = torch.FloatTensor(X_seq).to(self._config.device)

                with torch.no_grad():
                    for _ in range(5):
                        p = self._model(X_tensor).squeeze(-1).cpu().numpy()
                        mc_preds.append(p)

                mc_matrix = np.asarray(mc_preds, dtype=np.float64)
                mean_pred = np.mean(mc_matrix, axis=0)
                std_pred = np.std(mc_matrix, axis=0)

                # Güven: 1 - normalize varyans
                confidence = np.clip(1.0 - (std_pred / 0.5), 0.0, 1.0)
                return mean_pred, confidence
            except Exception as exc:
                logger.error("Transformer belirsizlik tahmini basarisiz", hata=str(exc))
                return self.predict(X), np.zeros(max(0, len(X) - self._config.sequence_length), dtype=np.float64)
            finally:
                if self._model is not None:
                    self._model.eval()

    def _create_sequences(self, X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Zaman serisi penceresi formatında örtüşen dizileri oluşturur."""
        seq_len = self._config.sequence_length
        if len(X) <= seq_len:
            return np.zeros((0, seq_len, X.shape[1] if X.ndim > 1 else 1)), np.zeros(0)

        X_seq: list[np.ndarray] = []
        y_seq: list[float] = []
        for i in range(len(X) - seq_len):
            X_seq.append(X[i : i + seq_len])
            y_seq.append(float(y[i + seq_len]))

        return np.asarray(X_seq, dtype=np.float64), np.asarray(y_seq, dtype=np.float64)

    def _build_model(self, torch_mod: Any, nn_mod: Any) -> Any:
        """PyTorch Transformer modelini oluşturur ve hedeflenen cihaza taşır."""
        cfg = self._config

        class _InternalTransformerModel(nn_mod.Module):
            """Çok başlı öz-dikkat ve MLP sınıflandırıcı katmanlarını barındıran iç model."""

            def __init__(self, inner_cfg: TransformerConfig) -> None:
                super().__init__()
                self.input_projection = nn_mod.Linear(inner_cfg.input_size, inner_cfg.d_model)
                self.pos_encoding = PositionalEncoding(inner_cfg.d_model, inner_cfg.max_position_encoding)
                encoder_layer = nn_mod.TransformerEncoderLayer(
                    d_model=inner_cfg.d_model,
                    nhead=inner_cfg.nhead,
                    dim_feedforward=inner_cfg.dim_feedforward,
                    dropout=inner_cfg.dropout,
                    batch_first=True,
                )
                self.transformer_encoder = nn_mod.TransformerEncoder(
                    encoder_layer,
                    num_layers=inner_cfg.num_encoder_layers,
                )
                self.fc = nn_mod.Sequential(
                    nn_mod.Linear(inner_cfg.d_model, 64),
                    nn_mod.GELU(),
                    nn_mod.Dropout(inner_cfg.dropout),
                    nn_mod.Linear(64, inner_cfg.output_size),
                )

            def forward(self, x: Any) -> Any:
                """İleri besleme adımı: projeksiyon, konumsal kodlama ve transformer kodlayıcı."""
                x = self.input_projection(x)
                x = self.pos_encoding(x)
                x = self.transformer_encoder(x)
                x = x[:, -1, :]  # Son zaman adımı token temsili
                return self.fc(x)

        model = _InternalTransformerModel(cfg)
        return model.to(cfg.device)

    def save(self, path: str) -> bool:
        """Model ağırlıklarını ve konfigürasyonunu diske kaydeder.

        Args:
            path: Kayıt hedef dosya yolu.

        Returns:
            Kayıt başarılı ise True, aksi halde False.
        """
        with self._lock:
            if self._model is None:
                logger.error("Kaydedilecek egitilmis model bulunamadi")
                return False
            try:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                import torch

                torch.save(
                    {
                        "model_state": self._model.state_dict(),
                        "config": self._config.to_dict(),
                        "training_history": self._training_history,
                    },
                    path,
                )
                logger.info("Transformer modeli basariyla kaydedildi", dosya=path)
                return True
            except Exception as exc:
                logger.error("Transformer kayit islemi basarisiz", hata=str(exc))
                return False

    def load(self, path: str) -> bool:
        """Diskteki model ağırlıklarını ve konfigürasyonunu yükler.

        Args:
            path: Model dosya yolu.

        Returns:
            Yükleme başarılı ise True, aksi halde False.
        """
        with self._lock:
            try:
                import torch
                import torch.nn as nn

                data = torch.load(path, map_location=self._config.device)
                cfg_dict = data.get("config", {})
                if isinstance(cfg_dict, dict):
                    self._config = TransformerConfig(**cfg_dict)

                self._training_history = data.get("training_history", [])
                self._model = self._build_model(torch, nn)
                self._model.load_state_dict(data["model_state"])
                self._model.eval()
                self._is_trained = True
                logger.info("Transformer modeli basariyla yuklendi", dosya=path)
                return True
            except Exception as exc:
                logger.error("Transformer yukleme islemi basarisiz", hata=str(exc))
                return False

    @property
    def is_trained(self) -> bool:
        """Modelin eğitilmiş olup olmadığını döndürür."""
        with self._lock:
            return self._is_trained

    @property
    def training_history(self) -> list[dict[str, Any]]:
        """Eğitim geçmişi kayıtlarını döndürür."""
        with self._lock:
            return list(self._training_history)

    def __repr__(self) -> str:
        """StockTransformer özet metin gösterimini oluşturur."""
        with self._lock:
            return f"StockTransformer(trained={self._is_trained}, config={self._config})"


__all__: Final[list[str]] = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_DIM_FEEDFORWARD",
    "DEFAULT_D_MODEL",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EARLY_STOPPING_PATIENCE",
    "DEFAULT_EPOCHS",
    "DEFAULT_EPSILON",
    "DEFAULT_INPUT_SIZE",
    "DEFAULT_LEARNING_RATE",
    "DEFAULT_MAX_POSITION_ENCODING",
    "DEFAULT_NHEAD",
    "DEFAULT_NUM_ENCODER_LAYERS",
    "DEFAULT_OUTPUT_SIZE",
    "DEFAULT_SEQUENCE_LENGTH",
    "DEFAULT_WARMUP_STEPS",
    "DEFAULT_WEIGHT_DECAY",
    "PositionalEncoding",
    "StockTransformer",
    "TransformerConfig",
    "configure_duckdb_wal",
]
