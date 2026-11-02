# -*- coding: utf-8 -*-
# pylint: disable=import-error,missing-function-docstring,protected-access
"""Distributor threshold, currency guard, mapping, and manager exceptions."""
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools.float_utils import float_compare

from .common import WholesaleControlCommon


@tagged('pos_wholesale_control', 'post_install', '-at_install')
class TestDistributorEligibility(WholesaleControlCommon):
    """Distributor-only thresholds; regular wholesale rules never apply."""

    def _same(self, left, right):
        rounding = self.company.currency_id.rounding
        return float_compare(left, right, precision_rounding=rounding) == 0

    def _previous_month_noon(self):
        month = self.company._wholesale_calendar_months()[1]
        return self.to_utc(month['year'], month['month'], 15)

    def _current_month_noon(self):
        month = self.company._wholesale_calendar_months()[2]
        return self.to_utc(month['year'], month['month'], 15)

    def _eligibility(self, partner=None, amount=0.0):
        partner = partner or self.partner_distribuidores
        return self.pos_env()['res.partner'].get_wholesale_eligibility(
            partner.id,
            self.company.id,
            amount,
            self.config.id,
        )

    def test_distributor_minimum_defaults_to_ten_thousand(self):
        self.assertTrue(self._same(self.company.wholesale_distributor_min, 10000.0))
        result = self._eligibility()
        self.assertEqual(result['pricing_program'], 'distributor')
        self.assertTrue(self._same(result['distributor_min'], 10000.0))
        self.assertEqual(result['customer_type'], 'distribuidores')

    def test_previous_month_one_cent_below_stays_retail(self):
        """MXN 9,999.99 last month does not qualify for distributor pricing."""
        self.create_pos_order(
            self.partner_distribuidores,
            amount_total=9999.99,
            date_order=self._previous_month_noon(),
        )
        result = self._eligibility(amount=0.0)
        self.assertTrue(self._same(result['previous_month_amount'], 9999.99))
        self.assertEqual(result['automatic_decision'], 'retail')
        self.assertEqual(result['pricing_program'], 'distributor')
        self.assertEqual(result['reason_code'], 'below_threshold')
        self.assertEqual(result['expected_pricelist']['id'], self.retail_pricelist.id)

    def test_previous_month_exact_minimum_uses_distributor_list(self):
        """MXN 10,000.00 in the previous month qualifies. Equality is enough."""
        self.create_pos_order(
            self.partner_distribuidores,
            amount_total=10000.0,
            date_order=self._previous_month_noon(),
        )
        result = self._eligibility(amount=1.0)
        self.assertEqual(result['automatic_decision'], 'wholesale')
        self.assertEqual(result['reason_code'], 'previous_month')
        self.assertEqual(result['expected_pricelist']['id'], self.distributor_pricelist.id)
        self.assertNotEqual(result['expected_pricelist']['id'], self.club_pricelist.id)

    def test_current_month_exact_minimum_uses_distributor_list(self):
        self.create_pos_order(
            self.partner_distribuidores,
            amount_total=10000.0,
            date_order=self._current_month_noon(),
        )
        result = self._eligibility(amount=0.0)
        self.assertEqual(result['automatic_decision'], 'wholesale')
        self.assertEqual(result['pricing_program'], 'distributor')
        self.assertEqual(result['reason_code'], 'current_month')
        self.assertEqual(result['expected_pricelist']['id'], self.distributor_pricelist.id)

    def test_current_month_plus_order_uses_distributor_list(self):
        self.create_pos_order(
            self.partner_distribuidores,
            amount_total=5000.0,
            date_order=self._current_month_noon(),
        )
        result = self._eligibility(amount=5000.0)
        self.assertEqual(result['automatic_decision'], 'wholesale')
        self.assertEqual(result['pricing_program'], 'distributor')
        self.assertEqual(result['reason_code'], 'current_order')
        self.assertEqual(result['expected_pricelist']['id'], self.distributor_pricelist.id)

    def test_distributor_below_ten_thousand_does_not_use_wholesale_rules(self):
        self.create_pos_order(
            self.partner_distribuidores,
            amount_total=1200.0,
            date_order=self._current_month_noon(),
        )
        result = self._eligibility(amount=300.0)
        self.assertEqual(result['automatic_decision'], 'retail')
        self.assertEqual(result['pricing_program'], 'distributor')
        self.assertEqual(result['reason_code'], 'below_threshold')
        self.assertEqual(result['expected_pricelist']['id'], self.retail_pricelist.id)

    def test_missing_distributor_mapping_does_not_use_club(self):
        self.env['pos.wholesale.pricelist.mapping'].sudo().search([
            ('company_id', '=', self.company.id),
            ('customer_type', '=', 'distribuidores'),
        ]).unlink()
        self.create_pos_order(
            self.partner_distribuidores,
            amount_total=10000.0,
            date_order=self._previous_month_noon(),
        )
        result = self._eligibility()
        self.assertEqual(result['automatic_decision'], 'retail')
        self.assertTrue(result['error'])
        self.assertNotEqual(
            (result.get('expected_pricelist') or {}).get('id'),
            self.club_pricelist.id,
        )
        self.assertEqual(result['expected_pricelist']['id'], self.retail_pricelist.id)

    def test_inactive_wrong_currency_and_unavailable_mapping_stay_retail(self):
        mapping = self.env['pos.wholesale.pricelist.mapping'].sudo().search([
            ('company_id', '=', self.company.id),
            ('customer_type', '=', 'distribuidores'),
        ])
        self.create_pos_order(
            self.partner_distribuidores,
            amount_total=10000.0,
            date_order=self._previous_month_noon(),
        )
        mapping.write({'active': False})
        inactive = self._eligibility()
        self.assertEqual(inactive['automatic_decision'], 'retail')
        self.assertIn('inactiva', inactive['error'])

        mapping.write({'active': True})
        self.distributor_pricelist.sudo().write({
            'currency_id': self.env.ref('base.USD').id,
        })
        wrong_currency = self._eligibility()
        self.assertEqual(wrong_currency['automatic_decision'], 'retail')
        self.assertIn('moneda', wrong_currency['error'])
        self.distributor_pricelist.sudo().write({'currency_id': self.mxn.id})

        # Available pricelists cannot change while the register session is open.
        self.session.sudo().write({'state': 'closed'})
        self.config.sudo().write({
            'available_pricelist_ids': [(3, self.distributor_pricelist.id)],
        })
        unavailable = self._eligibility()
        self.assertEqual(unavailable['automatic_decision'], 'retail')
        self.assertIn('no está disponible', unavailable['error'])
        self.assertEqual(unavailable['expected_pricelist']['id'], self.retail_pricelist.id)

    def test_mixed_company_currency_fails_closed(self):
        usd_company = self.env['res.company'].sudo().create({
            'name': 'Distributor USD branch',
            'currency_id': self.env.ref('base.USD').id,
        })

        def read_group(self, domain, fields, groupby, offset=0, limit=None,  # pylint: disable=unused-argument
                       orderby=False, lazy=True):
            if groupby == ['company_id']:
                if self._name == 'pos.order':
                    return [{
                        'company_id': (usd_company.id, usd_company.name),
                        '__count': 1,
                        'company_id_count': 1,
                    }]
                return []
            return []

        with patch.object(type(self.env['pos.order']), 'read_group', read_group), \
                patch.object(type(self.env['sale.order']), 'read_group', read_group):
            result = self._eligibility(amount=10000.0)
        self.assertEqual(result['reason_code'], 'currency_mismatch')
        self.assertEqual(result['automatic_decision'], 'retail')
        self.assertEqual(result['expected_pricelist']['id'], self.retail_pricelist.id)
        self.assertTrue(result['error'])


