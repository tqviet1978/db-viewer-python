"""MySQL driver using pymysql."""

from __future__ import annotations

import time
from typing import Any, Optional

import pymysql
import pymysql.cursors

from .base import GenericDriver


class MySQLDriver(GenericDriver):

    def initialize(self, settings: dict) -> Optional[str]:
        self.settings = settings
        try:
            self.conn = pymysql.connect(
                host=settings["server"],
                port=int(settings.get("port", 3306)),
                user=settings["user"],
                password=settings["password"],
                database=settings["database"],
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=True,
                connect_timeout=10,
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
            cur.execute("SHOW TABLES")
            rows = cur.fetchall()
        # pymysql DictCursor: key is "Tables_in_<db>"
        if not rows:
            return []
        key = list(rows[0].keys())[0]
        return [r[key] for r in rows]

    def get_table_columns(self, table: str) -> dict[str, str]:
        with self.conn.cursor() as cur:
            cur.execute(f"SHOW COLUMNS FROM `{table}`")
            rows = cur.fetchall()
        return {r["Field"]: r["Type"] for r in rows}

    def get_column_names(self, tables: list[str]) -> list[str]:
        if not tables:
            return []
        placeholders = ",".join(["%s"] * len(tables))
        query = f"SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME IN ({placeholders})"
        with self.conn.cursor() as cur:
            cur.execute(query, tables)
            rows = cur.fetchall()
        names = sorted(set(r["COLUMN_NAME"] for r in rows))
        return names

    def column_exists(self, table: str, column: str) -> tuple[bool, str]:
        with self.conn.cursor() as cur:
            cur.execute(f"SHOW COLUMNS FROM `{table}` WHERE Field = %s", (column,))
            row = cur.fetchone()
        if not row:
            return False, ""
        return True, row["Type"]

    def get_table_indexes(self, table: str) -> dict[str, list[str]]:
        with self.conn.cursor() as cur:
            cur.execute(f"SHOW INDEX FROM `{table}`")
            rows = cur.fetchall()
        indexes: dict[str, list[str]] = {}
        for r in rows:
            key = r["Key_name"]
            indexes.setdefault(key, []).append(r["Column_name"])
        return indexes

    def get_table_count(self, table: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS _COUNT FROM `{table}`")
            row = cur.fetchone()
        return int(row["_COUNT"]) if row else 0

    def get_table_data(self, table: str, offset: int = 0, limit: int = 100) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT * FROM `{table}` LIMIT %s, %s", (offset, limit))
            rows = cur.fetchall()
        return list(rows)

    def execute_query(self, query: str) -> tuple[Any, Optional[str], float]:
        t0 = time.time()
        try:
            with self.conn.cursor() as cur:
                cur.execute(query)
                elapsed = (time.time() - t0) * 1000
                is_select = query.strip().upper().startswith(
                    ("SELECT", "SHOW", "DESCRIBE", "EXPLAIN")
                )
                if is_select:
                    rows = list(cur.fetchall())
                    return rows, None, elapsed
                else:
                    return f"Done. Affected rows = {cur.rowcount} in {elapsed:.1f}ms", None, elapsed
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            return None, str(e), elapsed

    def truncate_table(self, table: str, dry_run: bool = False) -> str:
        query = f"TRUNCATE TABLE `{table}`"
        if dry_run:
            return query
        self.execute_query(query)
        return ""

    def drop_table(self, table: str, dry_run: bool = False) -> str:
        query = f"DROP TABLE `{table}`;"
        if dry_run:
            return query
        self.execute_query(query)
        return ""

    def rename_table(self, table: str, new_name: str, dry_run: bool = False) -> str:
        query = f"RENAME TABLE `{table}` TO `{new_name}`;"
        if dry_run:
            return query
        self.execute_query(query)
        return ""

    def clone_table(self, table: str, new_name: str, dry_run: bool = False) -> str:
        query = f"CREATE TABLE `{new_name}` AS SELECT * FROM `{table}`;"
        if dry_run:
            return query
        self.execute_query(query)
        return ""

    def insert_table_row(self, table: str, data: dict) -> int:
        from datetime import datetime as _dt
        if "ID" in data:
            row_id = int(data.pop("ID"))
            if data:
                set_clause = ", ".join(f"`{c}` = %s" for c in data)
                values = list(data.values())
                query = f"UPDATE `{table}` SET {set_clause} WHERE ID = %s"
                values.append(row_id)
                with self.conn.cursor() as cur:
                    cur.execute(query, values)
            return row_id
        else:
            defaults = {
                "NOTE": "",
                "GUID": 1,
                "JSON": "",
                "CREATION_DATE": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                "IMPORT_REF": "",
                "LATEST_UPDATE": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                "LATEST_UPDATE_GUID": "",
                "SSID": 0,
                "UDID": 1,
                "UUID": self.generate_uuid(),
            }
            merged = {**defaults, **data}
            cols = ", ".join(f"`{c}`" for c in merged)
            placeholders = ", ".join(["%s"] * len(merged))
            query = f"INSERT INTO `{table}` ({cols}) VALUES ({placeholders})"
            with self.conn.cursor() as cur:
                cur.execute(query, list(merged.values()))
                return self.conn.insert_id()

    def drop_index(self, index: str, table: str) -> None:
        if index.upper() == "PRIMARY":
            return
        self.execute_query(f"DROP INDEX `{index}` ON `{table}`")

    def get_sizes_as_html(self, tables: list[str]) -> str:
        table_list = "','".join(tables)
        query = (
            f"SELECT table_name, ROUND(data_length / 1024, 2) AS data_size_kb, "
            f"ROUND(index_length / 1024, 2) AS index_size_kb "
            f"FROM information_schema.tables WHERE TABLE_NAME IN ('{table_list}')"
        )
        rows, error, _ = self.execute_query(query)
        if error:
            return error
        return self.export_as_html_table(None, rows, [], ["data_size_kb", "index_size_kb"])
