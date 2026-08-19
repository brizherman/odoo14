# -*- coding: utf-8 -*-
# pylint: disable=import-error,missing-function-docstring,protected-access,invalid-name
"""Tests for partner classifier list, sales totals, and bulk customer type update."""
from odoo import fields
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
        partner.invalidate_cache([
            'total_sales_amount',
            'last_pos_sale_date',
            'last_sale_order_date',
        ])

    def _order_local_date(self, order):
        dt_value = order.date_order
        if isinstance(dt_value, str):
            dt_value = fields.Datetime.from_string(dt_value)
        local_dt = fields.Datetime.context_timestamp(order, dt_value)
        return local_dt.date()

    def _second_company(self):
        company = self.env['res.company'].search(
            [('id', '!=', self.env.company.id)],
            limit=1,
        )
        if company:
            return company
        return self.env['res.company'].create({
            'name': 'Alta Mayoristas Test Company',
        })

    def test_total_sales_amount_no_orders(self):
        partner = self.env['res.partner'].create({'name': 'No Sales Partner'})
        self._recompute_partner(partner)
        self.assertEqual(partner.total_sales_amount, 0.0)
        self.assertFalse(partner.primary_company_id)
        self.assertFalse(partner.last_pos_sale_date)
        self.assertFalse(partner.last_sale_order_date)

    def test_last_sale_dates_by_channel_and_state(self):
        pos_partner = self.env['res.partner'].create({'name': 'POS Date Partner'})
        pos_order = self._create_pos_order(pos_partner, 80.0)
        self.assertEqual(
            pos_partner.last_pos_sale_date,
            self._order_local_date(pos_order),
        )
        self.assertFalse(pos_partner.last_sale_order_date)

        so_partner = self.env['res.partner'].create({'name': 'SO Date Partner'})
        sale_order = self._create_sale_order(so_partner, 150.0)
        self.assertFalse(so_partner.last_pos_sale_date)
        self.assertEqual(
            so_partner.last_sale_order_date,
            self._order_local_date(sale_order),
        )

        draft_partner = self.env['res.partner'].create({'name': 'Draft Date Partner'})
        self._create_pos_order(draft_partner, 10.0, state='draft')
        self.env['sale.order'].create({
            'partner_id': draft_partner.id,
            'company_id': self.env.company.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': 40.0,
                'tax_id': [(6, 0, [])],
            })],
        })
        self.assertFalse(draft_partner.last_pos_sale_date)
        self.assertFalse(draft_partner.last_sale_order_date)

    def test_create_from_ui_sets_pos_company_from_payload(self):
        company = self.env.company
        partner_id = self.env['res.partner'].create_from_ui({
            'name': 'POS Created Customer',
            'customer_type': 'mayorista',
            'primary_company_id': company.id,
        })
        partner = self.env['res.partner'].browse(partner_id)
        self.assertEqual(partner.primary_company_id, company)

    def test_create_from_ui_falls_back_to_env_company(self):
        partner_id = self.env['res.partner'].create_from_ui({
            'name': 'POS Created Fallback',
            'customer_type': 'publico_general',
        })
        partner = self.env['res.partner'].browse(partner_id)
        self.assertEqual(partner.primary_company_id, self.env.company)

    def test_create_from_ui_does_not_change_existing_sucursal(self):
        company_b = self._second_company()
        partner = self.env['res.partner'].create({
            'name': 'Frozen Sucursal',
            'primary_company_id': company_b.id,
        })
        self.env['res.partner'].create_from_ui({
            'id': partner.id,
            'name': 'Frozen Sucursal',
            'primary_company_id': self.env.company.id,
        })
        self.assertEqual(partner.primary_company_id, company_b)

    def test_write_does_not_change_assigned_sucursal(self):
        company_b = self._second_company()
        partner = self.env['res.partner'].create({
            'name': 'Write Frozen',
            'primary_company_id': self.env.company.id,
        })
        partner.write({'primary_company_id': company_b.id, 'comment': 'keep sucursal'})
        self.assertEqual(partner.primary_company_id, self.env.company)
        self.assertEqual(partner.comment, 'keep sucursal')

    def test_pos_orders_do_not_reassign_sucursal(self):
        partner = self.env['res.partner'].create({
            'name': 'Keep Sucursal',
            'primary_company_id': self.env.company.id,
        })
        self._create_pos_order(partner, 50.0)
        self._recompute_partner(partner)
        self.assertEqual(partner.primary_company_id, self.env.company)

    def test_sql_backfill_uses_highest_amount_and_skips_set_values(self):
        company_b = self._second_company()
        empty = self.env['res.partner'].create({'name': 'Backfill Empty'})
        frozen = self.env['res.partner'].create({
            'name': 'Backfill Frozen',
            'primary_company_id': self.env.company.id,
        })
        high = self._create_pos_order(empty, 80.0)
        high.write({'company_id': company_b.id})
        self._create_pos_order(empty, 10.0)
        other = self._create_pos_order(frozen, 999.0)
        other.write({'company_id': company_b.id})
        self.env['res.partner']._sql_backfill_primary_company()
        empty.invalidate_cache(['primary_company_id'])
        frozen.invalidate_cache(['primary_company_id'])
        self.assertEqual(empty.primary_company_id, company_b)
        self.assertEqual(frozen.primary_company_id, self.env.company)

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

    def test_bulk_update_sets_distribuidores(self):
        partner = self.env['res.partner'].create({'name': 'Bulk Distributor'})
        self.env['res.partner'].with_user(self.pos_user).action_bulk_set_customer_type(
            partner.ids, 'distribuidores',
        )
        self.assertEqual(partner.customer_type, 'distribuidores')

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
        self.assertEqual(
            str(ctx.exception),
            'Seleccione Mayorista, Público General o Distribuidores.',
        )

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
