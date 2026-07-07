# -*- coding: utf-8 -*-
from datetime import date, timedelta
from unittest.mock import patch
import re

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


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
        in_window = today - timedelta(days=10)
        out_window = today - timedelta(days=120)
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
        self.assertEqual(invoice_nos, {'INV-IN'})

    @patch(
        'odoo.addons.po_vendor_sales_purchases_tab.services.sync_engine.run_global_sync',
        return_value={'created': 3, 'updated': 1, 'warnings': ['test'], 'error': None},
    )
    def test_sync_button_triggers_global_sync(self, mock_sync):
        po = self._create_po()
        action = po.with_user(self.user_direction).action_sync_vendor_sheet_data()
        mock_sync.assert_called_once()
        self.assertEqual(action['tag'], 'display_notification')
        self.assertIn('Synced 4 invoices', action['params']['message'])

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
