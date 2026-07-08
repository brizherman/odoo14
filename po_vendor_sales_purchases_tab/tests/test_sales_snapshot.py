# -*- coding: utf-8 -*-
import json
from datetime import date
from unittest.mock import MagicMock

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.po_vendor_sales_purchases_tab.services.sales_aggregator import (
    compute_sales_matrix,
)
from odoo.addons.po_vendor_sales_purchases_tab.services.sales_snapshot import (
    get_sales_matrix_for_po,
    matrix_from_snapshot,
    recompute_sales_snapshot,
)
from odoo.addons.po_vendor_sales_purchases_tab.services.sync_engine import run_global_sync


def _invoice_row(no_factura, fecha, total, total_pago='', fecha_pago='', sucursal='RIO'):
    return {
        'Proveedor': 'Snapshot Vendor',
        'Proveedor 2': '',
        'Ubicacion': sucursal,
        'No. Factura': no_factura,
        'Fecha': fecha,
        'Vence': fecha,
        'Total de Factura': total,
        'Total de pago': total_pago,
        'Fecha de pago': fecha_pago,
    }


@tagged('post_install', '-at_install', 'po_vendor_sales_purchases_tab')
class TestSalesSnapshot(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.Department = self.env['product.classification.department']
        self.ClassificationVendor = self.env['product.classification.vendor']
        self.ProductTemplate = self.env['product.template']
        self.SaleOrder = self.env['sale.order']
        self.Snapshot = self.env['vendor.sales.snapshot']

        self.dept_a = self.Department.create({'name': 'Dept A Snapshot'})
        self.class_vendor = self.ClassificationVendor.create({
            'name': 'Snapshot Vendor Class',
        })
        self.vendor = self.env['res.partner'].create({
            'name': 'Snapshot Vendor SA',
            'supplier_rank': 1,
        })
        self.env['vendor.sheet.mapping'].create({
            'sheet_proveedor': 'Snapshot Vendor',
            'partner_id': self.vendor.id,
            'classification_vendor_id': self.class_vendor.id,
        })
        self.product = self.ProductTemplate.create({
            'name': 'Snapshot Product',
            'type': 'product',
            'list_price': 100.0,
            'classification_vendor': self.class_vendor.id,
            'classification_department': self.dept_a.id,
        }).product_variant_id
        self.reference_date = date(2026, 7, 15)

    def _create_sale(self, amount, order_datetime):
        team = self.env['crm.team'].search([
            ('company_id', 'in', [False, self.company.id]),
        ], limit=1)
        order = self.SaleOrder.with_company(self.company).create({
            'partner_id': self.env['res.partner'].create({'name': 'Customer'}).id,
            'company_id': self.company.id,
            'team_id': team.id if team else False,
            'date_order': order_datetime,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1.0,
                'price_unit': amount,
            })],
        })
        order.action_confirm()
        order.write({'date_order': order_datetime})
        return order

    def test_recompute_writes_snapshot_rows(self):
        self._create_sale(100.0, '2026-07-10 12:00:00')
        rows = recompute_sales_snapshot(
            self.env,
            self.vendor.id,
            self.company.id,
            reference_date=self.reference_date,
        )
        self.assertGreater(rows, 0)
        self.assertTrue(self.Snapshot.search_count([
            ('partner_id', '=', self.vendor.id),
            ('company_id', '=', self.company.id),
        ]))

    def test_matrix_from_snapshot_matches_live_compute(self):
        self._create_sale(100.0, '2026-07-10 12:00:00')
        recompute_sales_snapshot(
            self.env,
            self.vendor.id,
            self.company.id,
            reference_date=self.reference_date,
        )
        live = compute_sales_matrix(
            self.env,
            self.vendor.id,
            self.company.id,
            reference_date=self.reference_date,
        )
        cached = matrix_from_snapshot(
            self.env,
            self.vendor.id,
            self.company.id,
            reference_date=self.reference_date,
        )
        self.assertIsNotNone(cached)
        self.assertAlmostEqual(cached['total'], live['total'])
        self.assertEqual(
            cached['cells'][str(self.dept_a.id)]['2026-07'],
            live['cells'][str(self.dept_a.id)]['2026-07'],
        )

    def test_po_reads_snapshot_after_sync_po(self):
        self._create_sale(80.0, '2026-07-05 12:00:00')
        config = self.env['vendor.sheet.config'].get_singleton()
        month = self.env['vendor.sheet.month'].search([
            ('config_id', '=', config.id),
            ('name', '=', '2026-07'),
        ], limit=1)
        if not month:
            month = self.env['vendor.sheet.month'].create({
                'config_id': config.id,
                'name': '2026-07',
                'spreadsheet_id': 'sheet-july-snapshot',
            })
        else:
            month.write({'spreadsheet_id': 'sheet-july-snapshot', 'synced_once': False})

        sucursal = self.env['vendor.sucursal.mapping'].search([
            ('sucursal', '=', 'RIO'),
        ], limit=1)
        if not sucursal:
            self.env['vendor.sucursal.mapping'].create({
                'sucursal': 'RIO',
                'company_id': self.company.id,
            })

        client = MagicMock()
        client.fetch_sheet_rows.return_value = [
            _invoice_row('SNAP-001', '1/7/2026', '$50.00'),
        ]
        result = run_global_sync(
            self.env,
            sheets_client=client,
            reference_date=self.reference_date,
        )
        self.assertIsNone(result['error'])
        self.assertFalse(self.Snapshot.search_count([
            ('partner_id', '=', self.vendor.id),
            ('company_id', '=', self.company.id),
        ]))

        po = self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'company_id': self.company.id,
        })
        empty_matrix = json.loads(po.vendor_sales_matrix)
        self.assertEqual(empty_matrix['total'], 0.0)

        po.action_sync_po_vendor_tab()
        matrix = json.loads(po.vendor_sales_matrix)
        self.assertGreater(matrix['total'], 0.0)
        self.assertEqual(
            matrix,
            get_sales_matrix_for_po(
                self.env,
                self.vendor.id,
                self.company.id,
                reference_date=self.reference_date,
            ),
        )
        last_log = self.env['vendor.sheet.sync.log'].search([
            ('sync_type', '=', 'po'),
            ('po_id', '=', po.id),
        ], limit=1)
        self.assertTrue(last_log)
        self.assertTrue(po.vendor_tab_po_last_sync)
