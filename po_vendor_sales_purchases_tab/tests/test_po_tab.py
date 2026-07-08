# -*- coding: utf-8 -*-
from datetime import date, timedelta
from unittest.mock import patch
import re

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.po_vendor_sales_purchases_tab.services.sync_engine import window_start_date


@tagged('post_install', '-at_install', 'po_vendor_sales_purchases_tab')
class TestPoVendorTab(TransactionCase):
    def setUp(self):
        super().setUp()
        self.PO = self.env['purchase.order']
        self.Invoice = self.env['vendor.sheet.invoice']
        self.company = self.env.company
        self.vendor = self.env['res.partner'].create({
            'name': 'Convergram Mexico SA',
            'supplier_rank': 1,
        })
        self.other_vendor = self.env['res.partner'].create({
            'name': 'Other Vendor',
            'supplier_rank': 1,
        })
        self.temporada = self.env['purchase.temporada'].search([], limit=1)
        if not self.temporada:
            self.temporada = self.env['purchase.temporada'].create({'name': 'Test Season'})

        self.group_direction = self.env.ref('custom_purchase_flow.group_purchase_direction')
        self.group_dept = self.env.ref('custom_purchase_flow.group_purchase_dept')
        self.group_coordinator = self.env.ref('custom_purchase_flow.group_purchase_coordinator')
        self.group_system = self.env.ref('base.group_system')

        self.user_direction = self._create_user('tab_test_direction', self.group_direction)
        self.user_dept = self._create_user('tab_test_dept', self.group_dept)
        self.user_coordinator = self._create_user('tab_test_coordinator', self.group_coordinator)
        self.user_admin = self.env.ref('base.user_admin')

    def _create_user(self, login, group):
        return self.env['res.users'].create({
            'name': login,
            'login': login,
            'groups_id': [(6, 0, [group.id])],
        })

    def _create_po(self, partner=None, company=None):
        return self.PO.create({
            'partner_id': (partner or self.vendor).id,
            'company_id': (company or self.company).id,
            'temporada_id': self.temporada.id,
        })

    def _form_arch(self, user):
        return self.PO.with_user(user).fields_view_get(view_type='form')['arch']

    def _tab_page_opening_tag(self, arch):
        match = re.search(r'<page[^>]*name="vendor_sales_purchases_tab"[^>]*>', arch)
        return match.group(0) if match else ''

    def test_tab_visible_for_direction_dept_admin(self):
        po = self._create_po()
        po.read(['vendor_sales_matrix'])
        for user in (self.user_direction, self.user_dept, self.user_admin):
            page_tag = self._tab_page_opening_tag(self._form_arch(user))
            self.assertIn('vendor_sales_purchases_tab', page_tag, user.login)
            self.assertNotIn('invisible="1"', page_tag, user.login)

    def test_tab_hidden_for_unauthorized_user(self):
        page_tag = self._tab_page_opening_tag(self._form_arch(self.user_coordinator))
        self.assertIn('vendor_sales_purchases_tab', page_tag)
        self.assertIn('invisible="1"', page_tag)

    def test_reporte_ventas_compras_still_on_form(self):
        arch = self._form_arch(self.user_direction)
        self.assertIn('reporte_ventas_compras', arch)

    def test_filtered_invoices_match_vendor_company_and_window(self):
        today = fields.Date.context_today(self.env.user)
        window_start = window_start_date(today)
        in_window = today - timedelta(days=10)
        early_oldest_month = window_start
        out_window = window_start - timedelta(days=1)
        other_company = self.env['res.company'].search([
            ('id', '!=', self.company.id),
        ], limit=1)

        self.Invoice.sudo().create([
            {
                'sucursal': 'RIO',
                'company_id': self.company.id,
                'proveedor': 'Test',
                'partner_id': self.vendor.id,
                'no_factura': 'INV-IN',
                'fecha': in_window,
                'total_factura': 100.0,
            },
            {
                'sucursal': 'RIO',
                'company_id': self.company.id,
                'proveedor': 'Test',
                'partner_id': self.vendor.id,
                'no_factura': 'INV-EARLY',
                'fecha': early_oldest_month,
                'total_factura': 40.0,
            },
            {
                'sucursal': 'RIO',
                'company_id': self.company.id,
                'proveedor': 'Test',
                'partner_id': self.other_vendor.id,
                'no_factura': 'INV-OTHER-VENDOR',
                'fecha': in_window,
                'total_factura': 50.0,
            },
            {
                'sucursal': 'RIO',
                'company_id': self.company.id,
                'proveedor': 'Test',
                'partner_id': self.vendor.id,
                'no_factura': 'INV-OLD',
                'fecha': out_window,
                'total_factura': 25.0,
            },
        ])
        if other_company:
            self.Invoice.sudo().create({
                'sucursal': 'OTHER',
                'company_id': other_company.id,
                'proveedor': 'Test',
                'partner_id': self.vendor.id,
                'no_factura': 'INV-OTHER-CO',
                'fecha': in_window,
                'total_factura': 75.0,
            })

        po = self._create_po()
        invoice_nos = set(po.vendor_sheet_invoice_ids.mapped('no_factura'))
        self.assertEqual(invoice_nos, {'INV-IN', 'INV-EARLY'})

    def test_purchases_html_groups_invoices_by_month(self):
        today = fields.Date.context_today(self.env.user)
        in_window_june = today.replace(day=15)
        if in_window_june.month == 1:
            in_window_may = in_window_june.replace(year=in_window_june.year - 1, month=12, day=10)
        else:
            in_window_may = in_window_june.replace(month=in_window_june.month - 1, day=10)

        self.Invoice.sudo().create([
            {
                'sucursal': 'RIO',
                'company_id': self.company.id,
                'proveedor': 'Test',
                'partner_id': self.vendor.id,
                'no_factura': 'INV-JUN',
                'fecha': in_window_june,
                'total_factura': 100.0,
            },
            {
                'sucursal': 'RIO',
                'company_id': self.company.id,
                'proveedor': 'Test',
                'partner_id': self.vendor.id,
                'no_factura': 'INV-MAY',
                'fecha': in_window_may,
                'total_factura': 50.0,
            },
        ])
        po = self._create_po()
        html = po.vendor_sheet_purchases_html or ''
        self.assertIn('INV-JUN', html)
        self.assertIn('INV-MAY', html)
        self.assertIn('o_vendor_purchases_month', html)
        self.assertIn('<details', html)
        self.assertIn('<summary', html)
        self.assertIn('Total general', html)
        self.assertIn('o_vendor_purchases_grand_total', html)

    @patch(
        'odoo.addons.po_vendor_sales_purchases_tab.services.sync_engine.run_global_sync',
        return_value={'created': 3, 'updated': 1, 'warnings': ['test'], 'error': None},
    )
    def test_sync_global_button_triggers_global_sync(self, mock_sync):
        po = self._create_po()
        action = po.with_user(self.user_direction).action_sync_global_vendor_sheets()
        mock_sync.assert_called_once()
        self.assertFalse(mock_sync.call_args.kwargs.get('refresh_sales_snapshots', True))
        self.assertEqual(action['tag'], 'display_notification')
        self.assertIn('Sincronización global: 4 facturas', action['params']['message'])

    @patch(
        'odoo.addons.po_vendor_sales_purchases_tab.services.sales_snapshot.recompute_sales_snapshot',
        return_value=12,
    )
    def test_sync_po_button_refreshes_po_panels(self, mock_recompute):
        po = self._create_po()
        action = po.with_user(self.user_dept).action_sync_po_vendor_tab()
        mock_recompute.assert_called_once()
        self.assertEqual(action['tag'], 'display_notification')
        self.assertIn('Paneles de OC actualizados', action['params']['message'])
        self.assertTrue(po.vendor_tab_po_last_sync)
        last_log = self.env['vendor.sheet.sync.log'].search([
            ('sync_type', '=', 'po'),
            ('po_id', '=', po.id),
        ], limit=1)
        self.assertTrue(last_log)

    def test_sync_po_requires_vendor_and_company(self):
        po = self.PO.new({
            'company_id': self.company.id,
            'temporada_id': self.temporada.id,
        })
        with self.assertRaises(UserError):
            po.action_sync_po_vendor_tab()

    def test_staging_readonly_for_tab_users(self):
        with self.assertRaises(Exception):
            self.Invoice.with_user(self.user_direction).create({
                'sucursal': 'RIO',
                'company_id': self.company.id,
                'proveedor': 'Test',
                'no_factura': 'INV-DENIED',
                'fecha': date.today(),
                'total_factura': 10.0,
            })
