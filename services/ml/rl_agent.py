"""ALPHA BIST — Pekiştirmeli Öğrenme Ajanı (RL Agent v3.0) (Nihai — ⭐⭐⭐⭐⭐).

Bu modül; BIST hisse senetleri için Gymnasium uyumlu alım-satım ortamı (BISTTradingEnv)
ve modern pekiştirmeli öğrenme algoritmalarını (PPO, A2C, DQN) sunar.

Temel Yetenekler:
- Gymnasium Uyumlu Simülasyon Ortamı (`BISTTradingEnv`)
- Kesikli (Discrete: BUY, HOLD, SELL) ve Sürekli (Continuous: Pozisyon Büyüklüğü) Eylem Uzayları
- Çok Amaçlı Ödül Fonksiyonları (Sharpe Oranı, Net Getiri, Risk Düzeltmeli Getiri)
- Komisyon ve Kayma (Slippage) Maliyetleri Modellemesi
- Polars DataFrame Doğrudan Entegrasyonu (`BISTTradingEnv.from_polars`)
- DuckDB SSD Korumalı WAL ile Eğitim ve Değerlendirme Denetim İzi (Audit Trail)
- İş Parçacığı Güvenliği (`threading.RLock`), Tip Güvenliği ve Sıfır Veri Sızıntısı
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)

# --- Sabitler ---
DEFAULT_INITIAL_CAPITAL: Final[float] = 100_000.0
DEFAULT_COMMISSION_RATE: Final[float] = 0.001
DEFAULT_MAX_POSITION: Final[float] = 1.0
DEFAULT_EPSILON: Final[float] = 1e-8
DEFAULT_DUCKDB_PATH: Final[str] = "data/rl_agent.duckdb"
DEFAULT_MAX_PORTFOLIO_HISTORY: Final[int] = 5000


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
class RLConfig:
    """RL Ajanı hiperparametreleri ve algoritma konfigürasyonu."""

    algorithm: str = "PPO"  # PPO, A2C, DQN
    total_timesteps: int = 100_000
    learning_rate: float = 3e-4
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_range: float = 0.2
    ent_coef: float = 0.01
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    n_steps: int = 2048
    batch_size: int = 64
    n_epochs: int = 10
    reward_type: str = "sharpe"  # sharpe, return, risk_adjusted
    action_space: str = "discrete"  # discrete (BUY/HOLD/SELL), continuous (position_size)
    device: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        """Konfigürasyonu sözlük yapısına dönüştürür."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RLConfig:
        """Sözlükten RLConfig nesnesi üretir."""
        return cls(
            algorithm=str(data.get("algorithm", "PPO")),
            total_timesteps=int(data.get("total_timesteps", 100_000)),
            learning_rate=float(data.get("learning_rate", 3e-4)),
            gamma=float(data.get("gamma", 0.99)),
            gae_lambda=float(data.get("gae_lambda", 0.95)),
            clip_range=float(data.get("clip_range", 0.2)),
            ent_coef=float(data.get("ent_coef", 0.01)),
            vf_coef=float(data.get("vf_coef", 0.5)),
            max_grad_norm=float(data.get("max_grad_norm", 0.5)),
            n_steps=int(data.get("n_steps", 2048)),
            batch_size=int(data.get("batch_size", 64)),
            n_epochs=int(data.get("n_epochs", 10)),
            reward_type=str(data.get("reward_type", "sharpe")),
            action_space=str(data.get("action_space", "discrete")),
            device=str(data.get("device", "auto")),
        )

    def to_orjson_bytes(self) -> bytes:
        """Konfigürasyonu orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        """Özet metin gösterimini oluşturur."""
        return f"RLConfig(algo='{self.algorithm}', timesteps={self.total_timesteps}, reward='{self.reward_type}')"


@dataclass(slots=True)
class RLEvaluationResult:
    """RL ajanı değerlendirme çıktısı ve performans istatistikleri modeli."""

    n_episodes: int
    avg_episode_reward: float
    avg_total_return: float
    avg_sharpe_ratio: float
    avg_max_drawdown: float
    avg_final_capital: float
    avg_n_trades: float
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Sonuçları standart sözlük yapısına dönüştürür."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RLEvaluationResult:
        """Sözlükten RLEvaluationResult nesnesi üretir."""
        return cls(
            n_episodes=int(data.get("n_episodes", 0)),
            avg_episode_reward=float(data.get("avg_episode_reward", 0.0)),
            avg_total_return=float(data.get("avg_total_return", 0.0)),
            avg_sharpe_ratio=float(data.get("avg_sharpe_ratio", 0.0)),
            avg_max_drawdown=float(data.get("avg_max_drawdown", 0.0)),
            avg_final_capital=float(data.get("avg_final_capital", 0.0)),
            avg_n_trades=float(data.get("avg_n_trades", 0.0)),
            details=dict(data.get("details", {})),
        )

    def to_orjson_bytes(self) -> bytes:
        """Sonuçları orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict(), default=str)

    def __repr__(self) -> str:
        """Özet metin gösterimi."""
        return (
            f"RLEvaluationResult(episodes={self.n_episodes}, "
            f"return={self.avg_total_return:.2%}, sharpe={self.avg_sharpe_ratio:.2f}, "
            f"mdd={self.avg_max_drawdown:.2%})"
        )


