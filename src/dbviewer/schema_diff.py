"""Schema comparison and patch generation — ported from PHP DatabaseHelper.

Supports three backends:
  - MySQL  : uses INFORMATION_SCHEMA.COLUMNS + INFORMATION_SCHEMA.STATISTICS
  - PostgreSQL : uses information_schema.columns + pg_indexes
  - MSSQL  : uses sys.columns + sys.indexes + sys.index_columns
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .drivers.base import GenericDriver


def _detect_db_type(handler: "GenericDriver") -> str:
    """Detect database type from handler class name or settings."""
    cls = type(handler).__name__.lower()
    if "mysql" in cls:
        return "mysql"
    if "postgres" in cls or "postgresql" in cls:
        return "postgres"
    if "mssql" in cls:
        return "mssql"
    # Fall back to settings
    return handler.settings.get("type", "mysql").lower()


def _get_schema(handler: "GenericDriver") -> dict:
    """Build a full schema map — dispatches to the correct backend."""
    db_type = _detect_db_type(handler)
    if db_type in ("postgres", "postgresql"):
        return _get_schema_postgres(handler)
    elif db_type == "mssql":
        return _get_schema_mssql(handler)
    else:
        return _get_schema_mysql(handler)


def _get_schema_mysql(handler: "GenericDriver") -> dict:
    """Build schema map from MySQL INFORMATION_SCHEMA."""
    db = handler.settings.get("database", "")
    tables_map: dict = {}

    rows, error, _ = handler.execute_query(
        f"SELECT TABLE_NAME,COLUMN_NAME,ORDINAL_POSITION,COLUMN_DEFAULT,IS_NULLABLE,"
        f"DATA_TYPE,COLLATION_NAME,COLUMN_TYPE,COLUMN_KEY,EXTRA "
        f"FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = '{db}'"
    )
    if error or not isinstance(rows, list):
        return tables_map

    for row in rows:
        table = row["TABLE_NAME"]
        column = row["COLUMN_NAME"]
        tables_map.setdefault(table, {"columns": {}, "indexes": {}})
        tables_map[table]["columns"][column] = row

    rows, error, _ = handler.execute_query(
        f"SELECT TABLE_NAME,NON_UNIQUE,INDEX_NAME,COLUMN_NAME,SEQ_IN_INDEX "
        f"FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA = '{db}'"
    )
    if error or not isinstance(rows, list):
        return tables_map

    for row in rows:
        table = row["TABLE_NAME"]
        index = row["INDEX_NAME"]
        column = row["COLUMN_NAME"]
        tables_map.setdefault(table, {"columns": {}, "indexes": {}})
        tables_map[table]["indexes"].setdefault(index, {})[column] = row

    return tables_map


def _get_schema_postgres(handler: "GenericDriver") -> dict:
    """Build schema map from PostgreSQL information_schema + pg_indexes.

    Normalises column metadata to the same keys used by the MySQL schema map
    so that _diff_columns / _diff_indexes / _get_column_spec work unchanged.
    """
    tables_map: dict = {}

    rows, error, _ = handler.execute_query(
        "SELECT table_name, column_name, ordinal_position, column_default, "
        "is_nullable, data_type, udt_name, character_maximum_length, "
        "numeric_precision, numeric_scale "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' "
        "ORDER BY table_name, ordinal_position"
    )
    if error or not isinstance(rows, list):
        return tables_map

    for row in rows:
        table = row["table_name"]
        column = row["column_name"]
        tables_map.setdefault(table, {"columns": {}, "indexes": {}})

        # Build a COLUMN_TYPE string similar to MySQL
        dtype = row["data_type"]
        udt = row.get("udt_name", dtype)
        max_len = row.get("character_maximum_length")
        prec = row.get("numeric_precision")
        scale = row.get("numeric_scale")
        if max_len:
            col_type = f"{udt}({max_len})"
        elif prec is not None and scale is not None and scale > 0:
            col_type = f"{udt}({prec},{scale})"
        elif prec is not None:
            col_type = f"{udt}({prec})"
        else:
            col_type = udt

        tables_map[table]["columns"][column] = {
            "TABLE_NAME": table,
            "COLUMN_NAME": column,
            "ORDINAL_POSITION": row["ordinal_position"],
            "COLUMN_DEFAULT": row.get("column_default"),
            "IS_NULLABLE": row["is_nullable"],
            "DATA_TYPE": dtype,
            "COLUMN_TYPE": col_type,
            "COLLATION_NAME": "",
            "COLUMN_KEY": "",
            "EXTRA": "",
        }

    # Indexes via pg_indexes
    rows, error, _ = handler.execute_query(
        "SELECT i.relname AS index_name, "
        "       t.relname AS table_name, "
        "       a.attname AS column_name, "
        "       ix.indisunique AS is_unique, "
        "       ix.indisprimary AS is_primary "
        "FROM pg_class t "
        "JOIN pg_index ix ON t.oid = ix.indrelid "
        "JOIN pg_class i ON i.oid = ix.indexrelid "
        "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey) "
        "JOIN pg_namespace n ON n.oid = t.relnamespace "
        "WHERE n.nspname = 'public' "
        "ORDER BY t.relname, i.relname, a.attname"
    )
    if not error and isinstance(rows, list):
        for row in rows:
            table = row["table_name"]
            index = row["index_name"]
            column = row["column_name"]
            if table not in tables_map:
                continue
            non_unique = "0" if row.get("is_unique") else "1"
            tables_map[table]["indexes"].setdefault(index, {})[column] = {
                "INDEX_NAME": index,
                "NON_UNIQUE": non_unique,
                "COLUMN_NAME": column,
                "SEQ_IN_INDEX": 1,
            }

    return tables_map


def _get_schema_mssql(handler: "GenericDriver") -> dict:
    """Build schema map from MSSQL sys.columns + sys.indexes + sys.index_columns.

    Normalises to the same keys used by the MySQL schema map.
    """
    tables_map: dict = {}

    # Columns via INFORMATION_SCHEMA (widely supported on MSSQL)
    rows, error, _ = handler.execute_query(
        "SELECT c.TABLE_NAME, c.COLUMN_NAME, c.ORDINAL_POSITION, "
        "       c.COLUMN_DEFAULT, c.IS_NULLABLE, c.DATA_TYPE, "
        "       c.CHARACTER_MAXIMUM_LENGTH, c.NUMERIC_PRECISION, c.NUMERIC_SCALE, "
        "       COLUMNPROPERTY(OBJECT_ID(c.TABLE_NAME), c.COLUMN_NAME, 'IsIdentity') AS IS_IDENTITY "
        "FROM INFORMATION_SCHEMA.COLUMNS c "
        "JOIN INFORMATION_SCHEMA.TABLES t "
        "  ON c.TABLE_NAME = t.TABLE_NAME AND c.TABLE_SCHEMA = t.TABLE_SCHEMA "
        "WHERE t.TABLE_TYPE = 'BASE TABLE' AND c.TABLE_SCHEMA = 'dbo' "
        "ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION"
    )
    if error or not isinstance(rows, list):
        return tables_map

    for row in rows:
        table = row["TABLE_NAME"]
        column = row["COLUMN_NAME"]
        tables_map.setdefault(table, {"columns": {}, "indexes": {}})

        dtype = row["DATA_TYPE"]
        max_len = row.get("CHARACTER_MAXIMUM_LENGTH")
        prec = row.get("NUMERIC_PRECISION")
        scale = row.get("NUMERIC_SCALE")
        if max_len and max_len != -1:
            col_type = f"{dtype}({max_len})"
        elif prec is not None and scale and scale > 0:
            col_type = f"{dtype}({prec},{scale})"
        elif prec is not None and dtype not in ("int", "bigint", "smallint", "tinyint", "bit"):
            col_type = f"{dtype}({prec})"
        else:
            col_type = dtype

        tables_map[table]["columns"][column] = {
            "TABLE_NAME": table,
            "COLUMN_NAME": column,
            "ORDINAL_POSITION": row["ORDINAL_POSITION"],
            "COLUMN_DEFAULT": row.get("COLUMN_DEFAULT"),
            "IS_NULLABLE": row["IS_NULLABLE"],
            "DATA_TYPE": dtype,
            "COLUMN_TYPE": col_type,
            "COLLATION_NAME": "",
            "COLUMN_KEY": "PRI" if False else "",  # determined from indexes below
            "EXTRA": "auto_increment" if row.get("IS_IDENTITY") == 1 else "",
        }

    # Indexes via sys tables
    rows, error, _ = handler.execute_query(
        "SELECT "
        "    t.name AS table_name, "
        "    i.name AS index_name, "
        "    c.name AS column_name, "
        "    ic.key_ordinal AS seq_in_index, "
        "    i.is_unique AS is_unique, "
        "    i.is_primary_key AS is_primary "
        "FROM sys.tables t "
        "JOIN sys.indexes i ON t.object_id = i.object_id "
        "JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id "
        "JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id "
        "JOIN sys.schemas s ON t.schema_id = s.schema_id "
        "WHERE s.name = 'dbo' "
        "ORDER BY t.name, i.name, ic.key_ordinal"
    )
    if not error and isinstance(rows, list):
        for row in rows:
            table = row["table_name"]
            index = row["index_name"] or "PRIMARY"
            column = row["column_name"]
            if table not in tables_map:
                continue
            non_unique = "0" if row.get("is_unique") else "1"
            tables_map[table]["indexes"].setdefault(index, {})[column] = {
                "INDEX_NAME": index,
                "NON_UNIQUE": non_unique,
                "COLUMN_NAME": column,
                "SEQ_IN_INDEX": row.get("seq_in_index", 1),
            }
            if row.get("is_primary"):
                tables_map[table]["columns"].get(column, {})["COLUMN_KEY"] = "PRI"

    return tables_map


def _get_column_spec(column: str, settings: dict) -> str:
    spec = f"`{column}`"
    spec += " " + settings.get("COLUMN_TYPE", settings.get("DATA_TYPE", ""))

    if settings.get("COLLATION_NAME"):
        spec += f" COLLATE {settings['COLLATION_NAME']}"

    default = settings.get("COLUMN_DEFAULT")
    if default is not None:
        spec += f" DEFAULT '{default}'"
    elif settings.get("IS_NULLABLE") == "YES":
        spec += " DEFAULT NULL"

    if settings.get("IS_NULLABLE") == "NO":
        spec += " NOT NULL"

    if settings.get("EXTRA") == "auto_increment":
        spec += " AUTO_INCREMENT"

    if settings.get("COLUMN_KEY") == "PRI":
        spec += " PRIMARY KEY"

    return spec


def _get_index_spec(index: str, columns: dict, include_key_modifier: bool = False) -> str:
    column_names = list(columns.keys())
    first = columns[column_names[0]]
    x = ""

    if str(first.get("NON_UNIQUE", "1")) == "0":
        if first.get("INDEX_NAME") == "PRIMARY":
            x = "PRIMARY"
        else:
            x = "UNIQUE"

    if include_key_modifier:
        x = (x + " KEY") if x else "KEY"
    
    if index != "PRIMARY":
        x += f" `{index}`"

    x += " (`" + "`, `".join(column_names) + "`)"
    return x


def get_diff(
    handler: "GenericDriver",
    peer_handler: "GenericDriver",
    tables: list[str] | None = None,
) -> str:
    local_schema = _get_schema(handler)
    peer_schema = _get_schema(peer_handler)

    local_tables = list(local_schema.keys())
    peer_tables = list(peer_schema.keys())

    if tables:
        local_tables = [t for t in local_tables if t in tables]
        peer_tables = [t for t in peer_tables if t in tables]

    new_tables = [t for t in local_tables if t not in peer_tables]
    deleted_tables = [t for t in peer_tables if t not in local_tables]
    modified_tables = [t for t in local_tables if t in peer_tables]

    lines: list[str] = []

    # Deleted tables
    for table in deleted_tables:
        lines.append(f">>>  DROP TABLE {table};")
    if deleted_tables:
        lines.append("")

    # Modified tables
    for table in modified_tables:
        schema = local_schema[table]
        peer = peer_schema[table]
        _diff_columns(table, schema["columns"], peer["columns"], lines)
        _diff_indexes(table, schema["indexes"], peer["indexes"], lines)

    # New tables
    for table in new_tables:
        schema = local_schema[table]
        _create_table_sql(table, schema["columns"], schema["indexes"], lines)
        lines.append("")

    return "\n".join(lines)


def _diff_columns(table: str, local_cols: dict, peer_cols: dict, lines: list) -> None:
    new_cols = [c for c in local_cols if c not in peer_cols]
    deleted_cols = [c for c in peer_cols if c not in local_cols]
    common_cols = [c for c in local_cols if c in peer_cols]

    for col in deleted_cols:
        lines.append(f">>  ALTER TABLE {table} DROP COLUMN {col};")
    if deleted_cols:
        lines.append("")

    for col in common_cols:
        local_spec = _get_column_spec(col, local_cols[col])
        peer_spec = _get_column_spec(col, peer_cols[col])
        if local_spec != peer_spec:
            lines.append(f"ALTER TABLE {table} MODIFY COLUMN {local_spec};")

    for col in new_cols:
        spec = _get_column_spec(col, local_cols[col])
        lines.append(f"ALTER TABLE {table} ADD COLUMN {spec};")
    if new_cols:
        lines.append("")


def _diff_indexes(table: str, local_idxs: dict, peer_idxs: dict, lines: list) -> None:
    new_idxs = [i for i in local_idxs if i not in peer_idxs]
    deleted_idxs = [i for i in peer_idxs if i not in local_idxs]
    common_idxs = [i for i in local_idxs if i in peer_idxs]

    for idx in deleted_idxs:
        lines.append(f">  ALTER TABLE {table} DROP INDEX {idx};")
    if deleted_idxs:
        lines.append("")

    active = False
    for idx in common_idxs:
        local_spec = _get_index_spec(idx, local_idxs[idx])
        peer_spec = _get_index_spec(idx, peer_idxs[idx])
        if local_spec != peer_spec:
            spec = _get_index_spec(idx, local_idxs[idx])
            lines.append(f"ALTER TABLE {table} MODIFY INDEX {spec};")
            active = True
    if active:
        lines.append("")

    for idx in new_idxs:
        spec = _get_index_spec(idx, local_idxs[idx])
        lines.append(f"ALTER TABLE {table} ADD INDEX {spec};")
    if new_idxs:
        lines.append("")


def _create_table_sql(table: str, columns: dict, indexes: dict, lines: list) -> None:
    col_lines = [_get_column_spec(col, settings) for col, settings in columns.items()]
    idx_lines = [_get_index_spec(idx, cols, include_key_modifier=True) for idx, cols in indexes.items()]
    all_lines = col_lines + idx_lines
    body = ",\n    ".join(all_lines)
    query = (
        f"CREATE TABLE `{table}` (\n"
        f"    {body}\n"
        f") ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8 COLLATE=utf8_unicode_ci;"
    )
    lines.append(query)


def _build_create_table_from_schema(table: str, handler: "GenericDriver") -> list[str]:
    """Build CREATE TABLE + INSERT statements for a table, backend-aware.

    Returns a list of SQL strings to execute on the peer.
    """
    db_type = _detect_db_type(handler)

    if db_type == "mysql":
        # MySQL: SHOW CREATE TABLE gives us the exact DDL
        rows, error, _ = handler.execute_query(f"SHOW CREATE TABLE `{table}`")
        if error or not rows:
            return []
        create_sql = rows[0].get("Create Table", "")
        source_db = handler.settings.get("database", "")
        return [
            f"DROP TABLE IF EXISTS `{table}`",
            create_sql,
            f"INSERT INTO `{table}` SELECT * FROM `{source_db}`.`{table}`",
        ]

    elif db_type in ("postgres", "postgresql"):
        # PostgreSQL: reconstruct DDL from information_schema + pg_index
        schema = _get_schema_postgres(handler)
        if table not in schema:
            return []
        tbl = schema[table]
        col_lines = []
        for col, info in tbl["columns"].items():
            dtype = info["COLUMN_TYPE"]
            nullable = "" if info["IS_NULLABLE"] == "YES" else " NOT NULL"
            default = f" DEFAULT {info['COLUMN_DEFAULT']}" if info.get("COLUMN_DEFAULT") is not None else ""
            col_lines.append(f'    "{col}" {dtype}{default}{nullable}')
        cols_body = ",\n".join(col_lines)
        create_sql = f'CREATE TABLE IF NOT EXISTS "{table}" (\n{cols_body}\n)'
        insert_sql = f'INSERT INTO "{table}" SELECT * FROM "{table}"'
        return [
            f'DROP TABLE IF EXISTS "{table}"',
            create_sql,
            insert_sql,
        ]

    else:
        # MSSQL: reconstruct from sys tables
        schema = _get_schema_mssql(handler)
        if table not in schema:
            return []
        tbl = schema[table]
        col_lines = []
        for col, info in tbl["columns"].items():
            dtype = info["COLUMN_TYPE"]
            nullable = "NOT NULL" if info["IS_NULLABLE"] == "NO" else "NULL"
            default = f" DEFAULT {info['COLUMN_DEFAULT']}" if info.get("COLUMN_DEFAULT") is not None else ""
            identity = " IDENTITY(1,1)" if "auto_increment" in info.get("EXTRA", "") else ""
            col_lines.append(f"    [{col}] {dtype}{identity}{default} {nullable}")
        cols_body_mssql = ",\n".join(col_lines)
        create_sql = f"CREATE TABLE [{table}] (\n{cols_body_mssql}\n)"
        return [
            f"IF OBJECT_ID(N'[{table}]', N'U') IS NOT NULL DROP TABLE [{table}]",
            create_sql,
            f"INSERT INTO [{table}] SELECT * FROM [{table}]",
        ]


def copy_tables(
    tables: list[str],
    handler: "GenericDriver",
    peer_handler: "GenericDriver",
    dry_run: bool = False,
) -> list[str]:
    """Copy tables from handler's DB to peer_handler's DB.

    Uses backend-specific DDL generation so MySQL/PostgreSQL/MSSQL all work.
    """
    all_queries: list[str] = []

    for table in tables:
        stmts = _build_create_table_from_schema(table, handler)
        all_queries.extend(stmts)

    if not dry_run:
        for q in all_queries:
            peer_handler.execute_query(q)

    return all_queries


def clone_database(
    handler: "GenericDriver",
    peer_handler: "GenericDriver",
    dry_run: bool = False,
) -> list[str]:
    """Clone all tables from handler's DB to peer_handler's DB."""
    all_tables = handler.get_table_names()
    return copy_tables(all_tables, handler, peer_handler, dry_run)
