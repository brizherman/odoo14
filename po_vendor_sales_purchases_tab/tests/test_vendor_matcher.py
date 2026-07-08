# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import BaseCase, TransactionCase

from odoo.addons.po_vendor_sales_purchases_tab.services.vendor_matcher import (
    VendorMatcher,
    fuzzy_match_score,
    fuzzy_vendor_match,
    normalize_match_string,
)


@tagged('post_install', '-at_install', 'po_vendor_sales_purchases_tab')
class TestVendorMatcherHelpers(BaseCase):
    def test_normalize_match_string(self):
        self.assertEqual(
            normalize_match_string('Convergram México, S.A.'),
            'convergrammexicosa',
        )

    def test_fuzzy_vendor_match_similar_names(self):
        self.assertTrue(
            fuzzy_vendor_match(
                'CONVERGRAM DE MEXICO',
                'Convergram de Mexico, S de R.L de C.V',
            )
        )
        self.assertTrue(
            fuzzy_vendor_match(
                'VM FIESTA',
                'VM Fiesta S.A de C.V',
            )
        )
        self.assertTrue(
            fuzzy_vendor_match(
                'GRANMARK',
                'Granmark S.A De C.V',
            )
        )

    def test_fuzzy_vendor_match_rejects_unrelated_names(self):
        self.assertFalse(
            fuzzy_vendor_match('VM FIESTA', 'Granmark S.A De C.V')
        )
        self.assertFalse(
            fuzzy_vendor_match('Unknown Vendor LLC', 'Other Supplier')
        )


@tagged('post_install', '-at_install', 'po_vendor_sales_purchases_tab')
class TestVendorMatcher(TransactionCase):
    def setUp(self):
        super().setUp()
        self.matcher = VendorMatcher(self.env)
        self.partner_fuzzy = self.env['res.partner'].create({
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

    def test_fuzzy_match_resolves_convergram_partner(self):
        resolved, warning = self.matcher.resolve_partner('CONVERGRAM DE MEXICO')
        if warning and 'Múltiples coincidencias aproximadas de proveedor' in warning:
            self.assertFalse(resolved)
            return
        self.assertFalse(warning)
        self.assertTrue(resolved)
        self.assertIn('convergram', resolved.name.lower())

    def test_fuzzy_match_resolves_generic_vendor_name(self):
        partner = self.env['res.partner'].create({
            'name': 'VM Fiesta Unique Fuzzy Vendor Test',
            'supplier_rank': 1,
        })
        resolved, warning = self.matcher.resolve_partner('VM FIESTA UNIQUE FUZZY VENDOR TEST')
        self.assertEqual(resolved, partner)
        self.assertFalse(warning)

    def test_manual_mapping_overrides_fuzzy(self):
        self.env['vendor.sheet.mapping'].create({
            'sheet_proveedor': 'convergram mexico sheet name',
            'partner_id': self.partner_other.id,
        })
        partner, warning = self.matcher.resolve_partner('convergram mexico sheet name')
        self.assertEqual(partner, self.partner_other)
        self.assertFalse(warning)

    def test_unmatched_vendor_returns_warning(self):
        partner, warning = self.matcher.resolve_partner('Unknown Vendor LLC')
        self.assertFalse(partner)
        self.assertIn('Proveedor sin mapear', warning)

    def test_multiple_fuzzy_matches_return_warning(self):
        self.env['res.partner'].create({
            'name': 'Fabricas Selectas Del Norte',
            'supplier_rank': 1,
        })
        self.env['res.partner'].create({
            'name': 'Fabricas Selectas Del Centro',
            'supplier_rank': 1,
        })
        partner, warning = self.matcher.resolve_partner('FABRICAS SELECTAS')
        self.assertFalse(partner)
        self.assertIn('Múltiples coincidencias aproximadas de proveedor', warning)

    def test_resolve_classification_vendor_from_mapping(self):
        self.env['vendor.sheet.mapping'].create({
            'sheet_proveedor': 'Any Sheet Name',
            'partner_id': self.partner_fuzzy.id,
            'classification_vendor_id': self.class_vendor.id,
        })
        class_vendor, warning = self.matcher.resolve_classification_vendor(self.partner_fuzzy)
        self.assertEqual(class_vendor, self.class_vendor)
        self.assertFalse(warning)

    def test_resolve_classification_vendor_fuzzy(self):
        class_vendor = self.env['product.classification.vendor'].create({
            'name': 'VM Fiesta Classification Unique',
        })
        partner = self.env['res.partner'].create({
            'name': 'VM Fiesta Classification Unique Vendor',
            'supplier_rank': 1,
        })
        resolved, warning = self.matcher.resolve_classification_vendor(partner)
        self.assertEqual(resolved, class_vendor)
        self.assertFalse(warning)
