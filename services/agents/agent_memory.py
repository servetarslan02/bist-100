"""
ALPHA BIST — Agent Memory System v2.0

3 katmanlı hafıza (arXiv Agentic Trading 2026 meta-analiz):
1. Working Memory — anlık bağlam (son 100 görev)
2. Episodic Memory — geçmiş olaylar (önemli olaylar + outcome tracking)
3. Semantic Memory — bilgi grafiği (öğrenilen kalıplar)

Memory consolidation periyodik yapılır.

FAZ 3: Agent Memory
"""

import gzip
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import orjson
import structlog

# Import at module level to avoid repeated import cost and circular import risk
try:
    from services.core.debounce import should_save
except ImportError:
    # Fallback: her zaman kaydet
    def should_save(_key: str, _interval: int) -> bool:
        return True


logger = structlog.get_logger()


@dataclass
class MemoryEntry:
    """Tek hafıza kaydı.

    Her bir agent görevi için oluşturulan hafıza kaydı.
    Working ve episodic memory'de kullanılır.
    """

    task_id: str
    agent_role: str
    ticker: str
    direction: str
    confidence: float
    reasoning: str
    timestamp: str
    outcome: dict | None = None
    expires_at: str | None = None  # ISO format, None = süresiz

    def is_expired(self) -> bool:
        """Kayıt süresi dolmuş mu?"""
        if self.expires_at is None:
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            return datetime.now(UTC) > exp
        except (ValueError, TypeError):
            return False

    def to_dict(self) -> dict[str, Any]:
        """Dict'e çevir (serialization için)."""
        d = {
            "task_id": self.task_id,
            "agent_role": self.agent_role,
            "ticker": self.ticker,
            "direction": self.direction,
            "confidence": self.confidence,
            "reasoning": self.reasoning[:300],
            "timestamp": self.timestamp,
            "outcome": self.outcome,
        }
        if self.expires_at:
            d["expires_at"] = self.expires_at
        return d


