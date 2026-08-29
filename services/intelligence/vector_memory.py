"""
ALPHA BIST — pgvector & Vector Memory Store v2.0
Semantik Vektör Benzerlik Arama & Rejim Belleği

Özellikler:
1. pgvector (PostgreSQL <-> cosine distance) desteği ile haber, KAP ve rejim embedding'leri
2. PostgreSQL offline iken dahili NumPy L2 / Cosine Similarity fallback motoru (Disk tabanlı JSON yedeklemeli)
3. Rejim Eşleştirme: "Geçmişte bu piyasa rejimine / V-Dip hareketine benzeyen anlar hangileriydi?"
4. Olay & Haber Eşleştirme: KAP duyuruları ve makro şokların tarihsel benzerlik taraması
5. Enterprise Connection Pool Entegrasyonu ve Bulk Upsert (store_embeddings_batch) desteği
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import structlog

from services.core.database import db_router

logger = structlog.get_logger()

# Fallback dosya yolu
FALLBACK_FILE = Path("data/vector_fallback.json")


@dataclass
class VectorRecord:
    """Vektör hafıza kaydı."""

    item_id: str
    category: str  # 'regime', 'kap_news', 'macro_event', 'model_feature'
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)
    text_content: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class SimilarityResult:
    """Benzerlik arama sonucu."""

    item_id: str
    category: str
    score: float  # Cosine similarity [0.0 - 1.0] (1.0 = birebir aynı)
    distance: float  # Cosine distance [0.0 - 2.0]
    metadata: dict[str, Any]
    text_content: str
    timestamp: str


class VectorMemoryStore:
    """pgvector destekli ve NumPy fallback'li çok amaçlı vektör deposu."""

    def __init__(self, fallback_path: Path = FALLBACK_FILE):
        """Otomatik eklendi."""
        self.fallback_path = fallback_path
        self._local_records: dict[str, VectorRecord] = {}
        self._load_fallback()

    def _load_fallback(self) -> Any:
        """Diskteki local fallback verisini yükler."""
        if not self.fallback_path.exists():
            return
        try:
            with open(self.fallback_path, encoding="utf-8") as f:
                data = orjson.loads(f.read())
                for k, v in data.items():
                    self._local_records[k] = VectorRecord(**v)
            logger.info("Vector local fallback loaded", count=len(self._local_records))
        except Exception as e:
            logger.error("Failed to load vector fallback", error=str(e))

    def _save_fallback(self) -> Any:
        """Yerel fallback verisini diske kaydeder (Fail-safe)."""
        try:
            self.fallback_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.fallback_path.with_suffix(".tmp")

            dump_data = {k: asdict(v) for k, v in self._local_records.items()}
            with open(temp_path, "wb") as f:
                f.write(orjson.dumps(dump_data))

            temp_path.replace(self.fallback_path)
        except Exception as e:
            logger.error("Failed to save vector fallback", error=str(e))

    def _cosine_similarity(self, v1: list[float] | np.ndarray, v2: list[float] | np.ndarray) -> float:
        """İki vektör arası cosine benzerliği hesapla."""
        a = np.asarray(v1, dtype=np.float32)
        b = np.asarray(v2, dtype=np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    async def store_embedding(
        self,
        item_id: str,
        category: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
        text_content: str = "",
    ) -> bool:
        """Tekil vektör embedding kaydet."""
        record = VectorRecord(
            item_id=item_id,
            category=category,
            embedding=[float(x) for x in embedding],
            metadata=metadata or {},
            text_content=text_content,
        )

        # Yerel hafızaya kaydet
        self._local_records[f"{category}:{item_id}"] = record
        self._save_fallback()

        # PostgreSQL / pgvector
        try:
            async with db_router.write() as conn:
                emb_str = f"[{','.join(str(x) for x in record.embedding)}]"
                query = """
                INSERT INTO market_event_embeddings (item_id, category, embedding, metadata, text_content, created_at, updated_at)
                VALUES ($1, $2, $3::vector, $4::jsonb, $5, NOW(), NOW())
                ON CONFLICT (item_id, category)
                DO UPDATE SET embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata, text_content = EXCLUDED.text_content, updated_at = NOW();
                """
                await conn.execute(
                    query, item_id, category, emb_str, orjson.dumps(record.metadata).decode("utf-8"), text_content
                )
        except Exception as e:
            logger.warning("pgvector write skipped, stored in local fallback", error=str(e), item_id=item_id)

        return True

    async def store_embeddings_batch(
        self,
        records: list[tuple[str, str, list[float], dict[str, Any], str]],
    ) -> bool:
        """
        Toplu (bulk) kayıt atma.
        records formatı: [(item_id, category, embedding, metadata, text_content), ...]
        """
        if not records:
            return True

        # Yerel hafızayı güncelle
        for r in records:
            item_id, category, embedding, meta, txt = r
            vr = VectorRecord(
                item_id=item_id,
                category=category,
                embedding=[float(x) for x in embedding],
                metadata=meta or {},
                text_content=txt,
            )
            self._local_records[f"{category}:{item_id}"] = vr

        self._save_fallback()

        # PostgreSQL / pgvector Bulk Insert
        try:
            async with db_router.write_transaction() as conn:
                # asyncpg executemany requires properly ordered arguments
                # For vector type, we must stringify lists of floats
                values = []
                for r in records:
                    item_id, category, embedding, meta, txt = r
                    emb_str = f"[{','.join(str(x) for x in embedding)}]"
                    meta_json = orjson.dumps(meta or {}).decode("utf-8")
                    values.append((item_id, category, emb_str, meta_json, txt))

                query = """
                INSERT INTO market_event_embeddings (item_id, category, embedding, metadata, text_content, created_at, updated_at)
                VALUES ($1, $2, $3::vector, $4::jsonb, $5, NOW(), NOW())
                ON CONFLICT (item_id, category)
                DO UPDATE SET embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata, text_content = EXCLUDED.text_content, updated_at = NOW();
                """
                await conn.executemany(query, values)
        except Exception as e:
            logger.warning("pgvector bulk write skipped, stored in local fallback", error=str(e), count=len(records))

        return True

    async def search_similar(
        self,
        query_embedding: list[float],
        category: str | None = None,
        top_k: int = 5,
        min_similarity: float = 0.0,
    ) -> list[SimilarityResult]:
        """En yakın vektörleri getir."""
        query_vec = np.asarray(query_embedding, dtype=np.float32)

        # PostgreSQL pgvector araması
        try:
            async with db_router.read() as conn:
                emb_str = f"[{','.join(str(x) for x in query_vec)}]"

                if category:
                    sql = f"""
                    SELECT item_id, category, 1 - (embedding <=> $1::vector) AS similarity,
                           (embedding <=> $1::vector) AS distance, metadata, text_content, created_at
                    FROM market_event_embeddings
                    WHERE category = $2
                    ORDER BY embedding <=> $1::vector ASC
                    LIMIT {top_k};
                    """
                    rows = await conn.fetch(sql, emb_str, category)
                else:
                    sql = f"""
                    SELECT item_id, category, 1 - (embedding <=> $1::vector) AS similarity,
                           (embedding <=> $1::vector) AS distance, metadata, text_content, created_at
                    FROM market_event_embeddings
                    ORDER BY embedding <=> $1::vector ASC
                    LIMIT {top_k};
                    """
                    rows = await conn.fetch(sql, emb_str)

                if rows:
                    results = []
                    for r in rows:
                        sim = float(r["similarity"])
                        if sim >= min_similarity:
                            # asyncpg can return strings or parsed JSON based on configuration, safe parse:
                            meta = r["metadata"]
                            if isinstance(meta, str):
                                meta = orjson.loads(meta)

                            results.append(
                                SimilarityResult(
                                    item_id=r["item_id"],
                                    category=r["category"],
                                    score=round(sim, 4),
                                    distance=round(float(r["distance"]), 4),
                                    metadata=meta or {},
                                    text_content=r["text_content"] or "",
                                    timestamp=str(r["created_at"]),
                                )
                            )
                    return results
        except Exception as e:
            logger.warning("pgvector query fallback to local memory", error=str(e))

        # In-Memory Cosine Similarity Fallback
        results: list[SimilarityResult] = []
        for key, rec in self._local_records.items():
            if category and rec.category != category:
                continue
            if len(rec.embedding) != len(query_vec):
                continue

            sim = self._cosine_similarity(query_vec, rec.embedding)
            if sim >= min_similarity:
                results.append(
                    SimilarityResult(
                        item_id=rec.item_id,
                        category=rec.category,
                        score=round(sim, 4),
                        distance=round(max(0.0, 1.0 - sim), 4),
                        metadata=rec.metadata,
                        text_content=rec.text_content,
                        timestamp=rec.timestamp,
                    )
                )

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]


