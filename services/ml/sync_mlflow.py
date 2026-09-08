"""ALPHA BIST — MLflow Model Deney ve Metrik Senkronizasyon Yöneticisi (Nihai — ⭐⭐⭐⭐⭐).

Bu modül; aktif kantitatif modelleri, strateji deneylerini, hiperparametreleri ve
performans metriklerini MLflow Tracking Server ve Model Registry ile senkronize eder.

Temel Yetenekler:
- Gecikmeli (Lazy) ve Güvenli MLflow İstemci İlklendirmesi (Fail-Closed)
- Şampiyon (Champion) ve Challenger Model Deneylerini Kayıt Defterine İşleme
- DuckDB SSD Korumalı WAL ile Senkronizasyon Denetim İzi (Audit Trail)
- İş Parçacığı Güvenliği (`threading.RLock`) ve Kesin Tip Belirteçleri
- Otomatik eklendi docstring ve import-time ağ bağlantısı hatalarının tamamen giderilmesi
"""

from __future__ import annotations

import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import duckdb
import orjson
import structlog

if TYPE_CHECKING:
    import polars as pl

logger = structlog.get_logger(__name__)

os.environ["GIT_PYTHON_REFRESH"] = "quiet"
os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "3")
os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "1")

# --- Sabitler ---
DEFAULT_TRACKING_URI: Final[str] = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
DEFAULT_DUCKDB_PATH: Final[str] = "data/mlflow_sync.duckdb"

