# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('custom_purchase_flow', 'post_install', '-at_install')
class TestRfqStatusDashboard(TransactionCase):
    """Tests for the RFQ status dashboard counts helper."""

    def setUp(self):
        super().setUp()
        vendor = self.env['res.partner'].create({
            'name': 'RFQ Dashboard Vendor',
            'supplier_rank': 1,
        })
        product = self.env['product.product'].create({
            'name': 'RFQ Dashboard Product',
            'type': 'product',
        })
        self.vendor = vendor
        self.product = product

    def _create_po(self, state='draft'):
        """Create a purchase order and move it to the given state using
        the custom flow where needed so counts reflect realistic usage."""
        po = self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_qty': 1.0,
                'price_unit': 100.0,
                'name': self.product.name,
                'date_planned': '2026-04-01 00:00:00',
            })],
        })
        if state == 'draft':
            return po

        # Walk through the custom flow to reach the requested state.
        if state in ('to approve', 'approved', 'sent', 'pending_payment', 'purchase', 'in_transit', 'arrived'):
            po.action_request_approval()
        if state in ('approved', 'sent', 'pending_payment', 'purchase', 'in_transit', 'arrived'):
            po.button_approve()
        if state in ('sent', 'pending_payment', 'purchase', 'in_transit', 'arrived'):
            po.action_send_to_vendor()
        if state in ('pending_payment',):
            po.action_set_pending_payment()
        if state in ('purchase', 'in_transit', 'arrived'):
            if po.state in ('sent', 'pending_payment'):
                po.action_set_fulfilling()
        if state in ('in_transit', 'arrived'):
            po.action_set_in_transit()
        if state == 'arrived':
            po.write({'tracking_number': 'RFQ-DASH-TRACK'})
            po.action_set_arrived()
        return po

    def test_get_rfq_dashboard_counts_per_state(self):
        """Helper should return one entry per custom state with correct counts."""
        target_states = [
            'draft',
            'to approve',
            'approved',
            'sent',
            'pending_payment',
            'purchase',
            'in_transit',
            'arrived',
        ]

        # Ensure a clean baseline (no assumptions about existing data).
        # We only assert relative counts produced by creating new POs here.
        before_counts = self.env['purchase.order'].get_rfq_dashboard_counts()

        # Create one PO in each target state.
        for state in target_states:
            self._create_po(state=state)

        after_counts = self.env['purchase.order'].get_rfq_dashboard_counts()

        # Each state count should have increased by exactly 1.
        for state in target_states:
            self.assertIn(state, after_counts, "State %r must be present in dashboard counts" % state)
            self.assertEqual(
                after_counts[state],
                before_counts.get(state, 0) + 1,
                "Dashboard count for state %r should increase by 1" % state,
            )

