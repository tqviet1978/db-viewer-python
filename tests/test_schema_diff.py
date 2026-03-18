"""Tests for schema_diff module."""

import pytest
from unittest.mock import MagicMock, patch
from dbviewer.schema_diff import get_diff, _get_column_spec, _get_index_spec


def _make_column(col_type="varchar(255)", nullable="YES", default=None, extra="", key="", collation=""):
    return {
        "COLUMN_TYPE": col_type,
        "DATA_TYPE": col_type.split("(")[0],
        "IS_NULLABLE": nullable,
        "COLUMN_DEFAULT": default,
        "EXTRA": extra,
        "COLUMN_KEY": key,
        "COLLATION_NAME": collation,
    }


def _make_index(col_name, non_unique="1", index_name="IDX_TEST"):
    return {col_name: {"NON_UNIQUE": non_unique, "INDEX_NAME": index_name, "COLUMN_NAME": col_name}}


def _make_handler(schema_rows, stats_rows, db_name="testdb"):
    handler = MagicMock()
    handler.settings = {"database": db_name}

    def execute_query(q):
        if "INFORMATION_SCHEMA.COLUMNS" in q:
            return schema_rows, None, 0.0
        elif "INFORMATION_SCHEMA.STATISTICS" in q:
            return stats_rows, None, 0.0
        return [], None, 0.0

    handler.execute_query = execute_query
    return handler


class TestColumnSpec:
    def test_basic_varchar(self):
        col = _make_column("varchar(255)", "YES")
        spec = _get_column_spec("NAME", col)
        assert "`NAME`" in spec
        assert "varchar(255)" in spec

    def test_not_null(self):
        col = _make_column("int(11)", "NO")
        spec = _get_column_spec("ID", col)
        assert "NOT NULL" in spec

    def test_auto_increment(self):
        col = _make_column("int(11)", "NO", extra="auto_increment", key="PRI")
        spec = _get_column_spec("ID", col)
        assert "AUTO_INCREMENT" in spec
        assert "PRIMARY KEY" in spec

    def test_default_value(self):
        col = _make_column("int(11)", "YES", default="0")
        spec = _get_column_spec("ORDERING", col)
        assert "DEFAULT '0'" in spec


class TestSchemaDiff:
    def _make_schema_rows(self, table, columns):
        rows = []
        for i, (col, dtype) in enumerate(columns.items()):
            rows.append({
                "TABLE_NAME": table,
                "COLUMN_NAME": col,
                "COLUMN_TYPE": dtype,
                "DATA_TYPE": dtype.split("(")[0],
                "ORDINAL_POSITION": i + 1,
                "IS_NULLABLE": "YES",
                "COLUMN_DEFAULT": None,
                "EXTRA": "",
                "COLUMN_KEY": "",
                "COLLATION_NAME": "",
            })
        return rows

    def test_new_table(self):
        local_rows = self._make_schema_rows("NEW_TABLE", {"ID": "int(11)", "NAME": "varchar(255)"})
        local_h = _make_handler(local_rows, [])
        peer_h = _make_handler([], [])

        diff = get_diff(local_h, peer_h)
        assert "CREATE TABLE" in diff
        assert "NEW_TABLE" in diff

    def test_deleted_table(self):
        peer_rows = self._make_schema_rows("OLD_TABLE", {"ID": "int(11)"})
        local_h = _make_handler([], [])
        peer_h = _make_handler(peer_rows, [])

        diff = get_diff(local_h, peer_h)
        assert "DROP TABLE" in diff
        assert "OLD_TABLE" in diff

    def test_new_column(self):
        local_rows = self._make_schema_rows("USERS", {"ID": "int(11)", "NAME": "varchar(255)", "EMAIL": "varchar(255)"})
        peer_rows = self._make_schema_rows("USERS", {"ID": "int(11)", "NAME": "varchar(255)"})
        local_h = _make_handler(local_rows, [])
        peer_h = _make_handler(peer_rows, [])

        diff = get_diff(local_h, peer_h)
        assert "ADD COLUMN" in diff
        assert "EMAIL" in diff

    def test_deleted_column(self):
        local_rows = self._make_schema_rows("USERS", {"ID": "int(11)", "NAME": "varchar(255)"})
        peer_rows = self._make_schema_rows("USERS", {"ID": "int(11)", "NAME": "varchar(255)", "OLD_COL": "text"})
        local_h = _make_handler(local_rows, [])
        peer_h = _make_handler(peer_rows, [])

        diff = get_diff(local_h, peer_h)
        assert "DROP COLUMN" in diff
        assert "OLD_COL" in diff

    def test_no_diff(self):
        rows = self._make_schema_rows("USERS", {"ID": "int(11)", "NAME": "varchar(255)"})
        local_h = _make_handler(rows, [])
        peer_h = _make_handler(rows, [])

        diff = get_diff(local_h, peer_h)
        assert diff.strip() == ""

    def test_table_filter(self):
        local_rows = (
            self._make_schema_rows("USERS", {"ID": "int(11)", "EMAIL": "varchar(255)"}) +
            self._make_schema_rows("ORDERS", {"ID": "int(11)", "TOTAL": "decimal(12,2)"})
        )
        peer_rows = self._make_schema_rows("USERS", {"ID": "int(11)"})
        local_h = _make_handler(local_rows, [])
        peer_h = _make_handler(peer_rows, [])

        # Only diff USERS table
        diff = get_diff(local_h, peer_h, tables=["USERS"])
        assert "EMAIL" in diff
        assert "ORDERS" not in diff

    def test_new_index(self):
        rows = self._make_schema_rows("PRODUCTS", {"ID": "int(11)", "CODE": "varchar(50)"})
        stats_local = [{
            "TABLE_NAME": "PRODUCTS",
            "INDEX_NAME": "IDX_CODE",
            "COLUMN_NAME": "CODE",
            "SEQ_IN_INDEX": 1,
            "NON_UNIQUE": "1",
        }]
        local_h = _make_handler(rows, stats_local)
        peer_h = _make_handler(rows, [])

        diff = get_diff(local_h, peer_h)
        assert "ADD INDEX" in diff
        assert "IDX_CODE" in diff
