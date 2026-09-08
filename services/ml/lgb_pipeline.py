"""ALPHA BIST — LightGBM Evren Alfa Tahmin ve Eğitim Hattı (Nihai — ⭐⭐⭐⭐⭐).

Bu modül, Borsa İstanbul evrenindeki tüm hisseler için zaman serisi Point-In-Time
öznitelik çıkarımı, göreceli getiri (benchmark excess return) etiketlemesi,
şampiyon model LightGBM eğitimi ve toplu (batch) getiri sıralama tahmin hattını içerir.

Temel Yetenekler:
- Sıfır Veri Sızıntısı (Point-In-Time snapshot offsets) ile güvenli veri üretimi
- BIST 100 / Sektör göreceli getiri (Excess Return) etiketleme motoru
- Vektörize toplu tahmin (Batch Inference) ile yüksek hızlı evren taraması
- Model serileştirme (diske kaydetme ve yükleme) desteği
- Polars DataFrame üzerinden doğrudan tahmin (`predict_polars`)
- DuckDB üzerinde SSD korumalı WAL ile eğitim ve tahmin denetim izi
- İş parçacığı güvenliği (`threading.RLock`) ve fail-closed mimari
"""

from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import duckdb
import lightgbm as lgb
import numpy as np
import orjson
import polars as pl
import structlog

from services.ml.feature_engine import compute_universe_features

logger = structlog.get_logger(__name__)

# --- Sabitler ---
DEFAULT_LEARNING_RATE: Final[float] = 0.05
DEFAULT_NUM_LEAVES: Final[int] = 31
DEFAULT_MAX_DEPTH: Final[int] = 5
DEFAULT_FEATURE_FRACTION: Final[float] = 0.80
DEFAULT_MIN_DATA_IN_LEAF: Final[int] = 20
DEFAULT_NUM_BOOST_ROUND: Final[int] = 100
DEFAULT_MIN_HISTORY_BARS: Final[int] = 120
DEFAULT_FORWARD_DAYS: Final[int] = 20
DEFAULT_RANDOM_STATE: Final[int] = 42
DEFAULT_DUCKDB_PATH: Final[str] = "data/lgb_pipeline.duckdb"
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


def safe_parse_datetime(date_val: datetime.datetime | str) -> datetime.datetime:
    """Farklı biçimlerdeki tarih girdilerini güvenli bir şekilde datetime nesnesine dönüştürür.

    Args:
        date_val: Datetime veya ISO tarih stringi.

    Returns:
        datetime.datetime nesnesi.
    """
    if isinstance(date_val, datetime.datetime):
        return date_val
    s_val = str(date_val).strip()
    try:
        return datetime.datetime.fromisoformat(s_val[:10])
    except Exception:
        return datetime.datetime.strptime(s_val[:10], "%Y-%m-%d")


