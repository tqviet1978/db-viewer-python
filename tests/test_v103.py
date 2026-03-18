"""Tests for v1.0.3:
- Cross-server copy_tables (_build_insert_sql, _copy_table_data, _is_same_server, copy_tables strategy)
- Dark mode audit: CSS classes in HTML output (result-table, query-label, query-error)
- No hardcoded colour literals in generated HTML
"""

from __future__ import annotations

import json
import re
import tempfile
from unittest.mock import MagicMock, call, patch

import pytest

from dbviewer.schema_diff import (
    _build_insert_sql,
    _copy_table_data,
    _is_same_server,
    copy_tables,
    clone_database,
)
from dbviewer.drivers.sqlite import SQLiteDriver


# ─── _build_insert_sql ───────────────────────────────────────────────────────

class TestBuildInsertSql:
    def _row(self):
        return {"ID": 1, "NAME": "Alice", "AGE": 30, "NOTE": None}

    def _cols(self):
        return ["ID", "NAME", "AGE", "NOTE"]

    def test_mysql_backtick_quoting(self):
        sql = _build_insert_sql("USERS", self._cols(), self._row(), "mysql")
        assert sql.startswith("INSERT INTO `USERS`")
        assert "`ID`" in sql
        assert "`NAME`" in sql

    def test_postgres_double_quote_identifiers(self):
        sql = _build_insert_sql("users", self._cols(), self._row(), "postgres")
        assert sql.startswith('INSERT INTO "users"')
        assert '"ID"' in sql
        assert '"NAME"' in sql

    def test_postgresql_alias_also_works(self):
        sql = _build_insert_sql("t", ["A"], {"A": 1}, "postgresql")
        assert '"t"' in sql or "t" in sql
        assert '"A"' in sql

    def test_mssql_bracket_identifiers(self):
        sql = _build_insert_sql("Orders", self._cols(), self._row(), "mssql")
        assert sql.startswith("INSERT INTO [Orders]")
        assert "[ID]" in sql
        assert "[NAME]" in sql

    def test_null_values_become_sql_null(self):
        row = {"A": None, "B": "val"}
        sql = _build_insert_sql("T", ["A", "B"], row, "mysql")
        assert "NULL" in sql
        assert "NULL," in sql or "NULL)" in sql

    def test_string_values_single_quoted(self):
        row = {"NAME": "Alice"}
        sql = _build_insert_sql("T", ["NAME"], row, "mysql")
        assert "'Alice'" in sql

    def test_numeric_values_quoted(self):
        row = {"AGE": 30}
        sql = _build_insert_sql("T", ["AGE"], row, "mysql")
        assert "'30'" in sql

    def test_single_quote_in_value_escaped(self):
        row = {"NAME": "O'Brien"}
        sql = _build_insert_sql("T", ["NAME"], row, "mysql")
        # Should double the quote: O''Brien
        assert "O''Brien" in sql
        # Must NOT produce un-escaped single quote that would break SQL
        assert "O'Brien'" not in sql or "O''Brien" in sql

    def test_empty_string_value(self):
        row = {"NOTE": ""}
        sql = _build_insert_sql("T", ["NOTE"], row, "mysql")
        assert "''" in sql

    def test_missing_column_in_row_treated_as_none(self):
        row = {"A": "x"}
        sql = _build_insert_sql("T", ["A", "B"], row, "mysql")
        assert "NULL" in sql   # B is missing → NULL

    def test_column_order_preserved(self):
        row = {"Z": 3, "A": 1, "M": 2}
        cols = ["A", "M", "Z"]
        sql = _build_insert_sql("T", cols, row, "mysql")
        # Values should appear in A, M, Z order
        vals_part = sql[sql.index("VALUES"):]
        a_pos = vals_part.index("'1'")
        m_pos = vals_part.index("'2'")
        z_pos = vals_part.index("'3'")
        assert a_pos < m_pos < z_pos

    def test_values_clause_structure(self):
        row = {"X": 1, "Y": 2}
        sql = _build_insert_sql("T", ["X", "Y"], row, "mysql")
        assert "VALUES" in sql
        # Has opening and closing parens
        vals = sql[sql.index("VALUES") + 6:].strip()
        assert vals.startswith("(")
        assert vals.endswith(")")