class WorkingMemory:
    """Anlık bağlam — son N görev.

    Amaç: Agent'ın yakın geçmişini bilmesi (varsayılan son 100 görev).
    Hızlı erişim, kısa süreli. deque kullanarak O(1) ekleme/silme.
    """

    def __init__(self, max_items: int = 100, ttl_hours: int = 24):
        self.items: deque[MemoryEntry] = deque(maxlen=max_items)
        self.max_items = max_items
        self._ttl_hours = ttl_hours

    def add(self, entry: MemoryEntry) -> None:
        """Görev ekle. TTL otomatik atanır. maxlen dolunca eski kayıt silinir."""
        if entry.expires_at is None:
            entry.expires_at = (datetime.now(UTC) + timedelta(hours=self._ttl_hours)).isoformat()
        self.items.append(entry)

    def cleanup_expired(self) -> int:
        """Süresi dolan kayıtları temizle. Silinen kayıt sayısı döner."""
        before = len(self.items)
        self.items = deque(
            [e for e in self.items if not e.is_expired()],
            maxlen=self.max_items,
        )
        return before - len(self.items)

    def get_recent(
        self,
        ticker: str | None = None,
        agent_role: str | None = None,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Son görevleri getir (opsiyonel filtre ile)."""
        filtered = self.items
        if ticker:
            filtered = [e for e in filtered if e.ticker == ticker]
        if agent_role:
            filtered = [e for e in filtered if e.agent_role == agent_role]
        return list(filtered)[-limit:]

    def get_last_direction(self, ticker: str) -> str | None:
        """Son yön kararını getir."""
        for entry in reversed(self.items):
            if entry.ticker == ticker:
                return entry.direction
        return None

    def clear(self) -> None:
        """Working memory'yi temizle."""
        self.items.clear()

    def to_dict(self) -> dict[str, Any]:
        """Serialization için dict'e çevir."""
        return {
            "count": len(self.items),
            "items": [e.to_dict() for e in list(self.items)[-10:]],  # Son 10
        }


class EpisodicMemory:
    """Geçmiş olaylar — outcome tracking ile.

    Amaç: Önemli olayları hatırlamak, doğruluk takibi yapmak.
    Uzun süreli, outcome odaklı.
    """

    def __init__(self, max_items: int = 1000, min_confidence_for_episode: float = 0.6, ttl_days: int = 30):
        self.episodes: deque[MemoryEntry] = deque(maxlen=max_items)
        self.outcomes: dict[str, dict] = {}  # task_id → outcome
        self.accuracy_by_regime: dict[str, list[float]] = {}
        self.accuracy_by_ticker: dict[str, list[float]] = {}
        self.max_items = max_items
        self._min_confidence = min_confidence_for_episode
        self._ttl_days = ttl_days
        # Hızlı task_id araması için indeks
        self._episode_index: dict[str, MemoryEntry] = {}

    def add(self, entry: MemoryEntry) -> None:
        """Önemli olay ekle.

        Sadece yüksek güven (>0.6) veya NO_TRADE yönündeki olayları kaydeder.
        TTL otomatik atanır.
        """
        if entry.confidence > self._min_confidence or entry.direction == "NO_TRADE":
            if entry.expires_at is None:
                entry.expires_at = (datetime.now(UTC) + timedelta(days=self._ttl_days)).isoformat()
            self.episodes.append(entry)
            self._episode_index[entry.task_id] = entry

    def cleanup_expired(self) -> int:
        """Süresi dolan kayıtları temizle. Silinen kayıt sayısı döner."""
        before = len(self.episodes)
        expired_ids = [e.task_id for e in self.episodes if e.is_expired()]
        self.episodes = deque(
            [e for e in self.episodes if not e.is_expired()],
            maxlen=self.max_items,
        )
        for tid in expired_ids:
            self._episode_index.pop(tid, None)
        for tid in expired_ids:
            self.outcomes.pop(tid, None)
        return before - len(self.episodes)

    def record_outcome(
        self,
        task_id: str,
        actual_return: float,
        regime: str = "UNKNOWN",
        holding_days: int = 1,
    ) -> None:
        """Sonuç kaydet — accuracy tracking.

        Predicted direction ile actual_return karşılaştırarak doğruluk hesaplar.
        """
        episode = self._episode_index.get(task_id)
        if not episode:
            return

        predicted = episode.direction
        # NO_TRADE tahmini her zaman "doğru" sayılır (risk almamak = korunma)
        if predicted == "NO_TRADE":
            correct = True
        elif predicted == "NEUTRAL":
            correct = abs(actual_return) < 2.0  # Küçük hareket = doğru tahmin
        else:
            correct = (predicted == "LONG" and actual_return > 0) or (predicted == "SHORT" and actual_return < 0)

        self.outcomes[task_id] = {
            "predicted": predicted,
            "actual_return": actual_return,
            "correct": correct,
            "regime": regime,
            "holding_days": holding_days,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        # Rejim bazlı doğruluk
        if regime not in self.accuracy_by_regime:
            self.accuracy_by_regime[regime] = []
        self.accuracy_by_regime[regime].append(1.0 if correct else 0.0)

        # Ticker bazlı doğruluk
        ticker = episode.ticker
        if ticker not in self.accuracy_by_ticker:
            self.accuracy_by_ticker[ticker] = []
        self.accuracy_by_ticker[ticker].append(1.0 if correct else 0.0)

    def get_accuracy(
        self,
        regime: str | None = None,
        ticker: str | None = None,
        last_n: int | None = None,
    ) -> float:
        """Doğruluk oranı hesapla (0-1 arası)."""
        if regime:
            scores = self.accuracy_by_regime.get(regime, [])
        elif ticker:
            scores = self.accuracy_by_ticker.get(ticker, [])
        else:
            scores = [1.0 if o["correct"] else 0.0 for o in self.outcomes.values()]

        if last_n and len(scores) > last_n:
            scores = scores[-last_n:]

        return round(sum(scores) / len(scores) if scores else 0, 4)

    def get_accuracy_by_regime(self) -> dict[str, float]:
        """Rejim bazlı doğruluk oranları."""
        return {
            regime: round(sum(scores) / len(scores) if scores else 0, 4)
            for regime, scores in self.accuracy_by_regime.items()
            if scores
        }

    def get_accuracy_by_ticker(self) -> dict[str, float]:
        """Ticker bazlı doğruluk oranları."""
        return {
            ticker: round(sum(scores) / len(scores) if scores else 0, 4)
            for ticker, scores in self.accuracy_by_ticker.items()
            if scores
        }

    def get_similar(
        self,
        ticker: str,
        regime: str | None = None,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        """Benzer olayları bul (ticker + opsiyonel rejim bazlı)."""
        filtered = [e for e in self.episodes if e.ticker == ticker]
        if regime:
            # Outcome'lardan rejim eşleşmesi bul
            regime_matches = [
                e for e in filtered if e.task_id in self.outcomes and self.outcomes[e.task_id].get("regime") == regime
            ]
            if regime_matches:
                return regime_matches[-limit:]
        return filtered[-limit:]

    def get_confidence_calibration(self) -> dict[str, Any]:
        """Confidence kalibrasyonu — beklenen vs gerçek doğruluk.

        Confidence aralıklarına göre gerçek doğruluk oranını hesaplar.
        İyi kalibre edilmiş bir modelde: confidence 0.7 ise gerçek doğruluk ~%70 olmalı.
        """
        if len(self.outcomes) < 10:
            return {"calibrated": False, "reason": "insufficient_data"}

        bins = [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]  # 1.0 dahil
        calibration = []

        for low, high in bins:
            matching_episodes = [e for e in self.episodes if low <= e.confidence < high and e.task_id in self.outcomes]
            if matching_episodes:
                avg_conf = sum(e.confidence for e in matching_episodes) / len(matching_episodes)
                actual_acc = sum(1 for e in matching_episodes if self.outcomes[e.task_id]["correct"]) / len(
                    matching_episodes
                )
                calibration.append(
                    {
                        "bin": f"{low:.1f}-{high:.1f}",
                        "avg_confidence": round(avg_conf, 4),
                        "actual_accuracy": round(actual_acc, 4),
                        "miscalibration": round(abs(avg_conf - actual_acc), 4),
                        "count": len(matching_episodes),
                    }
                )

        return {"calibrated": True, "calibration": calibration}

    def to_dict(self) -> dict[str, Any]:
        """Serialization için dict'e çevir."""
        return {
            "episode_count": len(self.episodes),
            "outcome_count": len(self.outcomes),
            "accuracy": self.get_accuracy(),
            "accuracy_by_regime": self.get_accuracy_by_regime(),
        }


class SemanticMemory:
    """Bilgi grafiği — öğrenilen kalıplar.

    Amaç: Uzun vadeli bilgi birikimi.
    Pattern recognition, korelasyonlar, sezonluk kalıplar.
    """

    def __init__(self, max_patterns_per_key: int = 500):
        self.patterns: dict[str, list[dict]] = {}  # ticker → patterns
        self.regime_patterns: dict[str, list[dict]] = {}  # regime → patterns
        self.sector_patterns: dict[str, list[dict]] = {}  # sector → patterns
        self._max_per_key = max_patterns_per_key

    def add_pattern(
        self,
        ticker: str,
        regime: str,
        pattern: dict[str, Any],
        sector: str | None = None,
    ) -> None:
        """Kalıp ekle (ticker, regime, opsiyonel sektör bazlı)."""
        entry = {
            **pattern,
            "ticker": ticker,
            "regime": regime,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        if ticker not in self.patterns:
            self.patterns[ticker] = []
        self.patterns[ticker].append(entry)
        # Sınırlı büyüme
        if len(self.patterns[ticker]) > self._max_per_key:
            self.patterns[ticker] = self.patterns[ticker][-self._max_per_key :]

        if regime not in self.regime_patterns:
            self.regime_patterns[regime] = []
        self.regime_patterns[regime].append(entry)
        if len(self.regime_patterns[regime]) > self._max_per_key:
            self.regime_patterns[regime] = self.regime_patterns[regime][-self._max_per_key :]

        if sector:
            if sector not in self.sector_patterns:
                self.sector_patterns[sector] = []
            self.sector_patterns[sector].append(entry)
            if len(self.sector_patterns[sector]) > self._max_per_key:
                self.sector_patterns[sector] = self.sector_patterns[sector][-self._max_per_key :]

    def get_patterns(
        self,
        ticker: str | None = None,
        regime: str | None = None,
        sector: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Kalıpları getir (opsiyonel filtre ile)."""
        results: list[dict] = []

        if ticker:
            results.extend(self.patterns.get(ticker, [])[-limit:])
        if regime:
            results.extend(self.regime_patterns.get(regime, [])[-limit:])
        if sector:
            results.extend(self.sector_patterns.get(sector, [])[-limit:])

        if not ticker and not regime and not sector:
            for patterns in self.patterns.values():
                results.extend(patterns[-3:])

        return results[-limit:]

    def prune_low_accuracy(self, threshold: float = 0.4) -> None:
        """Düşük doğruluklu kalıpları temizle.

        Not: Kalıplarda "accuracy" anahtarı yoksa, "confidence" kullanılır.
        İkisi de yoksa kalıp korunur (varsayılan: güvenli).
        """
        for ticker in list(self.patterns.keys()):
            self.patterns[ticker] = [
                p for p in self.patterns[ticker] if p.get("accuracy", p.get("confidence", 0.5)) >= threshold
            ]

    def to_dict(self) -> dict[str, Any]:
        """Serialization için dict'e çevir."""
        return {
            "ticker_patterns": sum(len(v) for v in self.patterns.values()),
            "regime_patterns": sum(len(v) for v in self.regime_patterns.values()),
            "sector_patterns": sum(len(v) for v in self.sector_patterns.values()),
        }


class AgentMemory:
    """3 katmanlı agent hafızası.

    Katmanlar:
    1. Working Memory — anlık bağlam (son 100 görev)
    2. Episodic Memory — geçmiş olaylar (önemli olaylar + outcome tracking)
    3. Semantic Memory — bilgi grafiği (öğrenilen kalıplar)

    Her agent rolü (TECHNICAL, FUNDAMENTAL, vb.) kendi AgentMemory instance'ına sahiptir.
    """

    def __init__(
        self,
        agent_role: str,
        max_working: int = 100,
        max_episodic: int = 1000,
        persistence_path: str | None = None,
    ):
        self.agent_role = agent_role
        self.working = WorkingMemory(max_items=max_working)
        self.episodic = EpisodicMemory(max_items=max_episodic)
        self.semantic = SemanticMemory()
        self._persistence_path = persistence_path

    def record_task(
        self,
        task_id: str,
        ticker: str,
        direction: str,
        confidence: float,
        reasoning: str,
    ) -> None:
        """Görev kaydet (working + episodic memory'ye)."""
        entry = MemoryEntry(
            task_id=task_id,
            agent_role=self.agent_role,
            ticker=ticker,
            direction=direction,
            confidence=confidence,
            reasoning=reasoning,
            timestamp=datetime.now(UTC).isoformat(),
        )

        # Working memory — her zaman
        self.working.add(entry)

        # Episodic memory — sadece yüksek güven veya önemli
        self.episodic.add(entry)

    def record_outcome(
        self,
        task_id: str,
        actual_return: float,
        regime: str = "UNKNOWN",
    ) -> None:
        """Sonuç kaydet (accuracy tracking için)."""
        self.episodic.record_outcome(task_id, actual_return, regime)

    def get_context_for_task(
        self,
        ticker: str,
        regime: str | None = None,
    ) -> dict[str, Any]:
        """Yeni görev için bağlam oluştur.

        Agent'ın geçmiş deneyimlerini, benzer olayları ve öğrenilen kalıpları döndürür.
        """
        return {
            "recent_tasks": [e.to_dict() for e in self.working.get_recent(ticker, limit=5)],
            "similar_events": [e.to_dict() for e in self.episodic.get_similar(ticker, limit=3)],
            "learned_patterns": self.semantic.get_patterns(ticker, regime, limit=3),
            "accuracy": self.episodic.get_accuracy(),
            "accuracy_by_regime": self.episodic.get_accuracy_by_regime(),
            "ticker_accuracy": self.episodic.get_accuracy(ticker=ticker),
        }

    def cleanup_expired(self) -> dict[str, int]:
        """Süresi dolan kayıtları tüm katmanlardan temizle.

        Returns:
            Her katmandan silinen kayıt sayısı
        """
        working_cleaned = self.working.cleanup_expired()
        episodic_cleaned = self.episodic.cleanup_expired()
        logger.info(
            "Memory cleanup",
            agent=self.agent_role,
            working_cleaned=working_cleaned,
            episodic_cleaned=episodic_cleaned,
        )
        return {
            "working": working_cleaned,
            "episodic": episodic_cleaned,
        }

    def get_performance_summary(self) -> dict[str, Any]:
        """Performans özeti — tüm katmanların istatistikleri."""
        return {
            "agent_role": self.agent_role,
            "working_memory_size": len(self.working.items),
            "episodic_memory_size": len(self.episodic.episodes),
            "total_outcomes": len(self.episodic.outcomes),
            "overall_accuracy": self.episodic.get_accuracy(),
            "accuracy_by_regime": self.episodic.get_accuracy_by_regime(),
            "calibration": self.episodic.get_confidence_calibration(),
            "semantic_patterns": self.semantic.to_dict(),
        }

    def save(self, path: str | None = None) -> None:
        """Memory'yi dosyaya kaydet (debounced — SSD dostu).

        Atomik yazım kullanır: önce tmp dosyaya yazar, sonra rename yapar.
        Bu sayede crash sırasında dosya bozulmaz.
        """
        save_path = path or self._persistence_path
        if not save_path:
            return
        if not should_save(f"agent_memory_{self.agent_role}", 60):
            return

        data = {
            "agent_role": self.agent_role,
            "saved_at": datetime.now(UTC).isoformat(),
            "working": self.working.to_dict(),
            "episodic": {
                "episodes": [e.to_dict() for e in self.episodic.episodes],
                "outcomes": self.episodic.outcomes,
                "accuracy_by_regime": self.episodic.accuracy_by_regime,
                "accuracy_by_ticker": self.episodic.accuracy_by_ticker,
            },
            "semantic": self.semantic.to_dict(),
            "performance": self.get_performance_summary(),
        }

        target = Path(save_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        # Atomik yazım: tmp + rename
        # Büyük dosyalar için gzip sıkıştırma (>100KB)
        json_bytes = orjson.dumps(data, option=orjson.OPT_INDENT_2, default=str)
        use_gzip = len(json_bytes) > 100 * 1024  # 100KB eşik

        if use_gzip:
            tmp_path = target.with_suffix(".tmp.gz")
            final_path = target.with_suffix(".json.gz") if target.suffix == ".json" else target.with_suffix(".gz")
        else:
            tmp_path = target.with_suffix(".tmp")
            final_path = target

        try:
            if use_gzip:
                with gzip.open(tmp_path, "wb") as f:
                    f.write(json_bytes)
            else:
                with open(tmp_path, "wb") as f:
                    f.write(json_bytes)
            tmp_path.rename(final_path)
            logger.info("Memory saved", path=str(final_path), compressed=use_gzip, size=len(json_bytes))
        except Exception as e:
            logger.error("Failed to save memory", path=save_path, error=str(e))
            tmp_path.unlink(missing_ok=True)

    def load(self, path: str | None = None) -> None:
        """Memory'yi dosyadan yükle.

        Hatalı kayıtları atlar, bozuk dosyayı loglar.
        Hem gzip sıkıştırılmış hem normal dosyaları okuyabilir.
        """
        load_path = path or self._persistence_path
        if not load_path:
            return

        # Hem .json.gz hem .json dosyalarını kontrol et
        target = Path(load_path)
        if target.with_suffix(".gz").exists():
            target = target.with_suffix(".gz")
        elif not target.exists():
            return

        try:
            if target.suffix == ".gz":
                with gzip.open(target, "rb") as f:
                    data = orjson.loads(f.read())
            else:
                with open(target, "rb") as f:
                    data = orjson.loads(f.read())

            # Working memory
            for item in data.get("working", {}).get("items", []):
                try:
                    self.working.add(MemoryEntry(**item))
                except (TypeError, KeyError) as e:
                    logger.debug("Skipping invalid working memory entry", error=str(e))

            # Episodic memory — hem eski format ("items") hem yeni format ("episodes") desteği
            episodic_data = data.get("episodic", {})
            episode_items = episodic_data.get("episodes", episodic_data.get("items", []))
            for item in episode_items:
                try:
                    self.episodic.add(MemoryEntry(**item))
                except (TypeError, KeyError) as e:
                    logger.debug("Skipping invalid episodic memory entry", error=str(e))

            # Outcomes ve accuracy istatistiklerini yükle
            for task_id, outcome in episodic_data.get("outcomes", {}).items():
                self.episodic.outcomes[task_id] = outcome
            self.episodic.accuracy_by_regime = episodic_data.get("accuracy_by_regime", {})
            self.episodic.accuracy_by_ticker = episodic_data.get("accuracy_by_ticker", {})

            logger.info(
                "Memory loaded",
                path=load_path,
                working=len(self.working.items),
                episodic=len(self.episodic.episodes),
                outcomes=len(self.episodic.outcomes),
            )
        except orjson.JSONDecodeError as e:
            logger.warning("Corrupted memory file", path=load_path, error=str(e))
        except FileNotFoundError:
            logger.debug("Memory file not found", path=load_path)
        except Exception as e:
            logger.warning("Failed to load memory", path=load_path, error=str(e))


class MemoryConsolidator:
    """Periyodik memory consolidation.

    Yapar:
    - Working memory'deki düşük güvenli kayıtları temizle
    - Başarısız pattern'ları semantic memory'den kaldır
    - Accuracy istatistiklerini güncelle
    - Dosyaya kaydet
    """

    def __init__(self, consolidation_interval_hours: int = 24):
        self.interval_hours = consolidation_interval_hours
        self._last_consolidation: dict[str, float] = {}

    def consolidate(self, memory: AgentMemory) -> dict[str, Any]:
        """Memory'yi temizle ve özetle.

        Not: Bu fonksiyon async değildi, gereksiz async kaldırıldı.
        I/O operasyonu (save) zaten blocking.
        """
        now = time.time()
        last = self._last_consolidation.get(memory.agent_role, 0)

        # Zaman kontrolü — ilk çalıştırmada bile interval'e saygı göster
        if last > 0 and (now - last) < self.interval_hours * 3600:
            return {"consolidated": False, "reason": "too_soon"}

        # Eğer hiç consolidation yapılmadıysa ve memory boşsa, sadece zaman damgası at
        if last == 0 and len(memory.working.items) == 0 and len(memory.episodic.episodes) == 0:
            self._last_consolidation[memory.agent_role] = now
            return {"consolidated": False, "reason": "empty_memory"}

        # 1. Süresi dolan kayıtları temizle (TTL)
        ttl_cleaned = memory.cleanup_expired()

        # 2. Düşük güvenli working memory'yi temizle
        old_count = len(memory.working.items)
        memory.working.items = deque(
            [e for e in memory.working.items if e.confidence > 0.3],
            maxlen=memory.working.max_items,
        )
        cleaned = old_count - len(memory.working.items)

        # 3. Semantic memory'den düşük doğruluklu kalıpları temizle
        memory.semantic.prune_low_accuracy(threshold=0.4)

        # 3. Kaydet
        if memory._persistence_path:
            memory.save()

        self._last_consolidation[memory.agent_role] = now

        result = {
            "consolidated": True,
            "ttl_cleaned_working": ttl_cleaned["working"],
            "ttl_cleaned_episodic": ttl_cleaned["episodic"],
            "low_confidence_cleaned": cleaned,
            "episodic_count": len(memory.episodic.episodes),
            "outcome_count": len(memory.episodic.outcomes),
            "accuracy": memory.episodic.get_accuracy(),
        }

        logger.info("Memory consolidated", **result)
        return result
