"""
ALPHA BIST — Production Migration Runner v2.0

PostgreSQL ve SQLite uyumlu schema migration sistemi.

Güvenlik:
- Distributed lock (DB-based, çakışma engeli)
- Lock timeout + stale lock recovery
- Migration dependency validation (sıra bozulursa hata)
- Checksum doğrulama (değişmiş dosya tespiti)
- Transaction bazlı (başarısız → rollback)
- Idempotent (tekrar çalıştırılabilir)

Kullanım:
    runner = MigrationRunner(db, dialect="postgresql")
    await runner.run_pending()
    await runner.rollback_to(version)
    await runner.status()
"""

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

MIGRATIONS_DIR = Path(__file__).parent

# Lock sabitleri
LOCK_TABLE = "migration_lock"
LOCK_TIMEOUT_SECONDS = 300  # 5 dakika
LOCK_OWNER_PREFIX = "alpha_migrate_"


@dataclass
class MigrationFile:
    """Parsed migration dosyası."""

    version: int
    name: str
    up_sql: str
    down_sql: str
    checksum: str

    @staticmethod
    def parse(filepath: Path) -> "MigrationFile":
        """Otomatik eklendi."""
        match = re.match(r"v(\d+)_(.+)\.sql", filepath.name)
        if not match:
            raise ValueError(f"Geçersiz migration dosyası: {filepath.name}")

        version = int(match.group(1))
        name = match.group(2)
        content = filepath.read_text(encoding="utf-8")

        if "-- migrate:down" in content:
            parts = content.split("-- migrate:down")
            up_sql = parts[0].strip()
            down_sql = parts[1].strip()
        else:
            up_sql = content.strip()
            down_sql = ""

        checksum = hashlib.sha256(up_sql.encode("utf-8")).hexdigest()[:16]

        return MigrationFile(
            version=version,
            name=name,
            up_sql=up_sql,
            down_sql=down_sql,
            checksum=checksum,
        )


@dataclass
class MigrationStatus:
    """Otomatik eklendi."""
    current_version: int
    pending_count: int
    applied: list[dict[str, Any]]
    pending: list[dict[str, Any]]


class MigrationLockError(Exception):
    """Migration lock alınamadı."""