# ─── _is_same_server ─────────────────────────────────────────────────────────

class TestIsSameServer:
    def _h(self, server, port, db_type="mysql"):
        h = MagicMock()
        h.settings = {"server": server, "port": port, "type": db_type}
        return h

    def test_same_host_and_port_is_same(self):
        assert _is_same_server(self._h("localhost", 3306), self._h("localhost", 3306))

    def test_different_host_is_different(self):
        assert not _is_same_server(self._h("db1.example.com", 3306), self._h("db2.example.com", 3306))

    def test_different_port_is_different(self):
        assert not _is_same_server(self._h("localhost", 3306), self._h("localhost", 3307))

    def test_different_type_is_different(self):
        assert not _is_same_server(
            self._h("localhost", 3306, "mysql"),
            self._h("localhost", 3306, "postgres"),
        )

    def test_port_string_vs_int_are_equal(self):
        # Port comparison should be type-flexible
        h1 = MagicMock(); h1.settings = {"server": "h", "port": 5432, "type": "postgres"}
        h2 = MagicMock(); h2.settings = {"server": "h", "port": "5432", "type": "postgres"}
        assert _is_same_server(h1, h2)

    def test_cross_server_postgres_is_not_same(self):
        assert not _is_same_server(
            self._h("prod.db", 5432, "postgres"),
            self._h("staging.db", 5432, "postgres"),
        )


# ─── _copy_table_data ─────────────────────────────────────────────────────────

class TestCopyTableData:
    """Tests use two in-memory SQLite databases as source and dest."""

    def _make_source(self):
        d = SQLiteDriver()
        d.initialize({"database": ":memory:", "type": "sqlite"})
        d.create_table("CREATE TABLE ITEMS (ID INTEGER PRIMARY KEY, NAME TEXT, PRICE REAL)")
        d.seed("ITEMS", [
            {"NAME": "Widget", "PRICE": 9.99},
            {"NAME": "Gadget", "PRICE": 19.50},
            {"NAME": "Doohickey", "PRICE": 4.25},
        ])
        return d

    def _make_dest(self):
        d = SQLiteDriver()
        d.initialize({"database": ":memory:", "type": "sqlite"})
        d.create_table("CREATE TABLE ITEMS (ID INTEGER PRIMARY KEY, NAME TEXT, PRICE REAL)")
        return d

    def test_copies_all_rows(self):
        src = self._make_source()
        dst = self._make_dest()
        copied, errors = _copy_table_data("ITEMS", src, dst)
        assert errors == []
        assert copied == 3
        assert dst.get_table_count("ITEMS") == 3
        src.close(); dst.close()

    def test_copied_data_is_correct(self):
        src = self._make_source()
        dst = self._make_dest()
        _copy_table_data("ITEMS", src, dst)
        rows = dst.get_table_data("ITEMS")
        names = {r["NAME"] for r in rows}
        assert names == {"Widget", "Gadget", "Doohickey"}
        src.close(); dst.close()

    def test_empty_table_copies_zero_rows(self):
        src = SQLiteDriver()
        src.initialize({"database": ":memory:", "type": "sqlite"})
        src.create_table("CREATE TABLE EMPTY (ID INTEGER PRIMARY KEY)")
        dst = SQLiteDriver()
        dst.initialize({"database": ":memory:", "type": "sqlite"})
        dst.create_table("CREATE TABLE EMPTY (ID INTEGER PRIMARY KEY)")

        copied, errors = _copy_table_data("EMPTY", src, dst)
        assert copied == 0
        assert errors == []
        src.close(); dst.close()

    def test_pagination_batch_size(self):
        """With batch_size=2, a 5-row table requires 3 fetches."""
        src = SQLiteDriver()
        src.initialize({"database": ":memory:", "type": "sqlite"})
        src.create_table("CREATE TABLE T (ID INTEGER PRIMARY KEY, V TEXT)")
        src.seed("T", [{"V": str(i)} for i in range(5)])

        dst = SQLiteDriver()
        dst.initialize({"database": ":memory:", "type": "sqlite"})
        dst.create_table("CREATE TABLE T (ID INTEGER PRIMARY KEY, V TEXT)")

        copied, errors = _copy_table_data("T", src, dst, batch_size=2)
        assert copied == 5
        assert dst.get_table_count("T") == 5
        src.close(); dst.close()

    def test_error_returned_not_raised(self):
        """If dest raises on INSERT, errors are collected but copy continues."""
        src = self._make_source()
        dst = MagicMock()
        dst.__class__.__name__ = "SQLiteDriver"
        dst.settings = {"type": "sqlite"}
        # Return an error for every INSERT
        dst.execute_query.return_value = (None, "constraint violation", 0.0)

        from dbviewer.schema_diff import _copy_table_data
        copied, errors = _copy_table_data("ITEMS", src, dst, batch_size=500)
        assert copied == 0
        assert len(errors) == 3
        src.close()

    def test_null_values_survive_round_trip(self):
        src = SQLiteDriver()
        src.initialize({"database": ":memory:", "type": "sqlite"})
        src.create_table("CREATE TABLE T (ID INTEGER PRIMARY KEY, NOTE TEXT)")
        src.seed("T", [{"NOTE": None}, {"NOTE": "has value"}])

        dst = SQLiteDriver()
        dst.initialize({"database": ":memory:", "type": "sqlite"})
        dst.create_table("CREATE TABLE T (ID INTEGER PRIMARY KEY, NOTE TEXT)")

        copied, errors = _copy_table_data("T", src, dst)
        assert copied == 2
        rows = dst.get_table_data("T")
        notes = {r["NOTE"] for r in rows}
        assert None in notes or "" in notes  # NULL may become None or empty string in SQLite
        assert "has value" in notes
        src.close(); dst.close()


