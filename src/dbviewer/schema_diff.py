"""Schema comparison and patch generation — ported from PHP DatabaseHelper."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .drivers.base import GenericDriver


def _get_schema(handler: "GenericDriver") -> dict:
    """Build a full schema map from INFORMATION_SCHEMA (MySQL-specific)."""
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


def copy_tables(
    tables: list[str],
    handler: "GenericDriver",
    peer_handler: "GenericDriver",
    dry_run: bool = False,
) -> list[str]:
    source_db = handler.settings.get("database", "")
    queries: list[str] = []

    for table in tables:
        rows, error, _ = handler.execute_query(f"SHOW CREATE TABLE {table}")
        if error or not rows:
            continue
        create_sql = rows[0].get("Create Table", "")
        queries.append(f"DROP TABLE IF EXISTS {table}")
        queries.append(create_sql)
        queries.append(f"INSERT INTO {table} SELECT * FROM {source_db}.{table}")

    if not dry_run:
        for q in queries:
            peer_handler.execute_query(q)

    return queries


def clone_database(
    handler: "GenericDriver",
    peer_handler: "GenericDriver",
    dry_run: bool = False,
) -> list[str]:
    all_tables = handler.get_table_names()
    return copy_tables(all_tables, handler, peer_handler, dry_run)
