"""Code generation — Vue 3 components and SQL snippets."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .name_helper import camel_name, friendly_module, friendly_title, snake_name

if TYPE_CHECKING:
    from .drivers.base import GenericDriver


def analyze_column_type(column: str, dbtype: str) -> dict:
    """Returns flags dict for a column based on its name and DB type."""
    result = {
        "is_int": False,
        "is_decimal": False,
        "is_percent": False,
        "is_date": False,
        "is_bool": False,
        "is_gender": False,
        "is_ref": False,
        "ref_module": "",
        "is_readonly": False,
    }

    m = re.match(r"^id_(.+)$", column, re.I) or re.match(r"^.+_id_(.+)$", column, re.I)
    if m:
        result["is_ref"] = True
        result["ref_module"] = friendly_module(m.group(1))
    elif re.match(r"^(gender)$", column, re.I):
        result["is_gender"] = True
    elif re.match(r"^(is_|has_)", column, re.I):
        result["is_bool"] = True
    elif re.match(r"^(dob)$", column, re.I):
        result["is_date"] = True
    elif re.match(r"^int", dbtype, re.I):
        result["is_int"] = True
    elif re.match(r"^(decimal|double)", dbtype, re.I):
        result["is_decimal"] = True
        if re.search(r"_(rate)$", column, re.I):
            result["is_percent"] = True
    elif re.match(r"^date", dbtype, re.I):
        result["is_date"] = True

    if re.match(r"^(code)$", column, re.I):
        result["is_readonly"] = True

    return result


def generate_vue_code(table: str, columns: dict[str, str]) -> str:
    """Generate Vue 3 Panel + Form components for a table."""
    sep = "+" * 82

    form_html = _get_vue_form(table, columns)
    panel_html = _get_vue_panel(table, columns)

    lines = [
        sep,
        camel_name(table) + "Form.vue",
        sep,
        "",
        form_html,
        "",
        sep,
        camel_name(table) + "Panel.vue",
        sep,
        "",
        panel_html,
    ]
    return "\n".join(lines).strip()


def _get_form_columns(columns: dict[str, str]) -> dict[str, str]:
    syscolumns = {
        "ID", "REFID", "GUID", "JSON", "WFID", "SSID", "CREATION_DATE",
        "LATEST_VIEW", "LATEST_UPDATE", "LATEST_UPDATE_GUID", "IMPORT_REF",
        "UDID", "UUID", "ID_COMPANY",
    }
    return {k: v for k, v in columns.items() if k.upper() not in syscolumns}


def _get_vue_form(table: str, all_columns: dict[str, str]) -> str:
    module = friendly_module(table)
    form_cols = _get_form_columns(all_columns)

    xselect = xdate = xcheckbox = xgender = xnumber = xpercent = False
    lines = [
        "<template>",
        f'  <x-form module="{module}" :blank="blank">',
        '    <template #main="{model}">',
        f'      <n-grid :cols="{3 if len(form_cols) > 6 else 2}" :x-gap="20" :y-gap="5">',
    ]

    for column, dbtype in form_cols.items():
        col2 = re.sub(r"^(is_|has_)", "", column, flags=re.I)
        label = friendly_title(col2)
        flags = analyze_column_type(column, dbtype)
        readonly = ':readonly="!!model.UUID" ' if flags["is_readonly"] else ""

        if flags["is_percent"]:
            lines += [
                f'        <n-form-item-gi label="{label}">',
                f'          <x-input-percent v-model:value="model.{column}" placeholder="" />',
                "        </n-form-item-gi>",
            ]
            xpercent = True
        elif flags["is_int"] or flags["is_decimal"]:
            lines += [
                f'        <n-form-item-gi label="{label}">',
                f'          <x-input-number v-model:value="model.{column}" placeholder="" />',
                "        </n-form-item-gi>",
            ]
            xnumber = True
        elif flags["is_date"]:
            lines += [
                f'        <n-form-item-gi label="{label}">',
                f'          <x-date v-model="model.{column}" placeholder="" />',
                "        </n-form-item-gi>",
            ]
            xdate = True
        elif flags["is_gender"]:
            lines += [
                f'        <n-form-item-gi label="{label}">',
                f'          <x-input-gender v-model="model.{column}" />',
                "        </n-form-item-gi>",
            ]
            xgender = True
        elif flags["is_bool"]:
            lines += [
                f'        <n-form-item-gi label="{label}?">',
                f'          <x-checkbox v-model="model.{column}" />',
                "        </n-form-item-gi>",
            ]
            xcheckbox = True
        elif flags["is_ref"]:
            lines += [
                f'        <n-form-item-gi label="{label}">',
                f'          <x-select v-model="model.{column}" module="{flags["ref_module"]}" placeholder=""/>',
                "        </n-form-item-gi>",
            ]
            xselect = True
        else:
            lines += [
                f'        <n-form-item-gi label="{label}">',
                f'          <n-input v-model:value="model.{column}" placeholder="" {readonly}/>',
                "        </n-form-item-gi>",
            ]

    lines += [
        "      </n-grid>",
        "    </template>",
        "  </x-form>",
        "</template>",
        "",
        "<script setup lang=\"ts\">",
        "import { NGrid, NFormItemGi, NInput } from 'naive-ui'",
        "import XForm from '@/components/XForm.vue'",
    ]

    if xcheckbox:
        lines.append("import XCheckbox from '@/components/XCheckbox.vue'")
    if xdate:
        lines.append("import XDate from '@/components/XDate.vue'")
    if xgender:
        lines.append("import XInputGender from '@/components/XInputGender.vue'")
    if xnumber:
        lines.append("import XInputNumber from '@/components/XInputNumber.vue'")
    if xpercent:
        lines.append("import XInputPercent from '@/components/XInputPercent.vue'")
    if xselect:
        lines.append("import XSelect from '@/components/XSelect.vue'")

    lines += ["", "const blank = {"]
    for col in form_cols:
        lines.append(f"  {col}: '',")
    lines += ["  UUID: ''", "}", "</script>"]

    return "\n".join(lines).strip()


def _get_vue_panel(table: str, all_columns: dict[str, str]) -> str:
    module = friendly_module(table)
    camel = camel_name(table)
    sname = snake_name(table)
    list_cols = _get_form_columns(all_columns)

    reftext_cols = []
    col_lines = []

    for i, (column, dbtype) in enumerate(list_cols.items()):
        col2 = re.sub(r"^(is_|has_)", "", column, flags=re.I)
        label = friendly_title(col2)
        flags = analyze_column_type(column, dbtype)
        sorter = ", sorter: 'default'" if i == 0 else ""

        if flags["is_ref"]:
            col_lines.append(f"  {{title: '{label}', key: 'reftext_{column}'{sorter}}},")
            reftext_cols.append(column)
        elif flags["is_int"] or flags["is_decimal"] or flags["is_date"]:
            col_lines.append(f"  {{title: '{label}', key: 'formatted_{column}'{sorter}}},")
        else:
            col_lines.append(f"  {{title: '{label}', key: '{column}'{sorter}}},")

    formatted_lines = []
    for column, dbtype in list_cols.items():
        flags = analyze_column_type(column, dbtype)
        if flags["is_percent"]:
            formatted_lines.append(f"    formatted_{column}: percentFormat(item.{column}),")
        elif flags["is_int"] or flags["is_decimal"]:
            formatted_lines.append(f"    formatted_{column}: numberFormat(item.{column}),")
        elif flags["is_date"]:
            formatted_lines.append(f"    formatted_{column}: dateFormat(item.{column}),")

    reftext_str = ",".join(reftext_cols)
    lines = [
        "<template>",
        f"  <{sname}-form @saved=\"onItemSaved\" @deleted=\"onItemDeleted\" :item=\"item\" />",
        '  <x-list :columns="columns" :data="items" @clicked="onItemClicked" :loading="loading.loadData" />',
        "</template>",
        "",
        '<script setup lang="ts">',
        "import { computed } from 'vue'",
        "import { storeToRefs } from 'pinia'",
        "import { useGlobalStore } from '@/stores/global'",
        "import { usePanelBehavior } from '@/composables/panel'",
        "import { numberFormat, dateFormat, percentFormat } from '@/composables/format'",
        f"import {camel}Form from './{camel}Form.vue'",
        "import XList from '@/components/XList.vue'",
        "",
        "const { companyCode } = storeToRefs(useGlobalStore())",
        "",
        "const columns = [",
    ] + col_lines + [
        "]",
        "",
        "const dataUrl = computed(() => {",
        f"  return '/api/{module}/getItems?companyCode=' + companyCode.value + '&reftextColumns={reftext_str}'",
        "})",
        "",
        "const getFormattedItem = function (item: any) {",
        "  return {",
        "    ...item,",
    ] + formatted_lines + [
        "  }",
        "}",
        "",
        "const { items, item, onItemClicked, onItemSaved, onItemDeleted, loading } = usePanelBehavior(dataUrl, getFormattedItem)",
        "</script>",
    ]

    return "\n".join(lines).strip()