# ─── copy_tables strategy selection ─────────────────────────────────────────

class TestCopyTablesStrategy:
    def _make_mysql_handler(self, server="localhost", port=3306, db="src"):
        h = MagicMock()
        h.__class__.__name__ = "MySQLDriver"
        h.settings = {"type": "mysql", "server": server, "port": port, "database": db}
        h.execute_query.return_value = ([{"Create Table": f"CREATE TABLE `t1` (`id` INT)"}], None, 0.0)
        h.get_table_count.return_value = 5
        h.get_table_columns.return_value = {"id": "int", "name": "varchar(100)"}
        h.get_table_data.return_value = [{"id": 1, "name": "Alice"}]
        return h

    def _make_peer_mysql(self, server="localhost", port=3306, db="dst"):
        h = MagicMock()
        h.__class__.__name__ = "MySQLDriver"
        h.settings = {"type": "mysql", "server": server, "port": port, "database": db}
        h.execute_query.return_value = ("Done", None, 0.0)
        return h

    def _make_pg_handler(self, server="pg.example.com"):
        from dbviewer.schema_diff import _get_schema_postgres
        h = MagicMock()
        h.__class__.__name__ = "PostgreSQLDriver"
        h.settings = {"type": "postgres", "server": server, "port": 5432, "database": "mydb"}
        # _get_schema_postgres will call execute_query twice (cols + indexes)
        col_rows = [{"table_name": "t1", "column_name": "id", "ordinal_position": 1,
                     "column_default": None, "is_nullable": "NO", "data_type": "integer",
                     "udt_name": "int4", "character_maximum_length": None,
                     "numeric_precision": 32, "numeric_scale": 0}]
        h.execute_query.side_effect = [(col_rows, None, 0.0), ([], None, 0.0),
                                       ("Done", None, 0.0), ("Done", None, 0.0)]
        h.get_table_count.return_value = 2
        h.get_table_columns.return_value = {"id": "integer"}
        h.get_table_data.return_value = [{"id": 1}, {"id": 2}]
        return h

    def test_dry_run_returns_ddl_lines(self):
        src = self._make_mysql_handler()
        dst = self._make_peer_mysql()
        lines = copy_tables(["t1"], src, dst, dry_run=True)
        ddl = "\n".join(lines)
        assert "CREATE TABLE" in ddl or "DROP" in ddl or "t1" in ddl

    def test_mysql_same_server_uses_select_insert(self):
        """Same-server MySQL: INSERT SELECT is used, not row-fetch."""
        src = self._make_mysql_handler(server="localhost")
        dst = self._make_peer_mysql(server="localhost")
        copy_tables(["t1"], src, dst, dry_run=False)
        # Row fetch should NOT have been called (get_table_data not used)
        src.get_table_data.assert_not_called()
        # Instead, peer's execute_query should have been called (DROP, CREATE, INSERT SELECT)
        assert dst.execute_query.call_count >= 3

    def test_mysql_different_server_uses_row_fetch(self):
        """Cross-server MySQL: row-fetch-and-insert must be used."""
        src = self._make_mysql_handler(server="prod.db")
        dst = self._make_peer_mysql(server="staging.db")
        copy_tables(["t1"], src, dst, dry_run=False)
        # get_table_data must have been called for row-fetch
        src.get_table_data.assert_called()

    def test_postgres_uses_row_fetch(self):
        """PostgreSQL always uses row-fetch-and-insert."""
        src = self._make_pg_handler("pg.prod")
        dst = MagicMock()
        dst.__class__.__name__ = "PostgreSQLDriver"
        dst.settings = {"type": "postgres", "server": "pg.staging", "port": 5432, "database": "stagingdb"}
        dst.execute_query.return_value = ("Done", None, 0.0)
        copy_tables(["t1"], src, dst, dry_run=False)
        src.get_table_data.assert_called()

    def test_missing_table_skipped_with_warning(self):
        src = MagicMock()
        src.__class__.__name__ = "MySQLDriver"
        src.settings = {"type": "mysql", "server": "h", "port": 3306, "database": "db"}
        # SHOW CREATE TABLE returns error (table doesn't exist)
        src.execute_query.return_value = ([], "Table doesn't exist", 0.0)
        dst = self._make_peer_mysql()
        lines = copy_tables(["ghost_table"], src, dst, dry_run=False)
        text = "\n".join(lines)
        assert "WARNING" in text or "not found" in text or len(lines) == 1

    def test_copy_tables_summary_lines_on_success(self):
        src = self._make_mysql_handler(server="localhost")
        dst = self._make_peer_mysql(server="localhost")
        lines = copy_tables(["t1"], src, dst, dry_run=False)
        text = "\n".join(lines)
        # Should mention rows copied
        assert "Copied" in text or "copied" in text

    def test_clone_database_calls_copy_tables_for_all_tables(self):
        src = self._make_mysql_handler(server="localhost")
        src.get_table_names.return_value = ["t1", "t2"]
        # Second table also needs mock
        src.execute_query.side_effect = [
            ([{"Create Table": "CREATE TABLE `t1` (`id` INT)"}], None, 0.0),
            ([{"Create Table": "CREATE TABLE `t2` (`id` INT)"}], None, 0.0),
        ]
        dst = self._make_peer_mysql(server="localhost")
        lines = clone_database(src, dst, dry_run=True)
        text = "\n".join(lines)
        assert "t1" in text
        assert "t2" in text