@tagged('pos_wholesale_control', 'post_install', '-at_install')
class TestDistributorPayment(WholesaleControlCommon):
    """Payment recalculates the distributor decision and keeps the audit row."""

    def _same(self, left, right):
        rounding = self.company.currency_id.rounding
        return float_compare(left, right, precision_rounding=rounding) == 0

    def _ticket(self):
        count = getattr(self, '_ticket_seq', 0) + 1
        self._ticket_seq = count  # pylint: disable=attribute-defined-outside-init
        return 'distributor-%s-%s' % (self._testMethodName, count)

    def _previous_month_noon(self):
        month = self.company._wholesale_calendar_months()[1]
        return self.to_utc(month['year'], month['month'], 15)

    def _current_month_noon(self):
        month = self.company._wholesale_calendar_months()[2]
        return self.to_utc(month['year'], month['month'], 15)

    def _line(self, qty, price_unit):
        amount = self.company.currency_id.round(price_unit * qty)
        return [0, 0, {
            'discount': 0.0,
            'pack_lot_ids': [],
            'price_unit': price_unit,
            'product_id': self.product.id,
            'price_subtotal': amount,
            'price_subtotal_incl': amount,
            'qty': qty,
            'tax_ids': [(6, 0, [])],
        }]

    def _draft(self, partner, ticket, pricelist=None, extra=None, qty=1.0):
        pricelist = pricelist or self.retail_pricelist
        amount = 100.0 * qty
        stamp = fields.Datetime.to_string(fields.Datetime.now())
        data = {
            'amount_paid': amount,
            'amount_return': 0,
            'amount_tax': 0,
            'amount_total': amount,
            'creation_date': stamp,
            'fiscal_position_id': False,
            'pricelist_id': pricelist.id,
            'lines': [self._line(qty, 100.0)],
            'name': ticket,
            'partner_id': partner.id,
            'pos_session_id': self.session.id,
            'sequence_number': self._ticket_seq,
            'statement_ids': [[0, 0, {
                'amount': amount,
                'name': stamp,
                'payment_method_id': self.config.payment_method_ids[:1].id,
            }]],
            'uid': ticket,
            'user_id': self.cashier_user.id,
            'employee_id': self.cashier_employee.id,
            'to_invoice': False,
        }
        if extra:
            data.update(extra)
        return data

    def _pay(self, partner, pricelist, ticket=None, extra=None, qty=1.0):
        ticket = ticket or self._ticket()
        payload = {
            'data': self._draft(partner, ticket, pricelist, extra, qty),
            'id': ticket,
            'to_invoice': False,
        }
        result = self.pos_env()['pos.order'].create_from_ui([payload])
        order = self.env['pos.order'].browse(result[0]['id'])
        self.assertEqual(order.state, 'paid')
        return order

    def _authorize(self, partner, ticket, reason='Precio de esta venta', pin='2580', extra=None):
        data = self._draft(partner, ticket, extra=extra)
        return self.pos_env()['pos.wholesale.override'].authorize_from_pos(
            self.manager_employee.id,
            pin,
            reason,
            'wholesale',
            data,
        )

    def test_exception_pays_distributor_list_and_stores_the_snapshot(self):
        partner = self.partner_distribuidores
        ticket = self._ticket()
        granted = self._authorize(partner, ticket)
        self.assertEqual(granted['pricing_program'], 'distributor')
        self.assertEqual(granted['applied_pricelist']['id'], self.distributor_pricelist.id)
        order = self._pay(partner, self.distributor_pricelist, ticket=ticket)
        self.assertEqual(order.wholesale_pricing_program, 'distributor')
        self.assertEqual(order.wholesale_customer_type, 'distribuidores')
        self.assertEqual(order.wholesale_automatic_decision, 'retail')
        self.assertEqual(order.wholesale_final_decision, 'wholesale')
        self.assertTrue(self._same(order.wholesale_distributor_min, 10000.0))
        self.assertEqual(order.wholesale_applied_pricelist_id, self.distributor_pricelist)
        self.assertEqual(order.wholesale_expected_pricelist_id, self.retail_pricelist)
        self.assertEqual(order.wholesale_override_id.pos_config_id, self.config)
        self.assertEqual(order.wholesale_override_id.pos_session_id, self.session)
        self.assertEqual(order.wholesale_override_id.pricing_program, 'distributor')
        with self.assertRaises(UserError):
            order.write({'wholesale_pricing_program': 'wholesale'})

    def test_tampered_program_does_not_grant_distributor_pricing(self):
        message = ''
        with self.assertRaises(UserError) as caught:
            self._pay(
                self.partner_distribuidores,
                self.distributor_pricelist,
                extra={
                    'pricing_program': 'distributor',
                    'wholesale_pricing_program': 'distributor',
                    'wholesale_automatic_decision': 'wholesale',
                    'wholesale_final_decision': 'wholesale',
                    'wholesale_distributor_min': 1.0,
                },
            )
        message = str(caught.exception)
        self.assertIn(self.retail_pricelist.display_name, message)

    def test_qualified_distributor_rejects_an_exception(self):
        self.create_pos_order(
            self.partner_distribuidores,
            amount_total=10000.0,
            date_order=self._previous_month_noon(),
        )
        with self.assertRaises(UserError):
            self._authorize(self.partner_distribuidores, self._ticket())
        order = self._pay(self.partner_distribuidores, self.distributor_pricelist)
        self.assertEqual(order.wholesale_reason_code, 'previous_month')
        self.assertFalse(order.wholesale_has_override)

    def test_mtd_plus_ticket_uses_distributor_pricing_at_payment(self):
        partner = self.partner_distribuidores
        self.create_pos_order(
            partner,
            amount_total=5000.0,
            date_order=self._current_month_noon(),
        )
        order = self._pay(partner, self.distributor_pricelist, qty=50.0)
        self.assertEqual(order.wholesale_pricing_program, 'distributor')
        self.assertEqual(order.wholesale_reason_code, 'current_order')
        self.assertEqual(order.wholesale_applied_pricelist_id, self.distributor_pricelist)

    def test_distributor_does_not_use_regular_wholesale_at_payment(self):
        partner = self.partner_distribuidores
        self.create_pos_order(
            partner,
            amount_total=800.0,
            date_order=self._previous_month_noon(),
        )
        with self.assertRaises(UserError):
            self._pay(partner, self.club_pricelist)
        order = self._pay(partner, self.retail_pricelist)
        self.assertEqual(order.wholesale_pricing_program, 'distributor')
        self.assertEqual(order.wholesale_reason_code, 'below_threshold')
        self.assertEqual(order.wholesale_applied_pricelist_id, self.retail_pricelist)

    def test_wrong_pin_empty_reason_and_other_ticket_are_rejected(self):
        partner = self.partner_distribuidores
        ticket = self._ticket()
        with self.assertRaises(UserError):
            self._authorize(partner, ticket, pin='0000')
        with self.assertRaises(UserError):
            self._authorize(partner, ticket, reason='   ')
        granted = self._authorize(partner, ticket)
        other = self._ticket()
        with self.assertRaises(UserError):
            self._pay(partner, self.distributor_pricelist, ticket=other)
        same = self._authorize(partner, ticket)
        self.assertEqual(same['id'], granted['id'])
        self._pay(partner, self.distributor_pricelist, ticket=ticket)
        with self.assertRaises(UserError):
            self._authorize(partner, ticket, reason='Otro motivo')

    def test_client_pricelist_cannot_replace_the_distributor_mapping(self):
        with self.assertRaises(UserError):
            self._authorize(
                self.partner_distribuidores,
                self._ticket(),
                extra={'applied_pricelist_id': self.club_pricelist.id},
            )
