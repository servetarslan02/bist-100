"""ALPHA BIST — FinRL BIST Çoklu Hisse Takviyeli Öğrenme Simülasyon Ortamı.

Bu modül, Borsa İstanbul (BIST) pay piyasası dinamiklerine uygun olarak tasarlanmış,
Gymnasium uyumlu, çok hisseli portföy yönetimi, gerçekçi işlem maliyetleri (komisyon + kayma),
nakit/pozisyon risk limitleri ve DuckDB denetim izi desteği sunan takviyeli öğrenme
(Reinforcement Learning) simülasyon ortamını içerir.

Temel Yetenekler:
- Çoklu hisse senedi portföy optimizasyonu ve pozisyon yönetimi
- Ayrık aksiyon uzayı (Her hisse için AL / TUT / SAT)
- Gerçekçi komisyon ve kayma (slippage) simülasyonu
- Sermaye ve azami pozisyon yüzdesi kısıtları
- Çeşitlendirilebilir ödül fonksiyonları (Sharpe, Log-Getiri, Risk Düzeltilmiş Getiri)
- Polars DataFrame üzerinden doğrudan ortam başlatma (`from_polars`)
- DuckDB üzerinde SSD korumalı WAL ile adım ve metrik denetim izi
- İş parçacığı güvenliği (`threading.RLock`) ve fail-closed mimari
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

logger = structlog.get_logger(__name__)

# --- Sabitler ---
DEFAULT_INITIAL_CAPITAL: Final[float] = 100_000.0
DEFAULT_COMMISSION_RATE: Final[float] = 0.001  # Binde 1 aracı kurum komisyonu
DEFAULT_SLIPPAGE_RATE: Final[float] = 0.0005   # On binde 5 likidite kayması
DEFAULT_MAX_POSITION_PCT: Final[float] = 0.10  # Tek hissede maksimum portföy payı (%10)
DEFAULT_MAX_TOTAL_EXPOSURE: Final[float] = 1.0 # Maksimum toplam hisse riski (%100)
DEFAULT_WINDOW_SIZE: Final[int] = 20
DEFAULT_FEATURES_PER_STOCK: Final[int] = 65
DEFAULT_ANNUAL_TRADING_DAYS: Final[int] = 252
DEFAULT_EPSILON: Final[float] = 1e-8
DEFAULT_MAX_HISTORY_LEN: Final[int] = 10_000
DEFAULT_DUCKDB_PATH: Final[str] = "data/bist_rl_env.duckdb"


class RewardType(StrEnum):
    """Takviyeli öğrenme ödül fonksiyonu tipleri."""

    SHARPE = "sharpe"
    RETURN = "return"
    LOG_RETURN = "log_return"
    RISK_ADJUSTED = "risk_adjusted"
    SORTINO = "sortino"


class ActionType(StrEnum):
    """Hisse başına ayrık işlem aksiyonları."""

    BUY = "buy"    # 0
    HOLD = "hold"  # 1
    SELL = "sell"  # 2


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
class BISTEnvConfig:
    """BIST Trading Environment konfigürasyon veri modeli."""

    initial_capital: float = DEFAULT_INITIAL_CAPITAL
    commission_rate: float = DEFAULT_COMMISSION_RATE
    slippage_rate: float = DEFAULT_SLIPPAGE_RATE
    max_position_pct: float = DEFAULT_MAX_POSITION_PCT
    max_total_exposure: float = DEFAULT_MAX_TOTAL_EXPOSURE
    reward_type: RewardType = RewardType.SHARPE
    window_size: int = DEFAULT_WINDOW_SIZE
    features_per_stock: int = DEFAULT_FEATURES_PER_STOCK
    duckdb_path: str = DEFAULT_DUCKDB_PATH

    def to_dict(self) -> dict[str, Any]:
        """Konfigürasyonu sözlük formatına dönüştürür."""
        return {
            "initial_capital": self.initial_capital,
            "commission_rate": self.commission_rate,
            "slippage_rate": self.slippage_rate,
            "max_position_pct": self.max_position_pct,
            "max_total_exposure": self.max_total_exposure,
            "reward_type": str(self.reward_type),
            "window_size": self.window_size,
            "features_per_stock": self.features_per_stock,
            "duckdb_path": self.duckdb_path,
        }

    def to_orjson_bytes(self) -> bytes:
        """Konfigürasyonu orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BISTEnvConfig:
        """Sözlükten BISTEnvConfig nesnesi oluşturur."""
        reward_raw = data.get("reward_type", RewardType.SHARPE.value)
        try:
            reward_enum = RewardType(reward_raw)
        except ValueError:
            reward_enum = RewardType.SHARPE
        return cls(
            initial_capital=float(data.get("initial_capital", DEFAULT_INITIAL_CAPITAL)),
            commission_rate=float(data.get("commission_rate", DEFAULT_COMMISSION_RATE)),
            slippage_rate=float(data.get("slippage_rate", DEFAULT_SLIPPAGE_RATE)),
            max_position_pct=float(data.get("max_position_pct", DEFAULT_MAX_POSITION_PCT)),
            max_total_exposure=float(data.get("max_total_exposure", DEFAULT_MAX_TOTAL_EXPOSURE)),
            reward_type=reward_enum,
            window_size=int(data.get("window_size", DEFAULT_WINDOW_SIZE)),
            features_per_stock=int(data.get("features_per_stock", DEFAULT_FEATURES_PER_STOCK)),
            duckdb_path=str(data.get("duckdb_path", DEFAULT_DUCKDB_PATH)),
        )

    def __repr__(self) -> str:
        return (
            f"BISTEnvConfig(initial_capital={self.initial_capital:.2f}, "
            f"reward_type='{self.reward_type}', commission={self.commission_rate:.4f})"
        )


