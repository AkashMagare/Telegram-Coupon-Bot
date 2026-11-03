"""SQLite persistence and search for coupon data."""

from __future__ import annotations

import datetime as dt
import logging
import math
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Coupon:
    """A coupon offer stored by the bot."""

    id: int
    code: str
    title: str
    store: str
    description: str
    category: str
    discount: str
    url: str | None
    expires_at: str | None
    created_at: str
    is_active: bool
    view_count: int
    used_count: int


@dataclass(frozen=True, slots=True)
class CouponPage:
    """A page of coupons and the total number of matching records."""

    items: tuple[Coupon, ...]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(self.total / self.page_size))


class CouponRepository:
    """Thread-safe repository using one SQLite connection per bot process."""

    def __init__(self, database_path: str) -> None:
        if database_path != ":memory:":
            Path(database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(
            database_path,
            check_same_thread=False,
            timeout=30,
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._fts_enabled = False
        self._configure()
        self._create_schema()

    def _configure(self) -> None:
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = NORMAL")

    def _create_schema(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS coupons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL COLLATE NOCASE,
            title TEXT NOT NULL,
            store TEXT NOT NULL COLLATE NOCASE,
            description TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'Other' COLLATE NOCASE,
            discount TEXT NOT NULL DEFAULT 'Special offer',
            url TEXT,
            expires_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_by INTEGER,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            view_count INTEGER NOT NULL DEFAULT 0,
            used_count INTEGER NOT NULL DEFAULT 0,
            UNIQUE (store, code)
        );

        CREATE INDEX IF NOT EXISTS idx_coupons_active_expiry
            ON coupons (is_active, expires_at);
        CREATE INDEX IF NOT EXISTS idx_coupons_category
            ON coupons (category, is_active);
        CREATE INDEX IF NOT EXISTS idx_coupons_store
            ON coupons (store, is_active);
        """
        with self._lock, self._connection:
            self._connection.executescript(schema)
            self._setup_full_text_search()

    def _setup_full_text_search(self) -> None:
        """Enable FTS5 when the local SQLite build provides it.

        SQLite builds without FTS5 still work through the indexed LIKE fallback.
        """

        try:
            table_exists = self._connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'coupons_fts'"
            ).fetchone()
            self._connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS coupons_fts USING fts5(
                    code, title, store, description, category,
                    content='coupons', content_rowid='id'
                )
                """
            )
            self._connection.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS coupons_ai AFTER INSERT ON coupons BEGIN
                    INSERT INTO coupons_fts(rowid, code, title, store, description, category)
                    VALUES (new.id, new.code, new.title, new.store, new.description, new.category);
                END;
                CREATE TRIGGER IF NOT EXISTS coupons_au AFTER UPDATE ON coupons BEGIN
                    INSERT INTO coupons_fts(coupons_fts, rowid, code, title, store, description, category)
                    VALUES ('delete', old.id, old.code, old.title, old.store, old.description, old.category);
                    INSERT INTO coupons_fts(rowid, code, title, store, description, category)
                    VALUES (new.id, new.code, new.title, new.store, new.description, new.category);
                END;
                CREATE TRIGGER IF NOT EXISTS coupons_ad AFTER DELETE ON coupons BEGIN
                    INSERT INTO coupons_fts(coupons_fts, rowid, code, title, store, description, category)
                    VALUES ('delete', old.id, old.code, old.title, old.store, old.description, old.category);
                END;
                """
            )
            if not table_exists:
                self._connection.execute("INSERT INTO coupons_fts(coupons_fts) VALUES ('rebuild')")
            self._fts_enabled = True
        except sqlite3.OperationalError:
            self._connection.rollback()
            logger.info("SQLite FTS5 is unavailable; using LIKE search")

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @staticmethod
    def _normalise_text(value: str, field: str, maximum: int) -> str:
        normalised = " ".join(value.strip().split())
        if not normalised:
            raise ValueError(f"{field} cannot be empty")
        if len(normalised) > maximum:
            raise ValueError(f"{field} must be {maximum} characters or fewer")
        return normalised

    @staticmethod
    def _normalise_optional_url(url: str | None) -> str | None:
        if url is None or not url.strip() or url.strip() == "-":
            return None
        value = url.strip()
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be a complete http:// or https:// URL")
        if len(value) > 500:
            raise ValueError("url must be 500 characters or fewer")
        return value

    @staticmethod
    def _normalise_expiry(expires_at: str | None) -> str | None:
        if expires_at is None or not expires_at.strip() or expires_at.strip() == "-":
            return None
        value = expires_at.strip()
        try:
            dt.date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("expires_at must use YYYY-MM-DD format") from exc
        return value

    @staticmethod
    def _row_to_coupon(row: sqlite3.Row) -> Coupon:
        return Coupon(
            id=int(row["id"]),
            code=str(row["code"]),
            title=str(row["title"]),
            store=str(row["store"]),
            description=str(row["description"]),
            category=str(row["category"]),
            discount=str(row["discount"]),
            url=row["url"],
            expires_at=row["expires_at"],
            created_at=str(row["created_at"]),
            is_active=bool(row["is_active"]),
            view_count=int(row["view_count"]),
            used_count=int(row["used_count"]),
        )

    @staticmethod
    def _active_clause(alias: str = "c") -> str:
        return f"{alias}.is_active = 1 AND ({alias}.expires_at IS NULL OR {alias}.expires_at >= ?)"

    @staticmethod
    def _sort_clause() -> str:
        return """
            ORDER BY
                CASE WHEN c.expires_at IS NULL THEN 1 ELSE 0 END,
                c.expires_at ASC,
                c.created_at DESC,
                c.id DESC
        """

    def add_coupon(
        self,
        *,
        store: str,
        code: str,
        title: str,
        discount: str = "Special offer",
        category: str = "Other",
        description: str = "",
        url: str | None = None,
        expires_at: str | None = None,
        created_by: int | None = None,
    ) -> int:
        """Validate and insert a coupon, returning its database ID."""

        store_value = self._normalise_text(store, "store", 100)
        code_value = self._normalise_text(code, "code", 80).upper()
        title_value = self._normalise_text(title, "title", 160)
        discount_value = self._normalise_text(discount or "Special offer", "discount", 120)
        category_value = self._normalise_text(category or "Other", "category", 80)
        description_value = " ".join(description.strip().split())
        if len(description_value) > 1000:
            raise ValueError("description must be 1000 characters or fewer")
        url_value = self._normalise_optional_url(url)
        expiry_value = self._normalise_expiry(expires_at)

        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO coupons (
                    code, title, store, description, category, discount,
                    url, expires_at, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code_value,
                    title_value,
                    store_value,
                    description_value,
                    category_value,
                    discount_value,
                    url_value,
                    expiry_value,
                    created_by,
                ),
            )
            return int(cursor.lastrowid)

    def deactivate_expired(self) -> int:
        """Mark expired records inactive and return the number changed."""

        today = dt.date.today().isoformat()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE coupons
                SET is_active = 0
                WHERE is_active = 1 AND expires_at IS NOT NULL AND expires_at < ?
                """,
                (today,),
            )
            return cursor.rowcount

    def _page_from_query(
        self,
        *,
        count_sql: str,
        count_params: list[Any],
        select_sql: str,
        select_params: list[Any],
        page: int,
        page_size: int,
    ) -> CouponPage:
        page = max(1, page)
        page_size = max(1, min(50, page_size))
        with self._lock:
            total = int(self._connection.execute(count_sql, count_params).fetchone()[0])
            rows = self._connection.execute(
                f"{select_sql} LIMIT ? OFFSET ?",
                [*select_params, page_size, (page - 1) * page_size],
            ).fetchall()
        return CouponPage(
            items=tuple(self._row_to_coupon(row) for row in rows),
            total=total,
            page=page,
            page_size=page_size,
        )

    def list_active(
        self,
        *,
        page: int = 1,
        page_size: int = 5,
        category: str | None = None,
        store: str | None = None,
    ) -> CouponPage:
        """Return active coupons ordered by nearest expiry."""

        where = [self._active_clause()]
        params: list[Any] = [dt.date.today().isoformat()]
        if category and category.strip():
            where.append("c.category = ?")
            params.append(category.strip())
        if store and store.strip():
            where.append("c.store = ?")
            params.append(store.strip())

        where_sql = " AND ".join(where)
        return self._page_from_query(
            count_sql=f"SELECT COUNT(*) FROM coupons AS c WHERE {where_sql}",
            count_params=params,
            select_sql=f"SELECT c.* FROM coupons AS c WHERE {where_sql} {self._sort_clause()}",
            select_params=params,
            page=page,
            page_size=page_size,
        )

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = re.findall(r"[\w]+", query, flags=re.UNICODE)
        return " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens[:12])

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def search(self, query: str, *, page: int = 1, page_size: int = 5) -> CouponPage:
        """Search active coupons using FTS5 or a safe LIKE fallback."""

        query = query.strip()
        if not query:
            return CouponPage(items=(), total=0, page=max(1, page), page_size=page_size)

        today = dt.date.today().isoformat()
        if self._fts_enabled and self._fts_query(query):
            fts_query = self._fts_query(query)
            active = self._active_clause()
            return self._page_from_query(
                count_sql=(
                    "SELECT COUNT(*) FROM coupons AS c "
                    "JOIN coupons_fts ON coupons_fts.rowid = c.id "
                    f"WHERE coupons_fts MATCH ? AND {active}"
                ),
                count_params=[fts_query, today],
                select_sql=(
                    "SELECT c.* FROM coupons AS c "
                    "JOIN coupons_fts ON coupons_fts.rowid = c.id "
                    f"WHERE coupons_fts MATCH ? AND {active} {self._sort_clause()}"
                ),
                select_params=[fts_query, today],
                page=page,
                page_size=page_size,
            )

        pattern = f"%{self._escape_like(query.lower())}%"
        active = self._active_clause()
        fields = " OR ".join(
            f"lower(c.{field}) LIKE ? ESCAPE '\\'"
            for field in ("code", "title", "store", "description", "category", "discount")
        )
        params = [today, *([pattern] * 6)]
        return self._page_from_query(
            count_sql=f"SELECT COUNT(*) FROM coupons AS c WHERE {active} AND ({fields})",
            count_params=params,
            select_sql=f"SELECT c.* FROM coupons AS c WHERE {active} AND ({fields}) {self._sort_clause()}",
            select_params=params,
            page=page,
            page_size=page_size,
        )

    def get_active(self, coupon_id: int) -> Coupon | None:
        today = dt.date.today().isoformat()
        with self._lock:
            row = self._connection.execute(
                f"SELECT c.* FROM coupons AS c WHERE c.id = ? AND {self._active_clause()}",
                (coupon_id, today),
            ).fetchone()
        return self._row_to_coupon(row) if row else None

    def record_view(self, coupon_id: int) -> Coupon | None:
        today = dt.date.today().isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                f"""
                UPDATE coupons
                SET view_count = view_count + 1
                WHERE id = ? AND is_active = 1
                  AND (expires_at IS NULL OR expires_at >= ?)
                """,
                (coupon_id, today),
            )
        return self.get_active(coupon_id)

    def mark_used(self, coupon_id: int) -> bool:
        today = dt.date.today().isoformat()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                f"""
                UPDATE coupons
                SET used_count = used_count + 1
                WHERE id = ? AND is_active = 1
                  AND (expires_at IS NULL OR expires_at >= ?)
                """,
                (coupon_id, today),
            )
            return cursor.rowcount == 1

    def deactivate(self, coupon_id: int) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE coupons SET is_active = 0 WHERE id = ? AND is_active = 1",
                (coupon_id,),
            )
            return cursor.rowcount == 1

    def categories(self) -> tuple[str, ...]:
        today = dt.date.today().isoformat()
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT DISTINCT category FROM coupons AS c
                WHERE {self._active_clause()}
                ORDER BY category COLLATE NOCASE
                """,
                (today,),
            ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def stores(self) -> tuple[str, ...]:
        today = dt.date.today().isoformat()
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT DISTINCT store FROM coupons AS c
                WHERE {self._active_clause()}
                ORDER BY store COLLATE NOCASE
                """,
                (today,),
            ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def stats(self) -> dict[str, int]:
        today = dt.date.today().isoformat()
        with self._lock:
            row = self._connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(is_active = 1 AND (expires_at IS NULL OR expires_at >= ?)), 0) AS active,
                    COALESCE(SUM(view_count), 0) AS views,
                    COALESCE(SUM(used_count), 0) AS uses
                FROM coupons
                """,
                (today,),
            ).fetchone()
        return {
            "total": int(row["total"]),
            "active": int(row["active"]),
            "views": int(row["views"]),
            "uses": int(row["uses"]),
        }
