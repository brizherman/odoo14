# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.po_vendor_sales_purchases_tab.services.vendor_matcher import VendorMatcher


@tagged('post_install', '-at_install', 'po_vendor_sales_purchases_tab')
class TestVendorMatcher(TransactionCase):
    def setUp(self):
        super().setUp()
        self.matcher = VendorMatcher(self.env)
        self.partner_mapped = self.env['res.partner'].create({
            'name': 'Convergram Mexico SA de CV',
            'supplier_rank': 1,
        })
        self.partner_other = self.env['res.partner'].create({
            'name': 'Other Supplier',
            'supplier_rank': 1,
        })
        self.class_vendor = self.env['product.classification.vendor'].create({
            'name': 'Convergram Mexico Class',
        })

    def test_complete_mapping_resolves_partner(self):
        sheet_name = 'Unique Mapped Vendor Test 20260708'
        self.env['vendor.sheet.mapping'].create({
            'sheet_proveedor': sheet_name,
            'partner_id': self.partner_mapped.id,
        })
        partner, warning = self.matcher.resolve_partner(sheet_name)
        self.assertEqual(partner, self.partner_mapped)
        self.assertFalse(warning)

    def test_stub_mapping_returns_pending_assignment_warning(self):
        sheet_name = 'Stub Pending Vendor Test 20260708'
        self.env['vendor.sheet.mapping'].create({
            'sheet_proveedor': sheet_name,
        })
        partner, warning = self.matcher.resolve_partner(sheet_name)
        self.assertFalse(partner)
        self.assertIn('pendiente de asignación', warning)

    def test_unmatched_vendor_returns_warning(self):
        partner, warning = self.matcher.resolve_partner('Unknown Vendor LLC')
        self.assertFalse(partner)
        self.assertIn('Proveedor sin mapear', warning)

    def test_similar_supplier_never_auto_resolves_without_mapping(self):
        self.env['res.partner'].create({
            'name': 'VM Fiesta Unique No Mapping Test',
            'supplier_rank': 1,
        })
        partner, warning = self.matcher.resolve_partner('VM FIESTA UNIQUE NO MAPPING TEST')
        self.assertFalse(partner)
        self.assertIn('Proveedor sin mapear', warning)

    def test_resolve_classification_vendor_from_mapping(self):
        self.env['vendor.sheet.mapping'].create({
            'sheet_proveedor': 'Any Sheet Name',
            'partner_id': self.partner_mapped.id,
            'classification_vendor_id': self.class_vendor.id,
        })
        class_vendor, warning = self.matcher.resolve_classification_vendor(self.partner_mapped)
        self.assertEqual(class_vendor, self.class_vendor)
        self.assertFalse(warning)

    def test_resolve_classification_vendor_without_mapping_returns_warning(self):
        partner = self.env['res.partner'].create({
            'name': 'Unmapped Classification Vendor',
            'supplier_rank': 1,
        })
        self.env['product.classification.vendor'].create({
            'name': 'Similar Classification Name',
        })
        class_vendor, warning = self.matcher.resolve_classification_vendor(partner)
        self.assertFalse(class_vendor)
        self.assertIn('No hay coincidencia de proveedor de clasificación', warning)