@dataclass(slots=True)
class BISTStepResult:
    """Ortam adım çıktısını temsil eden tip güvenli veri modeli."""

    step: int
    observation: np.ndarray
    reward: float
    terminated: bool
    truncated: bool
    portfolio_value: float
    cash: float
    total_commission: float
    info: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Adım sonucunu sözlük formatına dönüştürür."""
        return {
            "step": self.step,
            "reward": round(self.reward, 6),
            "terminated": self.terminated,
            "truncated": self.truncated,
            "portfolio_value": round(self.portfolio_value, 2),
            "cash": round(self.cash, 2),
            "total_commission": round(self.total_commission, 4),
            "info": self.info,
        }

    def to_orjson_bytes(self) -> bytes:
        """Adım sonucunu orjson byte dizisine serileştirir."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BISTStepResult:
        """Sözlükten BISTStepResult nesnesi oluşturur."""
        obs_raw = data.get("observation", np.zeros(1))
        obs_arr = np.asarray(obs_raw, dtype=np.float64) if not isinstance(obs_raw, np.ndarray) else obs_raw
        return cls(
            step=int(data.get("step", 0)),
            observation=obs_arr,
            reward=float(data.get("reward", 0.0)),
            terminated=bool(data.get("terminated", False)),
            truncated=bool(data.get("truncated", False)),
            portfolio_value=float(data.get("portfolio_value", 0.0)),
            cash=float(data.get("cash", 0.0)),
            total_commission=float(data.get("total_commission", 0.0)),
            info=dict(data.get("info", {})),
        )

    def __repr__(self) -> str:
        return (
            f"BISTStepResult(step={self.step}, reward={self.reward:.4f}, "
            f"portfolio_value={self.portfolio_value:.2f}, terminated={self.terminated})"
        )


