# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import BaseCase, TransactionCase

from odoo.addons.po_vendor_sales_purchases_tab.services.vendor_matcher import (
    VendorMatcher,
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

    def test_fuzzy_vendor_match_requires_tokens(self):
        self.assertTrue(
            fuzzy_vendor_match(
                'CONVERGRAM MEXICO SA',
                'Convergram Mexico Vendor',
            )
        )
        self.assertFalse(
            fuzzy_vendor_match('Convergram SA', 'Convergram Mexico Vendor')
        )
        self.assertFalse(
            fuzzy_vendor_match('Mexico Supplies', 'Convergram Mexico Vendor')
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

    def test_fuzzy_match_resolves_partner_when_unique(self):
        sheet_name = 'Convergram Mexico Unique Fuzzy Test'
        candidates = self.env['res.partner'].search([
            '|', ('name', 'ilike', 'convergram'), ('name', 'ilike', 'mexico'),
        ])
        existing_matches = candidates.filtered(
            lambda partner: fuzzy_vendor_match(sheet_name, partner.name)
        )
        if existing_matches:
            self.skipTest('Database already has convergram/mexico fuzzy matches.')

        partner = self.env['res.partner'].create({
            'name': 'Convergram Mexico Unique Fuzzy Test Partner',
            'supplier_rank': 1,
        })
        resolved, warning = self.matcher.resolve_partner(sheet_name)
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
        self.assertIn('Unmapped proveedor', warning)

    def test_resolve_classification_vendor_from_mapping(self):
        self.env['vendor.sheet.mapping'].create({
            'sheet_proveedor': 'Any Sheet Name',
            'partner_id': self.partner_fuzzy.id,
            'classification_vendor_id': self.class_vendor.id,
        })
        class_vendor, warning = self.matcher.resolve_classification_vendor(self.partner_fuzzy)
        self.assertEqual(class_vendor, self.class_vendor)
        self.assertFalse(warning)