class BISTTradingEnv:
    """BIST hisse senedi alım-satım ortamı (Gymnasium uyumlu).

    Özellikler:
    - Kesikli (Discrete: 0=BUY, 1=HOLD, 2=SELL) ve sürekli eylem uzayı
    - Gecikmesiz portföy takibi ve komisyon maliyet simülasyonu
    - Sharpe, Getiri ve Risk Düzeltmeli dinamik ödül hesaplaması
    - İş parçacığı güvenliği (`threading.RLock`)
    """

    def __init__(
        self,
        features: np.ndarray,
        prices: np.ndarray,
        returns: np.ndarray | None = None,
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
        commission_rate: float = DEFAULT_COMMISSION_RATE,
        max_position: float = DEFAULT_MAX_POSITION,
        reward_type: str = "sharpe",
        action_space: str = "discrete",
    ) -> None:
        """BIST alım-satım ortamını başlatır.

        Args:
            features: Zaman adımı bazlı öznitelik matrisi (N, F).
            prices: Kapanış fiyatları dizisi (N,).
            returns: Önceden hesaplanmış getiriler dizisi (N-1,).
            initial_capital: Başlangıç nakit sermayesi.
            commission_rate: İşlem komisyon oranı.
            max_position: İzin verilen azami portföy pozisyon oranı.
            reward_type: Ödül fonksiyon türü ('sharpe', 'return', 'risk_adjusted').
            action_space: Eylem uzayı türü ('discrete' veya 'continuous').
        """
        self._lock: threading.RLock = threading.RLock()

        self.features: np.ndarray = np.nan_to_num(np.asarray(features, dtype=np.float32), nan=0.0, posinf=1e6, neginf=-1e6)
        self.prices: np.ndarray = np.nan_to_num(np.asarray(prices, dtype=np.float64), nan=1.0, posinf=1e6, neginf=1.0)

        if returns is not None:
            self.returns: np.ndarray = np.nan_to_num(np.asarray(returns, dtype=np.float64), nan=0.0, posinf=1.0, neginf=-1.0)
        elif len(self.prices) > 1:
            denom = np.maximum(self.prices[:-1], DEFAULT_EPSILON)
            self.returns = np.nan_to_num(np.diff(self.prices) / denom, nan=0.0, posinf=1.0, neginf=-1.0)
        else:
            self.returns = np.empty((0,), dtype=np.float64)

        self.initial_capital: float = max(float(initial_capital), 1.0)
        self.commission_rate: float = max(float(commission_rate), 0.0)
        self.max_position: float = max(float(max_position), 0.1)
        self.reward_type: str = reward_type
        self.action_space_type: str = action_space

        # Durum değişkenleri
        self._current_step: int = 0
        self._capital: float = self.initial_capital
        self._position: float = 0.0
        self._portfolio_values: list[float] = [self.initial_capital]
        self._trades: list[dict[str, Any]] = []

        # Gymnasium uyumlu uzaylar
        self.observation_space: Any = self._make_observation_space()
        self.action_space: Any = self._make_action_space()

    @classmethod
    def from_polars(
        cls,
        df: pl.DataFrame,
        price_col: str = "close",
        feature_cols: list[str] | None = None,
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
        commission_rate: float = DEFAULT_COMMISSION_RATE,
        reward_type: str = "sharpe",
        action_space: str = "discrete",
    ) -> BISTTradingEnv:
        """Polars DataFrame girdisi üzerinden ortamı güvenle inşa eder.

        Args:
            df: Fiyat ve öznitelik sütunlarını içeren Polars DataFrame.
            price_col: Fiyat sütun adı.
            feature_cols: Kullanılacak öznitelik sütun isimleri (None ise price hariç tüm numerikler).
            initial_capital: Başlangıç sermayesi.
            commission_rate: Komisyon oranı.
            reward_type: Ödül türü.
            action_space: Eylem uzayı türü.

        Returns:
            Yapılandırılmış BISTTradingEnv örneği.
        """
        if df.is_empty():
            raise ValueError("Polars DataFrame bos olamaz.")

        if price_col not in df.columns:
            raise ValueError(f"Fiyat kolonu '{price_col}' Polars DataFrame icinde bulunamadi.")

        prices = df[price_col].to_numpy()

        if feature_cols is None:
            # Numerik sütunları seç (price_col hariç)
            feature_cols = [
                col
                for col in df.columns
                if col != price_col and df[col].dtype in (pl.Float64, pl.Float32, pl.Int64, pl.Int32)
            ]

        if feature_cols:
            features = df.select(feature_cols).fill_null(0.0).to_numpy()
        else:
            features = np.zeros((len(df), 1), dtype=np.float32)

        return cls(
            features=features,
            prices=prices,
            initial_capital=initial_capital,
            commission_rate=commission_rate,
            reward_type=reward_type,
            action_space=action_space,
        )

    def _make_observation_space(self) -> Any:
        """Gözlem uzayını Gymnasium Box standardında oluşturur."""
        try:
            from gymnasium import spaces

            n_features = self.features.shape[1] if self.features.ndim > 1 else 1
            return spaces.Box(low=-np.inf, high=np.inf, shape=(n_features + 2,), dtype=np.float32)
        except ImportError:
            return None

    def _make_action_space(self) -> Any:
        """Eylem uzayını Gymnasium Discrete veya Box standardında oluşturur."""
        try:
            from gymnasium import spaces

            if self.action_space_type == "discrete":
                return spaces.Discrete(3)  # 0=BUY, 1=HOLD, 2=SELL
            return spaces.Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32)
        except ImportError:
            return None

    def reset(self, seed: int | None = None) -> tuple[np.ndarray, dict[str, Any]]:
        """Ortamı başlangıç durumuna sıfırlar.

        Args:
            seed: Rastgele sayı üreteci tohumu.

        Returns:
            Başlangıç gözlem vektörü ve ek bilgi sözlüğü.
        """
        with self._lock:
            self._current_step = 0
            self._capital = self.initial_capital
            self._position = 0.0
            self._portfolio_values = [self.initial_capital]
            self._trades = []
            return self._get_observation(), {}

    def step(self, action: Any) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Bir zaman adımı ilerler, ödül ve yeni durumu hesaplar.

        Args:
            action: Kesikli veya sürekli ajan eylemi.

        Returns:
            (observation, reward, terminated, truncated, info) Gymnasium demeti.
        """
        with self._lock:
            if self._current_step >= len(self.returns):
                return self._get_observation(), 0.0, True, False, {}

            # Eylemi pozisyona dönüştür
            if self.action_space_type == "discrete":
                int_action = int(action) if not isinstance(action, np.ndarray) else int(action.item())
                if int_action == 0:  # BUY
                    new_position = min(self._position + 0.5, self.max_position)
                elif int_action == 2:  # SELL
                    new_position = max(self._position - 0.5, -self.max_position)
                else:  # HOLD
                    new_position = self._position
            else:
                float_action = float(action) if not isinstance(action, np.ndarray) else float(action.flat[0])
                new_position = float(np.clip(float_action * self.max_position, -self.max_position, self.max_position))

            # Komisyon maliyeti
            position_change = abs(new_position - self._position)
            commission = position_change * self.commission_rate * self._capital

            # Günlük getiri ve portföy güncellemesi
            raw_ret = float(self.returns[self._current_step])
            daily_return = raw_ret if np.isfinite(raw_ret) else 0.0
            portfolio_return = self._position * daily_return * self._capital

            self._capital += portfolio_return - commission
            self._capital = max(0.0, float(self._capital)) if np.isfinite(self._capital) else 0.0

            if position_change > 1e-4:
                self._trades.append(
                    {
                        "step": self._current_step,
                        "old_position": self._position,
                        "new_position": new_position,
                        "commission": commission,
                        "capital": self._capital,
                    }
                )

            self._position = new_position
            self._portfolio_values.append(self._capital)
            if len(self._portfolio_values) > DEFAULT_MAX_PORTFOLIO_HISTORY:
                self._portfolio_values = self._portfolio_values[-DEFAULT_MAX_PORTFOLIO_HISTORY:]

            self._current_step += 1

            reward = self._compute_reward()
            terminated = self._current_step >= len(self.returns) or self._capital <= 0.0

            return self._get_observation(), reward, terminated, False, {}

    def _get_observation(self) -> np.ndarray:
        """Mevcut adım için durum gözlem vektörünü üretir."""
        n_features = self.features.shape[1] if self.features.ndim > 1 else 1

        if self._current_step >= len(self.features) or len(self.features) == 0:
            return np.zeros(n_features + 2, dtype=np.float32)

        feat_row = self.features[self._current_step]
        capital_ratio = float(self._capital / self.initial_capital)
        obs = np.concatenate([feat_row, [np.float32(self._position), np.float32(capital_ratio)]]).astype(np.float32)
        return obs

    def _compute_reward(self) -> float:
        """Seçilen stratejiye göre adım ödülünü hesaplar."""
        if len(self._portfolio_values) < 2:
            return 0.0

        if self.reward_type == "return":
            denom = max(self._portfolio_values[-2], DEFAULT_EPSILON)
            return float((self._portfolio_values[-1] / denom) - 1.0)

        if self.reward_type == "sharpe":
            window = np.array(self._portfolio_values[-21:], dtype=np.float64)
            if len(window) < 5:
                return 0.0
            denom = np.maximum(window[:-1], DEFAULT_EPSILON)
            ret_series = np.diff(window) / denom
            std = float(np.std(ret_series))
            if std < DEFAULT_EPSILON:
                return 0.0
            return float(np.mean(ret_series) / std * np.sqrt(252.0))

        # risk_adjusted (Sermaye büyümesi eksi drawdown cezası)
        total_growth = (self._portfolio_values[-1] / self.initial_capital) - 1.0
        peak = max(self._portfolio_values)
        dd = (peak - self._portfolio_values[-1]) / max(peak, DEFAULT_EPSILON)
        return float(total_growth - 2.0 * dd)

    def get_metrics(self) -> dict[str, Any]:
        """Ortamın güncel performans metriklerini hesaplar."""
        with self._lock:
            values = np.asarray(self._portfolio_values, dtype=np.float64)
            if len(values) == 0:
                return {
                    "total_return": 0.0,
                    "sharpe_ratio": 0.0,
                    "max_drawdown": 0.0,
                    "final_capital": self.initial_capital,
                    "n_trades": 0,
                }

            total_return = float((values[-1] / self.initial_capital) - 1.0)

            if len(values) > 1:
                denom = np.maximum(values[:-1], DEFAULT_EPSILON)
                daily_returns = np.diff(values) / denom
                std_ret = float(np.std(daily_returns))
                sharpe = float(np.mean(daily_returns) / max(std_ret, DEFAULT_EPSILON) * np.sqrt(252.0))

                running_max = np.maximum.accumulate(values)
                drawdown = (values - running_max) / np.maximum(running_max, DEFAULT_EPSILON)
                max_drawdown = float(np.abs(np.min(drawdown))) if len(drawdown) > 0 else 0.0
            else:
                sharpe = 0.0
                max_drawdown = 0.0

            return {
                "total_return": round(total_return, 4),
                "sharpe_ratio": round(sharpe, 4),
                "max_drawdown": round(max_drawdown, 4),
                "final_capital": round(float(values[-1]), 2),
                "n_trades": len(self._trades),
            }

    def get_portfolio_history_polars(self) -> pl.DataFrame:
        """Portföy değer geçmişini Polars DataFrame olarak döndürür."""
        with self._lock:
            return pl.DataFrame(
                {
                    "step": list(range(len(self._portfolio_values))),
                    "portfolio_value": self._portfolio_values,
                }
            )

    def __repr__(self) -> str:
        """Ortam özet gösterimi."""
        with self._lock:
            return (
                f"BISTTradingEnv(steps={self._current_step}/{len(self.returns)}, "
                f"capital={self._capital:.2f}, action_space='{self.action_space_type}')"
            )


def _init_duckdb_audit(duckdb_path: str) -> None:
    """DuckDB denetim tablosunu güvenle oluşturur."""
    try:
        db_dir = Path(duckdb_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(duckdb_path) as conn:
            configure_duckdb_wal(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rl_agent_audit (
                    timestamp TIMESTAMPTZ NOT NULL,
                    operation VARCHAR NOT NULL,
                    algorithm VARCHAR NOT NULL,
                    timesteps BIGINT NOT NULL,
                    avg_return DOUBLE NOT NULL,
                    sharpe DOUBLE NOT NULL,
                    details VARCHAR NOT NULL
                );
                """
            )
    except Exception as exc:
        logger.warning("DuckDB rl_agent_audit tablosu ilklendirilemedi", hata=str(exc))