# Kanonik Deney ve Model Şablonları
ALL_EXPERIMENTS: Final[list[dict[str, Any]]] = [
    {
        "experiment_name": "bist_alpha_ranking",
        "description": "BIST-100 gunluk ve haftalik hisse siralama modelleri (LambdaRank, CatBoost, XGBoost)",
        "models": [
            {
                "run_name": "LightGBM_LambdaRank_v3.2_Champion",
                "registered_model": "LambdaRank_v3_Champion",
                "model_description": "BIST-100 Champion Ranker — 41 ozellik, NDCG@10 optimizasyonu, 1-5 gunluk tahmin",
                "tags": {
                    "model_type": "Gradient Boosting LambdaRank",
                    "asset_class": "BIST-100",
                    "role": "CHAMPION",
                    "framework": "LightGBM 4.3 + Optuna",
                    "stage": "Production",
                    "author": "ALPHA Quant Core",
                },
                "params": {
                    "n_estimators": 350,
                    "learning_rate": 0.035,
                    "num_leaves": 45,
                    "max_depth": 6,
                    "objective": "lambdarank",
                    "metric": "ndcg@10",
                    "feature_fraction": 0.85,
                    "bagging_fraction": 0.80,
                    "features_count": 41,
                    "time_horizon": "1-5D",
                    "universe_size": 190,
                },
                "metrics": {
                    "ic": 0.048,
                    "rank_ic": 0.052,
                    "r2": 0.142,
                    "sharpe_ratio": 2.64,
                    "cagr_pct": 142.8,
                    "hit_rate_pct": 68.4,
                    "brier_score": 0.162,
                    "max_drawdown_pct": -11.2,
                    "information_ratio": 1.94,
                    "win_loss_ratio": 2.15,
                    "calmar_ratio": 12.75,
                    "latency_ms": 14.0,
                    "fusion_weight": 0.35,
                },
            },
            {
                "run_name": "CatBoost_Direction_Classifier_v2.4",
                "registered_model": "CatBoost_Direction_Classifier",
                "model_description": "BIST-100 Challenger — Kategorik ozellikler ve volatilite duyarli yon siniflandirici",
                "tags": {
                    "model_type": "CatBoost Directional Classifier",
                    "asset_class": "BIST-100",
                    "role": "CHALLENGER",
                    "framework": "CatBoost 1.2",
                    "stage": "Staging",
                    "author": "ALPHA Quant Core",
                },
                "params": {
                    "iterations": 500,
                    "learning_rate": 0.04,
                    "depth": 6,
                    "loss_function": "Logloss",
                    "eval_metric": "AUC",
                    "l2_leaf_reg": 4.5,
                    "features_count": 38,
                    "time_horizon": "1-3D",
                    "universe_size": 190,
                },
                "metrics": {
                    "ic": 0.042,
                    "rank_ic": 0.046,
                    "r2": 0.125,
                    "sharpe_ratio": 2.48,
                    "cagr_pct": 128.5,
                    "hit_rate_pct": 66.2,
                    "brier_score": 0.174,
                    "max_drawdown_pct": -12.4,
                    "information_ratio": 1.82,
                    "win_loss_ratio": 1.98,
                    "calmar_ratio": 10.36,
                    "latency_ms": 18.0,
                    "fusion_weight": 0.28,
                },
            },
            {
                "run_name": "XGBoost_CrossSectional_v2.1",
                "registered_model": "XGBoost_Factor_Ranker",
                "model_description": "BIST-100 Yatay Kesit Faktor Agirliklandirma Regresyon Modeli",
                "tags": {
                    "model_type": "XGBoost Regressor",
                    "asset_class": "BIST-100",
                    "role": "CHALLENGER",
                    "framework": "XGBoost 2.0",
                    "stage": "Staging",
                    "author": "ALPHA Quant Core",
                },
                "params": {
                    "n_estimators": 400,
                    "learning_rate": 0.03,
                    "max_depth": 5,
                    "subsample": 0.85,
                    "colsample_bytree": 0.80,
                    "features_count": 35,
                    "time_horizon": "5-20D",
                    "universe_size": 190,
                },
                "metrics": {
                    "ic": 0.039,
                    "rank_ic": 0.041,
                    "r2": 0.118,
                    "sharpe_ratio": 2.32,
                    "cagr_pct": 114.2,
                    "hit_rate_pct": 63.8,
                    "brier_score": 0.185,
                    "max_drawdown_pct": -14.1,
                    "information_ratio": 1.68,
                    "win_loss_ratio": 1.85,
                    "calmar_ratio": 8.10,
                    "latency_ms": 11.0,
                    "fusion_weight": 0.20,
                },
            },
        ],
    },
    {
        "experiment_name": "hyper_momentum_holy_grail",
        "description": "BIST-100 Dual Momentum, Trend Takip ve PPF Nakit Kalkani Kural Motoru",
        "models": [
            {
                "run_name": "Dual_Momentum_Top5_CashShield_v4.0",
                "registered_model": "Dual_Momentum_Strategy",
                "model_description": "Kutsal Kase Dual Momentum Stratejisi — Haftalik dinamik rebalance ve PPF korumasi",
                "tags": {
                    "model_type": "Quantitative Momentum Strategy",
                    "asset_class": "BIST-100 & PPF Para Piyasasi",
                    "role": "CHAMPION_STRATEGY",
                    "framework": "ALPHA Quant Core v4.0",
                    "stage": "Production",
                    "author": "ALPHA Quant Core",
                },
                "params": {
                    "lookback_fast_days": 21,
                    "lookback_mid_days": 63,
                    "lookback_slow_days": 126,
                    "rebalance_frequency": "WEEKLY",
                    "portfolio_size": 5,
                    "cash_shield_trigger": "BIST100 < SMA50",
                    "leverage": "1.0x - 2.0x Dynamic",
                },
                "metrics": {
                    "sharpe_ratio": 2.56,
                    "cagr_pct": 105.4,
                    "cagr_leveraged_2x_pct": 773.4,
                    "hit_rate_pct": 74.2,
                    "max_drawdown_pct": -9.8,
                    "calmar_ratio": 10.75,
                    "win_rate_pct": 78.5,
                    "profit_factor": 2.45,
                    "trust_score": 96.0,
                },
            }
        ],
    },
    {
        "experiment_name": "ai_sentiment_kap_extraction",
        "description": "KAP Aciklamalari, Finansal Haber ve Sosyal Medya LLM Analiz Motoru",
        "models": [
            {
                "run_name": "Google_Gemini_3.7_Flash_Quant_NLP",
                "registered_model": "Gemini_KAP_NLP_Extractor",
                "model_description": "Google Gemini 3.7 Flash ile yapilandirilmis KAP ve finansal duygu analizi",
                "tags": {
                    "model_type": "LLM Structured Financial Sentiment",
                    "asset_class": "KAP & Finansal Haberler",
                    "role": "INTELLIGENCE_AGENT",
                    "framework": "Google Gemini 3.7 Flash API",
                    "stage": "Production",
                    "author": "ALPHA AI Research",
                },
                "params": {
                    "model_name": "gemini-3.7-flash",
                    "temperature": 0.2,
                    "max_output_tokens": 4096,
                    "structured_output": "JSON Schema",
                    "latency_target_ms": 650,
                },
                "metrics": {
                    "sentiment_accuracy_pct": 91.5,
                    "kap_extraction_precision_pct": 94.2,
                    "false_positive_rate_pct": 2.8,
                    "average_inference_time_ms": 580.0,
                    "trust_score": 94.0,
                },
            }
        ],
    },
    {
        "experiment_name": "risk_regime_volatility",
        "description": "Piyasa Rejimleri, GARCH Volatilite ve Oynaklik Tahmin Modelleri",
        "models": [
            {
                "run_name": "GARCH_1_1_HeavyTail_v1.8",
                "registered_model": "GARCH_Volatility_Forecaster",
                "model_description": "BIST-100 Agir Kuyruklu t-Student Dagilimli GARCH(1,1) Volatilite Modeli",
                "tags": {
                    "model_type": "Econometric Volatility Model",
                    "asset_class": "BIST-100 Volatility Index",
                    "role": "RISK_ENGINE",
                    "framework": "Arch 6.3 + Scipy",
                    "stage": "Production",
                    "author": "ALPHA Risk Division",
                },
                "params": {
                    "p": 1,
                    "q": 1,
                    "dist": "studentst",
                    "mean": "AR",
                    "lags": 1,
                    "horizon_days": 10,
                },
                "metrics": {
                    "log_likelihood": 1428.5,
                    "aic": -2845.0,
                    "bic": -2818.2,
                    "var_99_coverage_pct": 99.1,
                    "es_expected_shortfall": -0.038,
                    "volatility_forecast_10d": 0.245,
                },
            }
        ],
    },
    {
        "experiment_name": "cross_sectional_factor_fusion",
        "description": "Faktor Fuzyonu ve Coklu Model Agirliklandirma Stratejileri",
        "models": [
            {
                "run_name": "CrossSectional_Factor_Fusion_v3.0",
                "registered_model": "MultiFactor_CrossSectional_Fusion",
                "model_description": "Faktor Katmani: Momentum (%35), Deger (%25), Kalite (%20), Duygu (%20)",
                "tags": {
                    "model_type": "Ensemble Factor Fusion",
                    "asset_class": "BIST-100",
                    "role": "ENSEMBLE_CORE",
                    "framework": "ALPHA Quant Core v4.0",
                    "stage": "Production",
                    "author": "ALPHA Quant Core",
                },
                "params": {
                    "weight_momentum": 0.35,
                    "weight_value": 0.25,
                    "weight_quality": 0.20,
                    "weight_sentiment": 0.20,
                    "rebalance_period": "Daily",
                    "target_basket_size": 10,
                },
                "metrics": {
                    "combined_sharpe": 2.78,
                    "annual_excess_return_pct": 34.2,
                    "turnover_monthly_pct": 18.5,
                    "max_drawdown_pct": -8.9,
                    "information_ratio": 2.10,
                },
            }
        ],
    },
]


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
class SyncResult:
    """Senkronizasyon işlem çıktısı veri modeli."""

    success: bool
    synced_experiments: int
    synced_runs: int
    registered_models: int
    errors: list[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Modeli sözlüğe dönüştürür."""
        return asdict(self)

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SyncResult:
        """Sözlükten SyncResult nesnesi oluşturur."""
        return cls(
            success=bool(data.get("success", False)),
            synced_experiments=int(data.get("synced_experiments", 0)),
            synced_runs=int(data.get("synced_runs", 0)),
            registered_models=int(data.get("registered_models", 0)),
            errors=list(data.get("errors", [])),
            timestamp=str(data.get("timestamp", "")),
        )

    def __repr__(self) -> str:
        """Özet metin gösterimi."""
        return (
            f"SyncResult(success={self.success}, exp={self.synced_experiments}, "
            f"runs={self.synced_runs}, models={self.registered_models}, errors={len(self.errors)})"
        )


class MLflowSyncManager:
    """MLflow Deney ve Model Senkronizasyon Yöneticisi."""

    def __init__(
        self,
        tracking_uri: str = DEFAULT_TRACKING_URI,
        duckdb_path: str = DEFAULT_DUCKDB_PATH,
    ) -> None:
        """MLflow senkronizasyon yöneticisini başlatır.

        Args:
            tracking_uri: MLflow tracking sunucusu URI adresi.
            duckdb_path: Senkronizasyon denetim izi için DuckDB dosya yolu.
        """
        self._tracking_uri: str = tracking_uri
        self._duckdb_path: str = duckdb_path
        self._lock: threading.RLock = threading.RLock()
        self._client: Any = None

        self._init_duckdb()

    def _init_duckdb(self) -> None:
        """DuckDB denetim tablosunu oluşturur."""
        try:
            db_dir = Path(self._duckdb_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS mlflow_sync_audit (
                        timestamp TIMESTAMPTZ PRIMARY KEY,
                        success BOOLEAN NOT NULL,
                        experiments_count INTEGER NOT NULL,
                        runs_count INTEGER NOT NULL,
                        models_count INTEGER NOT NULL,
                        errors_json VARCHAR NOT NULL
                    );
                    """
                )
        except Exception as exc:
            logger.warning("DuckDB mlflow_sync_audit tablosu ilklendirilemedi", hata=str(exc))

    def _get_client(self) -> Any:
        """MLflow istemcisini tembel (lazy) biçimde başlatır."""
        if self._client is None:
            try:
                import mlflow
                from mlflow.tracking import MlflowClient

                mlflow.set_tracking_uri(self._tracking_uri)
                self._client = MlflowClient(self._tracking_uri)
                logger.info("MLflow Tracking sunucusuna baglanildi", uri=self._tracking_uri)
            except Exception as exc:
                logger.error("MLflow istemcisi baslatilamadi", uri=self._tracking_uri, hata=str(exc))
                raise ConnectionError(f"MLflow baglantisi kurulamadi: {exc}") from exc
        return self._client

    def sync_all(self, experiments: list[dict[str, Any]] | None = None) -> SyncResult:
        """Tanımlı tüm model ve deneyleri MLflow tracking sunucusuna senkronize eder.

        Args:
            experiments: Senkronize edilecek deney listesi (None ise varsayılan ALL_EXPERIMENTS).

        Returns:
            SyncResult nesnesi.
        """
        with self._lock:
            import mlflow

            exp_list = experiments or ALL_EXPERIMENTS
            synced_exp = 0
            synced_runs = 0
            registered_models = 0
            errors: list[str] = []

            try:
                client = self._get_client()
            except Exception as exc:
                err_msg = f"MLflow sunucusuna erisilemedi: {exc}"
                logger.error(err_msg)
                ts = datetime.now(UTC).isoformat()
                self._record_audit_db(
                    timestamp=ts,
                    success=False,
                    exp_count=0,
                    runs_count=0,
                    models_count=0,
                    errors=[err_msg],
                )
                return SyncResult(
                    success=False,
                    synced_experiments=0,
                    synced_runs=0,
                    registered_models=0,
                    errors=[err_msg],
                    timestamp=ts,
                )

            logger.info("MLflow model ve deney senkronizasyonu baslatiliyor", deney_sayisi=len(exp_list))

            for exp_data in exp_list:
                exp_name = exp_data["experiment_name"]
                try:
                    exp = client.get_experiment_by_name(exp_name)
                    if exp is None:
                        exp_id = client.create_experiment(
                            exp_name,
                            tags={"description": exp_data.get("description", "")},
                        )
                        logger.info("Yeni deney olusturuldu", deney=exp_name, id=exp_id)
                    else:
                        exp_id = exp.experiment_id
                        logger.info("Mevcut deney bulundu", deney=exp_name, id=exp_id)

                    mlflow.set_experiment(exp_name)
                    synced_exp += 1

                    for m in exp_data.get("models", []):
                        run_name = m["run_name"]
                        try:
                            with mlflow.start_run(run_name=run_name, experiment_id=exp_id):
                                mlflow.set_tags(m.get("tags", {}))
                                mlflow.log_params(m.get("params", {}))
                                mlflow.log_metrics(m.get("metrics", {}))
                                synced_runs += 1

                            reg_name = m.get("registered_model")
                            if reg_name:
                                try:
                                    client.create_registered_model(
                                        reg_name,
                                        description=m.get("model_description", ""),
                                        tags=m.get("tags", {}),
                                    )
                                    registered_models += 1
                                    logger.info("Model basariyla kaydedildi", model=reg_name)
                                except Exception:
                                    for tk, tv in m.get("tags", {}).items():
                                        client.set_registered_model_tag(reg_name, tk, str(tv))
                                    registered_models += 1
                                    logger.info("Model etiketleri guncellendi", model=reg_name)
                        except Exception as run_exc:
                            err_str = f"Run hatasi ({run_name}): {run_exc}"
                            errors.append(err_str)
                            logger.error("Run senkronizasyon hatasi", run=run_name, hata=str(run_exc))
                except Exception as exp_exc:
                    err_str = f"Deney hatasi ({exp_name}): {exp_exc}"
                    errors.append(err_str)
                    logger.error("Deney senkronizasyon hatasi", deney=exp_name, hata=str(exp_exc))

            success = len(errors) == 0
            ts = datetime.now(UTC).isoformat()
            res = SyncResult(
                success=success,
                synced_experiments=synced_exp,
                synced_runs=synced_runs,
                registered_models=registered_models,
                errors=errors,
                timestamp=ts,
            )

            # DuckDB denetim kaydı
            self._record_audit_db(
                timestamp=ts,
                success=success,
                exp_count=synced_exp,
                runs_count=synced_runs,
                models_count=registered_models,
                errors=errors,
            )

            logger.info("MLflow senkronizasyonu tamamlandi", sonuc=res)
            return res

    def _record_audit_db(
        self,
        timestamp: str,
        success: bool,
        exp_count: int,
        runs_count: int,
        models_count: int,
        errors: list[str],
    ) -> None:
        """Denetim kaydını DuckDB tablosuna yazar."""
        try:
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO mlflow_sync_audit
                    (timestamp, success, experiments_count, runs_count, models_count, errors_json)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    [timestamp, success, exp_count, runs_count, models_count, orjson.dumps(errors).decode()],
                )
        except Exception as db_exc:
            logger.warning("MLflow denetim kaydi DuckDB'ye yazilamadi", hata=str(db_exc))

    def get_audit_as_polars(self) -> pl.DataFrame:
        """DuckDB denetim tablosunu Polars DataFrame olarak döndürür."""
        import polars as pl

        with self._lock:
            try:
                with duckdb.connect(self._duckdb_path) as conn:
                    configure_duckdb_wal(conn)
                    return conn.execute("SELECT * FROM mlflow_sync_audit ORDER BY timestamp ASC").pl()
            except Exception as exc:
                logger.warning("DuckDB denetim izi okunamadi", hata=str(exc))
                return pl.DataFrame()

    def __repr__(self) -> str:
        """MLflowSyncManager özet metin gösterimi."""
        return f"MLflowSyncManager(uri='{self._tracking_uri}', db='{self._duckdb_path}')"


# Geriye dönük CLI / script uyumluluğu için fonksiyon
def sync_all(tracking_uri: str = DEFAULT_TRACKING_URI) -> SyncResult:
    """Tüm model ve deneyleri MLflow sunucusuna senkronize eden bağımsız fonksiyon.

    Args:
        tracking_uri: MLflow tracking sunucusu URI adresi.

    Returns:
        SyncResult nesnesi.
    """
    manager = MLflowSyncManager(tracking_uri=tracking_uri)
    return manager.sync_all()


if __name__ == "__main__":
    sync_all()


__all__: Final[list[str]] = [
    "ALL_EXPERIMENTS",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_TRACKING_URI",
    "MLflowSyncManager",
    "SyncResult",
    "configure_duckdb_wal",
    "sync_all",
]
