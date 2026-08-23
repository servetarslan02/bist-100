"""
ALPHA BIST — Development Database Adapter

Docker/PostgreSQL/Redis olmadığında SQLite + InMemory kullanır.
Production'da database.py kullanılır.

Kullanım:
  from services.core.database_dev import dev_db
"""

import asyncio
import json
import re
import sqlite3
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path
import structlog

logger = structlog.get_logger()

DB_PATH = Path(__file__).parent.parent.parent / "data" / "alpha_dev.db"


class DevDatabase:
    """SQLite + InMemory development database."""

    def __init__(self):
        self._db: Optional[sqlite3.Connection] = None
        self._redis_store: Dict[str, Any] = {}
        self._redis_hashes: Dict[str, Dict[str, str]] = {}
        self._pubsub_handlers: Dict[str, List] = {}

    async def init(self):
        """Initialize SQLite database."""
        if self._db is not None:
            return  # Zaten başlatılmış
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(DB_PATH), timeout=10)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        await self._run_migrations()
        await self._seed_default_data()
        logger.info("Dev database initialized", path=str(DB_PATH))

    async def _run_migrations(self):
        """Migration runner'ı çalıştır."""
        from .migrations.runner import MigrationRunner
        runner = MigrationRunner(self._db, dialect="sqlite")
        applied = await runner.run_pending()
        if applied:
            logger.info("Migrations applied", versions=applied)

    async def _seed_default_data(self):
        """Varsayılan verileri ekle (idempotent)."""
        # Sektörler
        sectors = [
            ('BANK', 'Bankacılık'), ('INDUST', 'Sanayi'), ('TECH', 'Teknoloji'),
            ('ENERGY', 'Enerji'), ('RETAIL', 'Perakende'), ('CONSTR', 'İnşaat'),
            ('FOOD', 'Gıda'), ('CHEM', 'Kimya'), ('METAL', 'Metal'),
            ('TELECOM', 'Telekomünikasyon'), ('HEALTH', 'Sağlık'),
            ('REAL', 'Gayrimenkul'), ('AUTO', 'Otomotiv'), ('TEXTIL', 'Tekstil'),
            ('AVIATION', 'Havacılık'), ('HOLDING', 'Holding'), ('OTHER', 'Diğer'),
        ]
        for code, name in sectors:
            self._db.execute(
                "INSERT OR IGNORE INTO sectors (code, name) VALUES (?, ?)",
                (code, name)
            )

        # Stratejiler
        strategies = [
            ('Momentum', 'Kısa-orta vadeli momentum', 'MOMENTUM'),
            ('Breakout', 'Fiyat sıkışması kırılım', 'BREAKOUT'),
            ('Mean Reversion', 'Ortalama dönüş', 'MEAN_REVERSION'),
            ('Event Driven', 'KAP/haber bazlı', 'EVENT_DRIVEN'),
            ('SPEC', 'Olağandışı hareket tespiti', 'SPEC'),
            ('Value', 'Fundamental değer', 'VALUE'),
            ('Defensive', 'Korunma odaklı', 'DEFENSIVE'),
        ]
        for name, desc, stype in strategies:
            self._db.execute(
                "INSERT OR IGNORE INTO strategies (name, description, strategy_type) VALUES (?, ?, ?)",
                (name, desc, stype)
            )

        # Risk config
        risk_configs = [
            ('risk.max_position_pct', '10', 'Max position %'),
            ('risk.max_sector_pct', '30', 'Max sector %'),
            ('risk.max_drawdown_pct', '15', 'Max drawdown %'),
            ('risk.daily_loss_limit_pct', '5', 'Daily loss limit %'),
        ]
        for key, val, desc in risk_configs:
            self._db.execute(
                "INSERT OR IGNORE INTO system_config (config_key, config_value, description) VALUES (?, ?, ?)",
                (key, val, desc)
            )

        self._db.commit()

    async def _create_tables(self):
        """Artık migration runner tarafından yönetiliyor."""
        pass

        # Seed default data
        self._db.execute("""
            INSERT OR IGNORE INTO system_config (config_key, config_value, description)
            VALUES ('risk.max_position_pct', '10', 'Max position %')
        """)
        self._db.execute("""
            INSERT OR IGNORE INTO system_config (config_key, config_value, description)
            VALUES ('risk.max_sector_pct', '30', 'Max sector %')
        """)
        self._db.execute("""
            INSERT OR IGNORE INTO system_config (config_key, config_value, description)
            VALUES ('risk.max_drawdown_pct', '15', 'Max drawdown %')
        """)
        self._db.execute("""
            INSERT OR IGNORE INTO system_config (config_key, config_value, description)
            VALUES ('risk.daily_loss_limit_pct', '5', 'Daily loss limit %')
        """)

        # Seed sectors
        sectors = [
            ('BANK', 'Bankacılık'), ('INDUST', 'Sanayi'), ('TECH', 'Teknoloji'),
            ('ENERGY', 'Enerji'), ('RETAIL', 'Perakende'), ('CONSTR', 'İnşaat'),
            ('FOOD', 'Gıda'), ('CHEM', 'Kimya'), ('METAL', 'Metal'),
            ('TELECOM', 'Telekomünikasyon'), ('HEALTH', 'Sağlık'),
            ('REAL', 'Gayrimenkul'), ('AUTO', 'Otomotiv'), ('TEXTIL', 'Tekstil'),
            ('AVIATION', 'Havacılık'), ('HOLDING', 'Holding'), ('OTHER', 'Diğer'),
        ]
        for code, name in sectors:
            self._db.execute(
                "INSERT OR IGNORE INTO sectors (code, name) VALUES (?, ?)",
                (code, name)
            )

        # Seed strategies
        strategies = [
            ('Momentum', 'Kısa-orta vadeli momentum', 'MOMENTUM'),
            ('Breakout', 'Fiyat sıkışması kırılım', 'BREAKOUT'),
            ('Mean Reversion', 'Ortalama dönüş', 'MEAN_REVERSION'),
            ('Event Driven', 'KAP/haber bazlı', 'EVENT_DRIVEN'),
            ('SPEC', 'Olağandışı hareket tespiti', 'SPEC'),
            ('Value', 'Fundamental değer', 'VALUE'),
            ('Defensive', 'Korunma odaklı', 'DEFENSIVE'),
        ]
        for name, desc, stype in strategies:
            self._db.execute(
                "INSERT OR IGNORE INTO strategies (name, description, strategy_type) VALUES (?, ?, ?)",
                (name, desc, stype)
            )

        self._db.commit()

    # =====================================================
    # PostgreSQL-compatible async interface
    # =====================================================

    async def pg_execute(self, query: str, *args) -> str:
        """Execute query (PostgreSQL syntax → SQLite translation)."""
        q = self._translate_query(query)
        try:
            cursor = self._db.execute(q, args)
            self._db.commit()
            return f"OK {cursor.rowcount}"
        except Exception as e:
            logger.error("SQL execute error", query=query[:100], error=str(e))
            raise

    async def pg_fetch(self, query: str, *args) -> List[Dict]:
        """Fetch rows."""
        q = self._translate_query(query)
        try:
            cursor = self._db.execute(q, args)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error("SQL fetch error", query=query[:100], error=str(e))
            return []

    async def pg_fetchrow(self, query: str, *args) -> Optional[Dict]:
        """Fetch single row."""
        q = self._translate_query(query)
        try:
            cursor = self._db.execute(q, args)
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error("SQL fetchrow error", query=query[:100], error=str(e))
            return None

    async def pg_fetchval(self, query: str, *args) -> Any:
        """Fetch single value."""
        q = self._translate_query(query)
        try:
            cursor = self._db.execute(q, args)
            row = cursor.fetchone()
            if row:
                return list(row.values())[0]
            return None
        except Exception as e:
            logger.error("SQL fetchval error", query=query[:100], error=str(e))
            return None

    def _translate_query(self, query: str) -> str:
        """PostgreSQL → SQLite syntax translation."""
        q = query
        # $1, $2, ... → ?, ?, ...
        q = re.sub(r'\$(\d+)', '?', q)
        # NOW() → CURRENT_TIMESTAMP
        q = q.replace('NOW()', 'CURRENT_TIMESTAMP')
        # BOOLEAN
        q = q.replace('TRUE', '1').replace('FALSE', '0')
        # TIMESTAMPTZ → TIMESTAMP
        q = q.replace('TIMESTAMPTZ', 'TIMESTAMP')
        # SERIAL → INTEGER (SQLite handles AUTOINCREMENT)
        # ON CONFLICT DO NOTHING → INSERT OR IGNORE
        q = q.replace('ON CONFLICT', 'OR IGNORE')
        # FOR UPDATE → (SQLite doesn't need it, remove)
        q = re.sub(r'\s+FOR UPDATE', '', q)
        return q

    # =====================================================
    # Redis-compatible interface
    # =====================================================

    async def redis_get(self, key: str) -> Optional[str]:
        """Redis'ten deger oku."""
        return self._redis_store.get(key)

    async def redis_set(self, key: str, value: str, ex: Optional[int] = None):
        """Redis'e deger yaz."""
        self._redis_store[key] = value

    async def redis_delete(self, key: str):
        """Redis'ten deger sil."""
        self._redis_store.pop(key, None)

    async def redis_hgetall(self, key: str) -> Dict[str, str]:
        """Redis hash tum alanlari getir."""
        return self._redis_hashes.get(key, {})

    async def redis_hset(self, key: str, mapping: Dict[str, str]):
        """Redis hash alanlarini guncelle."""
        if key not in self._redis_hashes:
            self._redis_hashes[key] = {}
        self._redis_hashes[key].update(mapping)

    async def redis_publish(self, channel: str, message: str):
        """Redis pub/sub yayin yap."""
        handlers = self._pubsub_handlers.get(channel, [])
        for h in handlers:
            try:
                if asyncio.iscoroutinefunction(h):
                    await h({"type": "message", "channel": channel, "data": message})
                else:
                    h({"type": "message", "channel": channel, "data": message})
            except Exception as e:
                logger.error("PubSub handler error", channel=channel, error=str(e))

    def redis_subscribe(self, channel: str, handler):
        """Redis pub/sub dinle."""
        if channel not in self._pubsub_handlers:
            self._pubsub_handlers[channel] = []
        self._pubsub_handlers[channel].append(handler)

    async def close(self):
        """Baglantilari kapat."""
        if self._db:
            self._db.close()
            self._db = None

    # =====================================================
    # Convenience methods
    # =====================================================

    async def ensure_default_portfolio(self) -> int:
        """Ensure default portfolio exists, return its id."""
        row = await self.pg_fetchrow(
            "SELECT id FROM portfolios WHERE name = ? LIMIT 1",
            "ALPHA Paper Portfolio"
        )
        if row:
            return row["id"]

        await self.pg_execute("""
            INSERT INTO portfolios (name, description, initial_capital, current_capital, cash_balance, is_paper)
            VALUES (?, ?, ?, ?, ?, ?)
        """, "ALPHA Paper Portfolio", "Default automated paper trading portfolio", 10000000.0, 10000000.0, 10000000.0, 1)

        row = await self.pg_fetchrow(
            "SELECT id FROM portfolios WHERE name = ? LIMIT 1",
            "ALPHA Paper Portfolio"
        )
        return row["id"] if row else 1

    async def seed_instruments(self, tickers: List[str], get_sector_fn=None):
        """Seed instruments into database."""
        for ticker in tickers:
            sector = "OTHER"
            if get_sector_fn:
                sector = get_sector_fn(ticker)

            # Ensure sector exists
            await self.pg_execute(
                "INSERT OR IGNORE INTO sectors (code, name) VALUES (?, ?)",
                sector, sector
            )

            # Ensure company exists
            sector_row = await self.pg_fetchrow("SELECT id FROM sectors WHERE code = ?", sector)
            sector_id = sector_row["id"] if sector_row else 1

            await self.pg_execute(
                "INSERT OR IGNORE INTO companies (ticker, name, sector_id, active) VALUES (?, ?, ?, ?)",
                ticker, ticker, sector_id, True
            )

            # Ensure instrument exists
            company_row = await self.pg_fetchrow("SELECT id FROM companies WHERE ticker = ?", ticker)
            company_id = company_row["id"] if company_row else 1

            await self.pg_execute(
                "INSERT OR IGNORE INTO instruments (company_id, symbol, instrument_type, exchange, active) VALUES (?, ?, ?, ?, ?)",
                company_id, ticker, "EQUITY", "BIST", True
            )

        self._db.commit()
        logger.info("Instruments seeded", count=len(tickers))


# Singleton
dev_db = DevDatabase()
