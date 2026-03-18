"""SQLite driver — used exclusively for integration testing.

SQLite allows the full GenericDriver interface to be exercised against a real
in-process database without requiring MySQL/PostgreSQL/MSSQL to be running.
Not intended for production use.
"""

from __future__ import annotations

import re
import sqlite3
import time
from typing import Any, Optional

from .base import GenericDriver


class SQLiteDriver(GenericDriver):
    """SQLite-backed driver for integration testing.

    Simulates the interface of MySQL/PostgreSQL/MSSQL drivers against an
    in-process SQLite database.  Type names are mapped to SQLite equivalents
    where necessary.
    """

    def initialize(self, settings: dict) -> Optional[str]:
        self.settings = settings
        path = settings.get("database", ":memory:")
        try:
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            # Enable WAL for better concurrency in tests
            self.conn.execute("PRAGMA journal_mode=WAL")
            return None
        except Exception as e:
            return str(e)

    def close(self) -> None:
        try:
            if self.conn:
                self.conn.close()
        except Exception:
            pass

    def get_table_names(self) -> list[str]:
        cur = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        return [row[0] for row in cur.fetchall()]

    def get_table_columns(self, table: str) -> dict[str, str]:
        cur = self.conn.execute(f"PRAGMA table_info(`{table}`)")
        rows = cur.fetchall()
        return {row["name"]: row["type"] or "TEXT" for row in rows}

    def get_column_names(self, tables: list[str]) -> list[str]:
        names: set[str] = set()
        for table in tables:
            names.update(self.get_table_columns(table).keys())
        return sorted(names)

    def column_exists(self, table: str, column: str) -> tuple[bool, str]:
        cols = self.get_table_columns(table)
        if column in cols:
            return True, cols[column]
        return False, ""

    def get_table_indexes(self, table: str) -> dict[str, list[str]]:
        cur = self.conn.execute(f"PRAGMA index_list(`{table}`)")
        index_rows = cur.fetchall()
        indexes: dict[str, list[str]] = {}
        for idx_row in index_rows:
            idx_name = idx_row["name"]
            icur = self.conn.execute(f"PRAGMA index_info(`{idx_name}`)")
            indexes[idx_name] = [r["name"] for r in icur.fetchall()]
        return indexes

    def get_table_count(self, table: str) -> int:
        cur = self.conn.execute(f"SELECT COUNT(*) FROM `{table}`")
        return cur.fetchone()[0]

    def get_table_data(self, table: str, offset: int = 0, limit: int = 100) -> list[dict]:
        cur = self.conn.execute(
            f"SELECT * FROM `{table}` LIMIT ? OFFSET ?", (limit, offset)
        )
        return [dict(row) for row in cur.fetchall()]

    def execute_query(self, query: str) -> tuple[Any, Optional[str], float]:
        t0 = time.time()
        try:
            # SQLite doesn't support multi-statement in cursor.execute; run them sequentially
            statements = [s.strip() for s in query.split(";") if s.strip()]
            last_result = None
            last_affected = 0
            for stmt in statements:
                cur = self.conn.execute(stmt)
                self.conn.commit()
                is_select = bool(re.match(r"^(SELECT|PRAGMA|EXPLAIN)", stmt.strip(), re.I))
                if is_select:
                    last_result = [dict(r) for r in cur.fetchall()]
                else:
                    last_affected = cur.rowcount
                    last_result = None
            elapsed = (time.time() - t0) * 1000
            if isinstance(last_result, list):
                return last_result, None, elapsed
            return f"Done. Affected rows = {last_affected} in {elapsed:.1f}ms", None, elapsed
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            return None, str(e), elapsed

    def truncate_table(self, table: str, dry_run: bool = False) -> str:
        query = f"DELETE FROM `{table}`"
        if dry_run:
            return query
        self.execute_query(query)
        return ""

    def drop_table(self, table: str, dry_run: bool = False) -> str:
        query = f"DROP TABLE IF EXISTS `{table}`"
        if dry_run:
            return query
        self.execute_query(query)
        return ""

    def rename_table(self, table: str, new_name: str, dry_run: bool = False) -> str:
        query = f"ALTER TABLE `{table}` RENAME TO `{new_name}`"
        if dry_run:
            return query
        self.execute_query(query)
        return ""

    def clone_table(self, table: str, new_name: str, dry_run: bool = False) -> str:
        query = f"CREATE TABLE `{new_name}` AS SELECT * FROM `{table}`"
        if dry_run:
            return query
        self.execute_query(query)
        return ""

    def insert_table_row(self, table: str, data: dict) -> int:
        from datetime import datetime as _dt
        if "ID" in data:
            row_id = int(data.pop("ID"))
            if data:
                set_clause = ", ".join(f"`{c}` = ?" for c in data)
                values = list(data.values()) + [row_id]
                self.conn.execute(f"UPDATE `{table}` SET {set_clause} WHERE ID = ?", values)
                self.conn.commit()
            return row_id
        else:
            defaults = {
                "NOTE": "", "GUID": 1, "JSON": "",
                "CREATION_DATE": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                "IMPORT_REF": "", "LATEST_UPDATE": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                "LATEST_UPDATE_GUID": "", "SSID": 0, "UDID": 1,
                "UUID": self.generate_uuid(),
            }
            # Only include defaults for columns that actually exist
            existing_cols = set(self.get_table_columns(table).keys())
            merged = {k: v for k, v in {**defaults, **data}.items() if k in existing_cols}
            if not merged:
                merged = data
            cols = ", ".join(f"`{c}`" for c in merged)
            placeholders = ", ".join(["?"] * len(merged))
            cur = self.conn.execute(
                f"INSERT INTO `{table}` ({cols}) VALUES ({placeholders})", list(merged.values())
            )
            self.conn.commit()
            return cur.lastrowid or 0

    def drop_index(self, index: str, table: str) -> None:
        self.execute_query(f"DROP INDEX IF EXISTS `{index}`")

    # ------------------------------------------------------------------
    # Test helpers — not part of GenericDriver interface
    # ------------------------------------------------------------------

    def create_table(self, ddl: str) -> None:
        """Execute a CREATE TABLE statement for test setup."""
        self.conn.execute(ddl)
        self.conn.commit()

    def seed(self, table: str, rows: list[dict]) -> None:
        """Insert multiple rows for test setup."""
        for row in rows:
            cols = ", ".join(f"`{c}`" for c in row)
            placeholders = ", ".join(["?"] * len(row))
            self.conn.execute(
                f"INSERT INTO `{table}` ({cols}) VALUES ({placeholders})", list(row.values())
            )
        self.conn.commit()
