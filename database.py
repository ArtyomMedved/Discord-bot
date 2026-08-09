"""Слой работы с SQLite.

Операции выполняются в отдельном потоке через asyncio.to_thread,
чтобы не блокировать event loop. Запись защищена блокировкой,
а переходы статусов — атомарными UPDATE с проверкой текущего статуса
(защита от одновременной обработки одной заявки).
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DATA_DIR / "afk.sqlite3"

STATUS_PENDING = "PENDING"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"
STATUS_EXPIRED = "EXPIRED"
STATUS_CANCELLED = "CANCELLED"

ACTIVE_STATUSES = (STATUS_PENDING, STATUS_APPROVED)
FINISHED_STATUSES = (STATUS_REJECTED, STATUS_EXPIRED, STATUS_CANCELLED)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS afk (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL,
    guild_id         INTEGER NOT NULL,
    reason           TEXT    NOT NULL DEFAULT '',
    start_time       TEXT    NOT NULL,
    end_time         TEXT    NOT NULL,
    status           TEXT    NOT NULL DEFAULT 'PENDING',
    created_at       TEXT    NOT NULL,
    reviewed_at      TEXT,
    reviewed_by      INTEGER,
    rejection_reason TEXT,
    message_id       INTEGER,
    channel_id       INTEGER
);

CREATE INDEX IF NOT EXISTS idx_afk_user ON afk (user_id, status);
CREATE INDEX IF NOT EXISTS idx_afk_status ON afk (status);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS soul_coins (
    user_id    INTEGER PRIMARY KEY,
    guild_id   INTEGER NOT NULL DEFAULT 0,
    month_key  TEXT NOT NULL DEFAULT '',
    balance    INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS soul_coin_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    guild_id     INTEGER NOT NULL,
    change       INTEGER NOT NULL,
    balance      INTEGER NOT NULL,
    reason       TEXT NOT NULL DEFAULT '',
    moderator_id INTEGER NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_soul_logs_user ON soul_coin_logs (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS verifications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    guild_id     INTEGER NOT NULL DEFAULT 0,
    static       TEXT NOT NULL DEFAULT '',
    in_game_name TEXT NOT NULL DEFAULT '',
    real_name    TEXT NOT NULL DEFAULT '',
    occupation   TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_verifications_user ON verifications (user_id);
"""

# Сколько резервных копий БД хранить (data/backups)
BACKUP_KEEP = 7


