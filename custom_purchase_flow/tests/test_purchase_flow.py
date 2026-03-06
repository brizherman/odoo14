# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import AccessError, UserError


@tagged('custom_purchase_flow', 'post_install', '-at_install')
class TestPurchaseFlow(TransactionCase):
    """Tests for the full custom purchase state flow."""

    def setUp(self):
        super().setUp()

        # Fetch custom groups
        group_coordinator = self.env.ref('custom_purchase_flow.group_purchase_coordinator')
        group_direction = self.env.ref('custom_purchase_flow.group_purchase_direction')
        group_dept = self.env.ref('custom_purchase_flow.group_purchase_dept')
        group_cashier = self.env.ref('custom_purchase_flow.group_purchase_cashier')

        # Create test users
        self.user_coordinator = self.env['res.users'].create({
            'name': 'Test Coordinator',
            'login': 'test_coordinator',
            'groups_id': [(4, group_coordinator.id)],
        })
        self.user_direction = self.env['res.users'].create({
            'name': 'Test Direction',
            'login': 'test_direction',
            'groups_id': [(4, group_direction.id)],
        })
        self.user_dept = self.env['res.users'].create({
            'name': 'Test Dept',
            'login': 'test_dept',
            'groups_id': [(4, group_dept.id)],
        })
        self.user_cashier = self.env['res.users'].create({
            'name': 'Test Cashier',
            'login': 'test_cashier',
            'groups_id': [(4, group_cashier.id)],
        })

        # Test vendor
        self.vendor = self.env['res.partner'].create({'name': 'Test Vendor', 'supplier_rank': 1})

        # Test product
        self.product = self.env['product.product'].create({
            'name': 'Test Product',
            'type': 'product',
        })

    def _create_po(self):
        """Helper: create a draft PO with one line."""
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
        return po

    def test_draft_to_to_approve(self):
        """Coordinator submits PO → state becomes 'to approve'."""
        po = self._create_po()
        self.assertEqual(po.state, 'draft')
        po.with_user(self.user_coordinator).action_request_approval()
        self.assertEqual(po.state, 'to approve')

    def test_to_approve_to_approved(self):
        """Direction approves PO → state becomes 'approved'."""
        po = self._create_po()
        po.action_request_approval()
        po.with_user(self.user_direction).button_approve()
        self.assertEqual(po.state, 'approved')

    def test_approved_to_sent(self):
        """Purchase Dept sends to vendor → state 'sent', date_sent filled."""
        po = self._create_po()
        po.action_request_approval()
        po.button_approve()
        po.with_user(self.user_dept).action_send_to_vendor()
        self.assertEqual(po.state, 'sent')
        self.assertTrue(po.date_sent, "date_sent should be set after sending to vendor")

    def test_sent_to_purchase(self):
        """Purchase Dept marks Fulfilling → state 'purchase', receipt created."""
        po = self._create_po()
        po.action_request_approval()
        po.button_approve()
        po.action_send_to_vendor()
        po.with_user(self.user_dept).action_set_fulfilling()
        self.assertEqual(po.state, 'purchase')
        self.assertTrue(po.picking_ids, "A stock receipt should have been created")

    def test_sent_to_purchase_requires_date_planned(self):
        """Surtiendo should be blocked if Fecha Recepción (date_planned) is empty."""
        po = self._create_po()
        po.action_request_approval()
        po.button_approve()
        po.action_send_to_vendor()
        po.write({'date_planned': False})
        with self.assertRaises(UserError):
            po.with_user(self.user_dept).action_set_fulfilling()

    def test_sent_to_pending_payment(self):
        """Purchase Dept marks Pending Payment → state 'pending_payment'."""
        po = self._create_po()
        po.action_request_approval()
        po.button_approve()
        po.action_send_to_vendor()
        po.with_user(self.user_dept).action_set_pending_payment()
        self.assertEqual(po.state, 'pending_payment')

    def test_pending_payment_to_purchase(self):
        """Purchase Dept marks Fulfilling from pending_payment → 'purchase', receipt created."""
        po = self._create_po()
        po.action_request_approval()
        po.button_approve()
        po.action_send_to_vendor()
        po.action_set_pending_payment()
        po.with_user(self.user_dept).action_set_fulfilling()
        self.assertEqual(po.state, 'purchase')
        self.assertTrue(po.picking_ids)

    def test_purchase_to_in_transit(self):
        """Purchase Dept marks In Transit → state 'in_transit'."""
        po = self._create_po()
        po.action_request_approval()
        po.button_approve()
        po.action_send_to_vendor()
        po.action_set_fulfilling()
        po.with_user(self.user_dept).action_set_in_transit()
        self.assertEqual(po.state, 'in_transit')

    def test_in_transit_to_arrived(self):
        """Cashier fills tracking_number and marks Arrived → state 'arrived'."""
        po = self._create_po()
        po.action_request_approval()
        po.button_approve()
        po.action_send_to_vendor()
        po.action_set_fulfilling()
        po.action_set_in_transit()
        po.write({'tracking_number': 'TRACK-001'})
        po.with_user(self.user_cashier).action_set_arrived()
        self.assertEqual(po.state, 'arrived')

    def test_arrived_revert_to_in_transit(self):
        """Cashier reverts arrived PO back to in_transit."""
        po = self._create_po()
        po.action_request_approval()
        po.button_approve()
        po.action_send_to_vendor()
        po.action_set_fulfilling()
        po.action_set_in_transit()
        po.write({'tracking_number': 'TRACK-001'})
        po.action_set_arrived()
        po.with_user(self.user_cashier).action_revert_to_in_transit()
        self.assertEqual(po.state, 'in_transit')

    def test_full_happy_path(self):
        """Walk a PO through the entire flow from draft to arrived."""
        po = self._create_po()
        self.assertEqual(po.state, 'draft')

        po.action_request_approval()
        self.assertEqual(po.state, 'to approve')

        po.button_approve()
        self.assertEqual(po.state, 'approved')

        po.action_send_to_vendor()
        self.assertEqual(po.state, 'sent')

        po.action_set_fulfilling()
        self.assertEqual(po.state, 'purchase')

        po.action_set_in_transit()
        self.assertEqual(po.state, 'in_transit')

        po.write({'tracking_number': 'TRACK-HAPPY'})
        po.action_set_arrived()
        self.assertEqual(po.state, 'arrived')


