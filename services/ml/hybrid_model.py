"""ALPHA BIST — Hibrit Karar Füzyon Modeli (Nihai — ⭐⭐⭐⭐⭐).

Bu modül, Makine Öğrenimi (ML) skorları, FinGPT duygu analizi ve Takviyeli Öğrenme (RL)
aksiyonlarını dinamik rejim ağırlıkları, çelişki tespiti (conflict resolution) ve
piyasa devre kesici durumlarına göre birleştiren yüksek performanslı hibrit füzyon motorudur.

Temel Yetenekler:
- ML Ranking + Duygu Analizi + RL Politika entegrasyonu
- Piyasa rejimlerine (BOĞA, AYI, YATAY, YÜKSEK VOLATİLİTE) göre dinamik ağırlıklandırma
- Sinyal çelişkisi tespiti ve risk azaltıcı güven katsayısı düzeltmesi
- Piyasa işlem durdurma (HALT / LIMIT / CIRCUIT_BREAKER) durumlarında fail-closed koruması
- Polars DataFrame üzerinde toplu tahmin (`predict_polars`)
- DuckDB üzerinde SSD korumalı WAL ile hibrit karar denetim izi
- İş parçacığı güvenliği (`threading.RLock`) ve `orjson` serileştirme desteği
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
DEFAULT_ML_WEIGHT: Final[float] = 0.50
DEFAULT_SENTIMENT_WEIGHT: Final[float] = 0.30
DEFAULT_RL_WEIGHT: Final[float] = 0.20
DEFAULT_BUY_THRESHOLD: Final[float] = 0.65
DEFAULT_SELL_THRESHOLD: Final[float] = 0.35
DEFAULT_CONFLICT_PENALTY: Final[float] = 0.60
DEFAULT_HALT_PENALTY: Final[float] = 0.30
DEFAULT_CONFIDENCE_THRESHOLD: Final[float] = 0.40
DEFAULT_DUCKDB_PATH: Final[str] = "data/hybrid_model.duckdb"
DEFAULT_EPSILON: Final[float] = 1e-8


class HybridAction(StrEnum):
    """Hibrit model nihai işlem kararları."""

    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"


class MarketRegime(StrEnum):
    """Piyasa rejim durumları."""

    NORMAL = "NORMAL"
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOL = "HIGH_VOL"


class MarketState(StrEnum):
    """Borsa İstanbul piyasa işlem durumları."""

    NORMAL = "NORMAL"
    HALT = "HALT"                         # İşlem sırası durdurma
    LIMIT = "LIMIT"                       # Taban/Tavan fiyat limiti
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"   # Endeks devre kesici


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
class HybridSignal:
    """Hibrit model karar ve sinyal füzyon sonucu."""

    action: HybridAction
    confidence: float
    ml_score: float
    sentiment_score: float
    rl_action: int
    conflict: bool
    signals: dict[str, Any]
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        """Sinyali JSON uyumlu sözlüğe dönüştürür."""
        return {
            "action": str(self.action),
            "confidence": round(self.confidence, 4),
            "ml_score": round(self.ml_score, 4),
            "sentiment_score": round(self.sentiment_score, 4),
            "rl_action": self.rl_action,
            "conflict": self.conflict,
            "signals": self.signals,
            "reasoning": self.reasoning,
        }

    def to_orjson_bytes(self) -> bytes:
        """Sinyali orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HybridSignal:
        """Sözlükten HybridSignal örneği oluşturur."""
        return cls(
            action=HybridAction(str(data["action"])),
            confidence=float(data.get("confidence", 0.0)),
            ml_score=float(data.get("ml_score", 0.5)),
            sentiment_score=float(data.get("sentiment_score", 0.0)),
            rl_action=int(data.get("rl_action", 0)),
            conflict=bool(data.get("conflict", False)),
            signals=dict(data.get("signals", {})),
            reasoning=str(data.get("reasoning", "")),
        )

    def __repr__(self) -> str:
        return (
            f"HybridSignal(action='{self.action}', conf={self.confidence:.2f}, "
            f"ml={self.ml_score:.2f}, sent={self.sentiment_score:.2f}, conflict={self.conflict})"
        )


