"""PostgreSQL driver using psycopg2."""

from __future__ import annotations

import time
from typing import Any, Optional

import psycopg2
import psycopg2.extras

from .base import GenericDriver


class PostgreSQLDriver(GenericDriver):

    def initialize(self, settings: dict) -> Optional[str]:
        self.settings = settings
        try:
            self.conn = psycopg2.connect(
                host=settings["server"],
                port=int(settings.get("port", 5432)),
                user=settings["user"],
                password=settings["password"],
                dbname=settings["database"],
            )
            self.conn.autocommit = True
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
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
            rows = cur.fetchall()
        return [r[0] for r in rows]

    def get_table_columns(self, table: str) -> dict[str, str]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = %s ORDER BY ordinal_position",
                (table,),
            )
            rows = cur.fetchall()
        return {r[0]: r[1] for r in rows}

    def get_column_names(self, tables: list[str]) -> list[str]:
        if not tables:
            return []
        placeholders = ",".join(["%s"] * len(tables))
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT column_name FROM information_schema.columns "
                f"WHERE table_name IN ({placeholders}) ORDER BY column_name",
                tables,
            )
            rows = cur.fetchall()
        return [r[0] for r in rows]

    def column_exists(self, table: str, column: str) -> tuple[bool, str]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = %s",
                (table, column),
            )
            row = cur.fetchone()
        if not row:
            return False, ""
        return True, row[0]

    def get_table_indexes(self, table: str) -> dict[str, list[str]]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = %s",
                (table,),
            )
            rows = cur.fetchall()
        indexes: dict[str, list[str]] = {}
        import re
        for name, defn in rows:
            m = re.findall(r"\(([^)]+)\)", defn)
            cols = [c.strip() for c in m[-1].split(",")] if m else []
            indexes[name] = cols
        return indexes

    def get_table_count(self, table: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            row = cur.fetchone()
        return int(row[0]) if row else 0

    def get_table_data(self, table: str, offset: int = 0, limit: int = 100) -> list[dict]:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f'SELECT * FROM "{table}" OFFSET %s LIMIT %s', (offset, limit))
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    def execute_query(self, query: str) -> tuple[Any, Optional[str], float]:
        t0 = time.time()
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query)
                elapsed = (time.time() - t0) * 1000
                is_select = query.strip().upper().startswith(
                    ("SELECT", "SHOW", "DESCRIBE", "EXPLAIN")
                )
                if is_select:
                    return [dict(r) for r in cur.fetchall()], None, elapsed
                else:
                    return f"Done. Affected rows = {cur.rowcount} in {elapsed:.1f}ms", None, elapsed
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            try:
                self.conn.rollback()
            except Exception:
                pass
            return None, str(e), elapsed

    def truncate_table(self, table: str, dry_run: bool = False) -> str:
        query = f"TRUNCATE TABLE {table}"
        if dry_run:
            return query
        self.execute_query(query)
        return ""

    def drop_table(self, table: str, dry_run: bool = False) -> str:
        query = f"DROP TABLE IF EXISTS {table}"
        if dry_run:
            return query
        self.execute_query(query)
        return ""

    def rename_table(self, table: str, new_name: str, dry_run: bool = False) -> str:
        query = f"ALTER TABLE {table} RENAME TO {new_name}"
        if dry_run:
            return query
        self.execute_query(query)
        return ""

    def clone_table(self, table: str, new_name: str, dry_run: bool = False) -> str:
        query = f"CREATE TABLE {new_name} AS SELECT * FROM {table}"
        if dry_run:
            return query
        self.execute_query(query)
        return ""

    def insert_table_row(self, table: str, data: dict) -> int:
        from datetime import datetime as _dt
        if "ID" in data:
            row_id = int(data.pop("ID"))
            if data:
                set_clause = ", ".join(f"{c} = %s" for c in data)
                values = list(data.values()) + [row_id]
                with self.conn.cursor() as cur:
                    cur.execute(f"UPDATE {table} SET {set_clause} WHERE ID = %s", values)
            return row_id
        else:
            defaults = {
                "NOTE": "", "GUID": 1, "JSON": "",
                "CREATION_DATE": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                "IMPORT_REF": "", "LATEST_UPDATE": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                "LATEST_UPDATE_GUID": "", "SSID": 0, "UDID": 1,
                "UUID": self.generate_uuid(),
            }
            merged = {**defaults, **data}
            cols = ", ".join(merged.keys())
            placeholders = ", ".join(["%s"] * len(merged))
            with self.conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) RETURNING ID",
                    list(merged.values()),
                )
                row = cur.fetchone()
            return row[0] if row else 0

    def drop_index(self, index: str, table: str) -> None:
        self.execute_query(f"DROP INDEX IF EXISTS {index}")
