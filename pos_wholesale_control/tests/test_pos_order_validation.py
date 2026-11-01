# -*- coding: utf-8 -*-
# pylint: disable=import-error,missing-function-docstring,protected-access
"""Payment rejection, manager overrides, history failure, and acceptance scenarios."""
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools.float_utils import float_compare

from .common import WholesaleControlCommon


@tagged('pos_wholesale_control', 'post_install', '-at_install')
class TestWholesaleOrderValidation(WholesaleControlCommon):
    """Server checks for tasks 7.10 through 7.15.

    The cashier screen blocks a manual list in the browser tests. These tests
    prove a modified client still cannot store a wholesale decision on its own.
    """

    def _same(self, left, right):
        rounding = self.company.currency_id.rounding
        return float_compare(left, right, precision_rounding=rounding) == 0

    def _ticket(self):
        count = getattr(self, '_ticket_seq', 0) + 1
        self._ticket_seq = count  # pylint: disable=attribute-defined-outside-init
        return f'wholesale-{self._testMethodName}-{count}'

    def _previous_month_noon(self):
        month = self.company._wholesale_calendar_months()[1]
        return self.to_utc(month['year'], month['month'], 15)

    def _line_amount(self, qty, price_unit, discount):
        net = price_unit * qty * (1.0 - (discount or 0.0) / 100.0)
        return self.company.currency_id.round(net)

    def _line(self, qty, price_unit=100.0, discount=0.0):
        """One POS line. The server prices it again from the retail list."""
        amount = self._line_amount(qty, price_unit, discount)
        return [0, 0, {
            'discount': discount,
            'pack_lot_ids': [],
            'price_unit': price_unit,
            'product_id': self.product.id,
            'price_subtotal': amount,
            'price_subtotal_incl': amount,
            'qty': qty,
            'tax_ids': [(6, 0, [])],
        }]

    def _ui_order(self, partner, pricelist, ticket, qty=1.0, price_unit=100.0,  # pylint: disable=too-many-arguments
                  discount=0.0, extra=None):
        amount = self._line_amount(qty, price_unit, discount)
        stamp = fields.Datetime.to_string(fields.Datetime.now())
        payment_method = self.config.payment_method_ids[:1]
        data = {
            'amount_paid': amount,
            'amount_return': 0,
            'amount_tax': 0,
            'amount_total': amount,
            'creation_date': stamp,
            'fiscal_position_id': False,
            'pricelist_id': pricelist.id,
            'lines': [self._line(qty, price_unit, discount)],
            'name': ticket,
            'partner_id': partner.id if partner else False,
            'pos_session_id': self.session.id,
            'sequence_number': self._ticket_seq,
            'statement_ids': [[0, 0, {
                'amount': amount,
                'name': stamp,
                'payment_method_id': payment_method.id,
            }]],
            'uid': ticket,
            'user_id': self.cashier_user.id,
            'employee_id': self.cashier_employee.id,
            'to_invoice': False,
        }
        if extra:
            data.update(extra)
        return {'data': data, 'id': ticket, 'to_invoice': False}

    def _draft_order(self, partner, ticket, qty=1.0, price_unit=100.0, discount=0.0):  # pylint: disable=too-many-arguments
        paid = self._ui_order(partner, self.retail_pricelist, ticket, qty, price_unit, discount)
        return paid['data']

    def _pay(self, partner, pricelist, qty=1.0, price_unit=100.0, discount=0.0,  # pylint: disable=too-many-arguments
             extra=None, ticket=None):
        ticket = ticket or self._ticket()
        payload = self._ui_order(
            partner, pricelist, ticket, qty, price_unit, discount, extra,
        )
        result = self.pos_env()['pos.order'].create_from_ui([payload])
        self.assertEqual(len(result), 1)
        order = self.env['pos.order'].browse(result[0]['id'])
        self.assertEqual(order.state, 'paid')
        return order

    def _reject(self, partner, pricelist, qty=1.0, price_unit=100.0, discount=0.0,  # pylint: disable=too-many-arguments
                extra=None, ticket=None):
        with self.assertRaises(UserError) as caught:
            self._pay(partner, pricelist, qty, price_unit, discount, extra, ticket)
        return str(caught.exception)

    def _eligibility(self, partner, amount):
        result = self.pos_env()['res.partner'].get_wholesale_eligibility(
            partner.id if partner else False,
            self.company.id,
            amount,
            self.config.id,
        )
        return result

    def _authorize(self, partner, ticket, decision='wholesale', reason='Cliente de mostrador',  # pylint: disable=too-many-arguments
                   pin='2580', manager=None, qty=1.0):
        manager = manager if manager is not None else self.manager_employee
        return self.pos_env()['pos.wholesale.override'].authorize_from_pos(
            manager.id,
            pin,
            reason,
            decision,
            self._draft_order(partner, ticket, qty=qty),
        )

    def _assert_decision(self, order, decision, reason, pricelist, retail_amount=None):  # pylint: disable=too-many-arguments
        self.assertEqual(order.wholesale_final_decision, decision)
        self.assertEqual(order.wholesale_automatic_decision, decision)
        self.assertEqual(order.wholesale_reason_code, reason)
        self.assertTrue(order.wholesale_reason_text)
        self.assertEqual(order.wholesale_applied_pricelist_id, pricelist)
        self.assertEqual(order.pricelist_id, pricelist)
        self.assertFalse(order.wholesale_has_override)
        self.assertEqual(order.wholesale_timezone, 'America/Tijuana')
        if retail_amount is not None:
            self.assertTrue(self._same(order.wholesale_retail_amount, retail_amount))

    def _customer_snapshot(self, partner):
        return (
            partner.customer_type,
            partner.with_company(self.company).property_product_pricelist,
        )

    def test_tampered_pricelist_is_rejected(self):
        """A cashier cannot store Club Mayorista by editing the ticket payload."""
        partner = self.partner_mayorista
        message = self._reject(partner, self.club_pricelist, qty=1.0)
        self.assertIn(self.retail_pricelist.display_name, message)
        fake_decision = {
            'wholesale_final_decision': 'wholesale',
            'wholesale_automatic_decision': 'wholesale',
            'wholesale_reason_code': 'previous_month',
            'wholesale_applied_pricelist_id': self.club_pricelist.id,
            '_wholesale_trusted': {
                'wholesale_final_decision': 'wholesale',
                'wholesale_automatic_decision': 'wholesale',
                'wholesale_reason_code': 'previous_month',
                'wholesale_reason_text': 'Changed in the browser',
                'wholesale_retail_amount': 1500.0,
                'wholesale_previous_month_amount': 800.0,
                'wholesale_previous_month_min': 800.0,
                'wholesale_current_order_min': 1500.0,
                'wholesale_timezone': 'UTC',
                'wholesale_applied_pricelist_id': self.club_pricelist.id,
                'wholesale_override_id': False,
                'wholesale_has_override': True,
            },
        }
        order = self._pay(partner, self.retail_pricelist, qty=1.0, extra=fake_decision)
        self._assert_decision(order, 'retail', 'below_threshold', self.retail_pricelist, 100.0)
        self.assertFalse(order.wholesale_has_override)

    def test_authorized_override_audit_is_immutable(self):
        """A manager PIN and a reason store one complete exception for this ticket."""
        partner = self.partner_mayorista
        before = self._customer_snapshot(partner)
        ticket = self._ticket()
        first = self._authorize(partner, ticket)
        second = self._authorize(partner, ticket)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(first['final_decision'], 'wholesale')
        self.assertEqual(first['automatic_decision'], 'retail')
        stored = self.env['pos.wholesale.override'].browse(first['id'])
        self.assertEqual(self.env['pos.wholesale.override'].search_count([
            ('pos_uid', '=', ticket),
        ]), 1)
        self.assertEqual(stored.partner_id, partner)
        self.assertEqual(stored.manager_employee_id, self.manager_employee)
        self.assertEqual(stored.manager_user_id, self.manager_user)
        self.assertEqual(stored.cashier_employee_id, self.cashier_employee)
        self.assertEqual(stored.reason, 'Cliente de mostrador')
        self.assertEqual(stored.automatic_decision, 'retail')
        self.assertEqual(stored.final_decision, 'wholesale')
        self.assertEqual(stored.reason_code, 'below_threshold')
        self.assertTrue(stored.reason_text)
        self.assertEqual(stored.applied_pricelist_id, self.club_pricelist)
        self.assertEqual(stored.company_id, self.company)
        self.assertEqual(stored.timezone, 'America/Tijuana')
        self.assertTrue(stored.override_datetime)
        self.assertTrue(self._same(stored.previous_month_min, 800.0))
        self.assertTrue(self._same(stored.current_order_min, 1500.0))
        order = self._pay(partner, self.club_pricelist, qty=1.0, ticket=ticket)
        self.assertEqual(order.wholesale_automatic_decision, 'retail')
        self.assertEqual(order.wholesale_final_decision, 'wholesale')
        self.assertEqual(order.wholesale_reason_code, 'below_threshold')
        self.assertTrue(order.wholesale_has_override)
        self.assertEqual(order.wholesale_override_id, stored)
        self.assertEqual(stored.pos_order_id, order)
        self.assertEqual(self._customer_snapshot(partner), before)
        with self.assertRaises(UserError):
            stored.sudo().write({'reason': 'Changed after the sale'})
        with self.assertRaises(AccessError):
            self.pos_env()['pos.wholesale.override'].browse(stored.id).write({
                'reason': 'Changed by the cashier',
            })
        with self.assertRaises(UserError):
            stored.sudo().unlink()
        with self.assertRaises(UserError):
            stored.sudo().copy()
        with self.assertRaises(UserError):
            order.sudo().write({'wholesale_final_decision': 'retail'})
        with self.assertRaises(UserError):
            order.sudo().with_context(wholesale_snapshot_write=True).write({
                'wholesale_reason_text': 'Changed after payment',
            })

    def test_unauthorized_override_is_denied(self):
        """Empty reasons, a bad PIN, and a cashier PIN do not create an exception."""
        partner = self.partner_mayorista
        before = self.env['pos.wholesale.override'].sudo().search_count([])
        ticket = self._ticket()
        with self.assertRaises(UserError) as empty_reason:
            self._authorize(partner, ticket, reason='   ')
        self.assertIn('motivo', str(empty_reason.exception))
        with self.assertRaises(UserError) as wrong_pin:
            self._authorize(partner, ticket, pin='0000')
        self.assertIn('NIP', str(wrong_pin.exception))
        with self.assertRaises(UserError) as cashier:
            self._authorize(partner, ticket, pin='1111', manager=self.cashier_employee)
        self.assertIn('gerente', str(cashier.exception))
        with self.assertRaises(UserError):
            self._authorize(self.env['res.partner'], ticket)
        with self.assertRaises(UserError):
            self.env['pos.wholesale.override'].sudo().create({
                'pos_uid': ticket,
                'company_id': self.company.id,
                'partner_id': partner.id,
                'manager_employee_id': self.manager_employee.id,
                'manager_user_id': self.manager_user.id,
                'reason': 'Direct create',
                'automatic_decision': 'retail',
                'final_decision': 'wholesale',
                'reason_code': 'below_threshold',
                'applied_pricelist_id': self.club_pricelist.id,
            })
        self.assertEqual(
            self.env['pos.wholesale.override'].sudo().search_count([]),
            before,
        )

    def test_override_does_not_change_the_next_ticket(self):
        """The exception belongs to one folio. The next ticket is evaluated again."""
        partner = self.partner_mayorista
        before = self._customer_snapshot(partner)
        first = self._ticket()
        self._authorize(partner, first)
        second = self._ticket()
        message = self._reject(partner, self.club_pricelist, ticket=second)
        self.assertIn(self.retail_pricelist.display_name, message)
        retail = self._pay(partner, self.retail_pricelist, ticket=second)
        self._assert_decision(retail, 'retail', 'below_threshold', self.retail_pricelist)
        wholesale = self._pay(partner, self.club_pricelist, ticket=first)
        self.assertTrue(wholesale.wholesale_has_override)
        self.assertEqual(self._customer_snapshot(partner), before)
        later = self._eligibility(partner, 0.0)
        self.assertEqual(later['automatic_decision'], 'retail')
        self.assertEqual(later['reason_code'], 'below_threshold')

    def test_history_failure_allows_only_an_audited_override(self):
        """A history error stays on retail until a manager authorizes wholesale."""
        partner = self.partner_mayorista
        before = self._customer_snapshot(partner)
        model = type(self.env['res.partner'])
        with patch.object(model, '_wholesale_monthly_totals', side_effect=Exception('down')):
            failed = self._eligibility(partner, 1500.0)
            self.assertEqual(failed['automatic_decision'], 'retail')
            self.assertEqual(failed['reason_code'], 'history_unavailable')
            self.assertTrue(failed['error'])
            self.assertEqual(failed['months'], [])
            blocked = self._reject(partner, self.club_pricelist, qty=15.0)
            self.assertIn('excepción', blocked)
            retail = self._pay(partner, self.retail_pricelist, qty=15.0)
            self._assert_decision(
                retail, 'retail', 'history_unavailable', self.retail_pricelist, 1500.0,
            )
            ticket = self._ticket()
            granted = self._authorize(partner, ticket, qty=15.0)
            self.assertEqual(granted['automatic_decision'], 'retail')
            self.assertEqual(granted['final_decision'], 'wholesale')
            order = self._pay(partner, self.club_pricelist, qty=15.0, ticket=ticket)
        self.assertEqual(order.wholesale_reason_code, 'history_unavailable')
        self.assertEqual(order.wholesale_final_decision, 'wholesale')
        self.assertEqual(order.wholesale_automatic_decision, 'retail')
        self.assertTrue(order.wholesale_has_override)
        self.assertEqual(order.wholesale_override_id.reason, 'Cliente de mostrador')
        self.assertEqual(self._customer_snapshot(partner), before)

    def test_scenario_previous_month_applies_wholesale(self):
        """Scenario 1. MXN 800 last month applies wholesale on this ticket."""
        partner = self.partner_mayorista
        self.create_pos_order(
            partner, amount_total=800.0, date_order=self._previous_month_noon(),
        )
        result = self._eligibility(partner, 100.0)
        self.assertEqual(result['automatic_decision'], 'wholesale')
        self.assertEqual(result['reason_code'], 'previous_month')
        order = self._pay(partner, self.club_pricelist, qty=1.0)
        self._assert_decision(order, 'wholesale', 'previous_month', self.club_pricelist, 100.0)

    def test_scenario_both_amounts_below_stay_retail(self):
        """Scenario 2. MXN 799.99 last month and MXN 1,499.99 now stay retail."""
        partner = self.partner_mayorista
        self.env['product.pricelist.item'].sudo().create({
            'pricelist_id': self.retail_pricelist.id,
            'applied_on': '0_product_variant',
            'product_id': self.product.id,
            'compute_price': 'fixed',
            'fixed_price': 1499.99,
        })
        self.create_pos_order(
            partner, amount_total=799.99, date_order=self._previous_month_noon(),
        )
        result = self._eligibility(partner, 1499.99)
        self.assertEqual(result['automatic_decision'], 'retail')
        self.assertEqual(result['reason_code'], 'below_threshold')
        self.assertTrue(self._same(result['previous_month_amount'], 799.99))
        self.assertTrue(self._same(result['retail_order_amount'], 1499.99))
        message = self._reject(partner, self.club_pricelist, qty=1.0, price_unit=1499.99)
        self.assertIn(self.retail_pricelist.display_name, message)
        order = self._pay(partner, self.retail_pricelist, qty=1.0, price_unit=1499.99)
        self._assert_decision(
            order, 'retail', 'below_threshold', self.retail_pricelist, 1499.99,
        )

    def test_scenario_current_order_applies_wholesale(self):
        """Scenario 3. A retail total of MXN 1,500 applies wholesale to every line."""
        partner = self.partner_mayorista
        result = self._eligibility(partner, 1500.0)
        self.assertEqual(result['reason_code'], 'current_order')
        message = self._reject(partner, self.retail_pricelist, qty=15.0)
        self.assertIn(self.club_pricelist.display_name, message)
        order = self._pay(partner, self.club_pricelist, qty=15.0)
        self._assert_decision(
            order, 'wholesale', 'current_order', self.club_pricelist, 1500.0,
        )

    def test_scenario_removed_item_restores_retail(self):
        """Scenario 4. Dropping below MXN 1,500 restores retail for that ticket."""
        partner = self.partner_mayorista
        qualified = self._eligibility(partner, 1500.0)
        self.assertEqual(qualified['reason_code'], 'current_order')
        reduced = self._eligibility(partner, 1400.0)
        self.assertEqual(reduced['automatic_decision'], 'retail')
        self.assertEqual(reduced['reason_code'], 'below_threshold')
        message = self._reject(partner, self.club_pricelist, qty=14.0)
        self.assertIn(self.retail_pricelist.display_name, message)
        order = self._pay(partner, self.retail_pricelist, qty=14.0)
        self._assert_decision(
            order, 'retail', 'below_threshold', self.retail_pricelist, 1400.0,
        )

    def test_scenario_wholesale_total_can_fall_below_threshold(self):
        """Scenario 5. Wholesale may drop below MXN 1,500 while retail does not."""
        self.env['product.pricelist.item'].sudo().create({
            'pricelist_id': self.club_pricelist.id,
            'applied_on': '0_product_variant',
            'product_id': self.product.id,
            'compute_price': 'fixed',
            'fixed_price': 90.0,
        })
        partner = self.partner_mayorista
        order = self._pay(partner, self.club_pricelist, qty=15.0, price_unit=90.0)
        self._assert_decision(
            order, 'wholesale', 'current_order', self.club_pricelist, 1500.0,
        )
        self.assertTrue(self._same(order.amount_total, 1350.0))

    def test_scenario_no_customer_stays_retail(self):
        """Scenario 6. No customer stays on retail, including a MXN 1,500 ticket."""
        result = self._eligibility(False, 1500.0)
        self.assertEqual(result['reason_code'], 'no_identified_customer')
        self.assertEqual(result['automatic_decision'], 'retail')
        self.assertEqual(result['months'], [])
        message = self._reject(False, self.club_pricelist, qty=15.0)
        self.assertIn(self.retail_pricelist.display_name, message)
        order = self._pay(False, self.retail_pricelist, qty=15.0)
        self._assert_decision(
            order, 'retail', 'no_identified_customer', self.retail_pricelist, 1500.0,
        )

    def test_scenario_assigned_wholesale_list_is_replaced(self):
        """Scenario 7. A customer's own wholesale list does not qualify the ticket."""
        partner = self.partner_mayorista
        partner.with_company(self.company).write({
            'property_product_pricelist': self.distributor_pricelist.id,
        })
        result = self._eligibility(partner, 100.0)
        self.assertEqual(result['expected_pricelist']['id'], self.retail_pricelist.id)
        message = self._reject(partner, self.distributor_pricelist, qty=1.0)
        self.assertIn(self.retail_pricelist.display_name, message)
        order = self._pay(partner, self.retail_pricelist, qty=1.0)
        self._assert_decision(order, 'retail', 'below_threshold', self.retail_pricelist)
        assigned = partner.with_company(self.company).property_product_pricelist
        self.assertEqual(assigned, self.distributor_pricelist)

    def test_scenario_manual_wholesale_selection_is_blocked(self):
        """Scenario 8. Choosing Club Mayorista by hand is rejected at payment."""
        partner = self.partner_mayorista
        message = self._reject(partner, self.club_pricelist, qty=1.0)
        self.assertIn(self.retail_pricelist.display_name, message)
        order = self._pay(partner, self.retail_pricelist, qty=1.0)
        self._assert_decision(order, 'retail', 'below_threshold', self.retail_pricelist)

    def test_scenario_manager_override_is_audited(self):
        """Scenario 9. An authorized override is stored and applied to this ticket."""
        partner = self.partner_mayorista
        ticket = self._ticket()
        granted = self._authorize(partner, ticket, reason='Precio acordado en tienda')
        order = self._pay(partner, self.club_pricelist, ticket=ticket)
        self.assertEqual(granted['id'], order.wholesale_override_id.id)
        self.assertEqual(order.wholesale_override_id.reason, 'Precio acordado en tienda')
        self.assertEqual(order.wholesale_final_decision, 'wholesale')
        self.assertEqual(order.wholesale_automatic_decision, 'retail')
        self.assertEqual(partner.customer_type, 'mayorista')

    def test_scenario_unauthorized_override_is_denied(self):
        """Scenario 10. A cashier PIN cannot authorize wholesale."""
        partner = self.partner_mayorista
        before = self.env['pos.wholesale.override'].sudo().search_count([])
        with self.assertRaises(UserError):
            self._authorize(
                partner, self._ticket(), pin='1111', manager=self.cashier_employee,
            )
        self.assertEqual(
            self.env['pos.wholesale.override'].sudo().search_count([]),
            before,
        )

    def test_scenario_customer_change_reprices(self):
        """Scenario 11. Another customer gets a new total and a new list."""
        qualified = self.partner_publico_general
        other = self.partner_mayorista
        self.create_pos_order(
            qualified, amount_total=800.0, date_order=self._previous_month_noon(),
        )
        qualified_result = self._eligibility(qualified, 100.0)
        other_result = self._eligibility(other, 100.0)
        self.assertEqual(qualified_result['reason_code'], 'previous_month')
        self.assertEqual(qualified_result['expected_pricelist']['id'], self.club_pricelist.id)
        self.assertTrue(self._same(qualified_result['previous_month_amount'], 800.0))
        self.assertEqual(len(qualified_result['months']), 3)
        self.assertEqual(other_result['reason_code'], 'below_threshold')
        self.assertEqual(other_result['expected_pricelist']['id'], self.retail_pricelist.id)
        self.assertTrue(self._same(other_result['previous_month_amount'], 0.0))
        self.assertNotEqual(
            qualified_result['months'][1]['amount'],
            other_result['months'][1]['amount'],
        )
        retail = self._pay(other, self.retail_pricelist, qty=1.0)
        wholesale = self._pay(qualified, self.club_pricelist, qty=1.0)
        self._assert_decision(retail, 'retail', 'below_threshold', self.retail_pricelist)
        self._assert_decision(
            wholesale, 'wholesale', 'previous_month', self.club_pricelist, 100.0,
        )

    def test_scenario_history_failure_stays_retail(self):
        """Scenario 12. Missing history stays retail unless an override is audited."""
        self.test_history_failure_allows_only_an_audited_override()

    def test_completed_orders_record_a_decision_reason(self):
        """Every paid ticket has a reason. Wholesale has a rule or an override."""
        partner = self.partner_mayorista
        below = self.partner_distribuidores
        retail = self._pay(below, self.retail_pricelist, qty=1.0)
        self.create_pos_order(
            partner, amount_total=800.0, date_order=self._previous_month_noon(),
        )
        qualified = self._pay(partner, self.club_pricelist, qty=1.0)
        ticket = self._ticket()
        self._authorize(below, ticket, reason='Excepción de esta venta')
        overridden = self._pay(below, self.distributor_pricelist, ticket=ticket)
        orders = retail | qualified | overridden
        for order in orders:
            self.assertTrue(order.wholesale_reason_code)
            self.assertTrue(order.wholesale_reason_text)
            self.assertIn(order.wholesale_final_decision, ('retail', 'wholesale'))
            if order.wholesale_final_decision != 'wholesale':
                continue
            qualified_rule = order.wholesale_reason_code in (
                'previous_month', 'current_month', 'current_order',
            )
            valid_override = (
                order.wholesale_override_id
                and order.wholesale_override_id.reason
                and order.wholesale_override_id.final_decision == 'wholesale'
            )
            self.assertTrue(qualified_rule or valid_override)
        self._assert_decision(retail, 'retail', 'below_threshold', self.retail_pricelist)
        self._assert_decision(
            qualified, 'wholesale', 'previous_month', self.club_pricelist,
        )
        self.assertEqual(overridden.wholesale_applied_pricelist_id, self.distributor_pricelist)
        self.assertTrue(overridden.wholesale_has_override)
        self.assertEqual(overridden.wholesale_reason_code, 'below_threshold')