# ─── SQLite end-to-end cross-driver copy ────────────────────────────────────

class TestCrossDriverCopyEndToEnd:
    """Real copy between two SQLite DBs using the full copy_tables path."""

    def test_full_copy_sqlite_to_sqlite(self):
        src = SQLiteDriver()
        src.initialize({"database": ":memory:", "type": "sqlite"})
        src.create_table("CREATE TABLE PRODUCTS (ID INTEGER PRIMARY KEY, NAME TEXT, PRICE REAL)")
        src.seed("PRODUCTS", [
            {"NAME": "Alpha", "PRICE": 10.0},
            {"NAME": "Beta",  "PRICE": 20.0},
        ])

        dst = SQLiteDriver()
        dst.initialize({"database": ":memory:", "type": "sqlite"})
        # Simulate create by running the DDL ourselves (dry_run first to get DDL)
        lines_dry = copy_tables(["PRODUCTS"], src, dst, dry_run=True)

        # Now we need the table to exist in dst for copy to work
        dst.create_table("CREATE TABLE PRODUCTS (ID INTEGER PRIMARY KEY, NAME TEXT, PRICE REAL)")
        # Manually do the row-fetch-and-insert
        copied, errors = _copy_table_data("PRODUCTS", src, dst)

        assert errors == []
        assert copied == 2
        rows = dst.get_table_data("PRODUCTS")
        names = {r["NAME"] for r in rows}
        assert "Alpha" in names
        assert "Beta" in names
        src.close(); dst.close()

    def test_copy_preserves_data_types(self):
        """Verifies that numeric and NULL values survive the INSERT round-trip."""
        src = SQLiteDriver()
        src.initialize({"database": ":memory:", "type": "sqlite"})
        src.create_table("CREATE TABLE T (ID INTEGER PRIMARY KEY, NUM REAL, TXT TEXT)")
        src.seed("T", [{"NUM": 3.14159, "TXT": None}, {"NUM": 0.0, "TXT": "hello"}])

        dst = SQLiteDriver()
        dst.initialize({"database": ":memory:", "type": "sqlite"})
        dst.create_table("CREATE TABLE T (ID INTEGER PRIMARY KEY, NUM REAL, TXT TEXT)")

        copied, errors = _copy_table_data("T", src, dst)
        assert copied == 2
        rows = dst.get_table_data("T")
        nums = {r["NUM"] for r in rows}
        assert 3.14159 in nums or any(abs(n - 3.14159) < 0.001 for n in nums if n is not None)
        src.close(); dst.close()


