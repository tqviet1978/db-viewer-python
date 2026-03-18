"""Driver interface tests using mock/in-memory approach."""

import pytest
from unittest.mock import MagicMock, patch

from dbviewer.drivers.base import SYSTEM_COLUMNS, GenericDriver


class ConcreteDriver(GenericDriver):
    """Minimal concrete implementation for testing shared methods."""

    def __init__(self):
        self.settings = {}
        self._tables = {
            "USERS": {"ID": "int(11)", "UUID": "varchar(32)", "NAME": "varchar(255)",
                      "EMAIL": "varchar(255)", "CREATION_DATE": "datetime"},
            "ORDERS": {"ID": "int(11)", "UUID": "varchar(32)", "ID_USER": "int(11)",
                       "TOTAL_VALUE": "decimal(12,2)", "ORDER_DATE": "date"},
        }

    def initialize(self, settings):
        return None

    def close(self):
        pass

    def get_table_names(self):
        return list(self._tables.keys())

    def get_table_columns(self, table):
        return self._tables.get(table, {})

    def get_column_names(self, tables):
        names = set()
        for t in tables:
            names.update(self._tables.get(t, {}).keys())
        return sorted(names)

    def column_exists(self, table, column):
        cols = self._tables.get(table, {})
        if column in cols:
            return True, cols[column]
        return False, ""

    def get_table_indexes(self, table):
        return {"PRIMARY": ["ID"]}

    def get_table_count(self, table):
        return 42

    def get_table_data(self, table, offset=0, limit=100):
        return [{"ID": 1, "UUID": "abc", "NAME": "Test"}]

    def execute_query(self, query):
        return f"Done. Affected rows = 1 in 0.5ms", None, 0.5

    def truncate_table(self, table, dry_run=False):
        return f"TRUNCATE TABLE `{table}`" if dry_run else ""

    def drop_table(self, table, dry_run=False):
        return f"DROP TABLE `{table}`;" if dry_run else ""

    def rename_table(self, table, new_name, dry_run=False):
        return f"RENAME TABLE `{table}` TO `{new_name}`;" if dry_run else ""

    def clone_table(self, table, new_name, dry_run=False):
        return f"CREATE TABLE `{new_name}` AS SELECT * FROM `{table}`;" if dry_run else ""

    def insert_table_row(self, table, data):
        return 1

    def drop_index(self, index, table):
        pass


class TestSystemColumns:
    def test_system_columns_set(self):
        for col in ("ID", "UUID", "GUID", "CREATION_DATE", "LATEST_UPDATE"):
            assert col in SYSTEM_COLUMNS


class TestGetNormalTableColumns:
    def setup_method(self):
        self.driver = ConcreteDriver()

    def test_excludes_system_columns(self):
        cols = self.driver.get_normal_table_columns("USERS")
        assert "ID" not in cols
        assert "UUID" not in cols
        assert "CREATION_DATE" not in cols
        assert "NAME" in cols
        assert "EMAIL" in cols

    def test_search_by_column_name(self):
        cols = self.driver.get_normal_table_columns("USERS", "EMAIL")
        assert "EMAIL" in cols
        assert "NAME" not in cols

    def test_search_by_type(self):
        cols = self.driver.get_normal_table_columns("ORDERS", "decimal")
        assert "TOTAL_VALUE" in cols
        assert "ORDER_DATE" not in cols

    def test_exclude_with_dash(self):
        cols = self.driver.get_normal_table_columns("USERS", "-NAME")
        assert "NAME" not in cols
        assert "EMAIL" in cols


class TestGetTableCounts:
    def test_returns_counts(self):
        driver = ConcreteDriver()
        counts = driver.get_table_counts(["USERS", "ORDERS"])
        assert counts["USERS"] == 42
        assert counts["ORDERS"] == 42


class TestExportAsConcept:
    def test_returns_table_sections(self):
        driver = ConcreteDriver()
        result = driver.export_tables_as_concept(["USERS"])
        assert "[USERS]" in result
        assert "NAME" in result
        assert "EMAIL" in result

    def test_excludes_system_columns(self):
        driver = ConcreteDriver()
        result = driver.export_tables_as_concept(["USERS"])
        assert "CREATION_DATE" not in result
        assert "UUID" not in result

    def test_multiple_tables(self):
        driver = ConcreteDriver()
        result = driver.export_tables_as_concept(["USERS", "ORDERS"])
        assert "[USERS]" in result
        assert "[ORDERS]" in result


class TestExportAsHtmlTable:
    def setup_method(self):
        self.driver = ConcreteDriver()

    def test_empty_returns_empty_text(self):
        result = self.driver.export_as_html_table("USERS", [], [], [])
        assert "(empty)" in result

    def test_generates_table_tag(self):
        rows = [{"ID": 1, "NAME": "Alice"}]
        result = self.driver.export_as_html_table("USERS", rows, ["ID", "NAME"], [])
        assert "<table" in result
        assert "ID" in result and "sortable" in result
        assert "Alice" in result

    def test_index_column(self):
        rows = [{"NAME": "Alice"}, {"NAME": "Bob"}]
        result = self.driver.export_as_html_table(None, rows, ["NAME"], [])
        assert "<th>#</th>" in result

    def test_shows_query(self):
        rows = [{"ID": 1}]
        result = self.driver.export_as_html_table("T", rows, ["ID"], [], query="SELECT 1")
        assert "SELECT" in result

    def test_decimal_formatting(self):
        rows = [{"PRICE": 1500.5}]
        result = self.driver.export_as_html_table("T", rows, ["PRICE"], ["PRICE"])
        assert "1,500.500000" in result


class TestTruncateDropBatch:
    def test_truncate_dry_run(self):
        driver = ConcreteDriver()
        result = driver.truncate_tables(["USERS", "ORDERS"], dry_run=True)
        assert "TRUNCATE" in result
        assert "USERS" in result

    def test_drop_dry_run(self):
        driver = ConcreteDriver()
        result = driver.drop_tables(["USERS"], dry_run=True)
        assert "DROP" in result
        assert "USERS" in result

    def test_truncate_live(self):
        driver = ConcreteDriver()
        result = driver.truncate_tables(["USERS"], dry_run=False)
        assert "truncated" in result


class TestAlterColumnDryRun:
    def test_rename_column_dry_run(self):
        driver = ConcreteDriver()
        result = driver.alter_column(["USERS"], "NAME", "FULL_NAME", "", dry_run=True)
        assert "RENAME COLUMN" in result
        assert "FULL_NAME" in result

    def test_change_type_dry_run(self):
        driver = ConcreteDriver()
        result = driver.alter_column(["USERS"], "NAME", "", "text", dry_run=True)
        assert "MODIFY" in result

    def test_column_not_found(self):
        driver = ConcreteDriver()
        result = driver.alter_column(["USERS"], "NONEXISTENT", "X", "text", dry_run=True)
        assert result == ""

    def test_drop_column_dry_run(self):
        driver = ConcreteDriver()
        result = driver.drop_column(["USERS"], "EMAIL", dry_run=True)
        assert "DROP COLUMN" in result
        assert "EMAIL" in result

    def test_drop_column_not_found(self):
        driver = ConcreteDriver()
        result = driver.drop_column(["USERS"], "GHOST_COL", dry_run=True)
        assert "not found" in result


class TestGetIndexesAsHtml:
    def test_returns_table_section(self):
        driver = ConcreteDriver()
        result = driver.get_indexes_as_html(["USERS"])
        assert "[USERS]" in result
        assert "PRIMARY" in result
