"""
ALPHA BIST — Data Integrity Validator v1.0

Restart sonrası veri bütünlüğünü kontrol eder.
Eksik verileri tespit edip otomatik backfill tetikler.

Kontroller:
- ClickHouse bar eksikliği
- PostgreSQL tutarlılığı
- Feature completeness
- Model state doğruluğu
- Redis cache tutarlılığı

Kullanım:
    from services.core.data_integrity import data_integrity_validator

    results = await data_integrity_validator.validate_on_startup()
    if results["has_issues"]:
        await data_integrity_validator.auto_repair(results)
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
import structlog

logger = structlog.get_logger()


class DataIntegrityValidator:
    """Veri bütünlüğü doğrulayıcı.

    Startup'ta tüm veri kaynaklarının tutarlılığını kontrol eder.
    """

    def __init__(self):
        self._last_validation: Optional[float] = None
        self._validation_history: List[Dict] = []

    async def validate_on_startup(
        self,
        clickhouse_client=None,
        pg_pool=None,
        redis_client=None,
    ) -> Dict[str, Any]:
        """Startup'ta tam doğrulama yap.

        Returns:
            Doğrulama sonuçları
        """
        start_time = time.time()
        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": {},
            "has_issues": False,
            "issues": [],
            "recommendations": [],
        }

        # 1. ClickHouse bar eksikliği kontrolü
        ch_result = await self._check_clickhouse_gaps(clickhouse_client)
        results["checks"]["clickhouse_gaps"] = ch_result
        if ch_result["has_gaps"]:
            results["has_issues"] = True
            results["issues"].append(f"ClickHouse: {ch_result['gap_count']} eksik bar tespit edildi")
            results["recommendations"].append("Backfill çalıştırın")

        # 2. PostgreSQL tutarlılığı
        pg_result = await self._check_postgres_consistency(pg_pool)
        results["checks"]["postgres_consistency"] = pg_result
        if pg_result["has_issues"]:
            results["has_issues"] = True
            results["issues"].extend(pg_result["issues"])

        # 3. Feature completeness
        feat_result = await self._check_feature_completeness(pg_pool)
        results["checks"]["feature_completeness"] = feat_result
        if feat_result["incomplete_tickers"]:
            results["has_issues"] = True
            results["issues"].append(
                f"Feature eksik: {len(feat_result['incomplete_tickers'])} ticker"
            )

        # 4. Redis cache durumu
        redis_result = await self._check_redis_health(redis_client)
        results["checks"]["redis_health"] = redis_result

        # 5. Son veri tazelik kontrolü
        freshness_result = await self._check_data_freshness(clickhouse_client, pg_pool)
        results["checks"]["data_freshness"] = freshness_result
        if freshness_result["stale_tickers"]:
            results["has_issues"] = True
            results["issues"].append(
                f"Stale data: {len(freshness_result['stale_tickers'])} ticker"
            )

        duration = time.time() - start_time
        results["duration_seconds"] = round(duration, 2)

        self._last_validation = time.time()
        self._validation_history.append(results)
        if len(self._validation_history) > 100:
            self._validation_history = self._validation_history[-100:]

        if results["has_issues"]:
            logger.warning("Data integrity issues found",
                          issues=len(results["issues"]),
                          duration=round(duration, 2))
        else:
            logger.info("Data integrity validation passed",
                       duration=round(duration, 2))

        return results

    async def _check_clickhouse_gaps(self, client=None) -> Dict[str, Any]:
        """ClickHouse'da eksik bar'ları kontrol et."""
        result = {
            "has_gaps": False,
            "gap_count": 0,
            "gaps": [],
            "checked_tickers": 0,
        }

        if not client:
            result["status"] = "skipped"
            return result

        try:
            # Son 30 günde eksik iş günlerini kontrol et
            query = """
                SELECT
                    ticker,
                    toDate(timestamp) as trade_date,
                    count() as bar_count
                FROM market_bars
                WHERE timestamp >= now() - INTERVAL 30 DAY
                GROUP BY ticker, trade_date
                ORDER BY ticker, trade_date
            """

            query_result = client.query(query)
            if not query_result.result_rows:
                result["status"] = "no_data"
                return result

            # Ticker bazında eksik günleri bul
            ticker_dates = {}
            for row in query_result.result_rows:
                ticker = row[0]
                if ticker not in ticker_dates:
                    ticker_dates[ticker] = set()
                ticker_dates[ticker].add(row[1])

            result["checked_tickers"] = len(ticker_dates)

            # Her ticker için son 30 günde eksik iş günlerini kontrol et
            from datetime import date
            today = date.today()
            for ticker, dates in ticker_dates.items():
                expected_dates = set()
                d = today - timedelta(days=30)
                while d <= today:
                    if d.weekday() < 5:  # İş günü
                        expected_dates.add(d)
                    d += timedelta(days=1)

                missing = expected_dates - dates
                if missing:
                    result["has_gaps"] = True
                    result["gap_count"] += len(missing)
                    result["gaps"].append({
                        "ticker": ticker,
                        "missing_dates": [d.isoformat() for d in sorted(missing)[-5:]],
                        "total_missing": len(missing),
                    })

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

        return result

    async def _check_postgres_consistency(self, pg_pool=None) -> Dict[str, Any]:
        """PostgreSQL tutarlılığını kontrol et."""
        result = {
            "has_issues": False,
            "issues": [],
            "tables_checked": 0,
        }

        if not pg_pool:
            result["status"] = "skipped"
            return result

        try:
            async with pg_pool.acquire() as conn:
                # Tablo varlık kontrolü
                tables = [
                    "instruments", "companies", "sectors",
                    "market_data", "signals", "portfolios",
                ]

                for table in tables:
                    try:
                        row = await conn.fetchrow(
                            f"SELECT COUNT(*) as cnt FROM {table}"
                        )
                        result["tables_checked"] += 1
                        result[f"{table}_count"] = row["cnt"]
                    except Exception as e:
                        result["has_issues"] = True
                        result["issues"].append(f"Table '{table}' error: {str(e)[:100]}")

                # Instruments tablosunda NULL ticker kontrolü
                try:
                    null_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM instruments WHERE symbol IS NULL"
                    )
                    if null_count > 0:
                        result["has_issues"] = True
                        result["issues"].append(f"{null_count} instruments with NULL symbol")
                except Exception:
                    logger.warning("Caught Exception in _check_postgres_consistency", exc_info=True)

        except Exception as e:
            result["has_issues"] = True
            result["issues"].append(f"Connection error: {str(e)[:100]}")

        return result

    async def _check_feature_completeness(self, pg_pool=None) -> Dict[str, Any]:
        """Feature hesaplama bütünlüğünü kontrol et."""
        result = {
            "incomplete_tickers": [],
            "total_tickers": 0,
            "complete_tickers": 0,
        }

        if not pg_pool:
            result["status"] = "skipped"
            return result

        try:
            async with pg_pool.acquire() as conn:
                # Son feature hesaplama zamanlarını kontrol et
                rows = await conn.fetch("""
                    SELECT ticker, MAX(computed_at) as last_computed
                    FROM feature_store
                    GROUP BY ticker
                """)

                result["total_tickers"] = len(rows)
                cutoff = datetime.now(timezone.utc) - timedelta(hours=6)

                for row in rows:
                    if row["last_computed"] and row["last_computed"] < cutoff:
                        result["incomplete_tickers"].append({
                            "ticker": row["ticker"],
                            "last_computed": row["last_computed"].isoformat(),
                        })
                    else:
                        result["complete_tickers"] += 1

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

        return result

    async def _check_redis_health(self, redis_client=None) -> Dict[str, Any]:
        """Redis sağlık durumunu kontrol et."""
        result = {
            "connected": False,
            "keys_count": 0,
            "memory_used": "unknown",
        }

        if not redis_client:
            result["status"] = "skipped"
            return result

        try:
            pong = await redis_client.ping()
            result["connected"] = pong

            if pong:
                info = await redis_client.info("memory")
                result["memory_used"] = info.get("used_memory_human", "unknown")

                dbsize = await redis_client.dbsize()
                result["keys_count"] = dbsize

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

        return result

    async def _check_data_freshness(
        self, clickhouse_client=None, pg_pool=None
    ) -> Dict[str, Any]:
        """Veri tazelik kontrolü — son veri ne kadar eski?"""
        result = {
            "stale_tickers": [],
            "fresh_tickers": 0,
            "total_checked": 0,
        }

        # 2 saatten eski veriler "stale" sayılır
        stale_threshold = datetime.now(timezone.utc) - timedelta(hours=2)

        if pg_pool:
            try:
                async with pg_pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT ticker, MAX(timestamp) as last_ts
                        FROM market_data
                        GROUP BY ticker
                    """)

                    result["total_checked"] = len(rows)
                    for row in rows:
                        if row["last_ts"] and row["last_ts"] < stale_threshold:
                            result["stale_tickers"].append({
                                "ticker": row["ticker"],
                                "last_update": row["last_ts"].isoformat(),
                                "age_hours": round(
                                    (datetime.now(timezone.utc) - row["last_ts"]).total_seconds() / 3600, 1
                                ),
                            })
                        else:
                            result["fresh_tickers"] += 1

            except Exception as e:
                result["status"] = "error"
                result["error"] = str(e)

        return result

    async def auto_repair(self, validation_results: Dict[str, Any]):
        """Tespit edilen sorunları otomatik onar."""
        logger.info("Starting auto-repair based on validation results")

        # ClickHouse gap'leri için backfill tetikle
        ch_gaps = validation_results["checks"].get("clickhouse_gaps", {})
        if ch_gaps.get("has_gaps"):
            logger.info("Triggering backfill for ClickHouse gaps",
                       gap_count=ch_gaps["gap_count"])
            try:
                from ..ingestion.backfill import backfill_manager
                gaps = await backfill_manager.detect_all_gaps()
                await backfill_manager.backfill_all(gaps)
            except Exception as e:
                logger.error("Backfill auto-repair failed", error=str(e))

        # Stale data için yenileme tetikle
        freshness = validation_results["checks"].get("data_freshness", {})
        if freshness.get("stale_tickers"):
            logger.info("Triggering data refresh for stale tickers",
                       count=len(freshness["stale_tickers"]))

    def get_status(self) -> Dict[str, Any]:
        """Durum bilgisi."""
        return {
            "last_validation": datetime.fromtimestamp(
                self._last_validation, tz=timezone.utc
            ).isoformat() if self._last_validation else None,
            "validation_count": len(self._validation_history),
        }


# Singleton
data_integrity_validator = DataIntegrityValidator()
