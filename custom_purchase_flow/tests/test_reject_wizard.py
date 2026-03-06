# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import ValidationError


@tagged('custom_purchase_flow', 'post_install', '-at_install')
class TestRejectWizard(TransactionCase):
    """Tests for the purchase order rejection wizard."""

    def setUp(self):
        super().setUp()
        group_direction = self.env.ref('custom_purchase_flow.group_purchase_direction')
        group_coordinator = self.env.ref('custom_purchase_flow.group_purchase_coordinator')

        self.user_direction = self.env['res.users'].create({
            'name': 'Test Direction RW',
            'login': 'test_direction_rw',
            'groups_id': [(4, group_direction.id)],
        })
        self.user_coordinator = self.env['res.users'].create({
            'name': 'Test Coordinator RW',
            'login': 'test_coordinator_rw',
            'groups_id': [(4, group_coordinator.id)],
        })

        vendor = self.env['res.partner'].create({'name': 'Vendor RW'})
        product = self.env['product.product'].create({'name': 'Product RW', 'type': 'product'})
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
        # Advance to 'to approve'
        self.po.action_request_approval()

    def _create_wizard(self, reason='Test rejection reason'):
        return self.env['purchase.order.reject.wizard'].create({
            'purchase_order_id': self.po.id,
            'rejection_reason': reason,
        })

    def test_reject_to_draft(self):
        """Wizard rejects PO → returns to draft, rejection_reason set, chatter posted."""
        wizard = self._create_wizard('Bad price')
        wizard.with_user(self.user_direction).action_reject_to_draft()
        self.assertEqual(self.po.state, 'draft')
        self.assertEqual(self.po.rejection_reason, 'Bad price')
        # Check chatter message was posted (body is HTML)
        messages = self.po.message_ids.filtered(lambda m: 'Returned to Draft' in (m.body or ''))
        self.assertTrue(messages, "Chatter message not found after rejection to draft")


    def test_reject_to_cancel(self):
        """Wizard cancels PO → state cancel, rejection_reason set, chatter posted."""
        wizard = self._create_wizard('Out of budget')
        wizard.with_user(self.user_direction).action_reject_to_cancel()
        self.assertEqual(self.po.state, 'cancel')
        self.assertEqual(self.po.rejection_reason, 'Out of budget')
        messages = self.po.message_ids.filtered(lambda m: 'Cancelled' in (m.body or ''))
        self.assertTrue(messages, "Chatter message not found after rejection to cancel")


    def test_reject_reason_required(self):
        """Wizard should raise ValidationError if rejection_reason is blank."""
        with self.assertRaises(ValidationError):
            self.env['purchase.order.reject.wizard'].create({
                'purchase_order_id': self.po.id,
                'rejection_reason': '   ',
            })

    def test_reject_reason_visible_on_po(self):
        """After rejection, rejection_reason on PO matches wizard input."""
        wizard = self._create_wizard('Price too high')
        wizard.action_reject_to_draft()
        self.assertEqual(self.po.rejection_reason, 'Price too high')
