# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import UserError


@tagged('custom_purchase_flow', 'post_install', '-at_install')
class TestTrackingValidation(TransactionCase):
    """Tests for tracking number / no-tracking-reason validation on arrival."""

    def setUp(self):
        super().setUp()
        group_cashier = self.env.ref('custom_purchase_flow.group_purchase_cashier')
        self.user_cashier = self.env['res.users'].create({
            'name': 'Test Cashier TV',
            'login': 'test_cashier_tv',
            'groups_id': [(4, group_cashier.id)],
        })

        vendor = self.env['res.partner'].create({'name': 'Vendor TV'})
        product = self.env['product.product'].create({'name': 'Product TV', 'type': 'product'})
        self.po = self.env['purchase.order'].create({
            'partner_id': vendor.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_qty': 1.0,
                'price_unit': 100.0,
                'name': product.name,
                'date_planned': '2026-04-01 00:00:00',
            })],
        })
        # Advance to 'in_transit'
        self.po.action_request_approval()
        self.po.button_approve()
        self.po.action_send_to_vendor()
        self.po.action_set_fulfilling()
        self.po.action_set_in_transit()

    def test_arrived_blocked_without_tracking(self):
        """Both tracking fields empty → action_set_arrived raises UserError."""
        self.po.write({'tracking_number': False, 'no_tracking_reason': False})
        with self.assertRaises(UserError):
            self.po.with_user(self.user_cashier).action_set_arrived()

    def test_arrived_with_tracking_number(self):
        """tracking_number filled → action_set_arrived succeeds."""
        self.po.write({'tracking_number': 'TRK-001', 'no_tracking_reason': False})
        self.po.with_user(self.user_cashier).action_set_arrived()
        self.assertEqual(self.po.state, 'arrived')

    def test_arrived_with_no_tracking_reason(self):
        """no_tracking_reason filled → action_set_arrived succeeds."""
        self.po.write({'tracking_number': False, 'no_tracking_reason': 'Pickup in person'})
        self.po.with_user(self.user_cashier).action_set_arrived()
        self.assertEqual(self.po.state, 'arrived')

    def test_arrived_with_both_fields(self):
        """Both fields filled → action_set_arrived succeeds."""
        self.po.write({'tracking_number': 'TRK-002', 'no_tracking_reason': 'Extra info'})
        self.po.with_user(self.user_cashier).action_set_arrived()
        self.assertEqual(self.po.state, 'arrived')
