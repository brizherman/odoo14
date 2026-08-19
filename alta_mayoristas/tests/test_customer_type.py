# -*- coding: utf-8 -*-
# pylint: disable=import-error,missing-function-docstring
"""Tests for res.partner customer_type field and POS create_from_ui."""
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

    def test_write_existing_partner_without_customer_type(self):
        partner = self.env['res.partner'].create({'name': 'Existing Customer'})
        partner.write({'phone': '5551234567'})
        self.assertFalse(partner.customer_type)

    def test_create_from_ui_with_customer_type(self):
        partner_id = self.env['res.partner'].create_from_ui({
            'name': 'POS Customer',
            'customer_type': 'mayorista',
        })
        partner = self.env['res.partner'].browse(partner_id)
        self.assertEqual(partner.name, 'POS Customer')
        self.assertEqual(partner.customer_type, 'mayorista')

    def test_create_from_ui_sets_customer_rank(self):
        partner_id = self.env['res.partner'].create_from_ui({
            'name': 'POS Rank Customer',
        })
        partner = self.env['res.partner'].browse(partner_id)
        self.assertEqual(partner.customer_rank, 1)

    # POS tour (mutual exclusivity + Save validation) deferred to manual QA — task 6.4.
