"""
ALPHA BIST — Alternative Data Base Infrastructure v1.0

Temel altyapı:
- BaseAdapter: Tüm adapter'lar için soyut sınıf
- RateLimiter: API rate limit koruması
- CircuitBreaker: Servis kesintisi koruması
- DataQualityValidator: Veri kalitesi kontrolü
- AdapterRegistry: Adapter kayıt ve yönetim
"""

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger()


# =====================================================
# RATE LIMITER
# =====================================================


class RateLimiter:
    """Token bucket rate limiter.

    Her kaynak için ayrı rate limit uygular.
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        """Rate limiter başlat.

        Args:
            max_requests: Pencere başına maksimum istek sayısı.
            window_seconds: Zaman penceresi süresi (saniye).
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._tokens = max_requests
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Token al, yoksa pencere dolana kadar bekle."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.max_requests, self._tokens + elapsed * (self.max_requests / self.window_seconds))
            self._last_refill = now

            if self._tokens < 1:
                wait_time = (1 - self._tokens) * (self.window_seconds / self.max_requests)
                logger.warning("Rate limit hit, waiting", wait_seconds=round(wait_time, 1))
                await asyncio.sleep(wait_time)
                self._tokens = 1

            self._tokens -= 1

    def __repr__(self) -> str:
        return f"RateLimiter(max_requests={self.max_requests}, window_seconds={self.window_seconds})"


# =====================================================
# CIRCUIT BREAKER
# =====================================================


class CircuitState(StrEnum):
    """Devre kesici durumları: CLOSED, OPEN, HALF_OPEN."""
    CLOSED = "CLOSED"  # Normal çalışma
    OPEN = "OPEN"  # Servis kesik, istek yok
    HALF_OPEN = "HALF_OPEN"  # Test aşaması


@dataclass
class CircuitBreaker:
    """Circuit breaker — servis kesintisi koruması.

    Kurallar:
    - failure_threshold ardışık hata → OPEN
    - OPEN → recovery_timeout sonra HALF_OPEN
    - HALF_OPEN → başarılı istek → CLOSED
    - HALF_OPEN → hata → OPEN
    """

    failure_threshold: int = 5
    recovery_timeout_seconds: int = 300

    _state: CircuitState = field(default=CircuitState.CLOSED)
    _failure_count: int = field(default=0)
    _last_failure_time: float = field(default=0)
    _success_count: int = field(default=0)

    @property
    def state(self) -> CircuitState:
        """Mevcut durumu döndür, recovery timeout kontrolü ile."""
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout_seconds:
                self._state = CircuitState.HALF_OPEN
        return self._state

    def record_success(self) -> None:
        """Başarılı istek kaydet. HALF_OPEN durumunda 2 başarılı istek sonrası CLOSED'a geçer."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= 2:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
                logger.info("Circuit breaker closed (recovered)")
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

    def record_failure(self) -> None:
        """Başarısız istek kaydet. Eşik aşılırsa OPEN durumuna geçer."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            logger.warning("Circuit breaker opened (half-open failure)")
        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "Circuit breaker opened",
                failures=self._failure_count,
                threshold=self.failure_threshold,
            )

    def allow_request(self) -> bool:
        """İstek izni var mı?"""
        state = self.state
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            return True  # Test isteği
        return False  # OPEN


# =====================================================
# DATA QUALITY VALIDATOR
# =====================================================