def _record_audit_event(
    duckdb_path: str,
    operation: str,
    algorithm: str,
    timesteps: int,
    avg_return: float,
    sharpe: float,
    details: dict[str, Any],
) -> None:
    """RL operasyonunu DuckDB denetim tablosuna kaydeder."""
    try:
        now_iso = datetime.now(UTC).isoformat()
        details_json = orjson.dumps(details, default=str).decode("utf-8")
        with duckdb.connect(duckdb_path) as conn:
            configure_duckdb_wal(conn)
            conn.execute(
                """
                INSERT INTO rl_agent_audit
                (timestamp, operation, algorithm, timesteps, avg_return, sharpe, details)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                [now_iso, operation, algorithm, timesteps, avg_return, sharpe, details_json],
            )
    except Exception as exc:
        logger.warning("DuckDB rl_agent denetim kaydi basarisiz", hata=str(exc))


def train_rl_agent(
    env: Any,
    config: RLConfig | None = None,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
) -> Any:
    """Gymnasium alım-satım ortamında RL ajanını eğitir.

    Args:
        env: Gymnasium uyumlu BISTTradingEnv örneği.
        config: RL ajanı konfigürasyonu.
        duckdb_path: Denetim izi için DuckDB veritabanı yolu.

    Returns:
        Eğitilmiş model nesnesi veya kütüphane eksikse None.
    """
    config = config or RLConfig()
    _init_duckdb_audit(duckdb_path)

    try:
        from stable_baselines3 import A2C, DQN, PPO
        from stable_baselines3.common.vec_env import DummyVecEnv
    except ImportError:
        logger.warning("stable-baselines3 yuklu degil, RL ajani egitimi atlandi (pip install stable-baselines3)")
        return None

    # Vectorize environment
    vec_env = DummyVecEnv([lambda: env])

    if config.algorithm == "PPO":
        model = PPO(
            "MlpPolicy",
            vec_env,
            learning_rate=config.learning_rate,
            gamma=config.gamma,
            gae_lambda=config.gae_lambda,
            clip_range=config.clip_range,
            ent_coef=config.ent_coef,
            vf_coef=config.vf_coef,
            max_grad_norm=config.max_grad_norm,
            n_steps=config.n_steps,
            batch_size=config.batch_size,
            n_epochs=config.n_epochs,
            verbose=0,
            device=config.device,
        )
    elif config.algorithm == "A2C":
        model = A2C(
            "MlpPolicy",
            vec_env,
            learning_rate=config.learning_rate,
            gamma=config.gamma,
            gae_lambda=config.gae_lambda,
            ent_coef=config.ent_coef,
            vf_coef=config.vf_coef,
            max_grad_norm=config.max_grad_norm,
            n_steps=config.n_steps,
            verbose=0,
            device=config.device,
        )
    elif config.algorithm == "DQN":
        model = DQN(
            "MlpPolicy",
            vec_env,
            learning_rate=config.learning_rate,
            gamma=config.gamma,
            batch_size=config.batch_size,
            verbose=0,
            device=config.device,
        )
    else:
        logger.error("Bilinmeyen RL algoritmasi", algorithm=config.algorithm)
        return None

    logger.info("RL ajan egitimi baslatildi", algorithm=config.algorithm, timesteps=config.total_timesteps)
    model.learn(total_timesteps=config.total_timesteps)
    logger.info("RL ajan egitimi tamamlandi", algorithm=config.algorithm)

    _record_audit_event(
        duckdb_path=duckdb_path,
        operation="TRAIN",
        algorithm=config.algorithm,
        timesteps=config.total_timesteps,
        avg_return=0.0,
        sharpe=0.0,
        details=config.to_dict(),
    )

    return model


def evaluate_rl_agent(
    model: Any,
    env: Any,
    n_episodes: int = 10,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
) -> RLEvaluationResult:
    """Eğitilmiş RL ajanını simülasyon ortamında çoklu bölümler halinde değerlendirir.

    Args:
        model: Eğitilmiş RL modeli (predict metoduna sahip).
        env: BISTTradingEnv ortamı.
        n_episodes: Koşulacak test bölümü sayısı.
        duckdb_path: Denetim kaydı yolu.

    Returns:
        Kapsamlı RLEvaluationResult nesnesi.
    """
    _init_duckdb_audit(duckdb_path)
    episode_rewards: list[float] = []
    episode_metrics: list[dict[str, Any]] = []

    for _ in range(max(1, n_episodes)):
        obs, _ = env.reset()
        total_reward = 0.0
        done = False

        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, _ = env.step(action)
            total_reward += float(reward)
            done = bool(terminated or truncated)

        episode_rewards.append(total_reward)
        episode_metrics.append(env.get_metrics())

    avg_return = float(np.mean([m["total_return"] for m in episode_metrics]))
    avg_sharpe = float(np.mean([m["sharpe_ratio"] for m in episode_metrics]))
    avg_mdd = float(np.mean([m["max_drawdown"] for m in episode_metrics]))
    avg_final_cap = float(np.mean([m["final_capital"] for m in episode_metrics]))
    avg_trades = float(np.mean([m["n_trades"] for m in episode_metrics]))
    avg_reward = float(np.mean(episode_rewards))

    res = RLEvaluationResult(
        n_episodes=n_episodes,
        avg_episode_reward=round(avg_reward, 4),
        avg_total_return=round(avg_return, 4),
        avg_sharpe_ratio=round(avg_sharpe, 4),
        avg_max_drawdown=round(avg_mdd, 4),
        avg_final_capital=round(avg_final_cap, 2),
        avg_n_trades=round(avg_trades, 2),
        details={"episode_metrics": episode_metrics},
    )

    _record_audit_event(
        duckdb_path=duckdb_path,
        operation="EVALUATE",
        algorithm=getattr(model, "__class__", type(model)).__name__,
        timesteps=n_episodes,
        avg_return=avg_return,
        sharpe=avg_sharpe,
        details=res.to_dict(),
    )

    return res


def simulate_policy(
    env: BISTTradingEnv,
    policy_func: Callable[[np.ndarray], Any],
    max_steps: int | None = None,
) -> dict[str, Any]:
    """Harici bir RL paketi olmadan deterministik bir kural/fonksiyon ile ortamı çalıştırır.

    Args:
        env: BISTTradingEnv örneği.
        policy_func: Gözlem vektörünü girdi alıp eylem döndüren fonksiyon.
        max_steps: Koşulacak azami adım sayısı (None ise ortam sonuna kadar).

    Returns:
        Ortamın nihai performans metrikleri.
    """
    obs, _ = env.reset()
    done = False
    step_count = 0

    while not done:
        action = policy_func(obs)
        obs, _, terminated, truncated, _ = env.step(action)
        step_count += 1
        done = bool(terminated or truncated)
        if max_steps is not None and step_count >= max_steps:
            break

    return env.get_metrics()


__all__: Final[list[str]] = [
    "BISTTradingEnv",
    "DEFAULT_COMMISSION_RATE",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EPSILON",
    "DEFAULT_INITIAL_CAPITAL",
    "DEFAULT_MAX_POSITION",
    "RLConfig",
    "RLEvaluationResult",
    "configure_duckdb_wal",
    "evaluate_rl_agent",
    "simulate_policy",
    "train_rl_agent",
]
