"""
ALPHA BIST — Development Database Adapter

Docker/PostgreSQL/Redis olmadığında SQLite + InMemory kullanır.
Production'da database.py kullanılır.

Kullanım:
  from services.core.database_dev import dev_db
"""

import asyncio
import json
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
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(DB_PATH))
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        await self._create_tables()
        logger.info("Dev database initialized", path=str(DB_PATH))

    async def _create_tables(self):
        """Create tables matching PostgreSQL schema."""
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS sectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                sector_id INTEGER REFERENCES sectors(id),
                active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS instruments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER REFERENCES companies(id),
                symbol TEXT UNIQUE NOT NULL,
                instrument_type TEXT DEFAULT 'EQUITY',
                exchange TEXT DEFAULT 'BIST',
                active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS portfolios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                initial_capital REAL NOT NULL DEFAULT 100000,
                current_capital REAL NOT NULL DEFAULT 100000,
                cash_balance REAL NOT NULL DEFAULT 100000,
                invested_value REAL DEFAULT 0,
                total_pnl REAL DEFAULT 0,
                total_return_pct REAL DEFAULT 0,
                status TEXT DEFAULT 'ACTIVE',
                is_paper BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_id INTEGER REFERENCES portfolios(id),
                instrument_id INTEGER REFERENCES instruments(id),
                quantity INTEGER NOT NULL DEFAULT 0,
                avg_cost REAL NOT NULL,
                current_price REAL,
                market_value REAL,
                unrealized_pnl REAL DEFAULT 0,
                unrealized_pnl_pct REAL DEFAULT 0,
                weight_pct REAL,
                entry_date TIMESTAMP,
                status TEXT DEFAULT 'OPEN',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(portfolio_id, instrument_id)
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_id INTEGER REFERENCES portfolios(id),
                instrument_id INTEGER REFERENCES instruments(id),
                order_type TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL,
                filled_quantity INTEGER DEFAULT 0,
                avg_fill_price REAL,
                status TEXT DEFAULT 'PENDING',
                source TEXT DEFAULT 'MANUAL',
                signal_id INTEGER,
                placed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                filled_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER REFERENCES orders(id),
                instrument_id INTEGER REFERENCES instruments(id),
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL,
                commission REAL DEFAULT 0,
                filled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_id INTEGER REFERENCES instruments(id),
                signal_type TEXT NOT NULL,
                direction TEXT,
                score REAL,
                confidence REAL,
                risk_level TEXT,
                horizon TEXT,
                expected_return_pct REAL,
                reasoning TEXT,
                model_version TEXT,
                status TEXT DEFAULT 'ACTIVE',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS system_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                config_key TEXT UNIQUE NOT NULL,
                config_value TEXT NOT NULL,
                description TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                strategy_type TEXT,
                status TEXT DEFAULT 'ACTIVE',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS models (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                model_type TEXT,
                status TEXT DEFAULT 'DRAFT',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS model_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id INTEGER REFERENCES models(id),
                version TEXT NOT NULL,
                metrics TEXT DEFAULT '{}',
                status TEXT DEFAULT 'CANDIDATE',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(model_id, version)
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT,
                instrument_id INTEGER,
                data TEXT DEFAULT '{}',
                acknowledged BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                entity_type TEXT,
                entity_id INTEGER,
                actor TEXT DEFAULT 'SYSTEM',
                details TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

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
        import re
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
        return self._redis_store.get(key)

    async def redis_set(self, key: str, value: str, ex: Optional[int] = None):
        self._redis_store[key] = value

    async def redis_delete(self, key: str):
        self._redis_store.pop(key, None)

    async def redis_hgetall(self, key: str) -> Dict[str, str]:
        return self._redis_hashes.get(key, {})

    async def redis_hset(self, key: str, mapping: Dict[str, str]):
        if key not in self._redis_hashes:
            self._redis_hashes[key] = {}
        self._redis_hashes[key].update(mapping)

    async def redis_publish(self, channel: str, message: str):
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
        if channel not in self._pubsub_handlers:
            self._pubsub_handlers[channel] = []
        self._pubsub_handlers[channel].append(handler)

    async def close(self):
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
        """, "ALPHA Paper Portfolio", "Default paper trading portfolio", 100000, 100000, 100000, True)

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
