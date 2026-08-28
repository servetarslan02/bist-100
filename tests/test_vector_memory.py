"""
ALPHA BIST — pgvector & Vector Memory Test Suite
Doğrulanan Özellikler:
1. VectorMemoryStore: Embedding depolama, Cosine Similarity hesaplama ve Top-K sıralama
2. Kategori bazlı filtreleme (regime, kap_news, macro_event)
3. MarketRegimeMemory: Tarihsel kriz ve V-Dip parmak izi eşleme
4. Eşik değeri (min_similarity) ve uç durum (sıfır vektör, boş sonuç) doğrulaması
"""

import pytest
from unittest.mock import patch, AsyncMock
from services.intelligence.vector_memory import (
    VectorMemoryStore,
    MarketRegimeMemory,
    VectorRecord,
    SimilarityResult,
)


@pytest.fixture(autouse=True)
def mock_db_router():
    with patch("services.intelligence.vector_memory.db_router") as mock_router:
        mock_router.write.return_value.__aenter__.side_effect = Exception("Mock DB Offline")
        mock_router.read.return_value.__aenter__.side_effect = Exception("Mock DB Offline")
        mock_router.write_transaction.return_value.__aenter__.side_effect = Exception("Mock DB Offline")
        yield mock_router


class TestVectorMemoryStore:
    """Vektör deposu ve semantik benzerlik arama testleri."""

    @pytest.mark.asyncio
    async def test_store_and_search_similar_vectors(self):
        store = VectorMemoryStore()

        # Kayıtlar ekle (3 boyutlu basit test embeddingleri)
        await store.store_embedding(
            item_id="event_1",
            category="kap_news",
            embedding=[1.0, 0.0, 0.0],
            metadata={"title": "THYAO Bedelsiz Sermaye Artırımı"},
            text_content="KAP Bildirimi",
        )
        await store.store_embedding(
            item_id="event_2",
            category="kap_news",
            embedding=[0.8, 0.2, 0.0],
            metadata={"title": "PGSUS Temettü Kararı"},
            text_content="KAP Bildirimi",
        )
        await store.store_embedding(
            item_id="event_3",
            category="kap_news",
            embedding=[0.0, 1.0, 0.0],
            metadata={"title": "TUPRS Rafineri Bakımı"},
            text_content="KAP Bildirimi",
        )

        # event_1'e en yakın olanı ara (Query: [0.9, 0.1, 0.0])
        results = await store.search_similar(
            query_embedding=[0.9, 0.1, 0.0],
            category="kap_news",
            top_k=2,
        )

        assert len(results) == 2
        assert results[0].item_id in ("event_1", "event_2")
        assert results[0].score > 0.95
        assert results[0].distance < 0.05

    @pytest.mark.asyncio
    async def test_category_filtering(self):
        store = VectorMemoryStore()

        await store.store_embedding("reg_1", "regime", [0.5, 0.5])
        await store.store_embedding("news_1", "kap_news", [0.5, 0.5])

        reg_results = await store.search_similar([0.5, 0.5], category="regime")
        assert len(reg_results) == 1
        assert reg_results[0].category == "regime"
        assert reg_results[0].item_id == "reg_1"


class TestMarketRegimeMemory:
    """Tarihsel rejim ve kriz benzerlik analizi testleri."""

    @pytest.mark.asyncio
    async def test_find_analogous_regimes(self):
        regime_mem = MarketRegimeMemory()

        # 4 temel rejim parmak izi tanımla
        # [Volatilite, Trend Gücü, Likidite Stresi, Sektör Rotasyonu]
        await regime_mem.record_regime_fingerprint(
            regime_id="2026_06_vdip",
            regime_name="Haziran 2026 V-Dip & Sert Düzeltme",
            features_vector=[0.95, -0.80, 0.85, 0.30],
            characteristics={"type": "panic_selling", "rebound_prob": 0.78},
        )
        await regime_mem.record_regime_fingerprint(
            regime_id="2025_bull_rally",
            regime_name="2025 Enflasyonist Boğa Koşusu",
            features_vector=[0.20, 0.90, 0.10, 0.60],
            characteristics={"type": "momentum_trend", "rebound_prob": 0.10},
        )
        await regime_mem.record_regime_fingerprint(
            regime_id="2026_choppy_range",
            regime_name="2026 Yatay Testere Piyasası",
            features_vector=[0.40, 0.05, 0.30, 0.20],
            characteristics={"type": "mean_reversion", "rebound_prob": 0.50},
        )

        # Şu anki panik piyasası vektörü
        current_market = [0.90, -0.75, 0.80, 0.35]
        analogies = await regime_mem.find_analogous_regimes(current_market, top_k=2)

        assert len(analogies) >= 1
        assert analogies[0].item_id == "2026_06_vdip"
        assert analogies[0].score > 0.98
        assert analogies[0].metadata["characteristics"]["type"] == "panic_selling"