class Database:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

    # ---------- низкоуровневые синхронные операции ----------

    def connect(self) -> None:
        """Создаёт файл БД и таблицы, если их ещё нет."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # timeout: при конкурентной записи ждём до 10 c вместо «database is locked».
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10.0)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            # synchronous=FULL: каждая транзакция ждёт записи на диск — надёжность важнее скорости.
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.execute("PRAGMA busy_timeout=10000")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        """Закрывает соединение, предварительно сводя WAL в основную базу."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.Error:
                    pass
                self._conn.close()
                self._conn = None

    # ---------- транзакции и резервные копии ----------

    def _tx(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        """Атомарная транзакция: BEGIN IMMEDIATE … COMMIT/ROLLBACK.

        Вызывается ТОЛЬКО изнутри _run (блокировка уже удержана).
        """
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            result = fn(self._conn)
        except BaseException:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()
            return result

    async def transaction(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        """Публичная async-обёртка для атомарных многокомандных операций."""
        return await self._run(self._tx, fn)

    def create_backup(self) -> Optional[Path]:
        """Консистентная копия БД (backup API корректно работает с WAL)."""
        backups_dir = DATA_DIR / "backups"
        try:
            backups_dir.mkdir(parents=True, exist_ok=True)
            dest = backups_dir / f"afk-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
            src = sqlite3.connect(self.path)
            dst = sqlite3.connect(dest)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            self._prune_backups()
            logger.info("Резервная копия БД: %s", dest)
            return dest
        except (sqlite3.Error, OSError):
            logger.exception("Не удалось создать резервную копию БД")
            return None

    async def backup_now(self) -> Optional[Path]:
        return await asyncio.to_thread(self.create_backup)

    def _prune_backups(self) -> None:
        backups_dir = DATA_DIR / "backups"
        try:
            files = sorted(backups_dir.glob("afk-*.sqlite3"))
            for old in files[:-BACKUP_KEEP]:
                old.unlink(missing_ok=True)
        except OSError:
            logger.warning("Не удалось очистить старые резервные копии")

    def _execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        cur = self._conn.execute(query, params)
        self._conn.commit()
        return cur

    def _fetch_one(self, query: str, params: tuple = ()) -> Optional[dict]:
        cur = self._conn.execute(query, params)
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def _fetch_all(self, query: str, params: tuple = ()) -> list[dict]:
        cur = self._conn.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

    async def _run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        def _target():
            with self._lock:
                return fn(*args, **kwargs)
        return await asyncio.to_thread(_target)

    # ---------- публичный API (async) ----------

    async def create_afk(
        self,
        *,
        user_id: int,
        guild_id: int,
        reason: str,
        start_time: str,
        end_time: str,
        created_at: str,
    ) -> int:
        def _create():
            cur = self._execute(
                "INSERT INTO afk "
                "(user_id, guild_id, reason, start_time, end_time, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, guild_id, reason, start_time, end_time, STATUS_PENDING, created_at),
            )
            return cur.lastrowid
        return await self._run(_create)

    async def get_afk(self, afk_id: int) -> Optional[dict]:
        return await self._run(self._fetch_one, "SELECT * FROM afk WHERE id = ?", (afk_id,))

    async def get_active_afk_for_user(self, user_id: int) -> Optional[dict]:
        placeholders = ",".join("?" * len(ACTIVE_STATUSES))
        return await self._run(
            self._fetch_one,
            f"SELECT * FROM afk WHERE user_id = ? AND status IN ({placeholders}) "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id, *ACTIVE_STATUSES),
        )

    async def list_afks(self, status: Optional[str] = None, limit: int = 100) -> list[dict]:
        if status:
            return await self._run(
                self._fetch_all,
                "SELECT * FROM afk WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        return await self._run(
            self._fetch_all,
            "SELECT * FROM afk ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )

    async def list_approved_afks(self) -> list[dict]:
        return await self._run(
            self._fetch_all,
            "SELECT * FROM afk WHERE status = ? ORDER BY end_time ASC",
            (STATUS_APPROVED,),
        )

    async def approve_afk(self, afk_id: int, reviewed_by: int, reviewed_at: str) -> bool:
        def _approve():
            cur = self._execute(
                "UPDATE afk SET status = ?, reviewed_by = ?, reviewed_at = ? "
                "WHERE id = ? AND status = ?",
                (STATUS_APPROVED, reviewed_by, reviewed_at, afk_id, STATUS_PENDING),
            )
            return cur.rowcount > 0
        return await self._run(_approve)

    async def reject_afk(self, afk_id: int, reviewed_by: int, reviewed_at: str, reason: str) -> bool:
        def _reject():
            cur = self._execute(
                "UPDATE afk SET status = ?, reviewed_by = ?, reviewed_at = ?, rejection_reason = ? "
                "WHERE id = ? AND status = ?",
                (STATUS_REJECTED, reviewed_by, reviewed_at, reason, afk_id, STATUS_PENDING),
            )
            return cur.rowcount > 0
        return await self._run(_reject)

    async def cancel_afk(
        self,
        afk_id: int,
        reviewed_by: Optional[int] = None,
        reviewed_at: Optional[str] = None,
    ) -> bool:
        def _cancel():
            placeholders = ",".join("?" * len(ACTIVE_STATUSES))
            cur = self._execute(
                f"UPDATE afk SET status = ?, "
                f"reviewed_by = COALESCE(?, reviewed_by), "
                f"reviewed_at = COALESCE(?, reviewed_at) "
                f"WHERE id = ? AND status IN ({placeholders})",
                (STATUS_CANCELLED, reviewed_by, reviewed_at, afk_id, *ACTIVE_STATUSES),
            )
            return cur.rowcount > 0
        return await self._run(_cancel)

    async def mark_expired(self, afk_id: int) -> bool:
        def _expire():
            cur = self._execute(
                "UPDATE afk SET status = ? WHERE id = ? AND status = ?",
                (STATUS_EXPIRED, afk_id, STATUS_APPROVED),
            )
            return cur.rowcount > 0
        return await self._run(_expire)

    async def set_afk_message(self, afk_id: int, message_id: int, channel_id: int) -> None:
        def _set():
            self._execute(
                "UPDATE afk SET message_id = ?, channel_id = ? WHERE id = ?",
                (message_id, channel_id, afk_id),
            )
        await self._run(_set)

    async def delete_finished(self) -> int:
        def _delete():
            placeholders = ",".join("?" * len(FINISHED_STATUSES))
            cur = self._execute(
                f"DELETE FROM afk WHERE status IN ({placeholders})",
                FINISHED_STATUSES,
            )
            return cur.rowcount
        return await self._run(_delete)

    async def set_setting(self, key: str, value: Optional[str]) -> None:
        def _set():
            if value is None:
                self._execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                self._execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
        await self._run(_set)

    async def get_setting(self, key: str) -> Optional[str]:
        row = await self._run(self._fetch_one, "SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else None

    # ---------- Soul-Coins ----------

    async def get_soul_balance(self, user_id: int, month_key: str) -> int:
        """Баланс игрока за конкретный месяц (0, если записи нет)."""

        def _get() -> int:
            row = self._fetch_one(
                "SELECT balance FROM soul_coins WHERE user_id = ? AND month_key = ?",
                (user_id, month_key),
            )
            return row["balance"] if row else 0
        return await self._run(_get)

    async def list_soul_balances(self, month_key: Optional[str] = None) -> list[dict]:
        if month_key:
            return await self._run(
                self._fetch_all,
                "SELECT * FROM soul_coins WHERE month_key = ?",
                (month_key,),
            )
        return await self._run(self._fetch_all, "SELECT * FROM soul_coins")

    async def add_soul_transaction(
        self,
        *,
        user_id: int,
        guild_id: int,
        month_key: str,
        change: int,
        balance: int,
        reason: str,
        moderator_id: int,
        created_at: str,
    ) -> None:
        """Атомарно: обновляет баланс и пишет запись в лог."""
        def _tx(conn):
            conn.execute(
                "INSERT INTO soul_coins (user_id, guild_id, month_key, balance, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "guild_id = excluded.guild_id, month_key = excluded.month_key, "
                "balance = excluded.balance, updated_at = excluded.updated_at",
                (user_id, guild_id, month_key, balance, created_at),
            )
            conn.execute(
                "INSERT INTO soul_coin_logs "
                "(user_id, guild_id, change, balance, reason, moderator_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, guild_id, change, balance, reason, moderator_id, created_at),
            )
        await self._run(self._tx, _tx)

    async def reset_soul_balances(self, new_month: str, guild_id: int = 0) -> None:
        """Начало нового месяца: обнуляет балансы и атомарно фиксирует месяц.

        Оба изменения в одной транзакции, чтобы при сбое не получить
        обнулённые балансы с «не закрытым» месяцем (иначе повторный запуск
        проверил бы всех как невыполнивших норму).
        """
        def _tx(conn):
            conn.execute(
                "UPDATE soul_coins SET month_key = ?, balance = 0, updated_at = ?",
                (new_month, datetime.now(timezone.utc).isoformat()),
            )
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('soul_month_key', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (new_month,),
            )
        await self._run(self._tx, _tx)

    async def get_soul_logs(self, user_id: int, limit: int = 20) -> list[dict]:
        return await self._run(
            self._fetch_all,
            "SELECT * FROM soul_coin_logs WHERE user_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (user_id, limit),
        )

    # ---------- Верификация ----------

    async def create_verification(
        self,
        *,
        user_id: int,
        guild_id: int,
        static: str,
        in_game_name: str,
        real_name: str,
        occupation: str,
        created_at: str,
    ) -> None:
        def _insert() -> None:
            self._execute(
                "INSERT INTO verifications "
                "(user_id, guild_id, static, in_game_name, real_name, occupation, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, guild_id, static, in_game_name, real_name, occupation, created_at),
            )
        await self._run(_insert)

    async def get_verification(self, user_id: int) -> Optional[dict]:
        """Последняя верификация пользователя (или None)."""
        return await self._run(
            self._fetch_one,
            "SELECT * FROM verifications WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        )


db = Database(DB_PATH)