@dataclass(slots=True)
class BISTEnvMetrics:
    """Ortam simülasyonu nihai performans metrikleri."""

    total_return: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    final_capital: float
    active_positions: int
    total_tickers: int
    total_steps: int

    def to_dict(self) -> dict[str, Any]:
        """Metrikleri sözlük formatına dönüştürür."""
        return {
            "total_return": round(self.total_return, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "sortino_ratio": round(self.sortino_ratio, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "final_capital": round(self.final_capital, 2),
            "active_positions": self.active_positions,
            "total_tickers": self.total_tickers,
            "total_steps": self.total_steps,
        }

    def to_orjson_bytes(self) -> bytes:
        """Metrikleri orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BISTEnvMetrics:
        """Sözlükten BISTEnvMetrics nesnesi oluşturur."""
        return cls(
            total_return=float(data.get("total_return", 0.0)),
            sharpe_ratio=float(data.get("sharpe_ratio", 0.0)),
            sortino_ratio=float(data.get("sortino_ratio", 0.0)),
            max_drawdown=float(data.get("max_drawdown", 0.0)),
            final_capital=float(data.get("final_capital", 0.0)),
            active_positions=int(data.get("active_positions", 0)),
            total_tickers=int(data.get("total_tickers", 0)),
            total_steps=int(data.get("total_steps", 0)),
        )

    def __repr__(self) -> str:
        return (
            f"BISTEnvMetrics(total_return={self.total_return:.2%}, "
            f"sharpe={self.sharpe_ratio:.2f}, max_dd={self.max_drawdown:.2%})"
        )


class BISTTradingEnv:
    """BIST Çoklu Hisse Senedi Takviyeli Öğrenme Simülasyon Ortamı.

    Gymnasium arayüzü ile uyumlu olup çoklu hisse senetlerinde pozisyon alma,
    nakit yönetimi, işlem maliyetleri ve portföy getiri/risk optimizasyonunu simüle eder.
    """

    def __init__(
        self,
        features: dict[str, np.ndarray],
        prices: dict[str, np.ndarray],
        tickers: list[str],
        config: BISTEnvConfig | None = None,
    ) -> None:
        """BISTTradingEnv ortamını başlatır ve gözlem/aksiyon uzaylarını kurar.

        Args:
            features: Hisse bazında zaman serisi öznitelik matrisleri `{ticker: (Zaman, Öznitelikler)}`.
            prices: Hisse bazında kapanış/işlem fiyatları serisi `{ticker: (Zaman,)}`.
            tickers: Simülasyona dahil edilen hisse kodu listesi.
            config: Ortam konfigürasyon parametreleri.

        Raises:
            ValueError: Hisse listesi boşsa veya fiyat serileri uyumsuzsa fırlatılır.
        """
        self._lock = threading.RLock()
        self.tickers = list(tickers)
        if not self.tickers:
            raise ValueError("Ortam baslatilamadi: Tickers listesi bos olamaz.")

        self.config = config or BISTEnvConfig()
        self.features = features
        self.prices = prices

        # Minimum adım sayısını belirle
        price_lengths = [len(v) for k, v in self.prices.items() if k in self.tickers]
        self._n_steps = min(price_lengths) if price_lengths else 0
        if self._n_steps < 2:
            raise ValueError(f"Ortam baslatilamadi: Yetersiz veri boyutu (adim={self._n_steps}).")

        # Portföy durumu
        self._current_step = 0
        self._capital = float(self.config.initial_capital)
        self._positions: dict[str, float] = {t: 0.0 for t in self.tickers}
        self._portfolio_values: list[float] = [self._capital]
        self._total_commission_paid = 0.0

        # Gymnasium uzayları
        self.observation_space = self._make_obs_space()
        self.action_space = self._make_action_space()

        # DuckDB denetim tablosunu hazırla
        self._init_duckdb()

        logger.info(
            "BISTTradingEnv basariyla baslatildi",
            hisseler=len(self.tickers),
            toplam_adim=self._n_steps,
            baslangic_sermaye=self._capital,
        )

    def _init_duckdb(self) -> None:
        """DuckDB denetim izi tablosunu oluşturur."""
        try:
            db_path = Path(self.config.duckdb_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(str(db_path)) as conn:
                configure_duckdb_wal(conn)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS bist_rl_env_audit (
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        step BIGINT,
                        portfolio_value DOUBLE,
                        capital DOUBLE,
                        reward DOUBLE,
                        commission DOUBLE,
                        active_positions BIGINT,
                        reward_type VARCHAR
                    );
                """)
        except Exception as exc:
            logger.warning("DuckDB denetim tablosu hazirlanamadi", hata=str(exc))

    def _make_obs_space(self) -> Any:
        """Gymnasium gözlem uzayını (Box) oluşturur.

        Returns:
            Gymnasium Box uzayı veya modül kurulu değilse None.
        """
        try:
            from gymnasium import spaces

            n_obs = len(self.tickers) * self.config.features_per_stock + len(self.tickers) + 1
            return spaces.Box(low=-np.inf, high=np.inf, shape=(n_obs,), dtype=np.float32)
        except ImportError:
            return None

    def _make_action_space(self) -> Any:
        """Gymnasium aksiyon uzayını (MultiDiscrete: 0=AL, 1=TUT, 2=SAT) oluşturur.

        Returns:
            Gymnasium MultiDiscrete uzayı veya modül kurulu değilse None.
        """
        try:
            from gymnasium import spaces

            return spaces.MultiDiscrete([3] * len(self.tickers))
        except ImportError:
            return None

    def reset(self, seed: int | None = None, options: dict[str, Any] | None = None) -> tuple[np.ndarray, dict[str, Any]]:
        """Ortamı başlangıç durumuna sıfırlar.

        Args:
            seed: Rastgele sayı üreteci tohum değeri.
            options: Ek sıfırlama opsiyonları.

        Returns:
            Başlangıç gözlem vektörü ve bilgi sözlüğü demeti.
        """
        with self._lock:
            if seed is not None:
                np.random.seed(seed)

            self._current_step = 0
            self._capital = float(self.config.initial_capital)
            self._positions = {t: 0.0 for t in self.tickers}
            self._portfolio_values = [self._capital]
            self._total_commission_paid = 0.0

            obs = self._get_obs()
            info: dict[str, Any] = {
                "step": 0,
                "portfolio_value": self._capital,
                "cash": self._capital,
            }
            return obs, info

    def step(self, actions: list[int] | np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Ortamda bir adım ilerler ve aksiyonları simüle eder.

        Args:
            actions: Her hisse için ayrık işlem kodu (0=AL, 1=TUT, 2=SAT).

        Returns:
            (Gözlem, Ödül, Sonlandı_mı, Kesildi_mi, Ek_Bilgi) demeti.
        """
        with self._lock:
            if self._current_step >= self._n_steps - 1:
                return self._get_obs(), 0.0, True, False, {"info": "Episode sonuna ulasildi"}

            total_commission = 0.0
            act_list = list(actions) if isinstance(actions, np.ndarray) else actions

            # 1. Aşama: SATIŞLAR (Nakit serbest bırakma)
            for i, ticker in enumerate(self.tickers):
                action = act_list[i] if i < len(act_list) else 1
                if action == 2:  # SAT (SELL)
                    qty = self._positions.get(ticker, 0.0)
                    price = float(self.prices[ticker][self._current_step])
                    if qty > 0 and price > 0:
                        revenue = qty * price
                        comm = revenue * self.config.commission_rate
                        slip = revenue * self.config.slippage_rate
                        net_revenue = revenue - (comm + slip)

                        self._capital += max(net_revenue, 0.0)
                        self._positions[ticker] = 0.0
                        total_commission += comm + slip

            # 2. Aşama: ALIŞLAR (Sermaye ve risk kısıtlarına göre tahsisat)
            curr_portfolio_val = self._calculate_current_portfolio_value()
            for i, ticker in enumerate(self.tickers):
                action = act_list[i] if i < len(act_list) else 1
                if action == 0:  # AL (BUY)
                    price = float(self.prices[ticker][self._current_step])
                    if price <= 0:
                        continue

                    # Maksimum pozisyon ve nakit kısıtı
                    max_invest = curr_portfolio_val * self.config.max_position_pct
                    available_cash = self._capital * 0.95  # %5 nakit tamponu
                    invest = min(max_invest, available_cash)

                    effective_price = price * (1.0 + self.config.slippage_rate)
                    unit_cost = effective_price * (1.0 + self.config.commission_rate)

                    if invest >= unit_cost and unit_cost > 0:
                        qty = int(invest / unit_cost)
                        if qty > 0:
                            cost = qty * price
                            comm = cost * self.config.commission_rate
                            slip = cost * self.config.slippage_rate
                            total_outflow = cost + comm + slip

                            if self._capital >= total_outflow:
                                self._capital -= total_outflow
                                self._positions[ticker] = self._positions.get(ticker, 0.0) + qty
                                total_commission += comm + slip

            self._total_commission_paid += total_commission

            # Adımı ilerlet
            self._current_step += 1

            # Yeni adım kapanışındaki portföy değerini hesapla
            new_portfolio_val = self._calculate_current_portfolio_value()
            self._portfolio_values.append(new_portfolio_val)
            if len(self._portfolio_values) > DEFAULT_MAX_HISTORY_LEN:
                self._portfolio_values = self._portfolio_values[-DEFAULT_MAX_HISTORY_LEN:]

            # Ödül hesapla
            reward = self._compute_reward()

            # Episode sonlanma koşulu
            terminated = (self._current_step >= self._n_steps - 1) or (new_portfolio_val <= self.config.initial_capital * 0.1)
            truncated = False

            info = {
                "step": self._current_step,
                "portfolio_value": round(new_portfolio_val, 2),
                "cash": round(self._capital, 2),
                "commission_step": round(total_commission, 4),
                "total_commission": round(self._total_commission_paid, 4),
                "active_positions": sum(1 for v in self._positions.values() if v > 0),
            }

            # DuckDB denetim kaydı (opsiyonel)
            if self._current_step % 20 == 0 or terminated:
                self._record_audit_log(new_portfolio_val, reward, total_commission)

            return self._get_obs(), reward, terminated, truncated, info

    def _calculate_current_portfolio_value(self) -> float:
        """Güncel adımın fiyatlarıyla toplam portföy değerini hesaplar."""
        val = float(self._capital)
        step_idx = min(self._current_step, self._n_steps - 1)
        for ticker in self.tickers:
            qty = self._positions.get(ticker, 0.0)
            if qty > 0 and step_idx < len(self.prices[ticker]):
                price = float(self.prices[ticker][step_idx])
                if np.isfinite(price) and price > 0:
                    val += qty * price
        return max(val, 0.0)

    def _get_obs(self) -> np.ndarray:
        """Mevcut adım için durum gözlem vektörünü (State Observation) üretir."""
        obs: list[float] = []
        step_idx = min(self._current_step, self._n_steps - 1)

        # 1. Hisse bazlı öznitelikler
        for ticker in self.tickers:
            feat_arr = self.features.get(ticker)
            if feat_arr is not None and step_idx < len(feat_arr):
                row = feat_arr[step_idx]
                if len(row) >= self.config.features_per_stock:
                    obs.extend(float(x) if np.isfinite(x) else 0.0 for x in row[: self.config.features_per_stock])
                else:
                    padded = [float(x) if np.isfinite(x) else 0.0 for x in row]
                    padded.extend([0.0] * (self.config.features_per_stock - len(row)))
                    obs.extend(padded)
            else:
                obs.extend([0.0] * self.config.features_per_stock)

        # 2. Pozisyon oranları
        total_val = max(self._portfolio_values[-1], 1.0)
        for ticker in self.tickers:
            qty = self._positions.get(ticker, 0.0)
            pos_val = 0.0
            if qty > 0 and step_idx < len(self.prices[ticker]):
                price = float(self.prices[ticker][step_idx])
                if np.isfinite(price) and price > 0:
                    pos_val = qty * price
            obs.append(float(pos_val / total_val))

        # 3. Nakit oranı
        obs.append(float(self._capital / total_val))

        return np.array(obs, dtype=np.float32)

    def _compute_reward(self) -> float:
        """Konfigürasyonda seçilen tipe göre ödülü hesaplar."""
        if len(self._portfolio_values) < 2:
            return 0.0

        v_curr = self._portfolio_values[-1]
        v_prev = self._portfolio_values[-2]

        if self.config.reward_type == RewardType.RETURN:
            if v_prev <= DEFAULT_EPSILON:
                return 0.0
            return float((v_curr / v_prev) - 1.0)

        elif self.config.reward_type == RewardType.LOG_RETURN:
            if v_curr <= DEFAULT_EPSILON or v_prev <= DEFAULT_EPSILON:
                return -1.0
            return float(np.log(v_curr / v_prev))

        elif self.config.reward_type == RewardType.SHARPE:
            # En az window_size + 1 gözlem gerekli
            win = self.config.window_size
            if len(self._portfolio_values) < win + 1:
                if v_prev <= DEFAULT_EPSILON:
                    return 0.0
                return float((v_curr / v_prev) - 1.0)

            # Doğru getiri dilimlemesi (boyut uyuşmazlığı fixi)
            recent_vals = np.array(self._portfolio_values[-(win + 1):], dtype=np.float64)
            returns = np.diff(recent_vals) / np.maximum(recent_vals[:-1], DEFAULT_EPSILON)

            ret_std = float(np.std(returns))
            if ret_std < DEFAULT_EPSILON or not np.isfinite(ret_std):
                return 0.0
            ret_mean = float(np.mean(returns))
            return float((ret_mean / ret_std) * np.sqrt(DEFAULT_ANNUAL_TRADING_DAYS))

        elif self.config.reward_type == RewardType.SORTINO:
            win = self.config.window_size
            if len(self._portfolio_values) < win + 1:
                return float((v_curr / max(v_prev, DEFAULT_EPSILON)) - 1.0)

            recent_vals = np.array(self._portfolio_values[-(win + 1):], dtype=np.float64)
            returns = np.diff(recent_vals) / np.maximum(recent_vals[:-1], DEFAULT_EPSILON)
            downside = returns[returns < 0]
            down_std = float(np.std(downside)) if len(downside) > 1 else float(np.std(returns))

            if down_std < DEFAULT_EPSILON or not np.isfinite(down_std):
                return 0.0
            return float((np.mean(returns) / down_std) * np.sqrt(DEFAULT_ANNUAL_TRADING_DAYS))

        else:  # RISK_ADJUSTED veya varsayılan
            total_ret = (v_curr / self.config.initial_capital) - 1.0
            return float(total_ret)

    def _record_audit_log(self, p_val: float, reward: float, step_comm: float) -> None:
        """Denetim kaydını DuckDB'ye yazar."""
        try:
            with duckdb.connect(self.config.duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO bist_rl_env_audit (
                        step, portfolio_value, capital, reward, commission, active_positions, reward_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    [
                        self._current_step,
                        float(p_val),
                        float(self._capital),
                        float(reward),
                        float(step_comm),
                        sum(1 for v in self._positions.values() if v > 0),
                        str(self.config.reward_type),
                    ],
                )
        except Exception as exc:
            logger.debug("DuckDB denetim kaydi atlandi", hata=str(exc))

    def get_metrics(self) -> BISTEnvMetrics:
        """Simülasyonun toplam getiri ve risk metriklerini hesaplar.

        Returns:
            BISTEnvMetrics veri modeli nesnesi.
        """
        with self._lock:
            values = np.array(self._portfolio_values, dtype=np.float64)
            init_cap = max(self.config.initial_capital, DEFAULT_EPSILON)
            total_return = float((values[-1] / init_cap) - 1.0)

            if len(values) > 1:
                daily_returns = np.diff(values) / np.maximum(values[:-1], DEFAULT_EPSILON)
                daily_returns = daily_returns[np.isfinite(daily_returns)]
                ret_std = float(np.std(daily_returns)) if len(daily_returns) > 0 else 0.0
                ret_mean = float(np.mean(daily_returns)) if len(daily_returns) > 0 else 0.0

                sharpe = float((ret_mean / max(ret_std, DEFAULT_EPSILON)) * np.sqrt(DEFAULT_ANNUAL_TRADING_DAYS))

                downside = daily_returns[daily_returns < 0]
                down_std = float(np.std(downside)) if len(downside) > 1 else ret_std
                sortino = float((ret_mean / max(down_std, DEFAULT_EPSILON)) * np.sqrt(DEFAULT_ANNUAL_TRADING_DAYS))
            else:
                sharpe = 0.0
                sortino = 0.0

            running_max = np.maximum.accumulate(values)
            drawdowns = (values - running_max) / np.maximum(running_max, DEFAULT_EPSILON)
            max_dd = float(np.abs(np.min(drawdowns))) if len(drawdowns) > 0 else 0.0

            active = sum(1 for v in self._positions.values() if v > 0)

            return BISTEnvMetrics(
                total_return=total_return,
                sharpe_ratio=sharpe if np.isfinite(sharpe) else 0.0,
                sortino_ratio=sortino if np.isfinite(sortino) else 0.0,
                max_drawdown=max_dd if np.isfinite(max_dd) else 0.0,
                final_capital=float(values[-1]),
                active_positions=active,
                total_tickers=len(self.tickers),
                total_steps=self._current_step,
            )

    @classmethod
    def from_polars(
        cls,
        df: pl.DataFrame,
        ticker_col: str = "ticker",
        price_col: str = "close",
        feature_cols: list[str] | None = None,
        config: BISTEnvConfig | None = None,
    ) -> BISTTradingEnv:
        """Polars DataFrame'den doğrudan BISTTradingEnv ortamını kurar.

        Args:
            df: Zaman serisi verilerini içeren Polars DataFrame (ticker, close ve öznitelik sütunları).
            ticker_col: Hisse kodu sütun adı.
            price_col: Fiyat sütun adı (varsayılan: 'close').
            feature_cols: Kullanılacak öznitelik sütun isimleri listesi.
            config: Ortam konfigürasyonu.

        Returns:
            Yapılandırılmış BISTTradingEnv örneği.
        """
        if ticker_col not in df.columns or price_col not in df.columns:
            raise ValueError(f"DataFrame gerekli sütunlari icermiyor: {ticker_col}, {price_col}")

        tickers = sorted(df[ticker_col].unique().to_list())
        if not tickers:
            raise ValueError("Polars DataFrame icinde hic ticker bulunamadi.")

        actual_feat_cols = feature_cols
        if actual_feat_cols is None:
            actual_feat_cols = [c for c in df.columns if c not in {ticker_col, price_col, "date", "timestamp"}]

        features: dict[str, np.ndarray] = {}
        prices: dict[str, np.ndarray] = {}

        for ticker in tickers:
            sub_df = df.filter(pl.col(ticker_col) == ticker)
            p_arr = sub_df[price_col].to_numpy().astype(np.float64)
            prices[ticker] = p_arr

            if actual_feat_cols:
                f_arr = sub_df.select(actual_feat_cols).to_numpy().astype(np.float32)
                features[ticker] = f_arr
            else:
                features[ticker] = np.zeros((len(p_arr), 1), dtype=np.float32)

        env_cfg = config or BISTEnvConfig()
        if actual_feat_cols:
            env_cfg.features_per_stock = len(actual_feat_cols)

        return cls(features=features, prices=prices, tickers=tickers, config=env_cfg)

    def __repr__(self) -> str:
        return (
            f"BISTTradingEnv(tickers={len(self.tickers)}, step={self._current_step}/{self._n_steps}, "
            f"capital={self._capital:.2f}, positions={sum(1 for v in self._positions.values() if v > 0)})"
        )


__all__: Final[list[str]] = [
    "DEFAULT_ANNUAL_TRADING_DAYS",
    "DEFAULT_COMMISSION_RATE",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EPSILON",
    "DEFAULT_FEATURES_PER_STOCK",
    "DEFAULT_INITIAL_CAPITAL",
    "DEFAULT_MAX_POSITION_PCT",
    "DEFAULT_MAX_TOTAL_EXPOSURE",
    "DEFAULT_SLIPPAGE_RATE",
    "DEFAULT_WINDOW_SIZE",
    "ActionType",
    "BISTEnvConfig",
    "BISTEnvMetrics",
    "BISTStepResult",
    "BISTTradingEnv",
    "RewardType",
    "configure_duckdb_wal",
]
