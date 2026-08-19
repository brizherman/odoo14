# -*- coding: utf-8 -*-
# pylint: disable=import-error,missing-function-docstring,protected-access,invalid-name
"""Tests for partner classifier list, sales totals, and bulk customer type update."""
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('alta_mayoristas', 'post_install', '-at_install')
class TestPartnerClassifier(TransactionCase):
    """Backend tests for classifier list and bulk assignment."""

    def setUp(self):
        super().setUp()
        suffix = str(self.env.cr.dbname)
        self.pos_user = self.env['res.users'].create({
            'name': 'POS Classifier User',
            'login': 'pos_classifier_test_%s' % suffix,
            'groups_id': [(6, 0, [self.env.ref('point_of_sale.group_pos_user').id])],
        })
        self.internal_user = self.env['res.users'].create({
            'name': 'Internal No POS',
            'login': 'internal_no_pos_test_%s' % suffix,
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        self.product = self.env['product.product'].create({
            'name': 'Classifier Test Product',
            'type': 'service',
            'list_price': 100.0,
            'taxes_id': [(6, 0, [])],
        })

    def _ensure_pos_session(self):
        config = self.env['pos.config'].search([], limit=1)
        if not config:
            config = self.env['pos.config'].create({'name': 'Classifier Test POS'})
        if not config.current_session_id:
            config.open_session_cb(check_coa=False)
        return config.current_session_id

    def _create_sale_order(self, partner, amount):
        order_vals = {
            'partner_id': partner.id,
            'company_id': self.env.company.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': amount,
                'tax_id': [(6, 0, [])],
            })],
        }
        team = self.env['crm.team'].search([
            ('company_id', 'in', [False, self.env.company.id]),
        ], limit=1)
        if team:
            order_vals['team_id'] = team.id
        order = self.env['sale.order'].create(order_vals)
        order.action_confirm()
        return order

    def _create_pos_order(self, partner, amount, state='paid'):
        session = self._ensure_pos_session()
        return self.env['pos.order'].create({
            'session_id': session.id,
            'partner_id': partner.id,
            'amount_tax': 0.0,
            'amount_total': amount,
            'amount_paid': amount,
            'amount_return': 0.0,
            'state': state,
        })

    def _recompute_partner(self, partner):
        self.env['res.partner']._recompute_total_sales_amount_for_partners(partner.ids)
        partner.invalidate_cache(['total_sales_amount', 'primary_company_id'])

    def _second_company(self):
        return self.env['res.company'].search(
            [('id', '!=', self.env.company.id)],
            limit=1,
        )

    def test_total_sales_amount_no_orders(self):
        partner = self.env['res.partner'].create({'name': 'No Sales Partner'})
        self._recompute_partner(partner)
        self.assertEqual(partner.total_sales_amount, 0.0)
        self.assertFalse(partner.primary_company_id)

    def test_primary_company_follows_highest_amount(self):
        company_b = self._second_company()
        if not company_b:
            self.skipTest('A second company is required')
        partner = self.env['res.partner'].create({'name': 'Multi Sucursal Partner'})
        order_low = self._create_pos_order(partner, 50.0)
        order_high = self._create_pos_order(partner, 80.0)
        order_high.write({'company_id': company_b.id})
        self._recompute_partner(partner)
        self.assertEqual(partner.primary_company_id, company_b)
        self.assertEqual(order_low.company_id, self.env.company)

    def test_primary_company_tie_uses_latest_sale(self):
        company_b = self._second_company()
        if not company_b:
            self.skipTest('A second company is required')
        partner = self.env['res.partner'].create({'name': 'Tie Partner'})
        older = self._create_pos_order(partner, 100.0)
        newer = self._create_pos_order(partner, 100.0)
        older.write({
            'date_order': '2026-01-01 10:00:00',
            'company_id': self.env.company.id,
        })
        newer.write({
            'date_order': '2026-06-01 10:00:00',
            'company_id': company_b.id,
        })
        self._recompute_partner(partner)
        self.assertEqual(partner.primary_company_id, company_b)

    def test_select_primary_company_id_empty(self):
        Partner = self.env['res.partner']
        self.assertFalse(Partner._select_primary_company_id({}))

    def test_classifier_domain_hides_other_company_and_allows_no_sales(self):
        company_b = self._second_company()
        if not company_b:
            self.skipTest('A second company is required')
        local_partner = self.env['res.partner'].create({'name': 'Local Sales'})
        other_partner = self.env['res.partner'].create({'name': 'Other Sales'})
        none_partner = self.env['res.partner'].create({'name': 'No Sales Filter'})
        self._create_pos_order(local_partner, 40.0)
        other_order = self._create_pos_order(other_partner, 40.0)
        other_order.write({'company_id': company_b.id})
        self._recompute_partner(local_partner | other_partner | none_partner)
        allowed = [self.env.company.id]
        visible = self.env['res.partner'].search([
            '|',
            ('primary_company_id', 'in', allowed),
            ('primary_company_id', '=', False),
            ('id', 'in', (local_partner | other_partner | none_partner).ids),
        ])
        self.assertIn(local_partner, visible)
        self.assertIn(none_partner, visible)
        self.assertNotIn(other_partner, visible)
        with_sales = visible.filtered('primary_company_id')
        self.assertEqual(with_sales, local_partner)

    def test_total_sales_amount_sale_orders_only(self):
        partner = self.env['res.partner'].create({'name': 'SO Partner'})
        self._create_sale_order(partner, 150.0)
        self._create_sale_order(partner, 50.0)
        self._recompute_partner(partner)
        self.assertEqual(partner.total_sales_amount, 200.0)

    def test_total_sales_amount_pos_orders_only(self):
        partner = self.env['res.partner'].create({'name': 'POS Partner'})
        self._create_pos_order(partner, 80.0)
        self._create_pos_order(partner, 20.0)
        self._recompute_partner(partner)
        self.assertEqual(partner.total_sales_amount, 100.0)

    def test_total_sales_amount_both_sources(self):
        partner = self.env['res.partner'].create({'name': 'Mixed Partner'})
        self._create_sale_order(partner, 100.0)
        self._create_pos_order(partner, 75.0)
        self._recompute_partner(partner)
        self.assertEqual(partner.total_sales_amount, 175.0)

    def test_bulk_update_sets_customer_type(self):
        partners = self.env['res.partner'].create([
            {'name': 'Bulk A'},
            {'name': 'Bulk B'},
        ])
        result = self.env['res.partner'].with_user(self.pos_user).action_bulk_set_customer_type(
            partners.ids, 'mayorista',
        )
        self.assertEqual(partners.mapped('customer_type'), ['mayorista', 'mayorista'])
        self.assertIn('Se actualizaron 2 contacto(s).', result['params']['message'])

    def test_bulk_update_overwrites_existing_type(self):
        partner = self.env['res.partner'].create({
            'name': 'Overwrite Partner',
            'customer_type': 'mayorista',
        })
        self.env['res.partner'].with_user(self.pos_user).action_bulk_set_customer_type(
            partner.ids, 'publico_general',
        )
        self.assertEqual(partner.customer_type, 'publico_general')

    def test_bulk_update_empty_partner_ids_raises(self):
        with self.assertRaises(UserError) as ctx:
            self.env['res.partner'].with_user(self.pos_user).action_bulk_set_customer_type(
                [], 'mayorista',
            )
        self.assertEqual(str(ctx.exception), 'Seleccione al menos un contacto.')

    def test_bulk_update_missing_customer_type_raises(self):
        partner = self.env['res.partner'].create({'name': 'Validation Partner'})
        with self.assertRaises(UserError) as ctx:
            self.env['res.partner'].with_user(self.pos_user).action_bulk_set_customer_type(
                partner.ids, False,
            )
        self.assertEqual(str(ctx.exception), 'Seleccione Mayorista o Público General.')

    def test_bulk_update_access_denied_without_pos_group(self):
        partner = self.env['res.partner'].create({'name': 'Access Partner'})
        with self.assertRaises(AccessError):
            self.env['res.partner'].with_user(self.internal_user).action_bulk_set_customer_type(
                partner.ids, 'mayorista',
            )

    def test_phone_display_fallback_to_mobile(self):
        partner = self.env['res.partner'].create({
            'name': 'Phone Partner',
            'mobile': '5559876543',
        })
        self.assertEqual(partner.phone_display, '5559876543')

    def test_phone_display_prefers_phone(self):
        partner = self.env['res.partner'].create({
            'name': 'Phone Partner 2',
            'phone': '5551112222',
            'mobile': '5559876543',
        })
        self.assertEqual(partner.phone_display, '5551112222')