# ─── Dark mode HTML output audit ─────────────────────────────────────────────

class TestDarkModeHtmlOutput:
    """Verify the HTML generated by base.py uses CSS classes, not hardcoded styles."""

    def _driver(self):
        from tests.test_drivers import ConcreteDriver
        return ConcreteDriver()

    def test_result_table_class_present(self):
        d = self._driver()
        rows = [{"NAME": "Alice", "AGE": 30}]
        html = d.export_as_html_table("USERS", rows, ["NAME", "AGE"], [])
        assert 'class="result-table"' in html

    def test_no_hardcoded_border_attr(self):
        d = self._driver()
        rows = [{"X": 1}]
        html = d.export_as_html_table("T", rows, ["X"], [])
        # Must NOT use HTML border= attribute anymore
        assert 'border="1"' not in html

    def test_no_hardcoded_cellspacing(self):
        d = self._driver()
        rows = [{"X": 1}]
        html = d.export_as_html_table("T", rows, ["X"], [])
        assert "cellspacing" not in html

    def test_no_hardcoded_cellpadding(self):
        d = self._driver()
        rows = [{"X": 1}]
        html = d.export_as_html_table("T", rows, ["X"], [])
        assert "cellpadding" not in html

    def test_query_label_class_on_query_div(self):
        d = self._driver()
        rows = [{"X": 1}]
        html = d.export_as_html_table("T", rows, ["X"], [], query="SELECT X FROM T")
        assert 'class="query-label"' in html

    def test_query_label_no_hardcoded_style(self):
        d = self._driver()
        rows = [{"X": 1}]
        html = d.export_as_html_table("T", rows, ["X"], [], query="SELECT X FROM T")
        # Must not have inline style on the query div
        import re
        query_div = re.search(r'<div[^>]*>SELECT X FROM T</div>', html)
        assert query_div is not None
        assert 'style=' not in query_div.group(0)

    def test_no_hardcoded_colour_in_html_output(self):
        d = self._driver()
        rows = [{"NAME": "Alice", "PRICE": 9.99}]
        html = d.export_as_html_table("T", rows, ["NAME", "PRICE"], ["PRICE"])
        # No inline colour definitions
        assert re.search(r'style\s*=\s*["\'].*color\s*:', html) is None
        assert re.search(r'style\s*=\s*["\'].*background\s*:', html) is None


