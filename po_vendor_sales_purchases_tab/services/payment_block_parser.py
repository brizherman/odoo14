# -*- coding: utf-8 -*-
from odoo.addons.po_vendor_sales_purchases_tab.scripts.po_vendor_sheet_parser.parser import (
    ParseResult,
    parse_sheet_rows,
)


def dict_rows_to_values(dict_rows):
    """Convert header-keyed dict rows into a 2D sheet matrix for the parser."""
    if not dict_rows:
        return []
    headers = list(dict_rows[0].keys())
    values = [headers]
    for row in dict_rows:
        values.append([row.get(header, '') for header in headers])
    return values


def parse_dict_rows(dict_rows, *, sheet_row_offset=0):
    """Parse Google Sheets dict rows into normalized invoice records."""
    values = dict_rows_to_values(dict_rows)
    if not values:
        return ParseResult()
    return parse_sheet_rows(values, sheet_row_offset=sheet_row_offset)


def parse_sheet_values(values, *, header_row_index=None, sheet_row_offset=0):
    """Parse raw 2D sheet values (including header row)."""
    if not values:
        return ParseResult()
    return parse_sheet_rows(
        values,
        header_row_index=header_row_index,
        sheet_row_offset=sheet_row_offset,
    )
