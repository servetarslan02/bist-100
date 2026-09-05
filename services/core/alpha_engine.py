"""ALPHA BIST — Alpha Engine v2.0 (Kurumsal Seviye Alpha Tahmin Motoru).

LightGBM tabanlı alfa sinyali ve aşırı getiri (excess return) tahminleme motoru:
- Sektör ve piyasa göstergelerine dayalı özellik mühendisliği (feature engineering)
- BIST hisselerinin ileriye dönük aşırı getiri potansiyelini skorlama
- CUDA / GPU hızlandırma desteği ile otomatik eğitim ve hiperparametre optimizasyonu
- Model versiyonlama, parmak izi hash kontrolü ve dosya tabanlı model kalıcılığı
- Vektörize toplu tahmin (batch inference) ve sayısal kararlılık guard'ları
"""

from __future__ import annotations

import datetime
import hashlib
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
import polars as pl
import structlog
import yfinance as yf
from opentelemetry import metrics, trace

from services.core.otel import otel_trace
from services.core.safe_pickle import safe_pickle_dump, safe_pickle_load
from services.ingestion.bist_universe import bist_universe
from services.ml.feature_engine import compute_universe_features
from services.ml.hyper_optimizer import HyperOptimizer

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.alpha_engine")
meter = metrics.get_meter("alpha-bist.alpha_engine")

# Varsayılan Hiperparametreler ve Sabitler
DEFAULT_MODEL_PATH = "data/alpha_engine_model.pkl"
DEFAULT_BATCH_SIZE = 100
DEFAULT_FORWARD_DAYS = 20
DEFAULT_MIN_HISTORY_BARS = 120
DEFAULT_EXCLUDE_FEATURES = [
    "momentum_accel",
    "roc_120d",
    "dist_sma200",
    "cs_zscore_ret_1d",
    "roc_5d",
]
DEFAULT_PARAMS: dict[str, Any] = {
    "objective": "regression",
    "metric": "rmse",
    "n_estimators": 100,
    "learning_rate": 0.05,
    "max_depth": 3,
    "num_leaves": 7,
    "verbose": -1,
    "n_jobs": -1,
    "random_state": 42,
    "seed": 42,
}


def _yf_to_polars(yf_df: Any) -> pl.DataFrame:
    """yfinance pandas DataFrame nesnesini timezone-naive Polars DataFrame'e dönüştürür.

    Args:
        yf_df: yfinance tarafından döndürülen pandas DataFrame veya None.

    Returns:
        pl.DataFrame: Polars DataFrame nesnesi.
    """
    if yf_df is None or len(yf_df) == 0:
        return pl.DataFrame()
    df = yf_df.reset_index()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # İsimsiz index'ten türeyen 'index' kolonunu 'Date' olarak normalize et
    if "index" in df.columns and "Date" not in df.columns:
        df = df.rename(columns={"index": "Date"})

    # Polars ve Python datetime karşılaştırmalarında timezone uyuşmazlığını önle
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)

    return pl.from_pandas(df)



def _detect_gpu_cuda() -> tuple[bool, str]:
    """NVIDIA CUDA / GPU donanım hızlandırma desteğini tespit eder.

    Returns:
        tuple[bool, str]: (GPU var mı, Cihaz adı).
    """
    try:
        import torch

        if torch.cuda.is_available():
            return True, str(torch.cuda.get_device_name(0))
    except Exception as exc:
        logger.debug("gpu_cuda_algilanamadi_cpu_kullanilacak", hata=str(exc))
    return False, "CPU"