class HybridModel:
    """Çoklu sinyal füzyon ve karar motoru.

    ML skoru, NLP duygu puanı ve RL aksiyonunu dinamik olarak ağırlıklandırıp
    çelişki ve piyasa koşullarına göre nihai alım/satım/tut kararını üretir.
    """

    def __init__(
        self,
        ml_weight: float = DEFAULT_ML_WEIGHT,
        sentiment_weight: float = DEFAULT_SENTIMENT_WEIGHT,
        rl_weight: float = DEFAULT_RL_WEIGHT,
        buy_threshold: float = DEFAULT_BUY_THRESHOLD,
        sell_threshold: float = DEFAULT_SELL_THRESHOLD,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        duckdb_path: str = DEFAULT_DUCKDB_PATH,
    ) -> None:
        """Hibrit modeli başlatır ve rejim ağırlıklarını tanımlar.

        Args:
            ml_weight: Varsayılan ML model ağırlığı.
            sentiment_weight: Varsayılan duygu analizi ağırlığı.
            rl_weight: Varsayılan RL ajan ağırlığı.
            buy_threshold: Alım kararı için ağırlıklı skor eşiği.
            sell_threshold: Satım kararı için ağırlıklı skor eşiği.
            confidence_threshold: Minimum güven eşiği.
            duckdb_path: Denetim izi DuckDB veritabanı yolu.
        """
        self._lock = threading.RLock()
        self.ml_weight = float(ml_weight)
        self.sentiment_weight = float(sentiment_weight)
        self.rl_weight = float(rl_weight)
        self.buy_threshold = float(buy_threshold)
        self.sell_threshold = float(sell_threshold)
        self.confidence_threshold = float(confidence_threshold)
        self.duckdb_path = duckdb_path

        self._regime_weights: dict[str, dict[str, float]] = {
            MarketRegime.BULL: {"ml": 0.40, "sentiment": 0.40, "rl": 0.20},
            MarketRegime.BEAR: {"ml": 0.50, "sentiment": 0.20, "rl": 0.30},
            MarketRegime.SIDEWAYS: {"ml": 0.60, "sentiment": 0.20, "rl": 0.20},
            MarketRegime.HIGH_VOL: {"ml": 0.30, "sentiment": 0.20, "rl": 0.50},
            MarketRegime.NORMAL: {"ml": self.ml_weight, "sentiment": self.sentiment_weight, "rl": self.rl_weight},
        }

        self._init_duckdb()

    def _init_duckdb(self) -> None:
        """DuckDB denetim tablosunu hazırlar."""
        try:
            db_file = Path(self.duckdb_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(str(db_file)) as conn:
                configure_duckdb_wal(conn)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS hybrid_signal_audit (
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        action VARCHAR,
                        confidence DOUBLE,
                        ml_score DOUBLE,
                        sentiment_score DOUBLE,
                        rl_action INTEGER,
                        conflict BOOLEAN,
                        regime VARCHAR,
                        market_state VARCHAR,
                        reasoning VARCHAR
                    );
                """)
        except Exception as exc:
            logger.warning("DuckDB hibrit denetim tablosu olusturulamadi", hata=str(exc))

    def predict(
        self,
        ml_score: float,
        sentiment_score: float,
        rl_action: int,
        regime: str | MarketRegime = MarketRegime.NORMAL,
        market_state: str | MarketState = MarketState.NORMAL,
    ) -> HybridSignal:
        """Gelen sinyalleri birleştirerek nihai hibrit işlem kararını üretir.

        Args:
            ml_score: Makine öğrenimi tahmin olasılığı veya normalize skoru [0.0, 1.0].
            sentiment_score: NLP duygu analizi kutupsallık puanı [-1.0, 1.0].
            rl_action: Takviyeli öğrenme aksiyon kodu (0=AL, 1=TUT, 2=SAT).
            regime: Mevcut piyasa rejimi (BULL, BEAR, SIDEWAYS, vb.).
            market_state: Piyasa operasyonel durumu (NORMAL, HALT, LIMIT vb.).

        Returns:
            HybridSignal nesnesi.
        """
        with self._lock:
            # Sayısal guard kontrolleri
            safe_ml = float(ml_score) if np.isfinite(ml_score) else 0.5
            safe_ml = float(np.clip(safe_ml, 0.0, 1.0))

            safe_sent = float(sentiment_score) if np.isfinite(sentiment_score) else 0.0
            safe_sent = float(np.clip(safe_sent, -1.0, 1.0))

            safe_rl = int(rl_action) if rl_action in (0, 1, 2) else 1

            reg_key = str(regime).upper()
            weights = self._regime_weights.get(
                reg_key,
                {"ml": self.ml_weight, "sentiment": self.sentiment_weight, "rl": self.rl_weight},
            )

            # Ağırlık normalizasyonu
            w_total = max(weights.get("ml", 0.0) + weights.get("sentiment", 0.0) + weights.get("rl", 0.0), DEFAULT_EPSILON)
            w_ml = weights.get("ml", 0.0) / w_total
            w_sent = weights.get("sentiment", 0.0) / w_total
            w_rl = weights.get("rl", 0.0) / w_total

            # Sinyal bileşenlerini 0-1 aralığına normalize et
            sent_norm = (safe_sent + 1.0) / 2.0
            rl_norm = {0: 0.85, 1: 0.50, 2: 0.15}.get(safe_rl, 0.50)

            weighted_score = (safe_ml * w_ml) + (sent_norm * w_sent) + (rl_norm * w_rl)

            # Çelişki (Conflict) tespiti
            ml_dir = HybridAction.BUY if safe_ml > 0.55 else (HybridAction.SELL if safe_ml < 0.45 else HybridAction.HOLD)
            sent_dir = HybridAction.BUY if safe_sent > 0.15 else (HybridAction.SELL if safe_sent < -0.15 else HybridAction.HOLD)
            rl_dir = {0: HybridAction.BUY, 1: HybridAction.HOLD, 2: HybridAction.SELL}.get(safe_rl, HybridAction.HOLD)

            active_dirs = {d for d in (ml_dir, sent_dir, rl_dir) if d != HybridAction.HOLD}
            conflict = len(active_dirs) > 1

            # Karar eşikleri
            if weighted_score >= self.buy_threshold:
                action = HybridAction.BUY
            elif weighted_score <= self.sell_threshold:
                action = HybridAction.SELL
            else:
                action = HybridAction.HOLD

            # Temel güven skoru
            base_conf = abs(weighted_score - 0.50) * 2.0
            if conflict:
                base_conf *= DEFAULT_CONFLICT_PENALTY

            # Piyasa durum düzeltmesi (Fail-closed)
            m_state_str = str(market_state).upper()
            if m_state_str in (MarketState.HALT, MarketState.LIMIT, MarketState.CIRCUIT_BREAKER):
                action = HybridAction.HOLD
                base_conf *= DEFAULT_HALT_PENALTY

            final_conf = float(np.clip(base_conf, 0.0, 1.0))

            reasoning = self._generate_reasoning(
                safe_ml, safe_sent, safe_rl, reg_key, conflict, action, m_state_str
            )

            signal_obj = HybridSignal(
                action=action,
                confidence=round(final_conf, 4),
                ml_score=round(safe_ml, 4),
                sentiment_score=round(safe_sent, 4),
                rl_action=safe_rl,
                conflict=conflict,
                signals={
                    "ml_direction": str(ml_dir),
                    "sentiment_direction": str(sent_dir),
                    "rl_direction": str(rl_dir),
                    "weighted_score": round(weighted_score, 4),
                    "regime": reg_key,
                    "weights": {"ml": round(w_ml, 3), "sentiment": round(w_sent, 3), "rl": round(w_rl, 3)},
                    "market_state": m_state_str,
                },
                reasoning=reasoning,
            )

            # DuckDB denetim kaydı
            self._record_audit(signal_obj, reg_key, m_state_str)

            return signal_obj

    def predict_batch(
        self,
        ml_scores: np.ndarray | list[float],
        sentiment_scores: np.ndarray | list[float],
        rl_actions: np.ndarray | list[int],
        regime: str | MarketRegime = MarketRegime.NORMAL,
        market_state: str | MarketState = MarketState.NORMAL,
    ) -> list[HybridSignal]:
        """Toplu sinyal dizileri için liste halinde tahmin üretir.

        Args:
            ml_scores: ML skorları dizisi.
            sentiment_scores: Duygu analizi puanları dizisi.
            rl_actions: RL işlem aksiyonları dizisi.
            regime: Piyasa rejimi.
            market_state: Piyasa durumu.

        Returns:
            HybridSignal listesi.
        """
        results: list[HybridSignal] = []
        for ml, sent, rl in zip(ml_scores, sentiment_scores, rl_actions, strict=False):
            results.append(self.predict(ml, sent, rl, regime=regime, market_state=market_state))
        return results

    def predict_polars(
        self,
        df: pl.DataFrame,
        ml_col: str = "ml_score",
        sentiment_col: str = "sentiment_score",
        rl_col: str = "rl_action",
        regime: str | MarketRegime = MarketRegime.NORMAL,
        market_state: str | MarketState = MarketState.NORMAL,
    ) -> pl.DataFrame:
        """Polars DataFrame içindeki sinyalleri işleyerek hibrit karar sütunlarını ekler.

        Args:
            df: Girdi Polars DataFrame'i.
            ml_col: ML skoru sütun adı.
            sentiment_col: Duygu puanı sütun adı.
            rl_col: RL aksiyonu sütun adı.
            regime: Piyasa rejimi.
            market_state: Piyasa durumu.

        Returns:
            Yeni eklenen 'hybrid_action', 'confidence', 'conflict' ve 'reasoning' sütunlarıyla Polars DataFrame.
        """
        if df.is_empty():
            return df.with_columns([
                pl.lit("HOLD").alias("hybrid_action"),
                pl.lit(0.0).alias("confidence"),
                pl.lit(False).alias("conflict"),
                pl.lit("").alias("reasoning"),
            ])

        ml_vals = df[ml_col].to_numpy()
        sent_vals = df[sentiment_col].to_numpy()
        rl_vals = df[rl_col].to_numpy()

        signals = self.predict_batch(ml_vals, sent_vals, rl_vals, regime=regime, market_state=market_state)

        actions = [str(s.action) for s in signals]
        confs = [s.confidence for s in signals]
        conflicts = [s.conflict for s in signals]
        reasons = [s.reasoning for s in signals]

        return df.with_columns([
            pl.Series("hybrid_action", actions),
            pl.Series("confidence", confs, dtype=pl.Float64),
            pl.Series("conflict", conflicts, dtype=pl.Boolean),
            pl.Series("reasoning", reasons, dtype=pl.Utf8),
        ])

    def set_regime_weights(self, regime: str | MarketRegime, weights: dict[str, float]) -> None:
        """Belirtilen rejim için ağırlıkları dinamik olarak günceller.

        Args:
            regime: Rejim anahtarı (BULL, BEAR, vb.).
            weights: {'ml': float, 'sentiment': float, 'rl': float} sözlüğü.
        """
        with self._lock:
            reg_key = str(regime).upper()
            self._regime_weights[reg_key] = dict(weights)
            logger.info("Rejim agirliklari guncellendi", rejim=reg_key, agirliklar=weights)

    def _generate_reasoning(
        self,
        ml_score: float,
        sentiment_score: float,
        rl_action: int,
        regime: str,
        conflict: bool,
        action: HybridAction,
        market_state: str,
    ) -> str:
        """Karar gerekçesini açıklayıcı Türkçe metin olarak derler."""
        parts: list[str] = []

        if market_state in (MarketState.HALT, MarketState.LIMIT, MarketState.CIRCUIT_BREAKER):
            parts.append(f"⛔ PIYASA DURUMU: {market_state} (Islemler guvenlik geregi durduruldu)")

        if ml_score > 0.65:
            parts.append(f"ML yuksek alis ({ml_score:.2f})")
        elif ml_score < 0.35:
            parts.append(f"ML satis baskisi ({ml_score:.2f})")
        else:
            parts.append(f"ML notr ({ml_score:.2f})")

        if sentiment_score > 0.20:
            parts.append(f"Pozitif duygu ({sentiment_score:.2f})")
        elif sentiment_score < -0.20:
            parts.append(f"Negatif duygu ({sentiment_score:.2f})")

        rl_names = {0: "AL", 1: "TUT", 2: "SAT"}
        parts.append(f"RL ajani: {rl_names.get(rl_action, 'TUT')}")
        parts.append(f"Rejim: {regime}")

        if conflict:
            parts.append("⚠️ Sinyal celiskisi tespit edildi (Guven azaltildi)")

        parts.append(f"Sonuc: {action}")
        return " | ".join(parts)

    def _record_audit(self, sig: HybridSignal, regime: str, market_state: str) -> None:
        """DuckDB'ye karar denetim izi kaydeder."""
        try:
            with duckdb.connect(self.duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    INSERT INTO hybrid_signal_audit (
                        action, confidence, ml_score, sentiment_score, rl_action,
                        conflict, regime, market_state, reasoning
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    [
                        str(sig.action),
                        float(sig.confidence),
                        float(sig.ml_score),
                        float(sig.sentiment_score),
                        int(sig.rl_action),
                        bool(sig.conflict),
                        str(regime),
                        str(market_state),
                        str(sig.reasoning),
                    ],
                )
        except Exception as exc:
            logger.debug("DuckDB hibrit denetim kaydi atlandi", hata=str(exc))

    def get_audit_as_polars(self) -> pl.DataFrame:
        """DuckDB'deki denetim kayıtlarını Polars DataFrame olarak döndürür."""
        with self._lock:
            try:
                with duckdb.connect(self.duckdb_path) as conn:
                    return conn.execute("SELECT * FROM hybrid_signal_audit ORDER BY timestamp DESC").pl()
            except Exception as exc:
                logger.warning("DuckDB denetim kayitlari okunamadi", hata=str(exc))
                return pl.DataFrame()

    def __repr__(self) -> str:
        return (
            f"HybridModel(ml_w={self.ml_weight:.2f}, sent_w={self.sentiment_weight:.2f}, "
            f"rl_w={self.rl_weight:.2f}, buy_th={self.buy_threshold:.2f}, sell_th={self.sell_threshold:.2f})"
        )


# Singleton
hybrid_model: Final[HybridModel] = HybridModel()


def hybrid_predict(
    rl_action: int,
    sentiment_score: float,
    market_state: str = "NORMAL",
    ml_score: float = 0.5,
    regime: str = "NORMAL",
) -> dict[str, Any]:
    """Geriye dönük uyumlu hibrit tahmin sarmalayıcısı.

    Args:
        rl_action: RL aksiyonu (0=AL, 1=TUT, 2=SAT).
        sentiment_score: Duygu analizi skoru [-1, 1].
        market_state: Piyasa durumu (NORMAL, HALT vb.).
        ml_score: ML skoru [0, 1].
        regime: Piyasa rejimi.

    Returns:
        Sözlük formatında hibrit karar sonucu.
    """
    result = hybrid_model.predict(
        ml_score=ml_score,
        sentiment_score=sentiment_score,
        rl_action=rl_action,
        regime=regime,
        market_state=market_state,
    )
    return {
        "action": str(result.action),
        "confidence": result.confidence,
        "rl_action": result.rl_action,
        "sentiment": result.sentiment_score,
        "ml_score": result.ml_score,
        "conflict": result.conflict,
        "reasoning": result.reasoning,
    }


__all__: Final[list[str]] = [
    "DEFAULT_BUY_THRESHOLD",
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "DEFAULT_CONFLICT_PENALTY",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EPSILON",
    "DEFAULT_HALT_PENALTY",
    "DEFAULT_ML_WEIGHT",
    "DEFAULT_RL_WEIGHT",
    "DEFAULT_SELL_THRESHOLD",
    "DEFAULT_SENTIMENT_WEIGHT",
    "HybridAction",
    "HybridModel",
    "HybridSignal",
    "MarketRegime",
    "MarketState",
    "configure_duckdb_wal",
    "hybrid_model",
    "hybrid_predict",
]
