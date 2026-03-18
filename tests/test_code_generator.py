"""Tests for code_generator module."""

import pytest
from dbviewer.code_generator import analyze_column_type, generate_vue_code


class TestAnalyzeColumnType:
    def test_int_type(self):
        result = analyze_column_type("QUANTITY", "int(11)")
        assert result["is_int"] is True
        assert result["is_decimal"] is False

    def test_decimal_type(self):
        result = analyze_column_type("PRICE", "decimal(10,2)")
        assert result["is_decimal"] is True
        assert result["is_percent"] is False

    def test_percent_rate(self):
        result = analyze_column_type("TAX_RATE", "decimal(5,2)")
        assert result["is_decimal"] is True
        assert result["is_percent"] is True

    def test_date_type(self):
        result = analyze_column_type("CREATED_AT", "datetime")
        assert result["is_date"] is True

    def test_dob_column(self):
        result = analyze_column_type("DOB", "varchar(20)")
        assert result["is_date"] is True

    def test_bool_is_prefix(self):
        result = analyze_column_type("IS_ACTIVE", "tinyint(1)")
        assert result["is_bool"] is True

    def test_bool_has_prefix(self):
        result = analyze_column_type("HAS_INVOICE", "tinyint(1)")
        assert result["is_bool"] is True

    def test_gender_column(self):
        result = analyze_column_type("GENDER", "varchar(1)")
        assert result["is_gender"] is True

    def test_ref_column_id_prefix(self):
        result = analyze_column_type("ID_COUNTRY", "int(11)")
        assert result["is_ref"] is True
        assert result["ref_module"] == "country"

    def test_ref_column_infix(self):
        result = analyze_column_type("ORDER_ID_STATUS", "int(11)")
        assert result["is_ref"] is True

    def test_code_is_readonly(self):
        result = analyze_column_type("CODE", "varchar(50)")
        assert result["is_readonly"] is True

    def test_plain_varchar(self):
        result = analyze_column_type("NAME", "varchar(255)")
        assert result["is_int"] is False
        assert result["is_ref"] is False
        assert result["is_bool"] is False
        assert result["is_date"] is False


class TestGenerateVueCode:
    def setup_method(self):
        self.table = "ORDER_ITEM"
        self.columns = {
            "ID": "int(11)",
            "UUID": "varchar(32)",
            "CODE": "varchar(50)",
            "ID_PRODUCT": "int(11)",
            "QUANTITY": "int(11)",
            "UNIT_PRICE": "decimal(12,2)",
            "TAX_RATE": "decimal(5,2)",
            "IS_CONFIRMED": "tinyint(1)",
            "ORDER_DATE": "date",
        }

    def test_generates_form_and_panel(self):
        code = generate_vue_code(self.table, self.columns)
        assert "Form.vue" in code
        assert "Panel.vue" in code

    def test_form_has_template_and_script(self):
        code = generate_vue_code(self.table, self.columns)
        assert "<template>" in code
        assert "<script setup" in code

    def test_ref_uses_x_select(self):
        code = generate_vue_code(self.table, self.columns)
        assert "x-select" in code

    def test_decimal_uses_input_number(self):
        code = generate_vue_code(self.table, self.columns)
        assert "x-input-number" in code

    def test_bool_uses_checkbox(self):
        code = generate_vue_code(self.table, self.columns)
        assert "x-checkbox" in code

    def test_date_uses_x_date(self):
        code = generate_vue_code(self.table, self.columns)
        assert "x-date" in code

    def test_system_columns_excluded(self):
        code = generate_vue_code(self.table, self.columns)
        # UUID, ID should not appear as form fields
        assert "v-model:value=\"model.UUID\"" not in code
        assert "v-model:value=\"model.ID\"" not in code

    def test_panel_has_columns_array(self):
        code = generate_vue_code(self.table, self.columns)
        assert "const columns = [" in code
