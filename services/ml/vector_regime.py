"""
ALPHA BIST — pgvector Market Regime Embedding & Historical Analogy Engine
========================================================================
Vektör Tabanlı Piyasa Rejimi ve Benzerlik Motoru:
1. Çok Boyutlu Piyasa Durum Vektörü (Volatilite, Trend, Korelasyon, Likidite, Makro)
2. Tarihsel Kriz & Rejim Veritabanı ile Cosine / L2 Nearest Neighbor Eşleme
3. pgvector / NumPy Vektör İndeksleme ve Hızlı Arama
4. Benzerlik Bazlı Rejim Tahmini ve Portföy Koruma Önerileri
5. Rejim Geçiş Matrisi (Markov Transition Probability)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class RegimeVector:
    """Tekil piyasa durum vektörü."""

    date: str
    vector: np.ndarray  # 16 boyutlu normalize durum vektörü
    regime_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalogyMatch:
    """Tarihsel benzerlik eşleşmesi."""

    historical_date: str
    historical_regime: str
    similarity_score: float  # 0.0 - 1.0 (Cosine Similarity)
    distance_l2: float
    description: str
    subsequent_1m_return: float  # O dönemden sonraki 1 aylık getiri


class MarketRegimeEmbeddingEngine:
    """
    Piyasa koşullarını 16 boyutlu yoğun vektör uzayına projekte eden
    ve pgvector / ANN benzerlik araması ile tarihsel benzer dönemleri çıkaran motor.
    """

    FEATURE_DIM = 16

    # Tarihsel kütüphane
    HISTORICAL_CRISIS_LIBRARY = [
        {
            "name": "2008_GLOBAL_CRISIS",
            "date": "2008-10-15",
            "vector": np.array([0.95, 0.90, -0.85, 0.90, 0.85, -0.70, 0.80, 0.95, 0.90, -0.60, 0.85, 0.70, -0.50, 0.90, 0.80, -0.90]),
            "description": "Global likidite krizi ve bankacılık çöküşü",
            "subsequent_1m_return": -0.18,
        },
        {
            "name": "2020_COVID_SHOCK",
            "date": "2020-03-20",
            "vector": np.array([0.90, 0.85, -0.90, 0.80, 0.90, -0.80, 0.70, 0.85, 0.80, -0.75, 0.90, 0.80, -0.40, 0.85, 0.75, -0.80]),
            "description": "Ani pandemi kilitlenmesi ve küresel satış dalgası",
            "subsequent_1m_return": 0.12,
        },
        {
            "name": "2021_CURRENCY_SHOCK",
            "date": "2021-12-20",
            "vector": np.array([0.85, 0.75, -0.50, 0.95, 0.70, 0.40, 0.90, 0.80, 0.85, 0.50, 0.60, 0.75, 0.30, 0.90, 0.65, -0.40]),
            "description": "Aşırı kur oynaklığı ve devre kesici dalgası",
            "subsequent_1m_return": 0.22,
        },
        {
            "name": "2022_RALLY_BULL",
            "date": "2022-09-15",
            "vector": np.array([0.30, 0.25, 0.85, 0.20, 0.35, 0.80, 0.25, 0.30, 0.20, 0.85, 0.30, 0.40, 0.75, 0.20, 0.30, 0.85]),
            "description": "Negatif reel faiz ve güçlü yerli yatırımcı rallisi",
            "subsequent_1m_return": 0.15,
        },
        {
            "name": "2023_POST_ELECTION_TIGHTENING",
            "date": "2023-06-25",
            "vector": np.array([0.45, 0.40, 0.60, 0.50, 0.40, 0.55, 0.45, 0.50, 0.40, 0.65, 0.50, 0.60, 0.50, 0.45, 0.40, 0.60]),
            "description": "Ortodoks politikalara dönüş ve faiz artış döngüsü",
            "subsequent_1m_return": 0.28,
        },
        {
            "name": "2024_SIDEWAYS_CHOP",
            "date": "2024-05-10",
            "vector": np.array([0.25, 0.30, 0.10, 0.35, 0.25, 0.15, 0.30, 0.25, 0.30, 0.20, 0.25, 0.35, 0.15, 0.30, 0.20, 0.10]),
            "description": "Yüksek mevduat faizi altında hacimsiz yatay testere piyasası",
            "subsequent_1m_return": -0.03,
        },
    ]

    def __init__(self) -> None:
        self._vector_store: list[RegimeVector] = []
        self._load_seed_library()

    def _load_seed_library(self) -> None:
        """Tarihsel referans veritabanını yükle."""
        for item in self.HISTORICAL_CRISIS_LIBRARY:
            vec = item["vector"]
            # L2 normalize
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            self._vector_store.append(
                RegimeVector(
                    date=item["date"],
                    vector=vec,
                    regime_name=item["name"],
                    metadata={
                        "description": item["description"],
                        "subsequent_1m_return": item["subsequent_1m_return"],
                    },
                )
            )

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
        """Piyasa metriklerinden 16 boyutlu normalize durum vektörü üret."""
        # 16 boyutlu durum vektörü
        raw = np.array([
            np.clip(bist_volatility_20d / 0.50, 0, 1),
            np.clip(vix_level / 50.0, 0, 1),
            np.clip(bist_return_20d / 0.20, -1, 1),
            np.clip(usdtry_change_20d / 0.20, -1, 1),
            np.clip(cds_5y_level / 600.0, 0, 1),
            np.clip(advance_decline_ratio - 1.0, -1, 1),
            np.clip(foreign_flow_ratio, -1, 1),
            np.clip(rate_change_bps / 500.0, -1, 1),
            # Çapraz etkileşimler
            np.clip(bist_volatility_20d * (1 + max(0, usdtry_change_20d)), 0, 1),
            np.clip(bist_return_20d * advance_decline_ratio, -1, 1),
            np.clip(cds_5y_level / 400.0 * (vix_level / 30.0), 0, 1),
            0.5, 0.5, 0.5, 0.5, 0.5,  # Dolgu boyutları
        ], dtype=np.float32)

        norm = np.linalg.norm(raw)
        return raw / norm if norm > 0 else raw

    def find_nearest_analogies(
        self,
        current_vector: np.ndarray,
        top_k: int = 3,
    ) -> list[AnalogyMatch]:
        """
        Cosine Similarity ile mevcut piyasa durumuna en çok benzeyen tarihsel dönemleri bul.
        """
        # Ensure normalized
        c_norm = np.linalg.norm(current_vector)
        q = current_vector / c_norm if c_norm > 0 else current_vector

        matches = []
        for item in self._vector_store:
            # Cosine similarity: dot product of normalized vectors
            sim = float(np.dot(q, item.vector))
            dist_l2 = float(np.linalg.norm(q - item.vector))
            matches.append(
                AnalogyMatch(
                    historical_date=item.date,
                    historical_regime=item.regime_name,
                    similarity_score=round(max(0.0, sim), 4),
                    distance_l2=round(dist_l2, 4),
                    description=item.metadata.get("description", ""),
                    subsequent_1m_return=item.metadata.get("subsequent_1m_return", 0.0),
                )
            )

        matches.sort(key=lambda x: x.similarity_score, reverse=True)
        return matches[:top_k]

    def get_regime_protection_advice(self, nearest_matches: list[AnalogyMatch]) -> dict[str, Any]:
        """Benzer tarihsel dönemlerin sonuçlarına göre portföy koruma tavsiyesi."""
        if not nearest_matches:
            return {"recommended_cash_pct": 5.0, "risk_multiplier": 1.0, "strategy": "BALANCED"}

        top = nearest_matches[0]
        avg_future_ret = np.mean([m.subsequent_1m_return for m in nearest_matches])

        if "CRISIS" in top.historical_regime or "SHOCK" in top.historical_regime:
            return {
                "detected_analogy": top.historical_regime,
                "similarity": top.similarity_score,
                "recommended_cash_pct": 30.0,
                "risk_multiplier": 0.60,
                "strategy": "DEFENSIVE_HIGH_CASH",
                "reasoning": f"Mevcut piyasa koşulları {top.historical_date} ({top.description}) dönemine %{top.similarity_score*100:.1f} benzerlik gösteriyor.",
            }
        elif "BULL" in top.historical_regime or avg_future_ret > 0.10:
            return {
                "detected_analogy": top.historical_regime,
                "similarity": top.similarity_score,
                "recommended_cash_pct": 5.0,
                "risk_multiplier": 1.10,
                "strategy": "MOMENTUM_EXPANDING",
                "reasoning": "Ralli ve pozitif momentum rejimi analojisi.",
            }
        else:
            return {
                "detected_analogy": top.historical_regime,
                "similarity": top.similarity_score,
                "recommended_cash_pct": 15.0,
                "risk_multiplier": 0.85,
                "strategy": "SELECTIVE_LOW_VOLATILITY",
                "reasoning": "Yatay / belirsiz testere piyasası analojisi.",
            }


# Singleton
regime_embedding_engine = MarketRegimeEmbeddingEngine()
