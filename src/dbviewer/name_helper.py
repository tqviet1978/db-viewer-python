"""Name transformation utilities — ported from PHP NameHelper."""

from __future__ import annotations

import re


def split_by_words(column: str) -> str:
    """Insert spaces before uppercase letters: 'orderDate' → 'order Date'."""
    return re.sub(r"([^A-Z0-9_\s])([A-Z0-9])", lambda m: m.group(1) + " " + m.group(2), column)


def plural(word: str) -> str:
    """English pluralization: 'Country' → 'Countries', 'Status' → 'Statuses'."""
    # Already-plural guard (Statuses, Countries, Branches)
    if re.search(r"(ses|ies|xes|oes|ches|shes)$", word, re.I):
        return word
    # non-vowel + y → ies
    if re.search(r"[^aeiou]y$", word, re.I):
        return re.sub(r"y$", "ies", word)
    # vowel + s → es (Status → Statuses)
    if re.search(r"(a|e|i|o|u)s$", word, re.I):
        return word + "es"
    # special endings → es (Branch → Branches)
    if re.search(r"(ch|sh|x|z|o)$", word, re.I):
        return word + "es"
    # already ends in s → plural (Items → Items)
    if re.search(r"s$", word, re.I):
        return word
    return word + "s"


def friendly_name(raw: str, keep_spaces: bool = False, plural_form: bool = False, lcfirst: bool = False) -> str:
    """Convert column name to friendly display name.
    Examples: 'ORDER_DATE' → 'Order Date' (keep_spaces) or 'OrderDate'.
    Special: 'ip', 'pr' → uppercase.
    """
    if raw.lower() in ("ip", "pr"):
        return raw.upper()

    raw = re.sub(r"(^id_)", "", raw, flags=re.I)
    raw = re.sub(r"_id_", "_", raw, flags=re.I)

    name = split_by_words(raw)
    name = name.replace("_", " ")
    name = name.title()

    if not keep_spaces:
        name = name.replace(" ", "")

    if plural_form:
        name = plural(name)

    if lcfirst:
        name = name[0].lower() + name[1:] if name else name

    return name


def camel_name(raw: str, lcfirst: bool = False) -> str:
    """CamelCase: 'ORDER_DATE' → 'OrderDate' or 'orderDate'."""
    return friendly_name(raw, keep_spaces=False, lcfirst=lcfirst)


def friendly_module(raw: str, force_hyphenated: bool = False) -> str:
    """Module name: 'ORDER_STATUS' → 'orderstatus' or 'order-status'."""
    raw = re.sub(r"(^id_)", "", raw, flags=re.I)
    raw = re.sub(r"_id_", "_", raw, flags=re.I)

    if force_hyphenated:
        return raw.lower().replace("_", "-")
    else:
        return raw.lower().replace("_", "")


def friendly_title(column: str) -> str:
    """Display title with spaces: 'ORDER_DATE' → 'Order Date'."""
    return friendly_name(column, keep_spaces=True)


def snake_name(name: str) -> str:
    """Snake case with hyphens: 'ORDER_DATE' → 'order-date'."""
    return name.lower().replace("_", "-")


def get_column_title(column: str, ucwords: bool = False) -> str:
    """Column display title: strip id_ prefix, replace _ with space, ucfirst."""
    label = re.sub(r"(^id_)", "", column, flags=re.I)
    label = re.sub(r"_id_", "_", label, flags=re.I)
    label = label.replace("_", " ").lower()
    if ucwords:
        return label.title()
    return label.capitalize()
