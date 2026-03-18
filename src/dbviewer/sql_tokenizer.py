"""SQL statement tokenizer.

Splits a SQL script into individual statements, correctly handling:
  - Semicolons inside string literals (single/double-quoted)
  - DELIMITER directives (MySQL stored-procedure convention)
  - Block comments /* ... */
  - Line comments -- ... and # ...
  - Dollar-sign quoting (PostgreSQL $$ ... $$)
  - BEGIN ... END blocks (stored procedures / triggers)

This replaces the naive ``query.split(";")`` approach used in v1.0.0–v1.0.1
which broke on any stored procedure or trigger definition.
"""

from __future__ import annotations

import re


def split_statements(script: str, delimiter: str = ";") -> list[str]:
    """Split *script* into a list of non-empty SQL statements.

    Respects:
    - String literals: ``'...'`` and ``"..."`` (with doubled-quote escape)
    - Block comments: ``/* ... */``
    - Line comments: ``-- ...`` and ``# ...``
    - PostgreSQL dollar-quoting: ``$tag$...$tag$``
    - DELIMITER changes: ``DELIMITER //`` ... ``DELIMITER ;``
    - Nested BEGIN/END blocks (depth-tracked so the delimiter inside is ignored)

    Parameters
    ----------
    script:
        Raw SQL text to split.
    delimiter:
        Initial statement terminator (default ``";"``).  A ``DELIMITER``
        directive in the script overrides this for subsequent statements.

    Returns
    -------
    list[str]
        Each element is a single complete statement, stripped of leading/
        trailing whitespace and the trailing delimiter.  Empty strings are
        excluded.
    """
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(script)
    current_delim = delimiter
    in_single_quote = False
    in_double_quote = False
    in_block_comment = False
    in_line_comment = False
    dollar_tag: str | None = None  # PostgreSQL dollar-quote tag
    begin_depth = 0                # track nested BEGIN...END

    def flush() -> None:
        stmt = "".join(buf).strip()
        # Strip trailing delimiter
        if stmt.upper().endswith(current_delim.upper()):
            stmt = stmt[: -len(current_delim)].strip()
        if stmt:
            statements.append(stmt)
        buf.clear()

    while i < n:
        ch = script[i]
        rest = script[i:]

        # ── Already inside a line comment ──────────────────────────────────
        if in_line_comment:
            buf.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        # ── Already inside a block comment ─────────────────────────────────
        if in_block_comment:
            buf.append(ch)
            if rest.startswith("*/"):
                buf.append("/")
                i += 2
                in_block_comment = False
            else:
                i += 1
            continue

        # ── Already inside dollar-quote ─────────────────────────────────────
        if dollar_tag is not None:
            end_tag = f"${dollar_tag}$"
            if rest.startswith(end_tag):
                buf.append(end_tag)
                i += len(end_tag)
                dollar_tag = None
            else:
                buf.append(ch)
                i += 1
            continue

        # ── Already inside single-quoted string ────────────────────────────
        if in_single_quote:
            buf.append(ch)
            if ch == "'" and i + 1 < n and script[i + 1] == "'":
                buf.append("'")
                i += 2
            elif ch == "'":
                in_single_quote = False
                i += 1
            else:
                i += 1
            continue

        # ── Already inside double-quoted string ────────────────────────────
        if in_double_quote:
            buf.append(ch)
            if ch == '"' and i + 1 < n and script[i + 1] == '"':
                buf.append('"')
                i += 2
            elif ch == '"':
                in_double_quote = False
                i += 1
            else:
                i += 1
            continue

        # ── Check for DELIMITER directive ───────────────────────────────────
        delim_match = re.match(r"DELIMITER\s+(\S+)", rest, re.I)
        if delim_match:
            flush()
            current_delim = delim_match.group(1)
            i += delim_match.end()
            continue

        # ── Enter block comment ─────────────────────────────────────────────
        if rest.startswith("/*"):
            in_block_comment = True
            buf.append("/*")
            i += 2
            continue

        # ── Enter line comment (-- or #) ────────────────────────────────────
        if rest.startswith("--") or (ch == "#" and not in_single_quote and not in_double_quote):
            in_line_comment = True
            buf.append(ch)
            i += 1
            continue

        # ── Enter PostgreSQL dollar-quote ───────────────────────────────────
        dollar_match = re.match(r"\$([^$]*)\$", rest)
        if dollar_match and not in_single_quote and not in_double_quote:
            tag = dollar_match.group(1)
            dollar_tag = tag
            buf.append(dollar_match.group(0))
            i += dollar_match.end()
            continue

        # ── Enter string literals ───────────────────────────────────────────
        if ch == "'":
            in_single_quote = True
            buf.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double_quote = True
            buf.append(ch)
            i += 1
            continue

        # ── Track BEGIN/END depth to avoid splitting inside blocks ──────────
        word_match = re.match(r"\b(BEGIN|END)\b", rest, re.I)
        if word_match:
            kw = word_match.group(1).upper()
            if kw == "BEGIN":
                begin_depth += 1
            elif kw == "END" and begin_depth > 0:
                begin_depth -= 1

        # ── Check for statement delimiter ───────────────────────────────────
        if rest.upper().startswith(current_delim.upper()) and begin_depth == 0:
            buf.append(current_delim)
            i += len(current_delim)
            flush()
            continue

        buf.append(ch)
        i += 1

    # Flush remaining content
    stmt = "".join(buf).strip()
    if stmt:
        # Remove trailing delimiter if present
        if stmt.upper().endswith(current_delim.upper()):
            stmt = stmt[: -len(current_delim)].strip()
        if stmt:
            statements.append(stmt)

    return statements
