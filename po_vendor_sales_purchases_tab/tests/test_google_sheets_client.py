# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.po_vendor_sales_purchases_tab.services.google_sheets_client import (
    DEFAULT_TAB_NAME,
    GoogleSheetsClient,
)


@tagged('post_install', '-at_install', 'po_vendor_sales_purchases_tab')
class TestGoogleSheetsClient(TransactionCase):
    def setUp(self):
        super().setUp()
        self.client = GoogleSheetsClient(self.env)
        self.config = self.env['vendor.sheet.config'].get_singleton()

    def test_format_sheet_range_quotes_spaces(self):
        self.assertEqual(
            GoogleSheetsClient._format_sheet_range('Pagos Proveedores'),
            "'Pagos Proveedores'",
        )

    def test_format_sheet_range_escapes_single_quotes(self):
        self.assertEqual(
            GoogleSheetsClient._format_sheet_range("Vendor's Tab"),
            "'Vendor''s Tab'",
        )

    def test_resolve_tab_title_exact_match(self):
        titles = ['Pagos Proveedores ', 'Gastos ']
        self.assertEqual(
            GoogleSheetsClient._resolve_tab_title(titles, 'Pagos Proveedores '),
            'Pagos Proveedores ',
        )

    def test_resolve_tab_title_ignores_surrounding_whitespace(self):
        titles = ['Pagos Proveedores ', 'Gastos ']
        self.assertEqual(
            GoogleSheetsClient._resolve_tab_title(titles, 'Pagos Proveedores'),
            'Pagos Proveedores ',
        )

    def test_resolve_tab_title_lists_available_tabs_on_miss(self):
        titles = ['Pagos Proveedores ', 'Gastos ']
        with self.assertRaises(UserError) as ctx:
            GoogleSheetsClient._resolve_tab_title(titles, 'Missing Tab')
        self.assertIn('Pagos Proveedores ', str(ctx.exception))

    def test_get_tab_name_from_settings(self):
        self.config.sheet_tab_name = 'My Custom Tab'
        self.assertEqual(self.client._get_tab_name(), 'My Custom Tab')

    def test_get_tab_name_explicit_override(self):
        self.config.sheet_tab_name = 'Settings Tab'
        self.assertEqual(self.client._get_tab_name('Override Tab'), 'Override Tab')

    def test_get_tab_name_defaults_when_settings_empty(self):
        self.config.sheet_tab_name = False
        self.assertEqual(self.client._get_tab_name(), DEFAULT_TAB_NAME)