@dataclass
class QualityReport:
    """Veri kalitesi raporu."""

    is_valid: bool
    score: float  # 0-1
    issues: list[str] = field(default_factory=list)
    checks_passed: int = 0
    checks_failed: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Raporu sözlük formatına çevir."""
        return {
            "is_valid": self.is_valid,
            "score": round(self.score, 4),
            "issues": self.issues,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
        }


class DataQualityValidator:
    """Veri kalitesi kontrolü.

    Kontroller:
    1. Null/None check
    2. Zero-value check (tüm değerler 0 mı?)
    3. Range check (makul aralık)
    4. Staleness check (veri ne kadar eski?)
    5. Completeness check (eksik alan var mı?)
    6. Anomaly check (anormal değer?)
    """

    def validate(
        self,
        data: dict[str, Any] | None,
        source: str = "unknown",
        expected_fields: list[str] | None = None,
        max_age_hours: int | None = None,
    ) -> QualityReport:
        """Veri kalitesi kontrolü yap.

        Args:
            data: Kontrol edilecek veri.
            source: Veri kaynak adı (loglama için).
            expected_fields: Olması gereken alanlar.
            max_age_hours: Verinin maksimum yaşı (saat).

        Returns:
            QualityReport nesnesi.
        """
        issues = []
        checks_passed = 0
        checks_failed = 0

        # 1. Null check
        if data is None:
            return QualityReport(
                is_valid=False,
                score=0.0,
                issues=["Data is None"],
                checks_passed=0,
                checks_failed=1,
            )

        checks_passed += 1

        # 2. Type check
        if not isinstance(data, dict):
            issues.append(f"Expected dict, got {type(data).__name__}")
            checks_failed += 1
        else:
            checks_passed += 1

        if not isinstance(data, dict):
            return QualityReport(
                is_valid=False,
                score=0.2,
                issues=issues,
                checks_passed=checks_passed,
                checks_failed=checks_failed,
            )

        # 3. Empty check
        if not data:
            issues.append("Data is empty dict")
            checks_failed += 1
        else:
            checks_passed += 1

        # 4. Zero-value check
        numeric_values = [v for v in data.values() if isinstance(v, (int, float))]
        if numeric_values and all(v == 0 for v in numeric_values):
            issues.append("All numeric values are zero")
            checks_failed += 1
        else:
            checks_passed += 1

        # 5. Expected fields check
        if expected_fields:
            missing = [f for f in expected_fields if f not in data]
            if missing:
                issues.append(f"Missing fields: {missing}")
                checks_failed += 1
            else:
                checks_passed += 1

        # 6. Range check (confidence/score 0-1 veya 0-100)
        for key, val in data.items():
            if isinstance(val, (int, float)):
                if ("confidence" in key.lower() or "ratio" in key.lower()) and (val < -1 or val > 1.5):
                    issues.append(f"{key}={val} out of expected range")
                    checks_failed += 1
                elif "score" in key.lower() and (val < -50 or val > 150):
                    issues.append(f"{key}={val} out of expected range")
                    checks_failed += 1
                else:
                    checks_passed += 1

        # 7. Staleness check
        if max_age_hours and "timestamp" in data:
            try:
                ts = data["timestamp"]
                if isinstance(ts, str):
                    ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                elif isinstance(ts, datetime):
                    ts_dt = ts
                else:
                    ts_dt = None

                if ts_dt:
                    age_hours = (datetime.now(UTC) - ts_dt).total_seconds() / 3600
                    if age_hours > max_age_hours:
                        issues.append(f"Data is {age_hours:.1f}h old (max: {max_age_hours}h)")
                        checks_failed += 1
                    else:
                        checks_passed += 1
            except Exception as e:
                logger.debug("Staleness check parse error", error=str(e))

        # Score hesapla
        total_checks = checks_passed + checks_failed
        score = checks_passed / total_checks if total_checks > 0 else 0
        is_valid = score >= 0.5 and checks_failed <= 2

        return QualityReport(
            is_valid=is_valid,
            score=round(score, 4),
            issues=issues,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
        )


# =====================================================
# BASE ADAPTER
# =====================================================


class BaseAdapter(ABC):
    """Tüm alternative data adapter'ları için soyut sınıf.

    Her adapter:
    - collect(): Veri toplar
    - compute_features(): Feature hesaplar
    - source_name: Kaynak adı
    - rate_limit: Dakikada max istek
    """

    source_name: str = "unknown"
    rate_limit: int = 60
    DEFAULT_CACHE_TTL: int = 3600

    def __init__(self):
        """Adapter'ı başlat: rate limiter, circuit breaker, validator ve cache."""
        self.rate_limiter = RateLimiter(
            max_requests=self.rate_limit,
            window_seconds=60,
        )
        self.circuit_breaker = CircuitBreaker()
        self._validator = DataQualityValidator()
        self._cache: dict[str, Any] = {}
        self._cache_ttl: dict[str, float] = {}

    @abstractmethod
    async def collect(self, ticker: str, **kwargs) -> dict[str, Any] | None:
        """Veri topla. Alt sınıflar implement etmeli."""

    @abstractmethod
    def compute_features(self, data: dict[str, Any], ticker: str) -> dict[str, float]:
        """Feature hesapla. Alt sınıflar implement etmeli."""

    async def fetch(self, ticker: str, **kwargs) -> dict[str, float]:
        """Tam pipeline: collect → validate → compute_features.

        Args:
            ticker: Hisse sembolü.
            **kwargs: Ek parametreler.

        Returns:
            Feature sözlüğü veya boş dict.
        """
        if not ticker or not ticker.strip():
            logger.warning("Empty ticker provided", source=self.source_name)
            return self._empty_features()
        # Cache kontrolü
        cache_key = f"{self.source_name}:{ticker}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        # Circuit breaker kontrolü
        if not self.circuit_breaker.allow_request():
            logger.warning("Circuit breaker open, skipping", source=self.source_name, ticker=ticker)
            return self._empty_features()

        # Rate limit
        await self.rate_limiter.acquire()

        try:
            # Veri topla
            raw_data = await self.collect(ticker, **kwargs)

            # Kalite kontrolü
            quality = self._validator.validate(raw_data, source=self.source_name)
            if not quality.is_valid:
                logger.warning(
                    "Data quality check failed",
                    source=self.source_name,
                    ticker=ticker,
                    score=quality.score,
                    issues=quality.issues,
                )
                self.circuit_breaker.record_failure()
                return self._empty_features()

            # Feature hesapla
            features = self.compute_features(raw_data, ticker)

            # Cache'e yaz
            self._set_cached(cache_key, features, ttl_seconds=3600)

            self.circuit_breaker.record_success()

            logger.info(
                "Alternative data collected",
                source=self.source_name,
                ticker=ticker,
                features=len(features),
                quality_score=quality.score,
            )

            return features

        except Exception as e:
            logger.error(
                "Alternative data collection failed",
                source=self.source_name,
                ticker=ticker,
                error=str(e),
            )
            self.circuit_breaker.record_failure()
            return self._empty_features()

    def _empty_features(self) -> dict[str, float]:
        """Boş feature dict döndür."""
        return {}

    def _get_cached(self, key: str) -> dict[str, float] | None:
        """Cache'den oku."""
        if key in self._cache:
            ttl = self._cache_ttl.get(key, 0)
            if time.time() < ttl:
                return self._cache[key]
            del self._cache[key]
            if key in self._cache_ttl:
                del self._cache_ttl[key]
        return None

    def _set_cached(self, key: str, value: dict[str, float], ttl_seconds: int | None = None) -> None:
        """Cache'e yaz."""
        ttl = ttl_seconds if ttl_seconds is not None else self.DEFAULT_CACHE_TTL
        self._cache[key] = value
        self._cache_ttl[key] = time.time() + ttl

    def get_status(self) -> dict[str, Any]:
        """Adapter durum bilgisini döndür."""
        return {
            "source": self.source_name,
            "rate_limit": self.rate_limit,
            "circuit_state": self.circuit_breaker.state.value,
            "cache_size": len(self._cache),
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(source={self.source_name!r}, rate_limit={self.rate_limit})"


# =====================================================
# ADAPTER REGISTRY
# =====================================================


class AdapterRegistry:
    """Adapter kayıt ve yönetim merkezi."""

    def __init__(self):
        """Boş registry başlat."""
        self._adapters: dict[str, BaseAdapter] = {}

    def register(self, adapter: BaseAdapter) -> None:
        """Adapter'ı registry'ye kaydet."""
        self._adapters[adapter.source_name] = adapter
        logger.info("Adapter registered", source=adapter.source_name)

    def get(self, source_name: str) -> BaseAdapter | None:
        """Kaynak adına göre adapter getir."""
        return self._adapters.get(source_name)

    def list_adapters(self) -> list[str]:
        """Kayıtlı adapter isimlerini listele."""
        return list(self._adapters.keys())

    def get_all_status(self) -> dict[str, Any]:
        """Tüm adapter'ların durum bilgisini döndür."""
        return {name: adapter.get_status() for name, adapter in self._adapters.items()}

    def __repr__(self) -> str:
        return f"AdapterRegistry(adapters={len(self._adapters)})"

    async def collect_all(
        self,
        ticker: str,
        sources: list[str] | None = None,
    ) -> dict[str, dict[str, float]]:
        """Tüm (veya belirtilen) kaynaklardan veri topla."""
        target_adapters = {
            name: adapter for name, adapter in self._adapters.items() if sources is None or name in sources
        }

        # Paralel toplama
        tasks = {name: adapter.fetch(ticker) for name, adapter in target_adapters.items()}

        results = {}
        gathered = await asyncio.gather(
            *tasks.values(),
            return_exceptions=True,
        )

        for (name, _), result in zip(tasks.items(), gathered, strict=True):
            if isinstance(result, Exception):
                logger.error("Adapter failed", source=name, error=str(result))
                results[name] = {}
            else:
                results[name] = result

        return results


# Singleton
adapter_registry = AdapterRegistry()
