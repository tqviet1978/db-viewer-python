"""Tests for name_helper module."""

import pytest
from dbviewer.name_helper import (
    camel_name, friendly_module, friendly_name, friendly_title,
    get_column_title, plural, snake_name, split_by_words,
)


class TestFriendlyName:
    def test_basic_upper_snake(self):
        assert friendly_name("ORDER_DATE", keep_spaces=True) == "Order Date"

    def test_no_spaces(self):
        assert friendly_name("ORDER_DATE") == "OrderDate"

    def test_special_ip(self):
        assert friendly_name("ip") == "IP"
        assert friendly_name("PR") == "PR"

    def test_strip_id_prefix(self):
        result = friendly_name("ID_USER", keep_spaces=True)
        assert "Id" not in result

    def test_lcfirst(self):
        result = friendly_name("ORDER_DATE", lcfirst=True)
        assert result[0].islower()

    def test_plural_form(self):
        result = friendly_name("ORDER_STATUS", keep_spaces=True, plural_form=True)
        assert result.endswith("es") or result.endswith("s")


class TestCamelName:
    def test_order_date(self):
        assert camel_name("ORDER_DATE") == "OrderDate"

    def test_lcfirst(self):
        assert camel_name("ORDER_DATE", lcfirst=True) == "orderDate"

    def test_single_word(self):
        assert camel_name("NAME") == "Name"


class TestPlural:
    def test_country(self):
        assert plural("Country") == "Countries"

    def test_status(self):
        assert plural("Status") == "Statuses"

    def test_items_already_plural(self):
        assert plural("Items") == "Items"

    def test_order(self):
        assert plural("Order") == "Orders"

    def test_company(self):
        assert plural("Company") == "Companies"

    def test_branch(self):
        assert plural("Branch") == "Branches"

    def test_already_ends_es(self):
        # Statuses is already plural — should not double-pluralize
        assert plural("Statuses") == "Statuses"


class TestSnakeName:
    def test_basic(self):
        assert snake_name("ORDER_DATE") == "order-date"

    def test_lowercase(self):
        assert snake_name("USER_NAME") == "user-name"


class TestFriendlyModule:
    def test_no_hyphens(self):
        assert friendly_module("ORDER_STATUS") == "orderstatus"

    def test_hyphenated(self):
        assert friendly_module("ORDER_STATUS", force_hyphenated=True) == "order-status"


class TestGetColumnTitle:
    def test_basic(self):
        assert get_column_title("ORDER_DATE") == "Order date"

    def test_strip_id_prefix(self):
        result = get_column_title("ID_USER")
        assert "id" not in result.lower() or result.lower().startswith("user")

    def test_ucwords(self):
        result = get_column_title("ORDER_DATE", ucwords=True)
        assert result == "Order Date"


class TestSplitByWords:
    def test_camel_case(self):
        result = split_by_words("orderDate")
        assert "order" in result.lower()

    def test_already_uppercase(self):
        result = split_by_words("ORDER_DATE")
        assert result == "ORDER_DATE"
