# -*- coding: utf-8 -*-
import json
from datetime import date, datetime

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.po_vendor_sales_purchases_tab.services.sales_aggregator import (
    compute_sales_matrix,
    local_day_range_utc_naive,
)


@tagged('post_install', '-at_install', 'po_vendor_sales_purchases_tab')
class TestSalesAggregatorHelpers(TransactionCase):
    def test_local_day_range_utc_naive_tijuana(self):
        start_utc, end_utc = local_day_range_utc_naive(date(2026, 6, 1), date(2026, 6, 1))
        self.assertEqual(start_utc, datetime(2026, 6, 1, 7, 0, 0))
        self.assertEqual(end_utc.strftime('%Y-%m-%d'), '2026-06-02')


@tagged('post_install', '-at_install', 'po_vendor_sales_purchases_tab')
class TestSalesAggregator(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.Department = self.env['product.classification.department']
        self.ClassificationVendor = self.env['product.classification.vendor']
        self.ProductTemplate = self.env['product.template']
        self.SaleOrder = self.env['sale.order']

        self.dept_a = self.Department.create({'name': 'Dept A'})
        self.dept_b = self.Department.create({'name': 'Dept B'})
        self.class_vendor = self.ClassificationVendor.create({
            'name': 'Convergram Mexico Vendor',
        })
        self.vendor = self.env['res.partner'].create({
            'name': 'Convergram Mexico SA',
            'supplier_rank': 1,
        })
        self.env['vendor.sheet.mapping'].create({
            'sheet_proveedor': 'ignored',
            'partner_id': self.vendor.id,
            'classification_vendor_id': self.class_vendor.id,
        })
        self.other_class_vendor = self.ClassificationVendor.create({
            'name': 'Other Vendor Class',
        })
        self.product_a = self.ProductTemplate.create({
            'name': 'Product A',
            'type': 'product',
            'list_price': 100.0,
            'classification_vendor': self.class_vendor.id,
            'classification_department': self.dept_a.id,
        }).product_variant_id
        self.product_b = self.ProductTemplate.create({
            'name': 'Product B',
            'type': 'product',
            'list_price': 50.0,
            'classification_vendor': self.class_vendor.id,
            'classification_department': self.dept_b.id,
        }).product_variant_id
        self.other_product = self.ProductTemplate.create({
            'name': 'Other Vendor Product',
            'type': 'product',
            'list_price': 75.0,
            'classification_vendor': self.other_class_vendor.id,
            'classification_department': self.dept_a.id,
        }).product_variant_id
        self.reference_date = date(2026, 7, 15)

    def _create_sale(self, product, amount, order_datetime):
        team = self.env['crm.team'].search([
            ('company_id', 'in', [False, self.company.id]),
        ], limit=1)
        order = self.SaleOrder.with_company(self.company).create({
            'partner_id': self.env['res.partner'].create({'name': 'Customer'}).id,
            'company_id': self.company.id,
            'team_id': team.id if team else False,
            'date_order': order_datetime,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 1.0,
                'price_unit': amount,
            })],
        })
        order.action_confirm()
        order.write({'date_order': order_datetime})
        return order

    def _line_total(self, order):
        return sum(order.order_line.mapped('price_total'))

    def test_vendor_classification_filter_excludes_other_vendors(self):
        sale_a = self._create_sale(self.product_a, 100.0, '2026-07-10 12:00:00')
        self._create_sale(self.other_product, 75.0, '2026-07-10 12:00:00')
        expected_total = self._line_total(sale_a)

        matrix = compute_sales_matrix(
            self.env,
            self.vendor.id,
            self.company.id,
            reference_date=self.reference_date,
        )
        self.assertAlmostEqual(matrix['total'], expected_total)
        self.assertAlmostEqual(matrix['cells'][str(self.dept_a.id)]['TOTAL'], expected_total)

    def test_month_boundary_assigns_sale_to_correct_local_month(self):
        # June 30 22:00 Tijuana == July 1 05:00 UTC (naive stored in Odoo).
        sale_june = self._create_sale(self.product_a, 100.0, '2026-07-01 05:00:00')
        # July 1 00:30 Tijuana == July 1 07:30 UTC.
        sale_july = self._create_sale(self.product_a, 200.0, '2026-07-01 07:30:00')
        june_total = self._line_total(sale_june)
        july_total = self._line_total(sale_july)

        matrix = compute_sales_matrix(
            self.env,
            self.vendor.id,
            self.company.id,
            reference_date=self.reference_date,
        )
        self.assertAlmostEqual(
            matrix['cells'][str(self.dept_a.id)]['2026-06'],
            june_total,
        )
        self.assertAlmostEqual(
            matrix['cells'][str(self.dept_a.id)]['2026-07'],
            july_total,
        )
        self.assertAlmostEqual(matrix['total'], june_total + july_total)

    def test_empty_department_shows_zero_with_warning(self):
        sale = self._create_sale(self.product_a, 120.0, '2026-07-10 12:00:00')
        expected_total = self._line_total(sale)

        matrix = compute_sales_matrix(
            self.env,
            self.vendor.id,
            self.company.id,
            reference_date=self.reference_date,
        )
        self.assertAlmostEqual(matrix['cells'][str(self.dept_b.id)]['TOTAL'], 0.0)
        self.assertAlmostEqual(matrix['total'], expected_total)
        self.assertTrue(matrix['has_warning'])
        self.assertIn('Some departments have no sales', matrix['warning'])

    def test_purchase_order_compute_populates_matrix(self):
        sale = self._create_sale(self.product_a, 80.0, '2026-07-05 12:00:00')
        expected_total = self._line_total(sale)
        po = self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'company_id': self.company.id,
        })
        matrix = json.loads(po.vendor_sales_matrix)
        self.assertAlmostEqual(matrix['total'], expected_total)
        self.assertIn(str(self.dept_a.id), matrix['cells'])

    def test_missing_classification_vendor_returns_warning(self):
        unknown_vendor = self.env['res.partner'].create({
            'name': 'Unknown Supplier',
            'supplier_rank': 1,
        })
        matrix = compute_sales_matrix(
            self.env,
            unknown_vendor.id,
            self.company.id,
            reference_date=self.reference_date,
        )
        self.assertTrue(matrix['has_warning'])
        self.assertIn('classification vendor', matrix['warning'].lower())
