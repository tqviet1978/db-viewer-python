"""MSSQL driver using pymssql."""

from __future__ import annotations

import time
from typing import Any, Optional

from .base import GenericDriver


class MSSQLDriver(GenericDriver):

    def initialize(self, settings: dict) -> Optional[str]:
        self.settings = settings
        try:
            import pymssql
            self.conn = pymssql.connect(
                server=settings["server"],
                port=str(settings.get("port", 1433)),
                user=settings["user"],
                password=settings["password"],
                database=settings["database"],
                as_dict=True,
            )
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
            cur.execute("SELECT name FROM SYSOBJECTS WHERE xtype = 'U' ORDER BY name")
            rows = cur.fetchall()
        return [r["name"] for r in rows]

    def get_table_columns(self, table: str) -> dict[str, str]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
                (table,),
            )
            rows = cur.fetchall()
        return {r["COLUMN_NAME"]: r["DATA_TYPE"] for r in rows}

    def get_column_names(self, tables: list[str]) -> list[str]:
        if not tables:
            return []
        placeholders = ",".join(["%s"] * len(tables))
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                f"WHERE TABLE_NAME IN ({placeholders}) ORDER BY COLUMN_NAME",
                tables,
            )
            rows = cur.fetchall()
        return [r["COLUMN_NAME"] for r in rows]

    def column_exists(self, table: str, column: str) -> tuple[bool, str]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = %s AND COLUMN_NAME = %s",
                (table, column),
            )
            row = cur.fetchone()
        if not row:
            return False, ""
        return True, row["DATA_TYPE"]

    def get_table_indexes(self, table: str) -> dict[str, list[str]]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT i.name AS index_name, c.name AS column_name "
                "FROM sys.indexes i "
                "JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id "
                "JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id "
                "WHERE OBJECT_NAME(i.object_id) = %s ORDER BY i.name, ic.key_ordinal",
                (table,),
            )
            rows = cur.fetchall()
        indexes: dict[str, list[str]] = {}
        for r in rows:
            indexes.setdefault(r["index_name"], []).append(r["column_name"])
        return indexes

    def get_table_count(self, table: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS _COUNT FROM {table}")
            row = cur.fetchone()
        return int(row["_COUNT"]) if row else 0

    def get_table_data(self, table: str, offset: int = 0, limit: int = 100) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM {table} ORDER BY (SELECT NULL) "
                f"OFFSET %s ROWS FETCH NEXT %s ROWS ONLY",
                (offset, limit),
            )
            rows = cur.fetchall()
        return list(rows)

    def execute_query(self, query: str) -> tuple[Any, Optional[str], float]:
        t0 = time.time()
        try:
            with self.conn.cursor() as cur:
                cur.execute(query)
                elapsed = (time.time() - t0) * 1000
                is_select = query.strip().upper().startswith(("SELECT", "SHOW", "DESCRIBE", "EXPLAIN"))
                if is_select:
                    return list(cur.fetchall()), None, elapsed
                else:
                    self.conn.commit()
                    return f"Done in {elapsed:.1f}ms", None, elapsed
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
        query = f"DROP TABLE {table}"
        if dry_run:
            return query
        self.execute_query(query)
        return ""

    def rename_table(self, table: str, new_name: str, dry_run: bool = False) -> str:
        query = f"EXEC sp_rename '{table}', '{new_name}'"
        if dry_run:
            return query
        self.execute_query(query)
        return ""

    def clone_table(self, table: str, new_name: str, dry_run: bool = False) -> str:
        query = f"SELECT * INTO {new_name} FROM {table}"
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
            merged = {**defaults, **data}
            cols = ", ".join(merged.keys())
            placeholders = ", ".join(["%s"] * len(merged))
            with self.conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {table} ({cols}) VALUES ({placeholders}); "
                    f"SELECT SCOPE_IDENTITY() AS new_id",
                    list(merged.values()),
                )
                row = cur.fetchone()
            self.conn.commit()
            return int(row["new_id"]) if row else 0

    def drop_index(self, index: str, table: str) -> None:
        self.execute_query(f"DROP INDEX {table}.{index}")
