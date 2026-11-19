# -*- coding: utf-8 -*-
# pylint: disable=import-error,missing-function-docstring
"""Tests for res.partner customer_type field and POS create_from_ui."""
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('alta_mayoristas', 'post_install', '-at_install')
class TestCustomerType(TransactionCase):
    """Backend tests for customer type on res.partner."""

    def test_create_partner_without_customer_type(self):
        partner = self.env['res.partner'].create({'name': 'Legacy Customer'})
        self.assertFalse(partner.customer_type)

    def test_create_partner_mayorista(self):
        partner = self.env['res.partner'].create({
            'name': 'Wholesale Customer',
            'customer_type': 'mayorista',
        })
        self.assertEqual(partner.customer_type, 'mayorista')

    def test_create_partner_publico_general(self):
        partner = self.env['res.partner'].create({
            'name': 'Retail Customer',
            'customer_type': 'publico_general',
        })
        self.assertEqual(partner.customer_type, 'publico_general')

    def test_create_partner_distribuidores(self):
        partner = self.env['res.partner'].create({
            'name': 'Distributor Customer',
            'customer_type': 'distribuidores',
        })
        self.assertEqual(partner.customer_type, 'distribuidores')

    def test_create_partner_mayorista_dormido(self):
        partner = self.env['res.partner'].create({
            'name': 'Dormant Wholesale Customer',
            'customer_type': 'mayorista_dormido',
        })
        self.assertEqual(partner.customer_type, 'mayorista_dormido')

    def test_write_existing_partner_without_customer_type(self):
        partner = self.env['res.partner'].create({'name': 'Existing Customer'})
        partner.write({'phone': '5551234567'})
        self.assertFalse(partner.customer_type)

    def test_create_from_ui_with_customer_type(self):
        partner_id = self.env['res.partner'].create_from_ui({
            'name': 'POS Customer',
            'mobile': '5550000004',
            'customer_type': 'mayorista',
        })
        partner = self.env['res.partner'].browse(partner_id)
        self.assertEqual(partner.name, 'POS Customer')
        self.assertEqual(partner.customer_type, 'mayorista')

    def test_create_from_ui_preserves_existing_mobile_when_omitted(self):
        partners = self.env['res.partner']
        partner = partners.create({
            'name': 'Existing POS Customer',
            'mobile': '5550000006',
        })

        partner_id = partners.create_from_ui({
            'id': partner.id,
            'name': 'Renamed POS Customer',
        })

        self.assertEqual(partner_id, partner.id)
        self.assertEqual(partner.name, 'Renamed POS Customer')
        self.assertEqual(partner.mobile, '5550000006')

    def test_create_from_ui_updates_mobile_without_trailing_space(self):
        partners = self.env['res.partner']
        partner = partners.create({
            'name': 'Existing POS Customer',
            'mobile': '5550000006',
        })

        partners.create_from_ui({'id': partner.id, 'mobile': '5550000007'})

        self.assertEqual(partner.mobile, '5550000007')

    def test_create_from_ui_rejects_explicitly_blank_mobile_on_edit(self):
        partners = self.env['res.partner']
        partner = partners.create({
            'name': 'Existing POS Customer',
            'mobile': '5550000006',
        })

        for mobile in (False, '', '   '):
            with self.subTest(mobile=mobile), self.assertRaisesRegex(
                UserError, r'Movil \(Whatsapp\) es obligatorio',
            ):
                partners.create_from_ui({'id': partner.id, 'mobile': mobile})

        self.assertEqual(partner.mobile, '5550000006')

    def test_create_from_ui_rejects_missing_mobile(self):
        partners = self.env['res.partner']
        legacy = partners.create({'name': 'Legacy POS Customer'})

        for values in (
            {'name': 'New POS Customer'},
            {'id': legacy.id, 'name': 'Changed'},
        ):
            with self.subTest(values=values), self.assertRaisesRegex(
                UserError, r'Movil \(Whatsapp\) es obligatorio',
            ):
                partners.create_from_ui(values)

        self.assertEqual(legacy.name, 'Legacy POS Customer')

    def test_create_from_ui_sets_customer_rank(self):
        partner_id = self.env['res.partner'].create_from_ui({
            'name': 'POS Rank Customer',
            'mobile': '5550000005',
        })
        partner = self.env['res.partner'].browse(partner_id)
        self.assertEqual(partner.customer_rank, 1)

    # POS tour (mutual exclusivity + Save validation) deferred to manual QA — task 6.4.