class AlphaEngine:
    """BIST hisse evreni için LightGBM tabanlı alfa tahmin ve skorlama motoru."""

    def __init__(self, exclude_features: list[str] | None = None) -> None:
        """AlphaEngine örneğini başlatır ve varsa kayıtlı modeli diskten yükler.

        Args:
            exclude_features: Eğitim ve tahminde hariç tutulacak gürültülü öznitelikler.
        """
        has_gpu, dev_name = _detect_gpu_cuda()
        self.has_gpu = has_gpu
        self.gpu_device_name = dev_name
        self.params: dict[str, Any] = dict(DEFAULT_PARAMS)
        if self.has_gpu:
            logger.info("alpha_engine_gpu_hizlandirma_aktif", cihaz=self.gpu_device_name)
        self.model: lgb.Booster | None = None
        self.features: list[str] = []
        self.exclude_features = (
            exclude_features if exclude_features is not None else list(DEFAULT_EXCLUDE_FEATURES)
        )

        # Disk üzerindeki model varsa otomatik yükle (30 günlük model geçerli kabul edilir)
        loaded = self._load_model(max_age_hours=24 * 30)
        if loaded:
            logger.info("alpha_engine_disk_modeli_yuklendi", ozellik_sayisi=len(self.features))
        else:
            logger.info("alpha_engine_egitilmemis_durumda")

    def __repr__(self) -> str:
        """AlphaEngine nesnesinin açıklayıcı dize temsili."""
        model_status = "egitilmis" if self.model is not None else "egitilmemis"
        return (
            f"AlphaEngine(durum={model_status!r}, "
            f"ozellik_sayisi={len(self.features)}, "
            f"gpu={self.has_gpu!r}, "
            f"cihaz={self.gpu_device_name!r})"
        )

    @otel_trace("alpha_engine.fetch_data")
    def fetch_data(
        self,
        start_date: str,
        end_date: str,
        tickers: list[str] | None = None,
    ) -> tuple[dict[str, pl.DataFrame], pl.DataFrame, dict[str, str]]:
        """BIST hisse evreni ve endeks verilerini çeker ve Polars DataFrame formatına çevirir.

        Args:
            start_date: Başlangıç tarihi (YYYY-MM-DD).
            end_date: Bitiş tarihi (YYYY-MM-DD).
            tickers: Çekilecek hisse kodları listesi (None ise evrendeki tüm hisseler).

        Returns:
            tuple: (market_data, bm_df, sector_map) verileri.
        """
        if tickers is None:
            tickers = (
                bist_universe.BIST_ALL_TICKERS
                if hasattr(bist_universe, "BIST_ALL_TICKERS") and bist_universe.BIST_ALL_TICKERS
                else []
            )
        sector_map = {t: bist_universe.get_ticker_sector(t) for t in tickers}

        market_data: dict[str, pl.DataFrame] = {}
        for i in range(0, len(tickers), DEFAULT_BATCH_SIZE):
            chunk = tickers[i : i + DEFAULT_BATCH_SIZE]
            chunk_symbols = [f"{t}.IS" for t in chunk]
            try:
                raw = yf.download(
                    tickers=" ".join(chunk_symbols),
                    start=start_date,
                    end=end_date,
                    group_by="ticker",
                    auto_adjust=True,
                    progress=False,
                    threads=True,
                )
                if raw is not None and len(raw) > 0:
                    for t in chunk:
                        tick_sym = f"{t}.IS"
                        try:
                            if isinstance(raw.columns, pd.MultiIndex):
                                if tick_sym in raw.columns.levels[0]:
                                    df_t = raw[tick_sym].dropna(how="all")
                                    if len(df_t) >= 10:
                                        market_data[t] = _yf_to_polars(df_t)
                            else:
                                df_t = raw.dropna(how="all")
                                if len(df_t) >= 10:
                                    market_data[t] = _yf_to_polars(df_t)
                        except Exception as parse_err:
                            logger.debug("alpha_engine_ticker_ayristirma_hatasi", ticker=t, hata=str(parse_err))
                            continue
            except Exception as e:
                logger.warning("alpha_engine_veri_indirme_uyarisi", chunk_index=i, hata=str(e))

        # Benchmark verisi
        bm_df = pl.DataFrame()
        try:
            bm_raw = yf.download("XU100.IS", start=start_date, end=end_date, auto_adjust=True, progress=False)
            if bm_raw is not None and len(bm_raw) > 0:
                bm_df = _yf_to_polars(bm_raw.dropna(how="all"))
        except Exception as e:
            logger.warning("alpha_engine_benchmark_indirme_uyarisi", hata=str(e))

        return market_data, bm_df, sector_map

    @otel_trace("alpha_engine.generate_training_samples")
    def generate_training_samples(
        self,
        market_data: dict[str, pl.DataFrame],
        bm_df: pl.DataFrame,
        sector_map: dict[str, str],
        train_start: datetime.datetime,
        train_end: datetime.datetime,
        snapshot_offsets: list[int] | None = None,
        forward_days: int = DEFAULT_FORWARD_DAYS,
    ) -> tuple[np.ndarray, np.ndarray, list[str]]:
        """Girdi piyasa verilerinden geçmiş anlık görüntüler alarak eğitim matrisini (X, y) oluşturur.

        Args:
            market_data: Hisse bazlı geçmiş fiyat verileri.
            bm_df: BIST 100 endeks verisi.
            sector_map: Hisse-sektör eşleme tablosu.
            train_start: Eğitim başlangıç tarihi.
            train_end: Eğitim bitiş tarihi.
            snapshot_offsets: Snapshot gün mesafeleri.
            forward_days: İleriye dönük getiri hedef ufku (varsayılan: 20 gün).

        Returns:
            tuple: (X öznitelik matrisi, y hedef vektörü, öznitelik isimleri listesi).
        """
        if snapshot_offsets is None:
            snapshot_offsets = [20, 40, 60, 80]
        rows: list[dict[str, float]] = []
        labels: list[float] = []
        feature_key_set: set[str] = set()

        for offset in snapshot_offsets:
            t_snap = train_end - datetime.timedelta(days=int(offset))
            t_fwd = t_snap + datetime.timedelta(days=int(forward_days))

            if t_snap < train_start:
                continue

            snap_md: dict[str, pl.DataFrame] = {}
            for t, df in market_data.items():
                if "Date" in df.columns:
                    sub_df = df.filter((pl.col("Date") >= train_start) & (pl.col("Date") <= t_snap))
                    if len(sub_df) >= DEFAULT_MIN_HISTORY_BARS:
                        snap_md[t] = sub_df

            if "Date" in bm_df.columns:
                snap_bm = bm_df.filter((pl.col("Date") >= train_start) & (pl.col("Date") <= t_snap))
            else:
                snap_bm = bm_df
            if len(snap_bm) < DEFAULT_MIN_HISTORY_BARS:
                continue

            features = compute_universe_features(snap_md, snap_bm, sector_map)

            for ticker, feats in features.items():
                if not feats or ticker not in market_data:
                    continue

                if self.exclude_features:
                    for exf in self.exclude_features:
                        feats.pop(exf, None)

                df_t = market_data[ticker]
                if "Date" in df_t.columns:
                    df_fwd = df_t.filter((pl.col("Date") >= t_snap) & (pl.col("Date") <= t_fwd))
                else:
                    df_fwd = df_t

                if "Date" in bm_df.columns:
                    bm_fwd = bm_df.filter((pl.col("Date") >= t_snap) & (pl.col("Date") <= t_fwd))
                else:
                    bm_fwd = bm_df

                if len(df_fwd) < 2 or len(bm_fwd) < 2:
                    continue

                try:
                    p_0 = float(df_fwd["Close"][0])
                    p_1 = float(df_fwd["Close"][-1])
                    b_0 = float(bm_fwd["Close"][0])
                    b_1 = float(bm_fwd["Close"][-1])
                except Exception:
                    continue

                # Sayısal kararlılık ve NaN/Inf/Sıfır guard kontrolleri
                if (
                    not np.isfinite(p_0)
                    or not np.isfinite(p_1)
                    or not np.isfinite(b_0)
                    or not np.isfinite(b_1)
                    or p_0 <= 0
                    or b_0 <= 0
                ):
                    continue

                stock_ret = (p_1 / p_0) - 1.0
                bm_ret = (b_1 / b_0) - 1.0
                excess_ret = float(stock_ret - bm_ret)

                if not np.isfinite(excess_ret):
                    continue

                rows.append(feats)
                labels.append(excess_ret)
                feature_key_set.update(feats.keys())

        if not rows or not feature_key_set:
            return np.array([]), np.array([]), []

        all_keys = sorted(feature_key_set)
        X = np.array([[float(r.get(k, 0.0) or 0.0) for k in all_keys] for r in rows], dtype=np.float64)
        y = np.array(labels, dtype=np.float64)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        return X, y, all_keys

    @otel_trace("alpha_engine.train")
    def train(
        self,
        market_data: dict[str, pl.DataFrame],
        bm_df: pl.DataFrame,
        sector_map: dict[str, str],
        train_start_str: str,
        train_end_str: str,
        optimize: bool = True,
    ) -> bool:
        """LightGBM modelini verilen tarih aralığındaki verilerle eğitir.

        Args:
            market_data: Hisse fiyat verileri.
            bm_df: Benchmark endeks verisi.
            sector_map: Sektör eşleme haritası.
            train_start_str: Eğitim başlangıcı (YYYY-MM-DD).
            train_end_str: Eğitim bitişi (YYYY-MM-DD).
            optimize: Hiperparametre optimizasyonu yapılsın mı.

        Returns:
            bool: Eğitim başarılı ise True, veri yetersizse False.
        """
        t_start = datetime.datetime.strptime(train_start_str, "%Y-%m-%d")
        t_end = datetime.datetime.strptime(train_end_str, "%Y-%m-%d")
        X, y, feature_names = self.generate_training_samples(market_data, bm_df, sector_map, t_start, t_end)

        if len(X) == 0:
            logger.error("alpha_engine_egitim_ornekleri_olusturulamadi")
            return False

        self.features = feature_names

        if optimize:
            optimizer = HyperOptimizer(n_trials=20, objective=self.params.get("objective", "regression"))
            best_params = optimizer.optimize(X, y, feature_names)
            self.params.update(best_params)
            lr = self.params.get("learning_rate", 0)
            leaves = self.params.get("num_leaves", 0)
            logger.info("alpha_engine_optuna_parametreleri", lr=lr, leaves=leaves)

        train_params = dict(self.params)
        if train_params.get("objective") == "lambdarank":
            train_data = lgb.Dataset(X, label=y, feature_name=feature_names, group=[len(X)])
        else:
            train_data = lgb.Dataset(X, label=y, feature_name=feature_names)

        if self.has_gpu:
            train_params["device"] = "gpu"
        try:
            self.model = lgb.train(train_params, train_data, num_boost_round=100)
        except Exception as gpu_err:
            logger.warning(
                "alpha_engine_gpu_egitimi_basarisiz_cpu_ile_deneniyor",
                hata=str(gpu_err),
            )
            train_params.pop("device", None)
            self.model = lgb.train(train_params, train_data, num_boost_round=100)

        logger.info("alpha_engine_model_egitildi", ornek_sayisi=len(X))
        self._save_model()
        return True

    @otel_trace("alpha_engine.predict")
    def predict(
        self,
        market_data: dict[str, pl.DataFrame],
        bm_df: pl.DataFrame,
        sector_map: dict[str, str],
        target_date_str: str,
    ) -> list[dict[str, Any]]:
        """Eğitilmiş model ile hedef tarih için hisse bazlı aşırı getiri skorlarını tahmin eder.

        Vektörize toplu tahmin (batch inference) kullanarak tüm hisseleri tek matris işlemiyle skorlar.

        Args:
            market_data: Hisse verileri.
            bm_df: Benchmark endeks verisi.
            sector_map: Sektör eşleme haritası.
            target_date_str: Tahmin yapılacak hedef tarih (YYYY-MM-DD).

        Returns:
            list[dict[str, Any]]: Azalan skor sırasına göre sıralanmış hisse tahmin listesi.

        Raises:
            ValueError: Model eğitilmemişse veya benchmark verisi yetersizse.
        """
        if not self.model:
            raise ValueError("Model henüz eğitilmemiş veya yüklenememiş.")

        target_date = datetime.datetime.strptime(target_date_str, "%Y-%m-%d")
        start_date_dt = target_date - datetime.timedelta(days=400)

        snap_md: dict[str, pl.DataFrame] = {}
        for t, df in market_data.items():
            if "Date" in df.columns:
                sub_df = df.filter((pl.col("Date") >= start_date_dt) & (pl.col("Date") <= target_date))
                if len(sub_df) >= DEFAULT_MIN_HISTORY_BARS:
                    snap_md[t] = sub_df

        if "Date" in bm_df.columns:
            snap_bm = bm_df.filter((pl.col("Date") >= start_date_dt) & (pl.col("Date") <= target_date))
        else:
            snap_bm = bm_df
        if len(snap_bm) < DEFAULT_MIN_HISTORY_BARS:
            raise ValueError(f"Yetersiz benchmark verisi (en az {DEFAULT_MIN_HISTORY_BARS} bar gereklidir).")

        features = compute_universe_features(snap_md, snap_bm, sector_map)

        if self.exclude_features:
            for ticker, feats in features.items():
                for exf in self.exclude_features:
                    feats.pop(exf, None)

        valid_tickers: list[str] = []
        feature_rows: list[list[float]] = []
        raw_feature_dicts: list[dict[str, float]] = []

        for ticker, feats in features.items():
            if not feats:
                continue
            row = [float(feats.get(k, 0.0) or 0.0) for k in self.features]
            valid_tickers.append(ticker)
            feature_rows.append(row)
            raw_feature_dicts.append(feats)

        if not valid_tickers:
            return []

        # Vektörize Toplu Tahmin (Batch Inference)
        X_matrix = np.array(feature_rows, dtype=np.float64)
        X_matrix = np.nan_to_num(X_matrix, nan=0.0, posinf=0.0, neginf=0.0)
        raw_scores = self.model.predict(X_matrix)

        predictions: list[dict[str, Any]] = []
        for ticker, score, feats in zip(valid_tickers, raw_scores, raw_feature_dicts, strict=False):
            predictions.append({
                "ticker": ticker,
                "score": float(score),
                "features": feats,
            })

        predictions.sort(key=lambda x: x["score"], reverse=True)
        return predictions

    def _save_model(self, path: str = DEFAULT_MODEL_PATH) -> None:
        """Eğitilmiş modeli ve öznitelik üst verilerini güvenli pickle ile diske kaydeder.

        Args:
            path: Model dosyasının yazılacağı hedef dizin ve dosya adı.
        """
        if self.model is None:
            return
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "model": self.model,
                "features": self.features,
                "params": self.params,
                "exclude_features": self.exclude_features,
                "trained_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "feature_hash": hashlib.sha256("|".join(sorted(self.features)).encode()).hexdigest()[:16],
            }
            safe_pickle_dump(payload, path)
            logger.info("alpha_engine_modeli_kaydedildi", yol=path, ozellik_sayisi=len(self.features))
        except Exception as e:
            logger.warning("alpha_engine_model_kayit_hatasi", hata=str(e))

    def _load_model(self, path: str = DEFAULT_MODEL_PATH, max_age_hours: int = 24) -> bool:
        """Model dosyasını doğrular ve geçerli ise belleğe yükler.

        Args:
            path: Yüklenecek model dosya yolu.
            max_age_hours: Modelin kabul edilebilir maksimum yaşı (saat).

        Returns:
            bool: Yükleme başarılı ve model geçerli ise True, aksi halde False.
        """
        if not Path(path).exists():
            return False
        try:
            payload = safe_pickle_load(path)
            trained_at = datetime.datetime.fromisoformat(payload["trained_at"])
            if trained_at.tzinfo is None:
                trained_at = trained_at.replace(tzinfo=datetime.UTC)
            age_hours = (datetime.datetime.now(datetime.UTC) - trained_at).total_seconds() / 3600
            if age_hours > max_age_hours:
                return False
            current_hash = hashlib.sha256("|".join(sorted(payload["features"])).encode()).hexdigest()[:16]
            if current_hash != payload.get("feature_hash"):
                logger.warning("alpha_engine_ozellik_hash_uyusmazligi")
                return False
            self.model = payload["model"]
            self.features = payload["features"]
            self.params = payload["params"]
            self.exclude_features = payload.get("exclude_features", self.exclude_features)
            logger.info("alpha_engine_model_yuklendi", yol=path, ozellik_sayisi=len(self.features))
            return True
        except Exception as e:
            logger.warning("alpha_engine_model_yukleme_hatasi", hata=str(e))
            return False

    @otel_trace("alpha_engine.run_daily_pipeline")
    def run_daily_pipeline(self, date: str) -> list[dict[str, Any]] | None:
        """Günlük alfa boru hattını (veri çekme -> gerekirse eğitim -> tahmin) çalıştırır.

        Args:
            date: Hedef işlem günü tarihi (YYYY-MM-DD).

        Returns:
            list[dict[str, Any]] | None: Tahmin sonuç listesi veya başarısızlık durumunda None.
        """
        end_date_dt = datetime.datetime.strptime(date, "%Y-%m-%d")
        start_date_dt = end_date_dt - datetime.timedelta(days=400)

        # 1. Model diskten yüklenebiliyorsa doğrudan veri çekip tahmin yap
        if self._load_model():
            logger.info("alpha_engine_onbellek_modeli_kullaniliyor")
            market_data, bm_df, sector_map = self.fetch_data(
                start_date_dt.strftime("%Y-%m-%d"), end_date_dt.strftime("%Y-%m-%d")
            )
            return self.predict(market_data, bm_df, sector_map, date)

        # 2. Model yoksa veya eskidiyse veriyi tek sefer çek, modeli eğit ve tahmin üret (çift indirme önlendi)
        market_data, bm_df, sector_map = self.fetch_data(
            start_date_dt.strftime("%Y-%m-%d"), end_date_dt.strftime("%Y-%m-%d")
        )
        success = self.train(market_data, bm_df, sector_map, start_date_dt.strftime("%Y-%m-%d"), date)
        if not success:
            return None

        return self.predict(market_data, bm_df, sector_map, date)


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_EXCLUDE_FEATURES",
    "DEFAULT_FORWARD_DAYS",
    "DEFAULT_MIN_HISTORY_BARS",
    "DEFAULT_MODEL_PATH",
    "DEFAULT_PARAMS",
    "AlphaEngine",
]

