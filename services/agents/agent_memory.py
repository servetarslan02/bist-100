"""
ALPHA BIST — Agent Memory System v1.0

3 katmanlı hafıza (arXiv Agentic Trading 2026 meta-analiz):
1. Working Memory — anlık bağlam (son 100 görev)
2. Episodic Memory — geçmiş olaylar (önemli olaylar + outcome tracking)
3. Semantic Memory — bilgi grafiği (öğrenilen kalıplar)

Memory consolidation periyodik yapılır.

FAZ 3: Agent Memory
"""

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import orjson
import structlog

logger = structlog.get_logger()


@dataclass
class MemoryEntry:
    """Tek hafıza kaydı."""

    task_id: str
    agent_role: str
    ticker: str
    direction: str
    confidence: float
    reasoning: str
    timestamp: str
    outcome: dict | None = None

    def to_dict(self) -> dict:
        """Otomatik eklendi."""
        return {
            "task_id": self.task_id,
            "agent_role": self.agent_role,
            "ticker": self.ticker,
            "direction": self.direction,
            "confidence": self.confidence,
            "reasoning": self.reasoning[:300],
            "timestamp": self.timestamp,
            "outcome": self.outcome,
        }


class WorkingMemory:
    """Anlık bağlam — son N görev.

    Amaç: Agent'ın yakın geçmişini bilmesi (son 100 görev).
    Hızlı erişim, kısa süreli.
    """

    def __init__(self, max_items: int = 100):
        """Otomatik eklendi."""
        self.items: list[MemoryEntry] = []
        self.max_items = max_items

    def add(self, entry: MemoryEntry) -> Any:
        """Görev ekle."""
        self.items.append(entry)
        if len(self.items) > self.max_items:
            self.items = self.items[-self.max_items :]

    def get_recent(
        self,
        ticker: str | None = None,
        agent_role: str | None = None,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Son görevleri getir."""
        filtered = self.items
        if ticker:
            filtered = [e for e in filtered if e.ticker == ticker]
        if agent_role:
            filtered = [e for e in filtered if e.agent_role == agent_role]
        return filtered[-limit:]

    def get_last_direction(self, ticker: str) -> str | None:
        """Son yön kararını getir."""
        for entry in reversed(self.items):
            if entry.ticker == ticker:
                return entry.direction
        return None

    def clear(self) -> Any:
        """Working memory'yi temizle."""
        self.items.clear()

    def to_dict(self) -> dict:
        """Otomatik eklendi."""
        return {
            "count": len(self.items),
            "items": [e.to_dict() for e in self.items[-10:]],  # Son 10
        }


class EpisodicMemory:
    """Geçmiş olaylar — outcome tracking ile.

    Amaç: Önemli olayları hatırlamak, doğruluk takibi yapmak.
    Uzun süreli, outcome odaklı.
    """

    def __init__(self, max_items: int = 1000, min_confidence_for_episode: float = 0.6):
        """Otomatik eklendi."""
        self.episodes: list[MemoryEntry] = []
        self.outcomes: dict[str, dict] = {}  # task_id → outcome
        self.accuracy_by_regime: dict[str, list[float]] = {}
        self.accuracy_by_ticker: dict[str, list[float]] = {}
        self.max_items = max_items
        self._min_confidence = min_confidence_for_episode

    def add(self, entry: MemoryEntry) -> Any:
        """Önemli olay ekle."""
        # Sadece yüksek güven veya başarısız olayları kaydet
        if entry.confidence > self._min_confidence or entry.direction == "NO_TRADE":
            self.episodes.append(entry)
            if len(self.episodes) > self.max_items:
                self.episodes = self.episodes[-self.max_items :]

    def record_outcome(
        self,
        task_id: str,
        actual_return: float,
        regime: str = "UNKNOWN",
        holding_days: int = 1,
    ) -> Any:
        """Sonuç kaydet — accuracy tracking."""
        episode = next((e for e in self.episodes if e.task_id == task_id), None)
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
        """Doğruluk oranı."""
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
        """Rejim bazlı doğruluk."""
        return {
            regime: round(sum(scores) / len(scores) if scores else 0, 4)
            for regime, scores in self.accuracy_by_regime.items()
            if scores
        }

    def get_accuracy_by_ticker(self) -> dict[str, float]:
        """Ticker bazlı doğruluk."""
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

    def get_confidence_calibration(self) -> dict:
        """Confidence kalibrasyonu — beklenen vs gerçek doğruluk."""
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

    def to_dict(self) -> dict:
        """Otomatik eklendi."""
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

    def __init__(self):
        """Otomatik eklendi."""
        self.patterns: dict[str, list[dict]] = {}  # ticker → patterns
        self.regime_patterns: dict[str, list[dict]] = {}  # regime → patterns
        self.sector_patterns: dict[str, list[dict]] = {}  # sector → patterns

    def add_pattern(
        self,
        ticker: str,
        regime: str,
        pattern: dict[str, Any],
        sector: str | None = None,
    ) -> Any:
        """Kalıp ekle."""
        entry = {
            **pattern,
            "ticker": ticker,
            "regime": regime,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        if ticker not in self.patterns:
            self.patterns[ticker] = []
        self.patterns[ticker].append(entry)

        if regime not in self.regime_patterns:
            self.regime_patterns[regime] = []
        self.regime_patterns[regime].append(entry)

        if sector:
            if sector not in self.sector_patterns:
                self.sector_patterns[sector] = []
            self.sector_patterns[sector].append(entry)

    def get_patterns(
        self,
        ticker: str | None = None,
        regime: str | None = None,
        sector: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Kalıpları getir."""
        results = []

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

    def prune_low_accuracy(self, threshold: float = 0.4) -> Any:
        """Düşük doğruluklu kalıpları temizle.

        Not: Kalıplarda "accuracy" anahtarı yoksa, "confidence" kullanılır.
        İkisi de yoksa kalıp korunur (varsayılan: güvenli).
        """
        for ticker in list(self.patterns.keys()):
            self.patterns[ticker] = [
                p for p in self.patterns[ticker] if p.get("accuracy", p.get("confidence", 0.5)) >= threshold
            ]

    def to_dict(self) -> dict:
        """Otomatik eklendi."""
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
    """

    def __init__(
        self,
        agent_role: str,
        max_working: int = 100,
        max_episodic: int = 1000,
        persistence_path: str | None = None,
    ):
        """Otomatik eklendi."""
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
    ) -> Any:
        """Görev kaydet (tüm katmanlara)."""
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
    ) -> Any:
        """Sonuç kaydet."""
        self.episodic.record_outcome(task_id, actual_return, regime)

    def get_context_for_task(
        self,
        ticker: str,
        regime: str | None = None,
    ) -> dict[str, Any]:
        """Yeni görev için bağlam oluştur."""
        return {
            "recent_tasks": [e.to_dict() for e in self.working.get_recent(ticker, limit=5)],
            "similar_events": [e.to_dict() for e in self.episodic.get_similar(ticker, limit=3)],
            "learned_patterns": self.semantic.get_patterns(ticker, regime, limit=3),
            "accuracy": self.episodic.get_accuracy(),
            "accuracy_by_regime": self.episodic.get_accuracy_by_regime(),
            "ticker_accuracy": self.episodic.get_accuracy(ticker=ticker),
        }

    def get_performance_summary(self) -> dict:
        """Performans özeti."""
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

    def save(self, path: str | None = None) -> Any:
        """Memory'yi dosyaya kaydet (debounced — SSD dostu)."""
        from services.core.debounce import should_save
        save_path = path or self._persistence_path
        if not save_path:
            return
        if not should_save(f"agent_memory_{self.agent_role}", 60):
            return

        data = {
            "agent_role": self.agent_role,
            "saved_at": datetime.now(UTC).isoformat(),
            "working": self.working.to_dict(),
            "episodic": self.episodic.to_dict(),
            "semantic": self.semantic.to_dict(),
            "performance": self.get_performance_summary(),
        }

        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w") as f:
            f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2, default=str).decode())

        logger.info("Memory saved", path=save_path)

    def load(self, path: str | None = None) -> Any:
        """Memory'yi dosyadan yükle."""
        load_path = path or self._persistence_path
        if not load_path or not Path(load_path).exists():
            return

        try:
            with open(load_path) as f:
                data = orjson.loads(f.read())

            # Working memory — her item'ı ayrı ayrı yükle, hatalı olanı atla
            for item in data.get("working", {}).get("items", []):
                try:
                    self.working.add(MemoryEntry(**item))
                except (TypeError, KeyError) as e:
                    logger.debug("Skipping invalid working memory entry", error=str(e))

            # Episodic memory
            for item in data.get("episodic", {}).get("items", []):
                try:
                    self.episodic.add(MemoryEntry(**item))
                except (TypeError, KeyError) as e:
                    logger.debug("Skipping invalid episodic memory entry", error=str(e))

            logger.info(
                "Memory loaded", path=load_path, working=len(self.working.items), episodic=len(self.episodic.episodes)
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
    - Working memory'deki eski kayıtları episodic'e taşı
    - Başarısız pattern'ları semantic memory'den kaldır
    - Accuracy istatistiklerini güncelle
    - Dosyaya kaydet
    """

    def __init__(self, consolidation_interval_hours: int = 24):
        """Otomatik eklendi."""
        self.interval_hours = consolidation_interval_hours
        self._last_consolidation: dict[str, float] = {}

    async def consolidate(self, memory: AgentMemory) -> dict[str, Any]:
        """Memory'yi temizle ve özetle."""
        now = time.time()
        last = self._last_consolidation.get(memory.agent_role, 0)

        # Zaman kontrolü — ilk çalıştırmada bile interval'e saygı göster
        if last > 0 and (now - last) < self.interval_hours * 3600:
            return {"consolidated": False, "reason": "too_soon"}

        # Eğer hiç consolidation yapılmadıysa ve memory boşsa, sadece zaman damgası at
        if last == 0 and len(memory.working.items) == 0 and len(memory.episodic.episodes) == 0:
            self._last_consolidation[memory.agent_role] = now
            return {"consolidated": False, "reason": "empty_memory"}

        # 1. Düşük güvenli working memory'yi temizle
        old_count = len(memory.working.items)
        memory.working.items = [e for e in memory.working.items if e.confidence > 0.3]
        cleaned = old_count - len(memory.working.items)

        # 2. Semantic memory'den düşük doğruluklu kalıpları temizle
        memory.semantic.prune_low_accuracy(threshold=0.4)

        # 3. Kaydet
        if memory._persistence_path:
            memory.save()

        self._last_consolidation[memory.agent_role] = now

        result = {
            "consolidated": True,
            "cleaned_working": cleaned,
            "episodic_count": len(memory.episodic.episodes),
            "outcome_count": len(memory.episodic.outcomes),
            "accuracy": memory.episodic.get_accuracy(),
        }

        logger.info("Memory consolidated", **result)
        return result
