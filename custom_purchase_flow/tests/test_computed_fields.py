# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('custom_purchase_flow', 'post_install', '-at_install')
class TestComputedFields(TransactionCase):
    """Tests for receipt_status computed field and date_sent auto-fill."""

    def setUp(self):
        super().setUp()
        vendor = self.env['res.partner'].create({'name': 'Vendor CF'})
        self.product = self.env['product.product'].create({
            'name': 'Product CF',
            'type': 'product',
        })
        self.po = self.env['purchase.order'].create({
            'partner_id': vendor.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_qty': 2.0,
                'price_unit': 50.0,
                'name': self.product.name,
                'date_planned': '2026-04-01 00:00:00',
            })],
        })

    def _advance_to_purchase(self):
        """Helper: advance the PO to 'purchase' state so a receipt is created."""
        self.po.action_request_approval()
        self.po.button_approve()
        self.po.action_send_to_vendor()
        self.po.action_set_fulfilling()

    def test_receipt_status_assigned(self):
        """PO in 'purchase' state → receipt_status reflects the picking state."""
        self._advance_to_purchase()
        self.assertEqual(self.po.state, 'purchase')
        self.assertTrue(self.po.picking_ids, "A receipt should exist")
        # receipt_status should match the actual picking state (e.g. 'assigned' or 'confirmed')
        picking_state = self.po.picking_ids[0].state
        self.assertEqual(self.po.receipt_status, picking_state)

    def test_receipt_status_done(self):
        """After validating the receipt, receipt_status returns 'done'."""
        self._advance_to_purchase()
        picking = self.po.picking_ids[0]
        # Force availability and validate
        picking.action_assign()
        for move in picking.move_lines:
            move.quantity_done = move.product_uom_qty
        picking.button_validate()
        self.assertEqual(self.po.receipt_status, 'done')

    def test_date_sent_auto_filled(self):
        """Advancing PO to 'sent' via action_send_to_vendor fills date_sent."""
        self.po.action_request_approval()
        self.po.button_approve()
        self.assertFalse(self.po.date_sent, "date_sent should be False before sending")
        self.po.action_send_to_vendor()
        self.assertTrue(self.po.date_sent, "date_sent should be set after sending to vendor")

    def test_date_sent_not_set_in_other_states(self):
        """PO in draft or approved states → date_sent is False."""
        self.assertFalse(self.po.date_sent, "date_sent should be False in draft")
        self.po.action_request_approval()
        self.po.button_approve()
        self.assertFalse(self.po.date_sent, "date_sent should be False in approved state")
