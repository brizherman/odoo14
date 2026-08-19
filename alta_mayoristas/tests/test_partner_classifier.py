# -*- coding: utf-8 -*-
# pylint: disable=import-error,missing-function-docstring,protected-access,invalid-name
"""Tests for partner classifier list, sales totals, and bulk customer type update."""
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.addons.alta_mayoristas.models import res_partner as partner_mod
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
        self.pricelist_mayorista = self._get_or_create_pricelist(
            'Lista de precios de Mayorista',
        )
        self.pricelist_publico = self._get_or_create_pricelist(
            'Lista de precios a Publico en General',
        )
        self.pricelist_distribuidores = self._get_or_create_pricelist(
            'Super Precios a Distribuidores',
        )

    def _get_or_create_pricelist(self, name):
        Pricelist = self.env['product.pricelist']
        existing = Pricelist.search([
            ('name', '=', name),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if existing:
            return existing
        return Pricelist.create({
            'name': name,
            'company_id': self.env.company.id,
            'currency_id': self.env.company.currency_id.id,
        })

    def _ensure_pos_session(self):
        config = self.env['pos.config'].search([], limit=1)
        if not config:
            config = self.env['pos.config'].create({'name': 'Classifier Test POS'})
        if not config.current_session_id:
            config.open_session_cb(check_coa=False)
        return config.current_session_id

    def _create_sale_order(self, partner, amount, company=None, confirm=True):
        company = company or self.env.company
        order_vals = {
            'partner_id': partner.id,
            'company_id': company.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': amount,
                'tax_id': [(6, 0, [])],
            })],
        }
        team = self.env['crm.team'].search([
            ('company_id', '=', company.id),
        ], limit=1)
        if not team:
            team = self.env['crm.team'].search([
                ('company_id', '=', False),
            ], limit=1)
        if team:
            order_vals['team_id'] = team.id
        if 'stock.warehouse' in self.env:
            warehouse = self.env['stock.warehouse'].search(
                [('company_id', '=', company.id)],
                limit=1,
            )
            if warehouse:
                order_vals['warehouse_id'] = warehouse.id
        order = self.env['sale.order'].with_company(company).create(order_vals)
        if confirm:
            order.action_confirm()
        return order

    def _create_pos_order(self, partner, amount, state='paid', company=None):
        company = company or self.env.company
        session = self._ensure_pos_session()
        order = self.env['pos.order'].create({
            'session_id': session.id,
            'partner_id': partner.id,
            'amount_tax': 0.0,
            'amount_total': amount,
            'amount_paid': amount,
            'amount_return': 0.0,
            'state': state,
        })
        if order.company_id != company:
            self.env.cr.execute(
                'UPDATE pos_order SET company_id = %s WHERE id = %s',
                (company.id, order.id),
            )
            order.invalidate_cache(['company_id'])
        return order

    def _recompute_partner(self, partner):
        self.env['res.partner']._recompute_total_sales_amount_for_partners(partner.ids)
        partner.invalidate_cache([
            'total_sales_amount',
            'last_pos_sale_date',
            'last_sale_order_date',
            'sales_last_6_months',
            'sales_last_6_months_avg',
        ])

    def _set_order_date(self, order, when):
        """Force date_order (confirmed SO date_order is readonly)."""
        date_value = fields.Datetime.to_string(when)
        if order._name == 'pos.order':
            self.env.cr.execute(
                'UPDATE pos_order SET date_order = %s WHERE id = %s',
                (date_value, order.id),
            )
        else:
            self.env.cr.execute(
                'UPDATE sale_order SET date_order = %s WHERE id = %s',
                (date_value, order.id),
            )
        order.invalidate_cache(['date_order'])

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
        self.assertEqual(partner.sales_last_6_months, 0.0)
        self.assertEqual(partner.sales_last_6_months_avg, 0.0)

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
        self._create_sale_order(draft_partner, 40.0, confirm=False)
        self.assertFalse(draft_partner.last_pos_sale_date)
        self.assertFalse(draft_partner.last_sale_order_date)

    def test_last_sale_order_date_all_companies(self):
        company_b = self._second_company()
        partner = self.env['res.partner'].create({
            'name': 'Cross Company SO Partner',
        })
        sale_order = self._create_sale_order(partner, 150.0, company=company_b)
        self.pos_user.write({
            'company_id': self.env.company.id,
            'company_ids': [(6, 0, [self.env.company.id])],
        })
        partner_as_user = partner.with_user(self.pos_user)
        partner_as_user.invalidate_cache(['last_sale_order_date'])
        self.assertEqual(
            partner_as_user.last_sale_order_date,
            self._order_local_date(sale_order),
        )

    def test_sales_last_6_months_old_orders_excluded(self):
        partner = self.env['res.partner'].create({'name': 'Old Sales Partner'})
        old = fields.Datetime.now() - relativedelta(months=7)
        sale_order = self._create_sale_order(partner, 900.0)
        pos_order = self._create_pos_order(partner, 100.0)
        self._set_order_date(sale_order, old)
        self._set_order_date(pos_order, old)
        self._recompute_partner(partner)
        self.assertEqual(partner.sales_last_6_months, 0.0)
        self.assertEqual(partner.sales_last_6_months_avg, 0.0)

    def test_sales_last_6_months_pos_only(self):
        partner = self.env['res.partner'].create({'name': 'POS 6M Partner'})
        self._create_pos_order(partner, 80.0)
        self._create_pos_order(partner, 40.0)
        self._recompute_partner(partner)
        self.assertEqual(partner.sales_last_6_months, 120.0)
        self.assertEqual(partner.sales_last_6_months_avg, 20.0)

    def test_sales_last_6_months_sale_orders_only(self):
        partner = self.env['res.partner'].create({'name': 'SO 6M Partner'})
        self._create_sale_order(partner, 90.0)
        self._create_sale_order(partner, 30.0)
        self._recompute_partner(partner)
        self.assertEqual(partner.sales_last_6_months, 120.0)
        self.assertEqual(partner.sales_last_6_months_avg, 20.0)

    def test_sales_last_6_months_both_sources_and_average(self):
        partner = self.env['res.partner'].create({'name': 'Mixed 6M Partner'})
        self._create_sale_order(partner, 70000.0)
        self._create_pos_order(partner, 50000.0)
        self._recompute_partner(partner)
        self.assertEqual(partner.sales_last_6_months, 120000.0)
        self.assertEqual(partner.sales_last_6_months_avg, 20000.0)

    def test_sales_last_6_months_excludes_draft_and_unconfirmed(self):
        partner = self.env['res.partner'].create({'name': 'Draft 6M Partner'})
        self._create_pos_order(partner, 10.0, state='draft')
        self._create_sale_order(partner, 40.0, confirm=False)
        self._recompute_partner(partner)
        self.assertEqual(partner.sales_last_6_months, 0.0)
        self.assertEqual(partner.sales_last_6_months_avg, 0.0)

    def test_sales_last_6_months_all_companies(self):
        company_b = self._second_company()
        partner = self.env['res.partner'].create({
            'name': 'Cross Company 6M Partner',
        })
        self._create_sale_order(partner, 150.0, company=company_b)
        self._recompute_partner(partner)
        self.pos_user.write({
            'company_id': self.env.company.id,
            'company_ids': [(6, 0, [self.env.company.id])],
        })
        partner_as_user = partner.with_user(self.pos_user)
        self.assertEqual(partner_as_user.sales_last_6_months, 150.0)
        self.assertEqual(partner_as_user.sales_last_6_months_avg, 25.0)

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
        high = self._create_pos_order(empty, 80.0, company=company_b)
        self._create_pos_order(empty, 10.0)
        self._create_pos_order(frozen, 999.0, company=company_b)
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
            partners.ids, 'mayorista', self.pricelist_mayorista.id,
        )
        self.assertEqual(partners.mapped('customer_type'), ['mayorista', 'mayorista'])
        self.assertEqual(
            set(partners.mapped('property_product_pricelist').ids),
            {self.pricelist_mayorista.id},
        )
        self.assertIn('Se actualizaron 2 contacto(s).', result['params']['message'])

    def test_bulk_update_overwrites_existing_type(self):
        partner = self.env['res.partner'].create({
            'name': 'Overwrite Partner',
            'customer_type': 'mayorista',
        })
        self.env['res.partner'].with_user(self.pos_user).action_bulk_set_customer_type(
            partner.ids, 'publico_general', self.pricelist_publico.id,
        )
        self.assertEqual(partner.customer_type, 'publico_general')
        self.assertEqual(partner.property_product_pricelist, self.pricelist_publico)

    def test_bulk_update_sets_distribuidores(self):
        partner = self.env['res.partner'].create({'name': 'Bulk Distributor'})
        self.env['res.partner'].with_user(self.pos_user).action_bulk_set_customer_type(
            partner.ids, 'distribuidores', self.pricelist_distribuidores.id,
        )
        self.assertEqual(partner.customer_type, 'distribuidores')
        self.assertEqual(
            partner.property_product_pricelist,
            self.pricelist_distribuidores,
        )

    def test_bulk_update_sets_mayorista_dormido_publico_pricelist(self):
        partner = self.env['res.partner'].create({
            'name': 'Bulk Dormant',
            'customer_type': 'mayorista',
        })
        self.env['res.partner'].with_user(self.pos_user).action_bulk_set_customer_type(
            partner.ids, 'mayorista_dormido', self.pricelist_publico.id,
        )
        self.assertEqual(partner.customer_type, 'mayorista_dormido')
        self.assertEqual(partner.property_product_pricelist, self.pricelist_publico)

    def test_bulk_update_type_without_pricelist_raises(self):
        partner = self.env['res.partner'].create({'name': 'No Pricelist Partner'})
        with self.assertRaises(UserError) as ctx:
            self.env['res.partner'].with_user(self.pos_user).action_bulk_set_customer_type(
                partner.ids, 'mayorista',
            )
        self.assertEqual(
            str(ctx.exception),
            'Seleccione la lista de precios que corresponde al tipo de cliente.',
        )

    def test_bulk_update_mismatched_pricelist_raises(self):
        partner = self.env['res.partner'].create({'name': 'Mismatch Partner'})
        with self.assertRaises(UserError) as ctx:
            self.env['res.partner'].with_user(self.pos_user).action_bulk_set_customer_type(
                partner.ids, 'mayorista', self.pricelist_publico.id,
            )
        self.assertEqual(
            str(ctx.exception),
            'La lista de precios no corresponde al tipo de cliente.',
        )

    def test_bulk_update_pricelist_only(self):
        partner = self.env['res.partner'].create({
            'name': 'Pricelist Only Partner',
            'customer_type': 'mayorista',
        })
        self.env['res.partner'].with_user(self.pos_user).action_bulk_set_customer_type(
            partner.ids, False, self.pricelist_distribuidores.id,
        )
        self.assertEqual(partner.customer_type, 'mayorista')
        self.assertEqual(
            partner.property_product_pricelist,
            self.pricelist_distribuidores,
        )

    def test_bulk_update_empty_partner_ids_raises(self):
        with self.assertRaises(UserError) as ctx:
            self.env['res.partner'].with_user(self.pos_user).action_bulk_set_customer_type(
                [], 'mayorista', self.pricelist_mayorista.id,
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
            'Seleccione un tipo de cliente o una lista de precios.',
        )

    def test_bulk_update_missing_required_pricelist_raises(self):
        partner = self.env['res.partner'].create({'name': 'Missing List Partner'})
        original = partner_mod.CUSTOMER_TYPE_PRICELIST_NAME['mayorista']
        partner_mod.CUSTOMER_TYPE_PRICELIST_NAME['mayorista'] = (
            'Lista inexistente XYZ 999'
        )
        try:
            with self.assertRaises(UserError) as ctx:
                self.env['res.partner'].with_user(self.pos_user).action_bulk_set_customer_type(
                    partner.ids, 'mayorista', self.pricelist_mayorista.id,
                )
            self.assertEqual(
                str(ctx.exception),
                'La lista de precios no corresponde al tipo de cliente.',
            )
        finally:
            partner_mod.CUSTOMER_TYPE_PRICELIST_NAME['mayorista'] = original

    def test_bulk_update_accepts_alternate_publico_pricelist(self):
        partner = self.env['res.partner'].create({
            'name': 'Duplicate Publico Partner',
        })
        alternate = self.env['product.pricelist'].create({
            'name': 'Lista de precios a Publico en General (MXN)',
            'company_id': False,
            'currency_id': self.env.company.currency_id.id,
        })
        self.env['res.partner'].with_user(self.pos_user).action_bulk_set_customer_type(
            partner.ids, 'publico_general', alternate.id,
        )
        self.assertEqual(partner.customer_type, 'publico_general')
        self.assertEqual(partner.property_product_pricelist, alternate)

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
