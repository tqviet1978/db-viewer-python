"""GenericDriver — abstract base class with all shared logic."""

from __future__ import annotations

import re
import secrets
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional


SYSTEM_COLUMNS = {
    "ID", "REFID", "GUID", "JSON", "WFID", "SSID",
    "CREATION_DATE", "LATEST_VIEW", "LATEST_UPDATE",
    "LATEST_UPDATE_GUID", "IMPORT_REF", "UDID", "UUID", "ID_COMPANY",
}

EDITABLE_COLUMNS = {"NAME", "TITLE", "ALIAS", "SHORT_NAME", "ORDERING"}


class GenericDriver(ABC):
    """Abstract base class for database drivers."""

    settings: dict = {}

    # -------------------------------------------------------------------------
    # Abstract interface — must be implemented by each driver
    # -------------------------------------------------------------------------

    @abstractmethod
    def initialize(self, settings: dict) -> Optional[str]:
        """Connect to the database. Returns error string or None on success."""

    @abstractmethod
    def close(self) -> None:
        """Close the connection."""

    @abstractmethod
    def get_table_names(self) -> list[str]:
        """Return list of all table names."""

    @abstractmethod
    def get_table_columns(self, table: str) -> dict[str, str]:
        """Return {column_name: column_type} for a table."""

    @abstractmethod
    def get_column_names(self, tables: list[str]) -> list[str]:
        """Return sorted unique column names across given tables."""

    @abstractmethod
    def column_exists(self, table: str, column: str) -> tuple[bool, str]:
        """Check if column exists in table. Returns (exists, existing_type)."""

    @abstractmethod
    def get_table_indexes(self, table: str) -> dict[str, list[str]]:
        """Return {index_name: [column_names]} for a table."""

    @abstractmethod
    def get_table_count(self, table: str) -> int:
        """Return row count for a table."""

    @abstractmethod
    def get_table_data(self, table: str, offset: int = 0, limit: int = 100) -> list[dict]:
        """Return rows from a table with pagination."""

    @abstractmethod
    def execute_query(self, query: str) -> tuple[Any, Optional[str], float]:
        """Execute SQL. Returns (result, error, elapsed_ms).
        result is list[dict] for SELECT/SHOW/DESCRIBE, or status string for DML."""

    @abstractmethod
    def truncate_table(self, table: str, dry_run: bool = False) -> str:
        """Truncate table. Returns SQL string if dry_run."""

    @abstractmethod
    def drop_table(self, table: str, dry_run: bool = False) -> str:
        """Drop table. Returns SQL string if dry_run."""

    @abstractmethod
    def rename_table(self, table: str, new_name: str, dry_run: bool = False) -> str:
        """Rename table."""

    @abstractmethod
    def clone_table(self, table: str, new_name: str, dry_run: bool = False) -> str:
        """Clone table with data."""

    @abstractmethod
    def insert_table_row(self, table: str, data: dict) -> int:
        """Insert or update a row. Returns row ID."""

    @abstractmethod
    def drop_index(self, index: str, table: str) -> None:
        """Drop a single index."""

    # -------------------------------------------------------------------------
    # Shared helpers
    # -------------------------------------------------------------------------

    def generate_uuid(self) -> str:
        """Generate a random 32-character hex UUID."""
        return secrets.token_hex(16)

    def get_table_counts(self, tables: list[str]) -> dict[str, int]:
        counts = {}
        for table in tables:
            try:
                counts[table] = self.get_table_count(table)
            except Exception:
                counts[table] = 0
        return counts

    def get_decimal_columns(self, table: str) -> list[str]:
        columns = self.get_normal_table_columns(table)
        return [col for col, dtype in columns.items() if re.search(r"double|decimal", dtype, re.I)]

    # -------------------------------------------------------------------------
    # Column filtering / normalization
    # -------------------------------------------------------------------------

    def get_normal_table_columns(self, table: str, search_string: str = "") -> dict[str, str]:
        """Filter columns, optionally by search pattern, excluding system columns."""
        # Parse exclusions: -KEYWORD
        excludes = re.findall(r"-([A-Za-z]+)", search_string)
        search_term = re.sub(r"-[A-Za-z]+", "", search_string).strip()

        search_by_type = bool(
            re.search(r"[\(]", search_term) or
            re.match(r"^(date|datetime|text|int|varchar|decimal|double|bigint|tinyint|float|char|blob|enum|timestamp)$", search_term, re.I)
        )

        columns = self.get_table_columns(table)
        result = {}
        for column, dtype in columns.items():
            # Exclude system columns if no search
            if not search_term and column.upper() in SYSTEM_COLUMNS:
                continue

            if search_term:
                if search_by_type:
                    if not re.search(search_term, dtype, re.I):
                        continue
                else:
                    if not re.search(search_term, column, re.I):
                        continue

            if excludes and column.upper() in [e.upper() for e in excludes]:
                continue

            result[column] = dtype

        return result

    def get_normalized_column_name(self, column: str) -> str:
        """Convert camelCase or mixed names to UPPER_SNAKE_CASE."""
        # Insert _ before uppercase letters preceded by lowercase
        col = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", column)
        # Insert _ before uppercase+lowercase sequences after uppercase run
        col = re.sub(r"([A-Z])([A-Z][a-z0-9])", r"\1_\2", col)
        # Keep known acronyms
        col = re.sub(r"(.+)(VAT|IP)", r"\1_\2", col)
        col = re.sub(r"([a-z0-9])(of)", r"\1_\2", col)
        return col.upper()

    def get_column_title(self, column: str, ucwords: bool = False) -> str:
        label = re.sub(r"(^id_)", "", column, flags=re.I)
        label = re.sub(r"_id_", "_", label, flags=re.I)
        label = label.replace("_", " ").lower()
        if ucwords:
            label = label.title()
        else:
            label = label.capitalize()
        return label

    # -------------------------------------------------------------------------
    # Schema export
    # -------------------------------------------------------------------------

    def export_tables_as_concept(self, tables: list[str], search: str = "") -> str:
        lines = []
        normalized_lines = []
        should_normalize = False

        for table in tables:
            columns = self.get_normal_table_columns(table, search)
            if not columns:
                continue

            lines.append(f"[{table}]")
            normalized_lines.append(f"[{self.get_normalized_column_name(table)}]")

            for column in columns:
                if not should_normalize:
                    should_normalize = not bool(re.match(r"^[A-Z0-9_]+$", column))
                if not should_normalize:
                    lines.append(column)
                else:
                    normalized_lines.append(self.get_normalized_column_name(column))

            lines.append("")

        lines.append("Done  ")
        normalized_lines.append("Done")

        content = "\n".join(normalized_lines if should_normalize else lines)
        return content.strip()

    def export_table_structures(self, tables: list[str], search: str = "") -> str:
        lines = []
        found_tables = []
        snippet_lines = ["        $tableColumns = [", "            'XXX' => ['CODE'],"]

        for table in tables:
            columns = self.get_normal_table_columns(table, search)
            if not columns:
                continue

            found_tables.append(table)
            col_keys = list(columns.keys())
            col_keys_joined = "', '".join(col_keys)
            snippet_lines.append(f"            '{table}' => ['{col_keys_joined}'],")

            lines.append(f"[{table}]")
            for column, dtype in columns.items():
                lines.append(f"{column:<30} | {dtype}")
            lines.append("")

        snippet_lines.append("        ];")
        snippet_lines.append("")
        lines.extend(snippet_lines)
        lines.append("Done  ")

        if found_tables:
            lines.insert(0, "Tables: " + " ".join(found_tables) + "\n")

        return "\n".join(lines).strip()

    # -------------------------------------------------------------------------
    # HTML rendering
    # -------------------------------------------------------------------------

    def _strval(self, value: Any, is_decimal: bool = False) -> str:
        if value is None:
            return ""
        if is_decimal:
            try:
                return f"{float(value):,.6f}"
            except (TypeError, ValueError):
                return str(value)
        if isinstance(value, (bytes, bytearray)):
            return "&lt;BINARY&gt;"
        if isinstance(value, datetime):
            return value.strftime("%d/%m/%Y")
        # Detect binary-like strings
        s = str(value)
        if "\x00" in s:
            return "&lt;BINARY&gt;"
        return s

    def export_as_html_table(
        self,
        table: Optional[str],
        rows: list[dict],
        columns: list[str],
        decimal_columns: list[str],
        query: Optional[str] = None,
    ) -> str:
        if not rows:
            return "(empty)"

        if not columns:
            columns = list(rows[0].keys()) if rows else []

        html = ""
        if query:
            clean_q = re.sub(r"\s+", " ", query)
            html += f'<div style="white-space: pre-wrap;margin-bottom: 10px;">{clean_q}</div>'

        if table:
            html += f"<h2>.: {table}</h2>"

        html += '<table border="1" cellspacing="5" cellpadding="5">'
        html += "<thead><tr><th>#</th>"
        for col in columns:
            html += f"<th>{col}</th>"
        html += "</tr></thead><tbody>"

        for idx, row in enumerate(rows, 1):
            row_dict = dict(row) if not isinstance(row, dict) else row
            html += f"<tr><td>{idx}</td>"
            for col in columns:
                value = row_dict.get(col)
                is_decimal = col in decimal_columns
                is_editable = col.upper() in EDITABLE_COLUMNS

                if is_editable and table:
                    uuid_val = row_dict.get("UUID", "")
                    attr = f' data-table="{table}" data-column="{col}" data-uuid="{uuid_val}" class="editable-cell"'
                else:
                    attr = ""

                html += f"<td{attr}>{self._strval(value, is_decimal)}</td>"
            html += "</tr>"

        html += "</tbody></table>"
        return html

    def get_indexes_as_html(self, tables: list[str]) -> str:
        lines = []
        for table in tables:
            lines.append(f"[{table}]")
            indexes = self.get_table_indexes(table)
            max_len = max((len(" + ".join(cols)) for cols in indexes.values()), default=0)
            for index, cols in indexes.items():
                col_str = " + ".join(cols)
                lines.append(f"{col_str:<{max_len}} | {index}")
            lines.append("")
        return "\n".join(lines).strip()

    def get_describe_as_html(self, tables: list[str]) -> str:
        htmls = []
        for table in tables:
            rows, error, _ = self.execute_query(f"DESCRIBE {table}")
            if error:
                htmls.append(error)
            elif isinstance(rows, str):
                htmls.append(rows)
            else:
                htmls.append(self.export_as_html_table(table, rows, [], []))
            htmls.append("")
        return "<br/>".join(htmls).strip()

    def get_sizes_as_html(self, tables: list[str]) -> str:
        """Query information_schema for table sizes (MySQL-specific default)."""
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

    # -------------------------------------------------------------------------
    # Table operations (batch)
    # -------------------------------------------------------------------------

    def truncate_tables(self, tables: list[str], dry_run: bool = False) -> str:
        lines = []
        for table in tables:
            res = self.truncate_table(table, dry_run)
            if dry_run:
                lines.append(res or f"TRUNCATE TABLE `{table}`")
            else:
                lines.append(f"Done. {table} is truncated")
        return "<br/>".join(lines)

    def drop_tables(self, tables: list[str], dry_run: bool = False) -> str:
        lines = []
        for table in tables:
            res = self.drop_table(table, dry_run)
            if dry_run:
                lines.append(res or f"DROP TABLE `{table}`")
            else:
                lines.append(f"Done. {table} is dropped")
        return "<br/>".join(lines)

    def drop_indexes(self, tables: list[str]) -> None:
        for table in tables:
            indexes = self.get_table_indexes(table)
            for index in indexes:
                if index.upper() != "PRIMARY":
                    self.drop_index(index, table)

    # -------------------------------------------------------------------------
    # Column operations
    # -------------------------------------------------------------------------

    def alter_column(
        self, tables: list[str], column: str, new_name: str, new_type: str, dry_run: bool = False
    ) -> str:
        responses = []
        for table in tables:
            exists, existing_type = self.column_exists(table, column)
            if not exists:
                continue

            query = None
            if new_name and not new_type:
                if column != new_name:
                    query = f"ALTER TABLE `{table}` RENAME COLUMN `{column}` TO `{new_name}`;"
            elif new_name and new_type:
                if column != new_name or existing_type != new_type:
                    query = f"ALTER TABLE `{table}` CHANGE `{column}` `{new_name}` {new_type};"
            elif not new_name and new_type:
                if existing_type != new_type:
                    query = f"ALTER TABLE `{table}` MODIFY `{column}` {new_type};"

            if query:
                if dry_run:
                    responses.append(query)
                else:
                    result, error, _ = self.execute_query(query)
                    responses.append(error if error else (result if isinstance(result, str) else "Done"))

        return "\n".join(responses)

    def insert_after_column(
        self, tables: list[str], column: str, new_name: str, new_type: str, dry_run: bool = False
    ) -> str:
        if not new_name:
            return "New column name not specified"
        if not new_type:
            return "New column type not specified"

        responses = []
        for table in tables:
            exists, _ = self.column_exists(table, column)
            if not exists:
                continue

            query = f"ALTER TABLE {table} ADD COLUMN {new_name} {new_type} AFTER {column};"
            if dry_run:
                responses.append(query)
            else:
                result, error, _ = self.execute_query(query)
                responses.append(error if error else (result if isinstance(result, str) else "Done"))

        return "\n".join(responses)

    def drop_column(self, tables: list[str], column: str, dry_run: bool = False) -> str:
        responses = []
        for table in tables:
            exists, _ = self.column_exists(table, column)
            if not exists:
                continue

            query = f"ALTER TABLE `{table}` DROP COLUMN `{column}`;"
            if dry_run:
                responses.append(query)
            else:
                result, error, _ = self.execute_query(query)
                responses.append(error if error else (result if isinstance(result, str) else "Done"))

        if not responses:
            return f"Column {column} is not found"

        return "\n".join(responses)

    # -------------------------------------------------------------------------
    # Schema copy / diff integration
    # -------------------------------------------------------------------------

    def get_peer_patch_as_html(self, tables: list[str], peer_handler: "GenericDriver") -> str:
        from ..schema_diff import get_diff
        diff = get_diff(self, peer_handler, tables)
        return diff if diff else "No diff"

    def copy_tables(self, tables: list[str], peer_handler: "GenericDriver", dry_run: bool = False) -> str:
        from ..schema_diff import copy_tables as _copy_tables
        queries = _copy_tables(tables, self, peer_handler, dry_run)
        if not dry_run:
            return "Done."
        return ";\n\n".join(queries) + ";"

    def clone_database(self, peer_handler: "GenericDriver", dry_run: bool = False) -> str:
        from ..schema_diff import clone_database as _clone_database
        queries = _clone_database(self, peer_handler, dry_run)
        if not dry_run:
            return "Done."
        return "<br/>".join(queries)

    # -------------------------------------------------------------------------
    # Code snippets
    # -------------------------------------------------------------------------

    def get_snippets_as_html(self, tables: list[str]) -> str:
        lines = []

        for table in tables:
            lines.append(f"ALTER TABLE {table} MODIFY XXX varchar(255)")
        lines.append("")

        for table in tables:
            lines.append(f"ALTER TABLE {table} ADD INDEX IDX_XXX (XXX)")
            lines.append(f"ALTER TABLE {table} ADD CONSTRAINT IDX_U_XXX UNIQUE KEY (XXX)")
            lines.append(f"CREATE UNIQUE INDEX IDX_U_1 ON {table} (XXX, YYY)")
            lines.append(f"DROP INDEX IDX_U_1 ON {table}")
        lines.append("")

        for table in tables:
            lines.append(f"SELECT * FROM {table} WHERE XXX = ''")
        lines.append("")

        for table in tables:
            lines.append(f"UPDATE {table} SET XXX = '' WHERE XXX = ''")
        lines.append("")

        for table in tables:
            lines.append(f"TRUNCATE TABLE {table}//Confirmed;")
        lines.append("")

        for table in tables:
            lines.append(f"DROP TABLE {table}//Confirmed;")
        lines.append("")

        for table in tables:
            columns = self.get_normal_table_columns(table)
            col_keys = list(columns.keys())

            lines.append(f"{table} ({','.join(col_keys)})\n")
            lines.append(f"[{table}]")
            lines.append(",".join(col_keys) + "\n")
            lines.append("'" + "', '".join(col_keys) + "'\n")

            for col in col_keys:
                lines.append(f"        $model->{col} = ")
            lines.append("")

            for col in col_keys:
                lines.append(f"        $model->{col} = $x->{col};")
            lines.append("")

            for col in col_keys:
                lines.append(f"        {col}: '',")
            lines.append("")

            lines.append("        $data = [")
            for col in col_keys:
                from ..name_helper import camel_name
                camel = camel_name(col, lcfirst=True)
                lines.append(f"            '{camel}' => '',")
            lines.append("        ];")
            lines.append("")

            # InsertOne (type 1)
            lines.append("        $model = (new WarehousePutItemCollection)->insertOne([")
            for col in col_keys:
                lines.append(f"            '{col}' => $row->{col},")
            lines.append("        ]);")
            lines.append("")

            # InsertOne (type 2)
            lines.append("        $model = (new WarehousePutItemCollection)->insertOne([")
            for col in col_keys:
                lines.append(f"            '{col}' => '',")
            lines.append("        ]);")
            lines.append("")

            # UpdateOne
            lines.append("        $model = (new WarehousePutItemCollection)->updateOne([], [")
            for col in col_keys:
                lines.append(f"            '{col}' => '',")
            lines.append("        ], [\"upsert\" => false]);")
            lines.append("")

            # naive-ui columns
            lines.append("const columns = [")
            for i, col in enumerate(col_keys):
                title = self.get_column_title(col)
                sorter = ", sorter: 'default'" if i == 0 else ""
                lines.append(f"  {{title: '{title}', key: '{col}'{sorter}}},")
            lines.append("]")
            lines.append("")

        return "\n".join(lines).strip()

    def get_toString_as_html(self, tables: list[str]) -> str:
        lines = []
        lines.append(",".join(tables))
        lines.append("")

        for table in tables:
            module = table.lower().replace("_", "")
            lines.append(f"* {module}")
        lines.append("")

        for table in tables:
            lines.append(f"[{table}]")
        lines.append("")

        for table in tables:
            module = table.lower().replace("_", "")
            lines.append(f"[{module}]")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Fake data generation
    # -------------------------------------------------------------------------

    def _generate_random_string(self, length: int, chars: str = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") -> str:
        import random
        return "".join(random.choice(chars) for _ in range(length))

    def _generate_fake_value(self, column: str, dtype: str) -> str:
        import random
        type0 = dtype.split("(")[0].lower().strip()

        if type0 == "date":
            import random
            import time
            ts = random.randint(946684800, 1640995200)  # 2000–2022
            return f"'{datetime.fromtimestamp(ts).strftime('%Y-%m-%d')}'"
        elif type0 == "time":
            return f"'{random.randint(0,23):02d}:{random.randint(0,59):02d}'"
        elif type0 == "enum":
            m = re.findall(r"'(.*?)'", dtype)
            if m:
                return f"'{random.choice(m)}'"
            return "''"
        elif type0 == "decimal":
            return str(round(random.uniform(0.1, 10.0), 2))
        else:
            return self._generate_fake_heuristics(column)

    def _generate_fake_heuristics(self, column: str) -> str:
        import random
        col = column.lower().replace(" ", "")

        if col == "uuid":
            return f"'{self._generate_random_string(32)}'"
        elif col == "udid":
            return "'0'"
        elif re.match(r"^id_(.+)$", column, re.I) or re.search(r"_id_(.+)$", column, re.I):
            return f"'{self._generate_random_string(16, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')}'"
        elif re.search(r"date", col):
            import time
            ts = random.randint(946684800, 1640995200)
            return f"'{datetime.fromtimestamp(ts).strftime('%Y-%m-%d')}'"
        elif re.search(r"no$|number$", col):
            return f"'{self._generate_random_string(6, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')}'"
        elif re.search(r"order|source|consignee|name|module|column|type|code|do_no", col):
            return f"'{self._generate_random_string(10)}'"
        elif re.search(r"kgs|quantity", col):
            return str(random.randint(1, 100))
        elif re.search(r"price", col):
            return str(random.randint(20000, 500000))
        elif re.search(r"phone", col):
            return f"'{self._generate_random_string(10, '0123456789')}'"
        elif re.search(r"time", col):
            return f"'{random.randint(0,23):02d}:{random.randint(0,59):02d}'"
        else:
            return f"'{self._generate_random_string(16)}'"

    def insert_fake_data(self, table: str, n: int = 5) -> None:
        columns = self.get_table_columns(table)
        for _ in range(n):
            col_names = ", ".join(f"`{c}`" for c in columns)
            values = ", ".join(self._generate_fake_value(c, t) for c, t in columns.items())
            query = f"INSERT INTO `{table}` ({col_names}) VALUES ({values})"
            self.execute_query(query)