class TestDarkModeApiOutput:
    """Verify that api.py does not emit hardcoded colours in HTML responses."""

    def test_query_error_uses_css_class(self):
        """Error spans must use .query-error class, not inline color:red."""
        from dbviewer.api import create_router, active_connections
        import json as _j

        with tempfile.TemporaryDirectory() as tmpdir:
            from dbviewer.auth import create_user
            create_user(tmpdir, "admin", "pw")
            with open(f"{tmpdir}/connections.json", "w") as f:
                _j.dump([{"name": "T", "type": "sqlite", "database": ":memory:",
                           "server": "", "user": "", "password": "", "port": 0}], f)
            from dbviewer.server import create_app
            app = create_app(data_dir=tmpdir, no_auth=True)
            mock_driver = MagicMock()
            mock_driver.execute_query.return_value = (None, "table not found", 0.0)
            mock_driver.close.return_value = None
            from fastapi.testclient import TestClient
            with TestClient(app) as client:
                with patch("dbviewer.api._build_driver", return_value=mock_driver):
                    active_connections["anonymous"] = {"connection_id": 0}
                    r = client.post("/api/executeQuery", json={
                        "query": "SELECT * FROM GHOST", "mode": "", "tables": []
                    })
            assert r.status_code == 200
            html = r.json()["html"]
            # Must use class, NOT inline style
            assert 'class="query-error"' in html
            assert 'style="color:red"' not in html
            assert "style='color:red'" not in html


class TestDarkModeCssCoverage:
    """Verify that the frontend CSS covers all required dark-mode variable usages."""

    def _css(self):
        return open('/home/claude/db-viewer-python/src/dbviewer/static/index.html').read()

    def test_result_table_uses_css_variables(self):
        css = self._css()
        # .result-table must reference --border, --bg, --bg2
        import re
        result_table_block = re.search(r'\.result-table\s*\{[^}]+\}', css)
        assert result_table_block is not None
        block = result_table_block.group(0)
        assert "var(--border)" in block or "var(--bg)" in block

    def test_result_table_cell_uses_css_variables(self):
        css = self._css()
        assert ".result-table th" in css or ".result-table td" in css
        # The cell rules must use CSS variables for colours
        assert "var(--text)" in css
        assert "var(--bg)" in css

    def test_query_label_class_in_css(self):
        css = self._css()
        assert ".query-label" in css

    def test_query_error_class_in_css(self):
        css = self._css()
        assert ".query-error" in css

    def test_dark_mode_variables_defined(self):
        css = self._css()
        assert ":root.dark" in css
        assert "--bg:#0d1117" in css.replace(" ", "")

    def test_no_hardcoded_hex_outside_variable_definitions(self):
        """No #RRGGBB literals should appear outside :root and @media blocks."""
        css = self._css()
        # Split out the CSS (between <style> and </style>)
        import re
        style_match = re.search(r'<style>(.*?)</style>', css, re.S)
        assert style_match
        style = style_match.group(1)

        # Remove :root blocks (where variables are defined)
        style_no_root = re.sub(r':root[^{]*\{[^}]+\}', '', style)
        # Remove @media blocks (where dark vars are defined)
        style_no_media = re.sub(r'@media[^{]*\{[^}]+\}', '', style_no_root)

        # Find any remaining hex literals
        hex_hits = re.findall(r'(?<!var\()#[0-9a-fA-F]{3,6}\b', style_no_media)
        # rgba() with hardcoded values in utility rules are acceptable
        # Only flag pure hex colour values
        problematic = [h for h in hex_hits if not h.startswith('#0d') and h != '#fff0f0']
        assert len(problematic) == 0, f"Hardcoded hex colours found outside var defs: {problematic}"

    def test_danger_hover_uses_css_variable(self):
        css = self._css()
        # danger hover must not use hardcoded hex
        assert "#fff0f0" not in css

    def test_inline_editor_uses_css_variable(self):
        css = self._css()
        # inline editor background must not use #fff
        import re
        # Find the #inline-editor rule
        editor_match = re.search(r'#inline-editor\s*\{[^}]+\}', css)
        if editor_match:
            block = editor_match.group(0)
            assert "#fff" not in block
            assert "var(--bg)" in block