class MarketRegimeMemory:
    """Piyasa rejimi ve tarihsel kriz / trend benzerlik motoru."""

    def __init__(self, vector_store: VectorMemoryStore | None = None):
        """Otomatik eklendi."""
        self.store = vector_store or VectorMemoryStore()

    async def record_regime_fingerprint(
        self,
        regime_id: str,
        regime_name: str,
        features_vector: list[float],
        characteristics: dict[str, Any],
    ) -> bool:
        """Piyasa rejimi vektör parmak izini kaydet."""
        meta = {
            "regime_name": regime_name,
            "characteristics": characteristics,
        }
        return await self.store.store_embedding(
            item_id=regime_id,
            category="regime",
            embedding=features_vector,
            metadata=meta,
            text_content=f"Regime: {regime_name} | {characteristics.get('description', '')}",
        )

    async def find_analogous_regimes(
        self,
        current_features_vector: list[float],
        top_k: int = 3,
    ) -> list[SimilarityResult]:
        """Şu anki piyasa dinamiklerine en çok benzeyen geçmiş rejimleri bul."""
        return await self.store.search_similar(
            query_embedding=current_features_vector,
            category="regime",
            top_k=top_k,
            min_similarity=0.5,
        )


# Singleton
vector_memory_store = VectorMemoryStore()
market_regime_memory = MarketRegimeMemory(vector_memory_store)
