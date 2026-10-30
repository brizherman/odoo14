# -*- coding: utf-8 -*-
# pylint: disable=import-error,missing-function-docstring,protected-access
"""Thresholds, net totals, boundaries, excluded states, and pricelist replacement."""
from datetime import datetime, timedelta

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools.float_utils import float_compare

from .common import WholesaleControlCommon


@tagged('pos_wholesale_control', 'post_install', '-at_install')
class TestWholesaleThresholds(WholesaleControlCommon):
    """Thresholds, totals, boundaries, excluded states, and pricelist replacement."""

    def _same_amount(self, left, right):
        rounding = self.company.currency_id.rounding
        return float_compare(left, right, precision_rounding=rounding) == 0

    def _month_noon(self, index):
        """Noon on the 15th of one eligibility month, as naive UTC.

        Index 0 is two months ago, 1 is the previous month, and 2 is the
        current month. The 15th stays clear of Tijuana daylight-saving gaps.
        """
        months = self.company._wholesale_calendar_months()
        month = months[index]
        return self.to_utc(month['year'], month['month'], 15)

    def _previous_month_noon(self):
        """Noon on the 15th of the previous America/Tijuana month, as naive UTC."""
        return self._month_noon(1)

    def _current_month_noon(self):
        """Noon on the 15th of the current America/Tijuana month, as naive UTC."""
        return self._month_noon(2)

    def _eligibility(self, retail_order_amount=0.0):
        amount = self.company.currency_id.round(retail_order_amount)
        result = self.pos_env()['res.partner'].get_wholesale_eligibility(
            partner_id=self.partner_mayorista.id,
            company_id=self.company.id,
            retail_order_amount=amount,
            config_id=self.config.id,
        )
        self.assertFalse(result['error'])
        self.assertEqual(result['customer_id'], self.partner_mayorista.id)
        self.assertTrue(self._same_amount(result['previous_month_min'], 800.0))
        self.assertTrue(self._same_amount(result['current_order_min'], 1500.0))
        return result

    def _assert_retail(self, result):
        self.assertEqual(result['automatic_decision'], 'retail')
        self.assertEqual(result['reason_code'], 'below_threshold')
        self.assertEqual(result['expected_pricelist']['id'], self.retail_pricelist.id)

    def _assert_wholesale(self, result, reason_code):
        self.assertEqual(result['automatic_decision'], 'wholesale')
        self.assertEqual(result['reason_code'], reason_code)
        self.assertEqual(result['expected_pricelist']['id'], self.club_pricelist.id)

    def test_previous_month_one_cent_below_stays_retail(self):
        """MXN 799.99 in the previous calendar month does not qualify."""
        self.create_pos_order(
            self.partner_mayorista,
            amount_total=799.99,
            date_order=self._previous_month_noon(),
        )
        result = self._eligibility(retail_order_amount=0.0)
        self.assertTrue(self._same_amount(result['previous_month_amount'], 799.99))
        self._assert_retail(result)

    def test_previous_month_exact_threshold_is_wholesale(self):
        """MXN 800.00 in the previous calendar month qualifies the order."""
        self.create_pos_order(
            self.partner_mayorista,
            amount_total=800.0,
            date_order=self._previous_month_noon(),
        )
        result = self._eligibility(retail_order_amount=0.0)
        self.assertTrue(self._same_amount(result['previous_month_amount'], 800.0))
        self._assert_wholesale(result, 'previous_month')

    def test_current_order_one_cent_below_stays_retail(self):
        """A retail total of MXN 1,499.99 does not qualify without history."""
        result = self._eligibility(retail_order_amount=1499.99)
        self.assertTrue(self._same_amount(result['previous_month_amount'], 0.0))
        self.assertTrue(self._same_amount(result['retail_order_amount'], 1499.99))
        self._assert_retail(result)

    def test_current_order_exact_threshold_is_wholesale(self):
        """A retail total of MXN 1,500.00 qualifies when the previous month does not."""
        result = self._eligibility(retail_order_amount=1500.0)
        self.assertTrue(self._same_amount(result['previous_month_amount'], 0.0))
        self.assertTrue(self._same_amount(result['retail_order_amount'], 1500.0))
        self._assert_wholesale(result, 'current_order')

    def _discounted_taxed_orders(self, creator):
        """One 10% discount with tax excluded, and one with tax included.

        Both tax-inclusive nets are MXN 1,044.00:
        1,000.00 x 0.90 x 1.16, and 1,160.00 x 0.90.
        """
        when = self._previous_month_noon()
        excluded = creator(
            price_unit=1000.0,
            discount=10.0,
            tax=self.tax_excluded,
            date_order=when,
        )
        included = creator(
            price_unit=1160.0,
            discount=10.0,
            tax=self.tax_included,
            date_order=when,
        )
        self.assertTrue(self._same_amount(excluded.amount_total, 1044.0))
        self.assertTrue(self._same_amount(included.amount_total, 1044.0))
        return excluded, included

    def _assert_month_amounts(self, previous, current):
        result = self._eligibility()
        self.assertEqual(len(result['months']), 3)
        self.assertTrue(self._same_amount(result['previous_month_amount'], previous))
        self.assertTrue(self._same_amount(result['months'][1]['amount'], previous))
        self.assertTrue(self._same_amount(result['months'][2]['amount'], current))
        self.assertTrue(result['months'][2]['is_current'])

    def test_pos_discount_and_taxes_use_net_total(self):
        """POS discounts and included or excluded taxes qualify on the tax-inclusive net."""
        def create_pos(**kwargs):
            return self.create_pos_order(self.partner_mayorista, **kwargs)

        self._discounted_taxed_orders(create_pos)
        self._assert_month_amounts(2088.0, 0.0)

    def test_sale_discount_and_taxes_use_net_total(self):
        """Confirmed sales use the same tax-inclusive net as POS orders."""
        def create_sale(**kwargs):
            return self.create_sale_order(
                self.partner_mayorista,
                kwargs.pop('price_unit'),
                kwargs.pop('date_order'),
                **kwargs
            )

        self._discounted_taxed_orders(create_sale)
        self._assert_month_amounts(2088.0, 0.0)

    def test_pos_refund_reduces_original_sale_month(self):
        """A full POS refund dated this month reduces the original sale month to zero."""
        order = self.create_pos_order(
            self.partner_mayorista,
            price_unit=1000.0,
            discount=10.0,
            tax=self.tax_excluded,
            date_order=self._previous_month_noon(),
        )
        refund = self.create_pos_refund(order, date_order=self._current_month_noon())
        self.assertTrue(self._same_amount(order.amount_total, 1044.0))
        self.assertTrue(self._same_amount(refund.amount_total, -1044.0))
        self._assert_month_amounts(0.0, 0.0)

    def test_partial_pos_refund_leaves_remainder_on_original_month(self):
        """A partial refund stays on the original sale month and leaves the net remainder."""
        order = self.create_pos_order(
            self.partner_mayorista,
            price_unit=1000.0,
            discount=10.0,
            tax=self.tax_excluded,
            date_order=self._previous_month_noon(),
        )
        refund = self.create_pos_refund(
            order, amount_total=400.0, date_order=self._current_month_noon(),
        )
        self.assertTrue(self._same_amount(order.amount_total, 1044.0))
        self.assertTrue(self._same_amount(refund.amount_total, -400.0))
        self._assert_month_amounts(644.0, 0.0)

    def test_sale_credit_note_reduces_original_sale_month(self):
        """A posted credit note reduces the original month and leaves the order total."""
        order = self.create_sale_order(
            self.partner_mayorista,
            1000.0,
            self._previous_month_noon(),
            discount=10.0,
            tax=self.tax_excluded,
        )
        self.assertTrue(self._same_amount(order.amount_total, 1044.0))
        self.create_sale_credit_note(order)
        order.invalidate_cache(['amount_total'])
        self.assertTrue(self._same_amount(order.amount_total, 1044.0))
        self._assert_month_amounts(0.0, 0.0)

    def _paid_at(self, amount, when):
        return self.create_pos_order(
            self.partner_mayorista,
            amount_total=amount,
            date_order=when,
        )

    def _rows_at(self, moment):
        return self.partner_mayorista._wholesale_monthly_totals(
            self.company, moment_utc=moment,
        )

    def test_local_midnight_splits_the_month(self):
        """The last local second stays in the old month. Midnight starts the next one.

        October 2026 is PDT, so America/Tijuana midnight is 07:00 UTC.
        """
        before = self.to_utc(2026, 9, 30, 23, 59) + timedelta(seconds=59)
        midnight = self.to_utc(2026, 10, 1, 0, 0)
        self.assertEqual(before, datetime(2026, 10, 1, 6, 59, 59))
        self.assertEqual(midnight, datetime(2026, 10, 1, 7, 0, 0))
        self._paid_at(100.0, before)
        self._paid_at(200.0, midnight)
        rows = self._rows_at(self.to_utc(2026, 10, 15))
        self.assertEqual((rows[1]['year'], rows[1]['month']), (2026, 9))
        self.assertEqual((rows[2]['year'], rows[2]['month']), (2026, 10))
        self.assertTrue(rows[2]['is_current'])
        self.assertTrue(self._same_amount(rows[1]['amount'], 100.0))
        self.assertTrue(self._same_amount(rows[2]['amount'], 200.0))

    def test_spring_forward_shortens_march(self):
        """March 2026 loses the 02:00 hour. Both sides of the gap stay in March.

        March 1 midnight is PST (08:00 UTC). April 1 midnight is PDT (07:00 UTC).
        """
        months = self.company._wholesale_calendar_months(self.to_utc(2026, 4, 15))
        march = months[1]
        self.assertEqual((march['year'], march['month']), (2026, 3))
        self.assertEqual(march['start_utc'], datetime(2026, 3, 1, 8, 0, 0))
        self.assertEqual(march['end_utc'], datetime(2026, 4, 1, 7, 0, 0))
        self.assertEqual(months[0]['end_utc'], march['start_utc'])
        self.assertEqual(march['end_utc'], months[2]['start_utc'])
        self.assertEqual(
            march['end_utc'] - march['start_utc'],
            timedelta(days=31) - timedelta(hours=1),
        )
        before_gap = self.to_utc(2026, 3, 8, 1, 59)
        after_gap = self.to_utc(2026, 3, 8, 3, 0)
        self.assertEqual(before_gap, datetime(2026, 3, 8, 9, 59, 0))
        self.assertEqual(after_gap, datetime(2026, 3, 8, 10, 0, 0))
        self._paid_at(10.0, before_gap)
        self._paid_at(20.0, after_gap)
        last_second = self.to_utc(2026, 3, 31, 23, 59) + timedelta(seconds=59)
        self.assertEqual(last_second, datetime(2026, 4, 1, 6, 59, 59))
        self._paid_at(30.0, last_second)
        self._paid_at(40.0, march['end_utc'])
        rows = self._rows_at(self.to_utc(2026, 4, 15))
        self.assertTrue(self._same_amount(rows[1]['amount'], 60.0))
        self.assertTrue(self._same_amount(rows[2]['amount'], 40.0))

    def test_fall_back_lengthens_november(self):
        """November 2026 repeats the 01:00 hour. Both UTC instants stay in November.

        November 1 midnight is still PDT (07:00 UTC). December 1 is PST (08:00 UTC).
        The earlier repeated hour is the one the local-time helper keeps.
        """
        months = self.company._wholesale_calendar_months(self.to_utc(2026, 12, 15))
        november = months[1]
        self.assertEqual((november['year'], november['month']), (2026, 11))
        self.assertEqual(november['start_utc'], datetime(2026, 11, 1, 7, 0, 0))
        self.assertEqual(november['end_utc'], datetime(2026, 12, 1, 8, 0, 0))
        self.assertEqual(months[0]['end_utc'], november['start_utc'])
        self.assertEqual(november['end_utc'], months[2]['start_utc'])
        self.assertEqual(
            november['end_utc'] - november['start_utc'],
            timedelta(days=30, hours=1),
        )
        first_half = datetime(2026, 11, 1, 8, 30, 0)
        second_half = datetime(2026, 11, 1, 9, 30, 0)
        self.assertEqual(self.to_utc(2026, 11, 1, 1, 30), first_half)
        self._paid_at(7.0, first_half)
        self._paid_at(8.0, second_half)
        last_second = self.to_utc(2026, 11, 30, 23, 59) + timedelta(seconds=59)
        self.assertEqual(last_second, datetime(2026, 12, 1, 7, 59, 59))
        self._paid_at(9.0, last_second)
        self._paid_at(70.0, november['end_utc'])
        rows = self._rows_at(self.to_utc(2026, 12, 15))
        self.assertTrue(self._same_amount(rows[1]['amount'], 24.0))
        self.assertTrue(self._same_amount(rows[2]['amount'], 70.0))

    def _assert_stored_total(self, order, amount):
        self.assertTrue(self._same_amount(order.amount_total, amount))

    def test_open_pos_orders_do_not_qualify(self):
        """Draft and cancelled POS orders keep their totals but do not qualify.

        Draft is the unpaid order. Paid, posted, and invoiced orders qualify.
        """
        when = self._previous_month_noon()
        draft = self.create_pos_order(
            self.partner_mayorista,
            amount_total=100.0,
            date_order=when,
            state='draft',
        )
        cancelled = self.create_pos_order(
            self.partner_mayorista,
            amount_total=200.0,
            date_order=when,
            state='cancel',
        )
        self.assertEqual(draft.state, 'draft')
        self.assertTrue(self._same_amount(draft.amount_paid, 0.0))
        self.assertEqual(cancelled.state, 'cancel')
        self.assertTrue(self._same_amount(cancelled.amount_paid, 0.0))
        self._assert_stored_total(draft, 100.0)
        self._assert_stored_total(cancelled, 200.0)
        for state, amount in (('paid', 10.0), ('done', 20.0), ('invoiced', 30.0)):
            order = self.create_pos_order(
                self.partner_mayorista,
                amount_total=amount,
                date_order=when,
                state=state,
            )
            self.assertEqual(order.state, state)
            self._assert_stored_total(order, amount)
        self._assert_month_amounts(60.0, 0.0)

    def test_open_sales_orders_do_not_qualify(self):
        """Quotations and cancelled sales keep their totals but do not qualify.

        A sent quotation is still incomplete. Confirmed and locked orders qualify.
        """
        when = self._previous_month_noon()
        partner = self.partner_mayorista
        draft = self.create_sale_order(partner, 100.0, when, state='draft')
        sent = self.create_sale_order(partner, 200.0, when, state='draft')
        sent.write({'state': 'sent'})
        cancelled = self.create_sale_order(partner, 300.0, when, state='cancel')
        self.assertEqual(draft.state, 'draft')
        self.assertEqual(sent.state, 'sent')
        self.assertEqual(cancelled.state, 'cancel')
        self._assert_stored_total(draft, 100.0)
        self._assert_stored_total(sent, 200.0)
        self._assert_stored_total(cancelled, 300.0)
        confirmed = self.create_sale_order(partner, 40.0, when, state='sale')
        locked = self.create_sale_order(partner, 50.0, when, state='done')
        self.assertEqual(confirmed.state, 'sale')
        self.assertEqual(locked.state, 'done')
        self._assert_stored_total(confirmed, 40.0)
        self._assert_stored_total(locked, 50.0)
        self._assert_month_amounts(90.0, 0.0)

    def _eligibility_for(self, partner_id, retail_order_amount=0.0):
        amount = self.company.currency_id.round(retail_order_amount)
        return self.pos_env()['res.partner'].get_wholesale_eligibility(
            partner_id=partner_id,
            company_id=self.company.id,
            retail_order_amount=amount,
            config_id=self.config.id,
        )

    def _assign_pricelist(self, partner, pricelist):
        partner.with_company(self.company).write({
            'property_product_pricelist': pricelist.id,
        })
        assigned = partner.with_company(self.company).property_product_pricelist
        self.assertEqual(assigned, pricelist)

    def _payment_order(self, partner, pricelist, ticket, lines=None):
        payload = {
            'name': ticket,
            'partner_id': partner.id if partner else False,
            'pricelist_id': pricelist.id,
            'pos_session_id': self.session.id,
            'lines': lines or [],
        }
        orders = self.pos_env()['pos.order']
        prepared = orders._wholesale_prepare_payment(payload, orders.browse())
        return payload, prepared

    def _assert_unidentified(self, result, retail_order_amount):
        self.assertFalse(result['error'])
        self.assertFalse(result['customer_id'])
        self.assertEqual(result['automatic_decision'], 'retail')
        self.assertEqual(result['reason_code'], 'no_identified_customer')
        self.assertEqual(result['expected_pricelist']['id'], self.retail_pricelist.id)
        self.assertEqual(result['months'], [])
        self.assertTrue(self._same_amount(result['previous_month_amount'], 0.0))
        self.assertTrue(self._same_amount(result['retail_order_amount'], retail_order_amount))

    def test_no_customer_stays_on_retail(self):
        """No customer stays on retail, including an order of MXN 1,500.00."""
        for partner_id in (False, 0, None, 999999999):
            result = self._eligibility_for(partner_id, retail_order_amount=1500.0)
            self._assert_unidentified(result, 1500.0)
        with self.assertRaises(UserError) as caught:
            self._payment_order(False, self.club_pricelist, 'no-customer-club')
        self.assertIn(self.retail_pricelist.display_name, str(caught.exception))
        payload, prepared = self._payment_order(
            False, self.retail_pricelist, 'no-customer-retail',
        )
        self.assertFalse(prepared['override'])
        trusted = payload['_wholesale_trusted']
        self.assertEqual(trusted['wholesale_final_decision'], 'retail')
        self.assertEqual(trusted['wholesale_reason_code'], 'no_identified_customer')
        self.assertEqual(
            trusted['wholesale_applied_pricelist_id'],
            self.retail_pricelist.id,
        )

    def test_preassigned_wholesale_pricelist_is_replaced(self):
        """The customer's own wholesale list is not used. The mapping is.

        Below the threshold the order stays on retail. Once the previous
        month qualifies, a mayorista gets Club Mayorista even if the
        customer record still points at the distributor list.
        """
        partner = self.partner_mayorista
        self._assign_pricelist(partner, self.club_pricelist)
        result = self._eligibility_for(partner.id, retail_order_amount=0.0)
        self.assertFalse(result['error'])
        self.assertEqual(result['automatic_decision'], 'retail')
        self.assertEqual(result['reason_code'], 'below_threshold')
        self.assertEqual(result['expected_pricelist']['id'], self.retail_pricelist.id)
        self._assign_pricelist(partner, self.distributor_pricelist)
        self.create_pos_order(
            partner,
            amount_total=800.0,
            date_order=self._previous_month_noon(),
        )
        result = self._eligibility_for(partner.id, retail_order_amount=0.0)
        self.assertEqual(result['automatic_decision'], 'wholesale')
        self.assertEqual(result['reason_code'], 'previous_month')
        self.assertEqual(result['expected_pricelist']['id'], self.club_pricelist.id)
        self.assertEqual(
            partner.with_company(self.company).property_product_pricelist,
            self.distributor_pricelist,
        )
        with self.assertRaises(UserError) as caught:
            self._payment_order(partner, self.distributor_pricelist, 'assigned-list')
        self.assertIn(self.club_pricelist.display_name, str(caught.exception))
        payload, prepared = self._payment_order(
            partner, self.club_pricelist, 'mapped-list',
        )
        self.assertFalse(prepared['override'])
        trusted = payload['_wholesale_trusted']
        self.assertEqual(trusted['wholesale_applied_pricelist_id'], self.club_pricelist.id)
        self.assertEqual(trusted['wholesale_reason_code'], 'previous_month')

    def _retail_line(self, qty, discount=0.0, price_unit=1.0):
        """One POS line. ``price_unit`` is a decoy the server must ignore."""
        return [0, 0, {
            'product_id': self.product.id,
            'qty': qty,
            'discount': discount,
            'price_unit': price_unit,
        }]

    def _decision_for_lines(self, partner, lines):
        record = partner or self.env['res.partner']
        amount = self.pos_env()['pos.order']._wholesale_retail_amount(
            self.company,
            record,
            self.env['account.fiscal.position'],
            lines,
        )
        partner_id = partner.id if partner else False
        return amount, self._eligibility_for(partner_id, amount)

    def _assert_line_decision(self, partner, lines, expected):
        retail_amount, result = self._decision_for_lines(partner, lines)
        self.assertFalse(result['error'])
        if partner:
            self.assertEqual(result['customer_id'], partner.id)
        else:
            self.assertFalse(result['customer_id'])
        self.assertTrue(self._same_amount(retail_amount, expected['amount']))
        order_amount = result['retail_order_amount']
        self.assertTrue(self._same_amount(order_amount, expected['amount']))
        self.assertEqual(result['automatic_decision'], expected['decision'])
        self.assertEqual(result['reason_code'], expected['reason'])
        self.assertEqual(result['expected_pricelist']['id'], expected['pricelist'].id)

    def _expect_payment(self, partner, submitted, lines, expected):
        ticket = f'reprice-{id(lines)}-{submitted.id}'
        if submitted == expected:
            payload, prepared = self._payment_order(partner, submitted, ticket, lines)
            self.assertFalse(prepared['override'])
            trusted = payload['_wholesale_trusted']
            applied = trusted['wholesale_applied_pricelist_id']
            self.assertEqual(applied, expected.id)
            return
        with self.assertRaises(UserError) as caught:
            self._payment_order(partner, submitted, ticket, lines)
        self.assertIn(expected.display_name, str(caught.exception))

    def test_quantity_discount_and_removal_reprice(self):
        """Quantity, discount, and removed lines reprice the order, then reverse.

        The product price is 100.00. Every line submits a unit price of 1.00
        so the retail total has to be calculated again from the retail list.
        """
        partner = self.partner_mayorista
        full = [self._retail_line(10), self._retail_line(5)]
        club = self.club_pricelist
        retail = self.retail_pricelist
        wholesale = {
            'decision': 'wholesale',
            'reason': 'current_order',
            'pricelist': club,
            'amount': 1500.0,
        }
        below = {
            'decision': 'retail',
            'reason': 'below_threshold',
            'pricelist': retail,
        }
        self._assert_line_decision(partner, full, wholesale)
        self._expect_payment(partner, club, full, club)
        short = [self._retail_line(10)]
        short_decision = dict(below, amount=1000.0)
        self._assert_line_decision(partner, short, short_decision)
        self._expect_payment(partner, club, short, retail)
        self._assert_line_decision(partner, full, wholesale)
        reduced = [self._retail_line(14)]
        self._assert_line_decision(partner, reduced, dict(below, amount=1400.0))
        restored = [self._retail_line(15)]
        self._assert_line_decision(partner, restored, wholesale)
        discounted = [self._retail_line(15, discount=10.0)]
        self._assert_line_decision(partner, discounted, dict(below, amount=1350.0))
        self._expect_payment(partner, club, discounted, retail)
        self._assert_line_decision(partner, restored, wholesale)
        self._expect_payment(partner, retail, restored, club)

    def test_customer_change_reprices_and_reverses(self):
        """The same lines follow the selected customer, then return to retail."""
        lines = [self._retail_line(1, price_unit=50.0)]
        mayorista = self.partner_mayorista
        qualified = self.partner_publico_general
        self.create_pos_order(
            qualified,
            amount_total=800.0,
            date_order=self._previous_month_noon(),
        )
        retail = self.retail_pricelist
        club = self.club_pricelist
        priced = {'pricelist': retail, 'amount': 100.0}
        unidentified = dict(priced, decision='retail', reason='no_identified_customer')
        below = dict(priced, decision='retail', reason='below_threshold')
        self._assert_line_decision(False, lines, unidentified)
        self._assert_line_decision(mayorista, lines, below)
        self._assert_line_decision(qualified, lines, {
            'decision': 'wholesale',
            'reason': 'previous_month',
            'pricelist': club,
            'amount': 100.0,
        })
        self._expect_payment(qualified, retail, lines, club)
        self._assert_line_decision(mayorista, lines, below)
        self._expect_payment(mayorista, club, lines, retail)
        self._assert_line_decision(False, lines, unidentified)

    def test_wholesale_payable_below_threshold_stays_eligible(self):
        """A wholesale total under 1,500 stays eligible when retail does not drop.

        Club Mayorista prices this product at 90. Fifteen units then cost
        1,350, while the retail reference stays at 1,500.
        """
        self.env['product.pricelist.item'].sudo().create({
            'pricelist_id': self.club_pricelist.id,
            'applied_on': '0_product_variant',
            'product_id': self.product.id,
            'compute_price': 'fixed',
            'fixed_price': 90.0,
        })
        partner = self.partner_mayorista
        club_price = self.club_pricelist.get_product_price(self.product, 15, partner)
        retail_price = self.retail_pricelist.get_product_price(self.product, 15, partner)
        self.assertTrue(self._same_amount(club_price, 90.0))
        self.assertTrue(self._same_amount(retail_price, 100.0))
        self.assertTrue(self._same_amount(club_price * 15, 1350.0))
        lines = [self._retail_line(15, price_unit=90.0)]
        self._assert_line_decision(partner, lines, {
            'decision': 'wholesale',
            'reason': 'current_order',
            'pricelist': self.club_pricelist,
            'amount': 1500.0,
        })
        self._expect_payment(partner, self.club_pricelist, lines, self.club_pricelist)
        compared_as_retail = self._eligibility_for(partner.id, 1350.0)
        self.assertEqual(compared_as_retail['automatic_decision'], 'retail')
        self.assertEqual(compared_as_retail['reason_code'], 'below_threshold')

    def _assert_customer_unchanged(self, partner, customer_type, pricelist):
        self.assertEqual(partner.customer_type, customer_type)
        assigned = partner.with_company(self.company).property_product_pricelist
        self.assertEqual(assigned, pricelist)

    def test_current_order_qualification_does_not_change_future_eligibility(self):
        """A MXN 1,500 ticket qualifies only itself. The next ticket stays retail.

        The completed sale lands in the current month. It does not raise the
        previous-month total, and it does not change the customer type or the
        customer's own pricelist.
        """
        partner = self.partner_mayorista
        customer_type = partner.customer_type
        pricelist = partner.with_company(self.company).property_product_pricelist
        self.assertEqual(customer_type, 'mayorista')

        qualified = self._eligibility(retail_order_amount=1500.0)
        self._assert_wholesale(qualified, 'current_order')
        self._assert_customer_unchanged(partner, customer_type, pricelist)

        self.create_pos_order(
            partner,
            amount_total=1500.0,
            date_order=self._current_month_noon(),
        )
        later = self._eligibility(retail_order_amount=0.0)
        self._assert_retail(later)
        self.assertTrue(self._same_amount(later['previous_month_amount'], 0.0))
        self._assert_month_amounts(0.0, 1500.0)
        self._assert_customer_unchanged(partner, customer_type, pricelist)
        self._expect_payment(
            partner,
            self.club_pricelist,
            [self._retail_line(1, price_unit=100.0)],
            self.retail_pricelist,
        )