@dataclass(slots=True)
class PipelinePrediction:
    """Hisse bazlı tahmin çıktısı veri modeli."""

    ticker: str
    score: float
    features: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        """Tahmin sonucunu sözlüğe dönüştürür."""
        return {
            "ticker": self.ticker,
            "score": round(self.score, 6),
            "features": self.features,
        }

    def to_orjson_bytes(self) -> bytes:
        """Tahmin sonucunu orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelinePrediction:
        """Sözlükten PipelinePrediction nesnesi oluşturur."""
        return cls(
            ticker=str(data.get("ticker", "")),
            score=float(data.get("score", 0.0)),
            features=dict(data.get("features", {})),
        )

    def __repr__(self) -> str:
        return f"PipelinePrediction(ticker='{self.ticker}', score={self.score:.4f})"


class LightGBMPipeline:
    """BIST evreni için LightGBM tabanlı alfa tahmin ve eğitim hattı."""

    def __init__(
        self,
        params: dict[str, Any] | None = None,
        duckdb_path: str = DEFAULT_DUCKDB_PATH,
    ) -> None:
        """LightGBMPipeline nesnesini başlatır.

        Args:
            params: LightGBM eğitim hiperparametreleri sözlüğü.
            duckdb_path: Denetim izi DuckDB veritabanı yolu.
        """
        self._lock = threading.RLock()
        self.model: lgb.Booster | None = None
        self.features: list[str] = []
        self.duckdb_path = duckdb_path

        self.params: dict[str, Any] = {
            "objective": "regression",
            "metric": "rmse",
            "boosting_type": "gbdt",
            "learning_rate": DEFAULT_LEARNING_RATE,
            "num_leaves": DEFAULT_NUM_LEAVES,
            "max_depth": DEFAULT_MAX_DEPTH,
            "feature_fraction": DEFAULT_FEATURE_FRACTION,
            "min_data_in_leaf": DEFAULT_MIN_DATA_IN_LEAF,
            "verbose": -1,
            "random_state": DEFAULT_RANDOM_STATE,
        }
        if params:
            self.params.update(params)

        self._init_duckdb()

    def _init_duckdb(self) -> None:
        """DuckDB denetim tablosunu hazırlar."""
        try:
            db_file = Path(self.duckdb_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(str(db_file)) as conn:
                configure_duckdb_wal(conn)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS lgb_pipeline_audit (
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        action VARCHAR,
                        sample_count BIGINT,
                        feature_count BIGINT,
                        target_date VARCHAR,
                        details VARCHAR
                    );
                """)
        except Exception as exc:
            logger.warning("DuckDB pipeline denetim tablosu hazirlanamadi", hata=str(exc))

    def generate_samples(
        self,
        market_data: dict[str, pl.DataFrame],
        bm_df: pl.DataFrame,
        sector_map: dict[str, str],
        train_start: datetime.datetime | str,
        train_end: datetime.datetime | str,
        snapshot_offsets: list[int] | None = None,
        forward_days: int = DEFAULT_FORWARD_DAYS,
        min_history_bars: int = DEFAULT_MIN_HISTORY_BARS,
    ) -> tuple[np.ndarray, np.ndarray, list[str]]:
        """Point-in-Time prensibine uygun eğitim örnekleri ve getiri etiketleri üretir.

        Args:
            market_data: Hisse bazında tarihsel çubuk verileri `{ticker: pl.DataFrame}`.
            bm_df: Karşılaştırma ölçütü (Benchmark / BIST 100) verisi.
            sector_map: Hisse-sektör eşleme sözlüğü `{ticker: sector}`.
            train_start: Eğitim başlangıç tarihi.
            train_end: Eğitim bitiş tarihi.
            snapshot_offsets: Snapshot offset günleri listesi (varsayılan: [20, 40, 60, 80]).
            forward_days: Gelecek etiketleme periyodu (işlem günü).
            min_history_bars: Öznitelik hesabı için gereken asgari geçmiş bar sayısı.

        Returns:
            `(X, y, feature_names)` demeti.
        """
        offsets = snapshot_offsets if snapshot_offsets is not None else [20, 40, 60, 80]
        rows: list[dict[str, float]] = []
        labels: list[float] = []
        all_keys: list[str] = []

        t_start = safe_parse_datetime(train_start)
        t_end = safe_parse_datetime(train_end)

        for offset in offsets:
            t_snap = t_end - datetime.timedelta(days=int(offset))
            t_fwd = t_snap + datetime.timedelta(days=int(forward_days))

            if t_snap < t_start:
                continue

            snap_md: dict[str, pl.DataFrame] = {}
            for t, df in market_data.items():
                if df is None or df.is_empty():
                    continue
                if "Date" in df.columns:
                    sub_df = df.filter(pl.col("Date") <= t_snap)
                else:
                    sub_df = df
                if len(sub_df) >= min_history_bars:
                    snap_md[t] = sub_df

            if bm_df is None or bm_df.is_empty():
                continue
            if "Date" in bm_df.columns:
                snap_bm = bm_df.filter(pl.col("Date") <= t_snap)
            else:
                snap_bm = bm_df
            if len(snap_bm) < min_history_bars:
                continue

            features = compute_universe_features(snap_md, snap_bm, sector_map)

            for ticker, feats in features.items():
                if not feats or ticker not in market_data:
                    continue

                df_t = market_data[ticker]
                if df_t is None or df_t.is_empty() or "Date" not in df_t.columns:
                    continue

                df_fwd = df_t.filter((pl.col("Date") >= t_snap) & (pl.col("Date") <= t_fwd))
                bm_fwd = (
                    bm_df.filter((pl.col("Date") >= t_snap) & (pl.col("Date") <= t_fwd))
                    if "Date" in bm_df.columns
                    else pl.DataFrame()
                )

                if len(df_fwd) < 2 or len(bm_fwd) < 2:
                    continue

                p_0 = float(df_fwd["Close"][0])
                p_1 = float(df_fwd["Close"][-1])
                b_0 = float(bm_fwd["Close"][0])
                b_1 = float(bm_fwd["Close"][-1])

                if p_0 <= DEFAULT_EPSILON or b_0 <= DEFAULT_EPSILON:
                    continue

                ret = (p_1 / p_0) - 1.0
                bm_ret = (b_1 / b_0) - 1.0
                excess_ret = ret - bm_ret

                if not np.isfinite(excess_ret):
                    continue

                rows.append(feats)
                labels.append(float(excess_ret))

                if not all_keys:
                    all_keys = sorted(feats.keys())

        if not rows:
            return np.array([]), np.array([]), []

        # NaN/Inf güvenli sayısal dönüşüm
        X_list = []
        for r in rows:
            row_vals = []
            for k in all_keys:
                val = r.get(k, 0.0)
                val_f = float(val) if val is not None and np.isfinite(val) else 0.0
                row_vals.append(val_f)
            X_list.append(row_vals)

        X = np.array(X_list, dtype=np.float32)
        y = np.array(labels, dtype=np.float64)

        return X, y, all_keys

    def train(
        self,
        market_data: dict[str, pl.DataFrame],
        bm_df: pl.DataFrame,
        sector_map: dict[str, str],
        train_start: datetime.datetime | str,
        train_end: datetime.datetime | str,
        snapshot_offsets: list[int] | None = None,
        forward_days: int = DEFAULT_FORWARD_DAYS,
        num_boost_round: int = DEFAULT_NUM_BOOST_ROUND,
        min_history_bars: int = DEFAULT_MIN_HISTORY_BARS,
    ) -> bool:
        """Tarihsel snapshot örnekleri üzerinde LightGBM modelini eğitir.

        Args:
            market_data: Piyasa fiyat verileri sözlüğü.
            bm_df: Karşılaştırma ölçütü verisi.
            sector_map: Sektör haritası.
            train_start: Eğitim başlangıç tarihi.
            train_end: Eğitim bitiş tarihi.
            snapshot_offsets: Snapshot offset günleri.
            forward_days: Gelecek etiketleme periyodu (işlem günü).
            num_boost_round: İterasyon (ağaç) sayısı.
            min_history_bars: Asgari geçmiş bar sayısı.

        Returns:
            Eğitim başarılı ise True, veri yoksa False.
        """
        with self._lock:
            X, y, feature_names = self.generate_samples(
                market_data=market_data,
                bm_df=bm_df,
                sector_map=sector_map,
                train_start=train_start,
                train_end=train_end,
                snapshot_offsets=snapshot_offsets,
                forward_days=forward_days,
                min_history_bars=min_history_bars,
            )

            if len(X) == 0:
                logger.warning("Egitim icin orneklem uretilemedi")
                return False

            self.features = feature_names
            train_data = lgb.Dataset(X, label=y, feature_name=feature_names)
            self.model = lgb.train(self.params, train_data, num_boost_round=num_boost_round)

            self._record_audit(
                action="TRAIN",
                sample_count=len(X),
                feature_count=len(feature_names),
                target_date=str(train_end),
                details=f"Egitim tamamlandi (num_boost_round={num_boost_round})",
            )

            logger.info(
                "LightGBM modeli egitildi",
                ornek_sayisi=len(X),
                oznitelik_sayisi=len(feature_names),
            )
            return True

    def train_direct(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: list[str],
        num_boost_round: int = DEFAULT_NUM_BOOST_ROUND,
    ) -> bool:
        """Doğrudan öznitelik matrisi ve hedef vektörü üzerinde LightGBM eğitir.

        Args:
            X: Öznitelik matrisi.
            y: Hedef değişken vektörü.
            feature_names: Öznitelik isimleri listesi.
            num_boost_round: İterasyon sayısı.

        Returns:
            Başarılı ise True.
        """
        with self._lock:
            if len(X) == 0:
                return False
            self.features = list(feature_names)
            train_data = lgb.Dataset(X, label=y, feature_name=feature_names)
            self.model = lgb.train(self.params, train_data, num_boost_round=num_boost_round)

            self._record_audit(
                action="TRAIN_DIRECT",
                sample_count=len(X),
                feature_count=len(feature_names),
                target_date="DIRECT",
                details=f"Dogrudan matris egitimi (num_boost_round={num_boost_round})",
            )
            return True

    def predict(
        self,
        market_data: dict[str, pl.DataFrame],
        bm_df: pl.DataFrame,
        sector_map: dict[str, str],
        target_date: datetime.datetime | str,
        min_history_bars: int = DEFAULT_MIN_HISTORY_BARS,
    ) -> list[PipelinePrediction]:
        """Hedef tarih itibarıyla evrendeki hisseler için getiri tahminlerini toplu üretir.

        Args:
            market_data: Piyasa fiyat verileri sözlüğü.
            bm_df: Karşılaştırma ölçütü verisi.
            sector_map: Sektör haritası.
            target_date: Tahmin yapılacak hedef tarih (Point-In-Time).
            min_history_bars: Asgari geçmiş bar sayısı.

        Returns:
            Skora göre azalan sıralı `PipelinePrediction` nesneleri listesi.
        """
        with self._lock:
            if not self.model or not self.features:
                logger.warning("Model henuz egitilmemis veya yuklenmemis")
                return []

            t_target = safe_parse_datetime(target_date)

            snap_md: dict[str, pl.DataFrame] = {}
            for t, df in market_data.items():
                if df is None or df.is_empty():
                    continue
                if "Date" in df.columns:
                    sub_df = df.filter(pl.col("Date") <= t_target)
                else:
                    sub_df = df
                if len(sub_df) >= min_history_bars:
                    snap_md[t] = sub_df

            if bm_df is None or bm_df.is_empty():
                return []
            if "Date" in bm_df.columns:
                snap_bm = bm_df.filter(pl.col("Date") <= t_target)
            else:
                snap_bm = bm_df
            if len(snap_bm) < min_history_bars:
                return []

            features = compute_universe_features(snap_md, snap_bm, sector_map)
            valid_tickers: list[str] = []
            x_batch_list: list[list[float]] = []
            valid_feats: list[dict[str, float]] = []

            for ticker, feats in features.items():
                if not feats:
                    continue
                row_vals = []
                for k in self.features:
                    val = feats.get(k, 0.0)
                    val_f = float(val) if val is not None and np.isfinite(val) else 0.0
                    row_vals.append(val_f)

                valid_tickers.append(ticker)
                x_batch_list.append(row_vals)
                valid_feats.append(feats)

            if not valid_tickers:
                return []

            # Vektörize Toplu Tahmin (Tek seferde tüm evren)
            X_batch = np.array(x_batch_list, dtype=np.float32)
            raw_scores = self.model.predict(X_batch)

            predictions: list[PipelinePrediction] = []
            for i, ticker in enumerate(valid_tickers):
                sc = float(raw_scores[i]) if np.isfinite(raw_scores[i]) else 0.0
                predictions.append(
                    PipelinePrediction(
                        ticker=ticker,
                        score=sc,
                        features=valid_feats[i],
                    )
                )

            # Skora göre azalan sırala
            predictions.sort(key=lambda x: x.score, reverse=True)

            self._record_audit(
                action="PREDICT",
                sample_count=len(predictions),
                feature_count=len(self.features),
                target_date=str(t_target),
                details=f"Toplu tahmin tamamlandi ({len(predictions)} hisse)",
            )

            return predictions

    def predict_polars(
        self,
        market_data: dict[str, pl.DataFrame],
        bm_df: pl.DataFrame,
        sector_map: dict[str, str],
        target_date: datetime.datetime | str,
        min_history_bars: int = DEFAULT_MIN_HISTORY_BARS,
    ) -> pl.DataFrame:
        """Tahmin sonuçlarını sıralanmış Polars DataFrame olarak döndürür.

        Args:
            market_data: Piyasa fiyat verileri sözlüğü.
            bm_df: Karşılaştırma ölçütü verisi.
            sector_map: Sektör haritası.
            target_date: Hedef tarih.
            min_history_bars: Asgari geçmiş bar sayısı.

        Returns:
            'ticker' ve 'score' sütunlarını içeren Polars DataFrame.
        """
        preds = self.predict(
            market_data=market_data,
            bm_df=bm_df,
            sector_map=sector_map,
            target_date=target_date,
            min_history_bars=min_history_bars,
        )
        if not preds:
            return pl.DataFrame({"ticker": [], "score": []}, schema={"ticker": pl.Utf8, "score": pl.Float64})

        return pl.DataFrame({
            "ticker": [p.ticker for p in preds],
            "score": [p.score for p in preds],
        })

    def save_model(self, file_path: str | Path) -> None:
        """Eğitilmiş LightGBM modelini ve öznitelik listesini diske kaydeder.

        Args:
            file_path: Model dosya yolu.

        Raises:
            ValueError: Model henüz eğitilmemişse fırlatılır.
        """
        with self._lock:
            if not self.model:
                raise ValueError("Kaydedilecek egitilmis model bulunamadi.")

            p = Path(file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self.model.save_model(str(p))

            meta_p = p.with_suffix(".meta.json")
            meta_data = {
                "features": self.features,
                "params": self.params,
            }
            meta_p.write_bytes(orjson.dumps(meta_data))
            logger.info("LightGBM modeli diske kaydedildi", dosya=str(p))

    def load_model(self, file_path: str | Path) -> None:
        """Diskten LightGBM modelini ve öznitelik listesini yükler.

        Args:
            file_path: Yüklenecek model dosya yolu.
        """
        with self._lock:
            p = Path(file_path)
            if not p.exists():
                raise FileNotFoundError(f"Model dosyasi bulunamadi: {p}")

            self.model = lgb.Booster(model_file=str(p))

            meta_p = p.with_suffix(".meta.json")
            if meta_p.exists():
                meta_data = orjson.loads(meta_p.read_bytes())
                self.features = meta_data.get("features", [])
                if "params" in meta_data:
                    self.params.update(meta_data["params"])

            logger.info("LightGBM modeli diskten yuklendi", dosya=str(p), oznitelikler=len(self.features))

    def _record_audit(
        self, action: str, sample_count: int, feature_count: int, target_date: str, details: str
    ) -> None:
        """DuckDB'ye işlem denetim kaydı ekler."""
        try:
            with duckdb.connect(self.duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO lgb_pipeline_audit (
                        action, sample_count, feature_count, target_date, details
                    ) VALUES (?, ?, ?, ?, ?);
                    """,
                    [
                        str(action),
                        int(sample_count),
                        int(feature_count),
                        str(target_date),
                        str(details),
                    ],
                )
        except Exception as exc:
            logger.debug("DuckDB pipeline denetim kaydi atlandi", hata=str(exc))

    def get_audit_as_polars(self) -> pl.DataFrame:
        """DuckDB'deki pipeline denetim kayıtlarını Polars DataFrame olarak döndürür."""
        import polars as pl

        with self._lock:
            try:
                with duckdb.connect(self.duckdb_path) as conn:
                    return conn.execute("SELECT * FROM lgb_pipeline_audit ORDER BY timestamp DESC").pl()
            except Exception as exc:
                logger.warning("DuckDB denetim kayitlari okunamadi", hata=str(exc))
                return pl.DataFrame()

    def __repr__(self) -> str:
        is_trained = self.model is not None
        return f"LightGBMPipeline(trained={is_trained}, features={len(self.features)}, lr={self.params.get('learning_rate')})"


__all__: Final[list[str]] = [
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EPSILON",
    "DEFAULT_FEATURE_FRACTION",
    "DEFAULT_FORWARD_DAYS",
    "DEFAULT_LEARNING_RATE",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MIN_DATA_IN_LEAF",
    "DEFAULT_MIN_HISTORY_BARS",
    "DEFAULT_NUM_BOOST_ROUND",
    "DEFAULT_NUM_LEAVES",
    "DEFAULT_RANDOM_STATE",
    "LightGBMPipeline",
    "PipelinePrediction",
    "configure_duckdb_wal",
    "safe_parse_datetime",
]