class MigrationRunner:
    """Production-grade migration runner with distributed locking."""

    def __init__(self, db, dialect: str = "postgresql"):
        """Otomatik eklendi."""
        self._db = db
        self._dialect = dialect
        self._lock_id: str | None = None
        self._heartbeat_task: asyncio.Task | None = None

    # =====================================================
    # LOCK TABLE
    # =====================================================

    async def _init_lock_table(self) -> Any:
        """Lock tablosunu oluştur."""
        await self._execute(f"""
            CREATE TABLE IF NOT EXISTS {LOCK_TABLE} (
                lock_key TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                acquired_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
        """)

    async def _acquire_lock(self) -> bool:
        """Distributed lock al.

        Returns:
            True: lock alındı
            False: başka bir instance kilitli (timeout dolmamış)
        """
        import uuid

        await self._init_lock_table()

        self._lock_id = f"{LOCK_OWNER_PREFIX}{uuid.uuid4().hex[:8]}"
        now = time.time()
        expires = now + LOCK_TIMEOUT_SECONDS

        # Stale lock temizle (timeout aşmış)
        await self._execute(f"DELETE FROM {LOCK_TABLE} WHERE expires_at < ?", now)

        # Lock almayı dene (INSERT = atomic, çakışma yok)
        try:
            await self._execute(
                f"INSERT INTO {LOCK_TABLE} (lock_key, owner, acquired_at, expires_at) VALUES (?, ?, ?, ?)",
                "migration",
                self._lock_id,
                now,
                expires,
            )
            logger.info("Migration lock acquired", owner=self._lock_id)
            self._start_heartbeat()
            return True
        except Exception:
            # Lock zaten var — timeout kontrolü
            row = await self._fetchone(
                f"SELECT owner, acquired_at, expires_at FROM {LOCK_TABLE} WHERE lock_key = ?", "migration"
            )
            if row:
                if row["expires_at"] < now:
                    # Stale lock — zorla al
                    await self._execute(
                        f"UPDATE {LOCK_TABLE} SET owner = ?, acquired_at = ?, expires_at = ? WHERE lock_key = ?",
                        self._lock_id,
                        now,
                        expires,
                        "migration",
                    )
                    logger.warning("Stale migration lock recovered", old_owner=row["owner"])
                    return True
                else:
                    logger.warning(
                        "Migration locked by another instance",
                        owner=row["owner"],
                        remaining_sec=int(row["expires_at"] - now),
                    )
                    return False
            return False

    async def _release_lock(self) -> Any:
        """Lock'u serbest bırak."""
        self._stop_heartbeat()
        if self._lock_id:
            try:
                await self._execute(
                    f"DELETE FROM {LOCK_TABLE} WHERE lock_key = ? AND owner = ?", "migration", self._lock_id
                )
                logger.info("Migration lock released", owner=self._lock_id)
            except Exception as e:
                logger.debug("Handled exception", error=str(e), context="runner.py:174")
            self._lock_id = None

    async def _refresh_lock(self) -> Any:
        """Lock süresini uzat."""
        if self._lock_id:
            try:
                new_expires = time.time() + LOCK_TIMEOUT_SECONDS
                await self._execute(
                    f"UPDATE {LOCK_TABLE} SET expires_at = ? WHERE lock_key = ? AND owner = ?",
                    new_expires,
                    "migration",
                    self._lock_id,
                )
            except Exception as e:
                logger.debug("Handled exception", error=str(e), context="runner.py:187")

    def _start_heartbeat(self) -> Any:
        """Arka planda lock süresini otomatik yenile."""
        if self._heartbeat_task is not None:
            return

        async def _heartbeat_loop() -> Any:
            """Otomatik eklendi."""
            while True:
                try:
                    await asyncio.sleep(LOCK_TIMEOUT_SECONDS // 3)
                    await self._refresh_lock()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug("Handled exception", error=str(e), context="runner.py:201")

        try:
            self._heartbeat_task = asyncio.ensure_future(_heartbeat_loop())
        except RuntimeError:
            logger.warning("Runtime error in _heartbeat_loop", exc_info=True)

    def _stop_heartbeat(self) -> Any:
        """Heartbeat durdur."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

    # =====================================================
    # INIT
    # =====================================================

    async def init_schema_migrations(self) -> Any:
        """Otomatik eklendi."""
        ts_type = "TIMESTAMP" if self._dialect == "sqlite" else "TIMESTAMPTZ"
        default_ts = "CURRENT_TIMESTAMP" if self._dialect == "sqlite" else "NOW()"
        await self._execute(f"""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL DEFAULT '',
                applied_at {ts_type} DEFAULT {default_ts}
            )
        """)

    # =====================================================
    # DISCOVERY
    # =====================================================

    def discover_migrations(self) -> list[MigrationFile]:
        """Otomatik eklendi."""
        migrations = []
        for f in sorted(MIGRATIONS_DIR.glob("v*.sql")):
            try:
                migrations.append(MigrationFile.parse(f))
            except ValueError as e:
                logger.warning("Skipping invalid migration file", error=str(e))
        return migrations

    async def get_applied(self) -> dict[int, dict[str, Any]]:
        """Otomatik eklendi."""
        try:
            rows = await self._fetchall(
                "SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version"
            )
            return {r["version"]: dict(r) for r in rows}
        except Exception:
            return {}

    async def get_current_version(self) -> int:
        """Otomatik eklendi."""
        applied = await self.get_applied()
        return max(applied.keys()) if applied else 0

    # =====================================================
    # DEPENDENCY VALIDATION
    # =====================================================

    def _validate_dependencies(self, migrations: list[MigrationFile], applied: dict[int, dict]) -> Any:
        """Migration bağımlılıklarını doğrula.

        Kural: Uygulanmış migration'lar arasında boşluk olmamalı.
        Örn: v1 ve v3 uygulanmış ama v2 yoksa hata ver.
        İlk çalıştırmada (applied boş) sorun yok.
        """
        all_versions = sorted([m.version for m in migrations])
        applied_versions = sorted(applied.keys())

        if not applied_versions:
            return  # İlk çalıştırmada sorun yok

        # Uygulanmış version'lar arasında boşluk var mı?
        max_applied = max(applied_versions)
        expected = set(range(1, max_applied + 1))
        missing = expected - set(applied_versions)
        if missing:
            raise RuntimeError(
                f"Migration sırasında boşluk tespit edildi! "
                f"Eksik version'lar: {sorted(missing)}. "
                f"Bu, bir migration'ın silindiğini veya atlandığını gösterir."
            )

        # Uygulanmış version'lar dosya sistemiyle uyumlu mu?
        available_versions = set(all_versions)
        for v in applied_versions:
            if v not in available_versions:
                raise RuntimeError(
                    f"DB'de v{v:03d} uygulanmış ama dosyası bulunamadı! Migration dosyası silinmiş olabilir."
                )

    # =====================================================
    # STATUS
    # =====================================================

    async def status(self) -> MigrationStatus:
        """Otomatik eklendi."""
        await self.init_schema_migrations()
        applied_map = await self.get_applied()
        all_migrations = self.discover_migrations()

        applied_list = []
        pending_list = []

        for m in all_migrations:
            info = {"version": m.version, "name": m.name, "checksum": m.checksum}
            if m.version in applied_map:
                db_info = applied_map[m.version]
                info["applied_at"] = db_info.get("applied_at", "")
                info["checksum_match"] = db_info.get("checksum", "") == m.checksum
                applied_list.append(info)
            else:
                pending_list.append(info)

        return MigrationStatus(
            current_version=max(applied_map.keys()) if applied_map else 0,
            pending_count=len(pending_list),
            applied=applied_list,
            pending=pending_list,
        )

    # =====================================================
    # RUN (UP) — with distributed lock
    # =====================================================

    async def run_pending(self) -> list[int]:
        """Bekleyen migration'ları uygula (distributed lock ile)."""
        # Lock al
        if not await self._acquire_lock():
            raise MigrationLockError(
                "Migration kilitli — başka bir instance migration çalıştırıyor. "
                "Lütfen bekleyin veya kilit timeout'unu (300s) bekleyin."
            )

        try:
            await self.init_schema_migrations()
            applied_map = await self.get_applied()
            all_migrations = self.discover_migrations()

            # Dependency validation
            self._validate_dependencies(all_migrations, applied_map)

            applied_versions = []
            for m in all_migrations:
                if m.version in applied_map:
                    # Checksum doğrula
                    db_checksum = applied_map[m.version].get("checksum", "")
                    if db_checksum and db_checksum != m.checksum:
                        raise RuntimeError(
                            f"Migration v{m.version:03d} checksum değişmiş! "
                            f"DB: {db_checksum}, Dosya: {m.checksum}. "
                            f"Güvenli devam için manuel müdahale gerekli."
                        )
                    continue

                logger.info("Applying migration", version=m.version, name=m.name)
                try:
                    await self._apply_up(m)
                    applied_versions.append(m.version)
                    logger.info("Migration applied", version=m.version)
                except Exception as e:
                    logger.error("Migration failed", version=m.version, error=str(e))
                    raise

            if not applied_versions:
                logger.info("No pending migrations")

            return applied_versions

        finally:
            await self._release_lock()

    async def _apply_up(self, m: MigrationFile) -> Any:
        """Tek bir up migration uygula."""
        statements = self._split_statements(m.up_sql)

        await self._begin_transaction()
        try:
            for stmt in statements:
                stmt = self._prepare_statement(stmt)
                if stmt:
                    await self._execute_safe(stmt)
                    # Uzun migration'larda lock yenile
                    await self._refresh_lock()

            await self._execute(
                "INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)",
                m.version,
                m.name,
                m.checksum,
            )
            await self._commit()
        except Exception:
            await self._rollback()
            raise

    # =====================================================
    # ROLLBACK (DOWN) — with distributed lock
    # =====================================================

    async def rollback_to(self, target_version: int) -> list[int]:
        """Belirli version'a geri al (distributed lock ile)."""
        if not await self._acquire_lock():
            raise MigrationLockError("Migration kilitli — rollback yapılamıyor.")

        try:
            await self.init_schema_migrations()
            applied_map = await self.get_applied()
            all_migrations = self.discover_migrations()

            to_rollback = sorted([v for v in applied_map if v > target_version], reverse=True)

            if not to_rollback:
                logger.info("Nothing to rollback", target=target_version)
                return []

            rolled_back = []
            for version in to_rollback:
                m = next((m for m in all_migrations if m.version == version), None)
                if not m:
                    raise RuntimeError(f"Rollback için migration dosyası bulunamadı: v{version:03d}")
                if not m.down_sql:
                    raise RuntimeError(f"v{version:03d} için down migration tanımlanmamış")

                logger.info("Rolling back migration", version=version, name=m.name)
                try:
                    await self._apply_down(m)
                    rolled_back.append(version)
                    logger.info("Migration rolled back", version=version)
                except Exception as e:
                    logger.error("Rollback failed", version=version, error=str(e))
                    raise

            return rolled_back

        finally:
            await self._release_lock()

    async def _apply_down(self, m: MigrationFile) -> Any:
        """Otomatik eklendi."""
        statements = self._split_statements(m.down_sql)
        await self._begin_transaction()
        try:
            for stmt in statements:
                stmt = self._prepare_statement(stmt)
                if stmt:
                    await self._execute_safe(stmt)
            await self._execute("DELETE FROM schema_migrations WHERE version = ?", m.version)
            await self._commit()
        except Exception:
            await self._rollback()
            raise

    # =====================================================
    # TRANSACTION MANAGEMENT
    # =====================================================

    async def _begin_transaction(self) -> Any:
        """Otomatik eklendi."""
        if self._dialect == "sqlite":
            pass  # DuckDB auto-transaction
        else:
            await self._db.execute("BEGIN")

    async def _commit(self) -> Any:
        """Otomatik eklendi."""
        if self._dialect == "sqlite":
            self._db.commit()
        else:
            await self._db.execute("COMMIT")

    async def _rollback(self) -> Any:
        """Otomatik eklendi."""
        try:
            if self._dialect == "sqlite":
                self._db.rollback()
            else:
                await self._db.execute("ROLLBACK")
            logger.info("Transaction rolled back")
        except Exception as e:
            logger.error("Rollback failed", error=str(e))

    # =====================================================
    # SQL PREPARATION
    # =====================================================

    def _prepare_statement(self, stmt: str) -> str | None:
        """Otomatik eklendi."""
        stmt = stmt.strip()
        if not stmt:
            return None
        lines = []
        for line in stmt.split("\n"):
            stripped = line.strip()
            if stripped.startswith("--") and "migrate:" not in stripped:
                continue
            lines.append(line)
        stmt = "\n".join(lines).strip()
        if not stmt:
            return None
        if self._dialect == "sqlite":
            stmt = self._pg_to_sqlite(stmt)
        return stmt

    def _split_statements(self, sql: str) -> list[str]:
        """Otomatik eklendi."""
        if "-- migrate:split" in sql:
            parts = sql.split("-- migrate:split")
            return [p.strip() for p in parts if p.strip()]

        statements = []
        current = []
        in_create = False

        for line in sql.split("\n"):
            stripped = line.strip()
            if stripped.startswith("--") and "migrate:" not in stripped:
                continue
            if "CREATE TABLE" in stripped.upper():
                in_create = True
            current.append(line)
            if in_create and stripped == ");":
                statements.append("\n".join(current))
                current = []
                in_create = False
            elif not in_create and stripped.endswith(";"):
                statements.append("\n".join(current))
                current = []

        if current:
            remaining = "\n".join(current).strip()
            if remaining:
                statements.append(remaining)
        return statements

    def _pg_to_sqlite(self, stmt: str) -> str:
        """Otomatik eklendi."""
        s = stmt
        s = s.replace("TIMESTAMPTZ", "TIMESTAMP")
        s = re.sub(r"\bBOOLEAN\b", "INTEGER", s, flags=re.IGNORECASE)
        s = re.sub(r"\bTRUE\b", "1", s)
        s = re.sub(r"\bFALSE\b", "0", s)
        s = s.replace("NOW()", "CURRENT_TIMESTAMP")
        s = re.sub(r"\bBIGSERIAL\b", "INTEGER", s, flags=re.IGNORECASE)
        s = re.sub(r"\bSERIAL\b", "INTEGER", s, flags=re.IGNORECASE)
        s = re.sub(r"VARCHAR\(\d+\)", "TEXT", s, flags=re.IGNORECASE)
        s = re.sub(r"\$(\d+)", "?", s)
        # INSERT ... ON CONFLICT (...) DO NOTHING  ->  INSERT OR IGNORE ...
        s = (
            re.sub(
                r"\bINSERT\b",
                "INSERT OR IGNORE",
                s,
                flags=re.IGNORECASE,
            )
            if re.search(r"ON CONFLICT\s+\([^)]+\)\s+DO NOTHING", s, re.IGNORECASE)
            else s
        )
        s = re.sub(r"ON CONFLICT\s+\([^)]+\)\s+DO NOTHING", "", s, flags=re.IGNORECASE)
        # Partial indexes (WHERE clause) - SQLite supports them but strip them from UNIQUE CREATE INDEX WHERE for safety
        s = re.sub(
            r"(CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF NOT EXISTS\s+)?\w+\s+ON\s+\w+\s*\([^)]+\))\s+WHERE\s+[^\n;]+",
            r"\1",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(r"\s+FOR UPDATE", "", s, flags=re.IGNORECASE)
        s = re.sub(r"GENERATED ALWAYS AS\s*\([^)]+\)", "", s, flags=re.IGNORECASE)
        s = re.sub(
            r"ALTER TABLE\s+(\w+)\s+ADD COLUMN\s+IF NOT EXISTS", r"ALTER TABLE \1 ADD COLUMN", s, flags=re.IGNORECASE
        )
        s = re.sub(r"\bDOUBLE PRECISION\b", "REAL", s, flags=re.IGNORECASE)
        s = re.sub(r"\bJSONB\b", "TEXT", s, flags=re.IGNORECASE)
        s = re.sub(r"\bDECIMAL\(\d+,\d+\)\b", "REAL", s, flags=re.IGNORECASE)
        return s

    # =====================================================
    # SAFE EXECUTION
    # =====================================================

    async def _execute_safe(self, sql: str) -> Any:
        """Otomatik eklendi."""
        try:
            await self._execute(sql)
        except Exception as e:
            error_msg = str(e).lower()
            if "duplicate column" in error_msg or "already exists" in error_msg:
                logger.info("Column/table already exists, skipping", sql=sql[:80])
                return
            if "table" in error_msg and "already exists" in error_msg:
                logger.info("Table already exists, skipping", sql=sql[:80])
                return
            raise

    async def _execute(self, sql: str, *args) -> Any:
        """Otomatik eklendi."""
        if self._dialect == "sqlite":
            if args:
                # Parametreli sorgular tek statement olmalı
                cursor = self._db.execute(sql, args)
            else:
                # Parametresiz: statement'ları ayrı ayrı çalıştır
                for stmt in self._split_statements(sql):
                    stmt = stmt.strip()
                    if stmt:
                        self._db.execute(stmt)
                cursor = None
            self._db.commit()
            return cursor
        else:
            return await self._db.execute(sql, *args)

    async def _fetchall(self, sql: str, *args) -> list[dict]:
        """Otomatik eklendi."""
        if self._dialect == "sqlite":
            cursor = self._db.execute(sql, args)
            return [dict(r) for r in cursor.fetchall()]
        else:
            return [dict(r) for r in await self._db.fetch(sql, *args)]

    async def _fetchone(self, sql: str, *args) -> dict | None:
        """Otomatik eklendi."""
        if self._dialect == "sqlite":
            cursor = self._db.execute(sql, args)
            row = cursor.fetchone()
            return dict(row) if row else None
        else:
            row = await self._db.fetchrow(sql, *args)
            return dict(row) if row else None