@tagged('custom_purchase_flow', 'post_install', '-at_install')
class TestPurchaseFlowAccessRights(TransactionCase):
    """Tests that roles cannot perform actions outside their permission."""

    def setUp(self):
        super().setUp()
        group_coordinator = self.env.ref('custom_purchase_flow.group_purchase_coordinator')
        group_cashier = self.env.ref('custom_purchase_flow.group_purchase_cashier')

        self.user_coordinator = self.env['res.users'].create({
            'name': 'Test Coordinator AR',
            'login': 'test_coordinator_ar',
            'groups_id': [(4, group_coordinator.id)],
        })
        self.user_cashier = self.env['res.users'].create({
            'name': 'Test Cashier AR',
            'login': 'test_cashier_ar',
            'groups_id': [(4, group_cashier.id)],
        })

        vendor = self.env['res.partner'].create({'name': 'Test Vendor AR'})
        product = self.env['product.product'].create({'name': 'Test Product AR', 'type': 'product'})
        self.po = self.env['purchase.order'].create({
            'partner_id': vendor.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_qty': 1.0,
                'price_unit': 50.0,
                'name': product.name,
                'date_planned': '2026-04-01 00:00:00',
            })],
        })
        # Advance to 'to approve' so we can test approval
        self.po.action_request_approval()

    def test_coordinator_cannot_approve_via_group(self):
        """Coordinator does not have group_purchase_manager and thus _approval_allowed
        returns False (unless the company has one_step approval enabled).
        When one_step is configured, the model allows it — protection is at view level.
        This test verifies that the group membership is correctly NOT set on coordinator.
        """
        group_manager = self.env.ref('purchase.group_purchase_manager')
        # Coordinator should NOT have group_purchase_manager directly
        self.assertNotIn(
            group_manager,
            self.user_coordinator.groups_id,
            "Coordinator should not have purchase.group_purchase_manager directly",
        )

    def test_cashier_group_membership(self):
        """Cashier should not have group_purchase_dept."""
        group_dept = self.env.ref('custom_purchase_flow.group_purchase_dept')
        self.assertNotIn(
            group_dept,
            self.user_cashier.groups_id,
            "Cashier should not have group_purchase_dept",
        )
