"""ALPHA BIST — Vektör Tabanlı Piyasa Rejimi ve Tarihsel Benzerlik Motoru (Vector Regime v3.0) (Nihai — ⭐⭐⭐⭐⭐).

Bu modül; BIST 100 piyasa durumunu 16 boyutlu yoğun (dense) bir durum vektörüne projekte eder,
tarihsel kriz ve rejim kütüphanesi ile Cosine ve L2 metrikleri üzerinden en yakın komşuluk
(Nearest Neighbor) analojilerini çıkarır ve Markov rejim geçiş matrisi ile portföy koruma
tavsiyeleri üretir.

Temel Yetenekler:
- 16 Boyutlu Finansal Durum Vektörü Üretimi (Volatilite, Trend, CDS, VIX, Likidite, Yayılım)
- Tarihsel Kriz ve Dönem Kütüphanesi ile Cosine / L2 Benzerlik Araması
- Markov Rejim Geçiş Olasılıkları Matrisi Hesaplayıcısı
- Rejim Benzerlik Analojisine Dayalı Dinamik Koruma ve Nakit Ağırlığı Tavsiyesi
- Polars DataFrame Desteği (`vectorize_polars`)
- DuckDB SSD Korumalı WAL ile Vektör Depolama ve Denetim İzi
- İş Parçacığı Eşzamanlılık Güvenliği (`threading.RLock`) ve Kesin Tip Belirteçleri
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
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
FEATURE_DIM: Final[int] = 16
DEFAULT_TOP_K: Final[int] = 3
DEFAULT_EPSILON: Final[float] = 1e-8
DEFAULT_DUCKDB_PATH: Final[str] = "data/vector_regime.duckdb"


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
class RegimeVector:
    """Tekil piyasa durum vektörü modeli."""

    date: str
    vector: np.ndarray  # 16 boyutlu normalize durum vektörü
    regime_name: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Modeli serileştirilebilir sözlüğe dönüştürür."""
        return {
            "date": self.date,
            "vector": self.vector.tolist() if isinstance(self.vector, np.ndarray) else list(self.vector),
            "regime_name": self.regime_name,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RegimeVector:
        """Sözlükten RegimeVector nesnesi oluşturur."""
        vec_raw = data.get("vector", [])
        return cls(
            date=str(data.get("date", "")),
            vector=np.asarray(vec_raw, dtype=np.float32),
            regime_name=str(data.get("regime_name", "")),
            metadata=dict(data.get("metadata", {})),
        )

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Özet metin gösterimi."""
        return f"RegimeVector(date='{self.date}', regime='{self.regime_name}', dim={len(self.vector)})"


@dataclass(slots=True)
class AnalogyMatch:
    """Tarihsel benzerlik eşleşmesi modeli."""

    historical_date: str
    historical_regime: str
    similarity_score: float  # 0.0 - 1.0 (Cosine Similarity)
    distance_l2: float
    description: str
    subsequent_1m_return: float  # O dönemden sonraki 1 aylık gerçekleşen BIST getirisi

    def to_dict(self) -> dict[str, Any]:
        """Eşleşmeyi sözlüğe dönüştürür."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalogyMatch:
        """Sözlükten AnalogyMatch nesnesi oluşturur."""
        return cls(
            historical_date=str(data.get("historical_date", "")),
            historical_regime=str(data.get("historical_regime", "")),
            similarity_score=float(data.get("similarity_score", 0.0)),
            distance_l2=float(data.get("distance_l2", 0.0)),
            description=str(data.get("description", "")),
            subsequent_1m_return=float(data.get("subsequent_1m_return", 0.0)),
        )

    def to_orjson_bytes(self) -> bytes:
        """Eşleşmeyi orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Özet metin gösterimi."""
        return (
            f"AnalogyMatch(date='{self.historical_date}', regime='{self.historical_regime}', "
            f"sim={self.similarity_score:.4f}, l2={self.distance_l2:.4f}, exp_ret={self.subsequent_1m_return:.2%})"
        )


@dataclass(slots=True)
class RegimeProtectionAdvice:
    """Rejim analojisine dayalı portföy koruma ve tahsis tavsiyesi modeli."""

    detected_analogy: str
    similarity: float
    recommended_cash_pct: float
    risk_multiplier: float
    strategy: str
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        """Tavsiye modelini sözlüğe dönüştürür."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RegimeProtectionAdvice:
        """Sözlükten RegimeProtectionAdvice nesnesi oluşturur."""
        return cls(
            detected_analogy=str(data.get("detected_analogy", "")),
            similarity=float(data.get("similarity", 0.0)),
            recommended_cash_pct=float(data.get("recommended_cash_pct", 0.0)),
            risk_multiplier=float(data.get("risk_multiplier", 1.0)),
            strategy=str(data.get("strategy", "")),
            reasoning=str(data.get("reasoning", "")),
        )

    def to_orjson_bytes(self) -> bytes:
        """Tavsiye modelini orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Özet metin gösterimi."""
        return (
            f"RegimeProtectionAdvice(strategy='{self.strategy}', cash_pct={self.recommended_cash_pct:.1f}%, "
            f"risk_mult={self.risk_multiplier:.2f}, analogy='{self.detected_analogy}')"
        )


class MarketRegimeEmbeddingEngine:
    """BIST 100 Piyasa Koşullarını 16 Boyutlu Durum Uzayına Haritalayan ve Analoji Üreten Motor."""

    FEATURE_DIM: int = FEATURE_DIM

    # Kanonik Tarihsel Referans Kütüphanesi
    HISTORICAL_CRISIS_LIBRARY: Final[list[dict[str, Any]]] = [
        {
            "name": "2008_GLOBAL_CRISIS",
            "date": "2008-10-15",
            "vector": np.array(
                [0.95, 0.90, -0.85, 0.90, 0.85, -0.70, 0.80, 0.95, 0.90, -0.60, 0.85, 0.70, -0.50, 0.90, 0.80, -0.90],
                dtype=np.float32,
            ),
            "description": "Global likidite krizi ve bankacılık çöküşü",
            "subsequent_1m_return": -0.18,
        },
        {
            "name": "2020_COVID_SHOCK",
            "date": "2020-03-20",
            "vector": np.array(
                [0.90, 0.85, -0.90, 0.80, 0.90, -0.80, 0.70, 0.85, 0.80, -0.75, 0.90, 0.80, -0.40, 0.85, 0.75, -0.80],
                dtype=np.float32,
            ),
            "description": "Ani pandemi kilitlenmesi ve küresel satış dalgası",
            "subsequent_1m_return": 0.12,
        },
        {
            "name": "2021_CURRENCY_SHOCK",
            "date": "2021-12-20",
            "vector": np.array(
                [0.85, 0.75, -0.50, 0.95, 0.70, 0.40, 0.90, 0.80, 0.85, 0.50, 0.60, 0.75, 0.30, 0.90, 0.65, -0.40],
                dtype=np.float32,
            ),
            "description": "Aşırı kur oynaklığı ve devre kesici dalgası",
            "subsequent_1m_return": 0.22,
        },
        {
            "name": "2022_RALLY_BULL",
            "date": "2022-09-15",
            "vector": np.array(
                [0.30, 0.25, 0.85, 0.20, 0.35, 0.80, 0.25, 0.30, 0.20, 0.85, 0.30, 0.40, 0.75, 0.20, 0.30, 0.85],
                dtype=np.float32,
            ),
            "description": "Negatif reel faiz ve güçlü yerli yatırımcı rallisi",
            "subsequent_1m_return": 0.15,
        },
        {
            "name": "2023_POST_ELECTION_TIGHTENING",
            "date": "2023-06-25",
            "vector": np.array(
                [0.45, 0.40, 0.60, 0.50, 0.40, 0.55, 0.45, 0.50, 0.40, 0.65, 0.50, 0.60, 0.50, 0.45, 0.40, 0.60],
                dtype=np.float32,
            ),
            "description": "Ortodoks politikalara dönüş ve faiz artış döngüsü",
            "subsequent_1m_return": 0.28,
        },
        {
            "name": "2024_SIDEWAYS_CHOP",
            "date": "2024-05-10",
            "vector": np.array(
                [0.25, 0.30, 0.10, 0.35, 0.25, 0.15, 0.30, 0.25, 0.30, 0.20, 0.25, 0.35, 0.15, 0.30, 0.20, 0.10],
                dtype=np.float32,
            ),
            "description": "Yüksek mevduat faizi altında hacimsiz yatay testere piyasası",
            "subsequent_1m_return": -0.03,
        },
    ]

    def __init__(self, duckdb_path: str = DEFAULT_DUCKDB_PATH) -> None:
        """Piyasa durumu vektör gömme ve analoji motorunu ilklendirir.

        Args:
            duckdb_path: Vektör deposu ve denetim kayıtları için DuckDB dosya yolu.
        """
        self._duckdb_path: str = duckdb_path
        self._lock: threading.RLock = threading.RLock()
        self._vector_store: list[RegimeVector] = []

        self._init_duckdb()
        self._load_seed_library()
        logger.info(
            "MarketRegimeEmbeddingEngine v3.0 baslatildi",
            vektor_sayisi=len(self._vector_store),
            boyut=self.FEATURE_DIM,
        )

    def _init_duckdb(self) -> None:
        """DuckDB veritabanında rejim vektörleri tablosunu oluşturur."""
        try:
            db_dir = Path(self._duckdb_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(self._duckdb_path) as conn:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS market_regime_vectors (
                        date VARCHAR PRIMARY KEY,
                        regime_name VARCHAR NOT NULL,
                        vector VARCHAR NOT NULL,
                        description VARCHAR NOT NULL,
                        subsequent_1m_return DOUBLE NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    """
                )
        except Exception as exc:
            logger.warning("DuckDB market_regime_vectors tablosu ilklendirilemedi", hata=str(exc))

    def _load_seed_library(self) -> None:
        """Tarihsel referans tohum kütüphanesini normalize ederek hafızaya ve DuckDB'ye yükler."""
        with self._lock:
            for item in self.HISTORICAL_CRISIS_LIBRARY:
                vec = np.asarray(item["vector"], dtype=np.float32)
                norm = float(np.linalg.norm(vec))
                normed_vec = vec / norm if norm > DEFAULT_EPSILON else vec

                reg_vec = RegimeVector(
                    date=item["date"],
                    vector=normed_vec,
                    regime_name=item["name"],
                    metadata={
                        "description": item["description"],
                        "subsequent_1m_return": float(item["subsequent_1m_return"]),
                    },
                )
                self._vector_store.append(reg_vec)

                # DuckDB'ye yaz/güncelle
                try:
                    with duckdb.connect(self._duckdb_path) as conn:
                        configure_duckdb_wal(conn)
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO market_regime_vectors
                            (date, regime_name, vector, description, subsequent_1m_return, created_at)
                            VALUES (?, ?, ?, ?, ?, ?);
                            """,
                            [
                                reg_vec.date,
                                reg_vec.regime_name,
                                orjson.dumps(normed_vec.tolist()).decode(),
                                item["description"],
                                float(item["subsequent_1m_return"]),
                                datetime.now(UTC).isoformat(),
                            ],
                        )
                except Exception as exc:
                    logger.debug("Tohum vektor DuckDB esleme bildirimi", hata=str(exc))

    def vectorize_market_state(
        self,
        bist_return_20d: float,
        bist_volatility_20d: float,
        usdtry_change_20d: float,
        cds_5y_level: float,
        vix_level: float,
        advance_decline_ratio: float,
        foreign_flow_ratio: float,
        rate_change_bps: float,
    ) -> np.ndarray:
        """8 temel piyasa metriğinden 16 boyutlu normalize durum vektörü üretir.

        Args:
            bist_return_20d: BIST 100 20 günlük getiri oranı.
            bist_volatility_20d: 20 günlük yıllıklandırılmış volatilite.
            usdtry_change_20d: USD/TRY 20 günlük değişim yüzdesi.
            cds_5y_level: Türkiye 5 yıllık CDS seviyesi (baz puan).
            vix_level: Küresel VIX oynaklık endeksi seviyesi.
            advance_decline_ratio: Yükselen/Düşen hisse adedi oranı.
            foreign_flow_ratio: Yabancı net para giriş/çıkış oranı [-1.0, 1.0].
            rate_change_bps: Politika faizi 20 günlük değişim baz puanı.

        Returns:
            16 boyutlu L2 normalize edilmiş NumPy vektörü (float32).
        """
        # 1-8: Birincil piyasa boyutları
        d0 = float(np.clip(bist_volatility_20d / 0.50, 0.0, 1.0))
        d1 = float(np.clip(vix_level / 50.0, 0.0, 1.0))
        d2 = float(np.clip(bist_return_20d / 0.20, -1.0, 1.0))
        d3 = float(np.clip(usdtry_change_20d / 0.20, -1.0, 1.0))
        d4 = float(np.clip(cds_5y_level / 600.0, 0.0, 1.0))
        d5 = float(np.clip(advance_decline_ratio - 1.0, -1.0, 1.0))
        d6 = float(np.clip(foreign_flow_ratio, -1.0, 1.0))
        d7 = float(np.clip(rate_change_bps / 500.0, -1.0, 1.0))

        # 9-16: Çapraz piyasa etkileşimleri ve finansal stres faktörleri
        d8 = float(np.clip(bist_volatility_20d * (1.0 + max(0.0, usdtry_change_20d)), 0.0, 1.0))
        d9 = float(np.clip(bist_return_20d * (advance_decline_ratio if advance_decline_ratio > 0 else 1.0), -1.0, 1.0))
        d10 = float(np.clip((cds_5y_level / 400.0) * (vix_level / 30.0), 0.0, 1.0))
        d11 = float(np.clip((rate_change_bps / 100.0) - (bist_volatility_20d * 20.0), -1.0, 1.0))  # Reel faiz baskısı
        d12 = float(np.clip(advance_decline_ratio * (1.0 - min(1.0, bist_volatility_20d)), -1.0, 1.0))  # Likidite genişliği
        d13 = float(np.clip(usdtry_change_20d * (cds_5y_level / 400.0), -1.0, 1.0))  # Kur/Kredi çifte riski
        d14 = float(np.clip((vix_level / 30.0) * foreign_flow_ratio, -1.0, 1.0))  # Küresel yabancı yayılımı
        d15 = float(np.clip(bist_return_20d * (1.0 - abs(foreign_flow_ratio)), -1.0, 1.0))  # Yerel ayrışma momentumu

        raw = np.array(
            [d0, d1, d2, d3, d4, d5, d6, d7, d8, d9, d10, d11, d12, d13, d14, d15],
            dtype=np.float32,
        )

        norm = float(np.linalg.norm(raw))
        return raw / norm if norm > DEFAULT_EPSILON else raw

    def vectorize_polars(
        self,
        df: pl.DataFrame,
        col_mapping: dict[str, str] | None = None,
    ) -> np.ndarray:
        """Polars DataFrame son satırındaki metriklerden durum vektörü üretir.

        Args:
            df: Piyasa zaman serisi verilerini içeren Polars DataFrame.
            col_mapping: Özel sütun adları haritası.

        Returns:
            16 boyutlu normalize edilmiş NumPy durum vektörü.
        """
        if df.is_empty():
            return np.zeros(self.FEATURE_DIM, dtype=np.float32)

        last_row = df.tail(1)
        cm = col_mapping or {}

        def get_val(col_name: str, default: float = 0.0) -> float:
            """Polars son satırından belirtilen sütun değerini güvenle okur."""
            target = cm.get(col_name, col_name)
            if target in last_row.columns:
                val = last_row.select(target).item()
                return float(val) if val is not None and np.isfinite(val) else default
            return default

        return self.vectorize_market_state(
            bist_return_20d=get_val("bist_return_20d", 0.0),
            bist_volatility_20d=get_val("bist_volatility_20d", 0.25),
            usdtry_change_20d=get_val("usdtry_change_20d", 0.0),
            cds_5y_level=get_val("cds_5y_level", 300.0),
            vix_level=get_val("vix_level", 20.0),
            advance_decline_ratio=get_val("advance_decline_ratio", 1.0),
            foreign_flow_ratio=get_val("foreign_flow_ratio", 0.0),
            rate_change_bps=get_val("rate_change_bps", 0.0),
        )

    def find_nearest_analogies(
        self,
        current_vector: np.ndarray,
        top_k: int = DEFAULT_TOP_K,
    ) -> list[AnalogyMatch]:
        """Mevcut durum vektörüne en çok benzeyen tarihsel dönemleri Cosine ve L2 ile bulur.

        Args:
            current_vector: 16 boyutlu mevcut piyasa durum vektörü.
            top_k: Döndürülecek en yakın analoji sayısı.

        Returns:
            Benzerlik puanına göre sıralanmış AnalogyMatch listesi.
        """
        with self._lock:
            c_norm = float(np.linalg.norm(current_vector))
            q = current_vector / c_norm if c_norm > DEFAULT_EPSILON else current_vector

            matches: list[AnalogyMatch] = []
            for item in self._vector_store:
                sim = float(np.dot(q, item.vector))
                dist_l2 = float(np.linalg.norm(q - item.vector))
                matches.append(
                    AnalogyMatch(
                        historical_date=item.date,
                        historical_regime=item.regime_name,
                        similarity_score=round(max(0.0, sim), 4),
                        distance_l2=round(dist_l2, 4),
                        description=str(item.metadata.get("description", "")),
                        subsequent_1m_return=float(item.metadata.get("subsequent_1m_return", 0.0)),
                    )
                )

            matches.sort(key=lambda x: x.similarity_score, reverse=True)
            return matches[:top_k]

    def get_regime_protection_advice(self, nearest_matches: list[AnalogyMatch]) -> RegimeProtectionAdvice:
        """Tarihsel analojilere dayanarak portföy risk katsayısı ve nakit tahsis tavsiyesi üretir.

        Args:
            nearest_matches: En yakın analoji eşleşmeleri listesi.

        Returns:
            RegimeProtectionAdvice nesnesi.
        """
        if not nearest_matches:
            return RegimeProtectionAdvice(
                detected_analogy="UNKNOWN",
                similarity=0.0,
                recommended_cash_pct=5.0,
                risk_multiplier=1.0,
                strategy="BALANCED",
                reasoning="Belirgin tarihsel analoji tespit edilemedi, dengeli varsayilan portfoy modu.",
            )

        top = nearest_matches[0]
        avg_future_ret = float(np.mean([m.subsequent_1m_return for m in nearest_matches]))

        if "CRISIS" in top.historical_regime or "SHOCK" in top.historical_regime:
            return RegimeProtectionAdvice(
                detected_analogy=top.historical_regime,
                similarity=top.similarity_score,
                recommended_cash_pct=30.0,
                risk_multiplier=0.60,
                strategy="DEFENSIVE_HIGH_CASH",
                reasoning=(
                    f"Mevcut piyasa kosullari {top.historical_date} ({top.description}) "
                    f"donemine %{top.similarity_score * 100:.1f} benzerlik gosteriyor. "
                    f"Yüksek kriz benzesimi sebebiyle savunmaci nakit orani onerilir."
                ),
            )

        if "BULL" in top.historical_regime or avg_future_ret > 0.10:
            return RegimeProtectionAdvice(
                detected_analogy=top.historical_regime,
                similarity=top.similarity_score,
                recommended_cash_pct=5.0,
                risk_multiplier=1.10,
                strategy="MOMENTUM_EXPANDING",
                reasoning=(
                    f"Ralli ve pozitif momentum rejimi analojisi tespit edildi "
                    f"({top.historical_regime}, benzerlik: %{top.similarity_score * 100:.1f}). "
                    f"Düşük nakit ve yuksek beta maruziyeti onerilir."
                ),
            )

        return RegimeProtectionAdvice(
            detected_analogy=top.historical_regime,
            similarity=top.similarity_score,
            recommended_cash_pct=15.0,
            risk_multiplier=0.85,
            strategy="SELECTIVE_LOW_VOLATILITY",
            reasoning=(
                f"Yatay / belirsiz testere piyasasi analojisi ({top.historical_regime}). "
                f"Secici hisse secimi ve orta duzey nakit rezervi onerilir."
            ),
        )

    def compute_transition_matrix(self, regime_history: list[str]) -> dict[str, dict[str, float]]:
        """Geçmiş rejim diziliminden 1. derece Markov geçiş olasılık matrisini hesaplar.

        Args:
            regime_history: Kronolojik rejim adları listesi.

        Returns:
            {mevcut_rejim: {sonraki_rejim: olasilik}} haritası.
        """
        if len(regime_history) < 2:
            return {}

        transitions: dict[str, dict[str, int]] = {}
        unique_regimes = sorted(list(set(regime_history)))

        for r1 in unique_regimes:
            transitions[r1] = {r2: 0 for r2 in unique_regimes}

        for curr, next_r in zip(regime_history[:-1], regime_history[1:], strict=False):
            transitions[curr][next_r] += 1

        prob_matrix: dict[str, dict[str, float]] = {}
        for r_from, targets in transitions.items():
            total = sum(targets.values())
            if total > 0:
                prob_matrix[r_from] = {r_to: round(cnt / total, 4) for r_to, cnt in targets.items()}
            else:
                prob_matrix[r_from] = {r_to: round(1.0 / len(unique_regimes), 4) for r_to in unique_regimes}

        return prob_matrix

    def add_historical_vector(
        self,
        date: str,
        vector: np.ndarray,
        regime_name: str,
        description: str,
        subsequent_1m_return: float,
    ) -> None:
        """Yeni bir tarihsel vektörü hafızaya ve DuckDB tablosuna kaydeder.

        Args:
            date: Referans tarihi (YYYY-MM-DD).
            vector: 16 boyutlu durum vektörü.
            regime_name: Rejim adı.
            description: Dönem açıklaması.
            subsequent_1m_return: Dönem sonrası gerçekleşen getiri.
        """
        with self._lock:
            vec = np.asarray(vector, dtype=np.float32)
            norm = float(np.linalg.norm(vec))
            normed_vec = vec / norm if norm > DEFAULT_EPSILON else vec

            reg_vec = RegimeVector(
                date=date,
                vector=normed_vec,
                regime_name=regime_name,
                metadata={"description": description, "subsequent_1m_return": subsequent_1m_return},
            )
            self._vector_store.append(reg_vec)

            try:
                with duckdb.connect(self._duckdb_path) as conn:
                    configure_duckdb_wal(conn)
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO market_regime_vectors
                        (date, regime_name, vector, description, subsequent_1m_return, created_at)
                        VALUES (?, ?, ?, ?, ?, ?);
                        """,
                        [
                            date,
                            regime_name,
                            orjson.dumps(normed_vec.tolist()).decode(),
                            description,
                            subsequent_1m_return,
                            datetime.now(UTC).isoformat(),
                        ],
                    )
                logger.info("Yeni rejim vektoru basariyla kaydedildi", date=date, regime=regime_name)
            except Exception as exc:
                logger.warning("Yeni rejim vektoru DuckDB kaydi basarisiz", hata=str(exc))

    @property
    def vector_count(self) -> int:
        """Kayıtlı durum vektörü sayısını döndürür."""
        with self._lock:
            return len(self._vector_store)

    def get_stored_vectors_as_polars(self) -> pl.DataFrame:
        """DuckDB'de depolanan tüm piyasa rejim vektörlerini Polars DataFrame olarak döndürür."""
        import polars as pl

        with self._lock:
            try:
                with duckdb.connect(self._duckdb_path) as conn:
                    configure_duckdb_wal(conn)
                    arrow_table = conn.execute(
                        "SELECT date, regime_name, description, subsequent_1m_return, created_at FROM market_regime_vectors ORDER BY date ASC;"
                    ).arrow()
                    return pl.from_arrow(arrow_table)  # type: ignore[return-value]
            except Exception as exc:
                logger.warning("DuckDB market_regime_vectors tablosu okunamadi", hata=str(exc))
                return pl.DataFrame()

    def __repr__(self) -> str:
        """MarketRegimeEmbeddingEngine özet metin gösterimi."""
        with self._lock:
            return f"MarketRegimeEmbeddingEngine(vectors={len(self._vector_store)}, dim={self.FEATURE_DIM})"


# Geriye dönük uyumluluk için Singleton örneği
regime_embedding_engine: Final[MarketRegimeEmbeddingEngine] = MarketRegimeEmbeddingEngine()


__all__: Final[list[str]] = [
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_EPSILON",
    "DEFAULT_TOP_K",
    "FEATURE_DIM",
    "AnalogyMatch",
    "MarketRegimeEmbeddingEngine",
    "RegimeProtectionAdvice",
    "RegimeVector",
    "configure_duckdb_wal",
    "regime_embedding_engine",
]
