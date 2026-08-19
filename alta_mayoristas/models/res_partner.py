# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods
"""Extend res.partner with POS/backend customer type classification."""
from collections import defaultdict
from datetime import date, datetime
from unicodedata import category, normalize as unicode_normalize

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

SALE_ORDER_STATES = ('sale', 'done')
POS_ORDER_STATES = ('paid', 'done', 'invoiced')
VALID_CUSTOMER_TYPES = (
    'mayorista',
    'publico_general',
    'distribuidores',
    'mayorista_dormido',
)
PRICELIST_NAME_PUBLICO = 'Lista de precios a Publico en General'
CUSTOMER_TYPE_PRICELIST_NAME = {
    'mayorista': 'Lista de precios de Mayorista',
    'publico_general': PRICELIST_NAME_PUBLICO,
    'distribuidores': 'Super Precios a Distribuidores',
    'mayorista_dormido': PRICELIST_NAME_PUBLICO,
}


class ResPartner(models.Model):
    """Add mayorista / público general customer type and sales totals."""

    _inherit = 'res.partner'

    customer_type = fields.Selection(
        selection=[
            ('mayorista', _('Mayorista')),
            ('publico_general', _('Público General')),
            ('distribuidores', _('Distribuidores')),
            ('mayorista_dormido', _('Mayorista dormido')),
        ],
        default=False,
    )
    total_sales_amount = fields.Float(
        compute='_compute_total_sales_amount',
        store=True,
        digits='Product Price',
    )
    primary_company_id = fields.Many2one(
        'res.company',
        string='Sucursal',
        index=True,
        readonly=True,
        copy=False,
    )
    phone_display = fields.Char(
        string='Phone',
        compute='_compute_phone_display',
    )
    last_pos_sale_date = fields.Date(
        string='Last POS Sale',
        compute='_compute_last_sale_dates',
    )
    last_sale_order_date = fields.Date(
        string='Last Sales Order',
        compute='_compute_last_sale_dates',
    )
    sales_last_6_months = fields.Float(
        string='Last 6 Months Sales',
        compute='_compute_sales_last_6_months',
        store=True,
        digits='Product Price',
    )
    sales_last_6_months_avg = fields.Float(
        string='6-Month Monthly Average',
        compute='_compute_sales_last_6_months',
        store=True,
        digits='Product Price',
    )

    @api.depends('phone', 'mobile')
    def _compute_phone_display(self):
        for partner in self:
            partner.phone_display = partner.phone or partner.mobile or ''

    @api.depends()
    def _compute_total_sales_amount(self):
        totals = self._read_sales_totals_by_partner(self.ids)
        for partner in self:
            partner.total_sales_amount = totals.get(partner.id, 0.0)

    @api.depends()
    def _compute_last_sale_dates(self):
        pos_dates = self._read_max_order_date_by_partner(
            'pos.order', POS_ORDER_STATES, self.ids,
        )
        so_dates = self._read_max_order_date_by_partner(
            'sale.order', SALE_ORDER_STATES, self.ids,
        )
        for partner in self:
            partner.last_pos_sale_date = pos_dates.get(partner.id, False)
            partner.last_sale_order_date = so_dates.get(partner.id, False)

    @api.depends()
    def _compute_sales_last_6_months(self):
        cutoff = fields.Datetime.now() - relativedelta(months=6)
        totals = self._read_sales_totals_by_partner_since(self.ids, cutoff)
        for partner in self:
            amount = totals.get(partner.id, 0.0)
            partner.sales_last_6_months = amount
            partner.sales_last_6_months_avg = amount / 6.0

    def _max_datetime_to_date(self, value):
        """Convert an order datetime (UTC) to a calendar date in user TZ."""
        if not value:
            return False
        if isinstance(value, datetime):
            dt_value = value
        elif isinstance(value, date):
            return value
        else:
            dt_value = fields.Datetime.from_string(value)
            if not dt_value:
                return False
        local_dt = fields.Datetime.context_timestamp(self, dt_value)
        return local_dt.date()

    @api.model
    def _read_max_order_date_by_partner(self, model_name, states, partner_ids):
        """Return partner_id -> max date_order as Date for counted orders.

        Dates are global (all companies). sudo() is required so company
        record rules on pos.order / sale.order do not hide other sucursales.
        """
        if not partner_ids or model_name not in self.env:
            return {}
        groups = self.env[model_name].sudo().read_group(
            [('partner_id', 'in', partner_ids), ('state', 'in', list(states))],
            ['date_order:max'],
            ['partner_id'],
            lazy=False,
        )
        dates = {}
        for group in groups:
            partner_ref = group.get('partner_id')
            if not partner_ref:
                continue
            dates[partner_ref[0]] = self._max_datetime_to_date(
                group.get('date_order'),
            )
        return dates

    @api.model
    def _read_sales_totals_by_partner(self, partner_ids):
        """Aggregate SO + POS amount_total grouped by order partner_id."""
        if not partner_ids:
            return {}
        totals = defaultdict(float)
        order_specs = (
            ('pos.order', POS_ORDER_STATES),
            ('sale.order', SALE_ORDER_STATES),
        )
        for model_name, states in order_specs:
            if model_name not in self.env:
                continue
            groups = self.env[model_name].read_group(
                [('partner_id', 'in', partner_ids), ('state', 'in', list(states))],
                ['amount_total:sum'],
                ['partner_id'],
                lazy=False,
            )
            for group in groups:
                partner_ref = group.get('partner_id')
                if partner_ref:
                    totals[partner_ref[0]] += group.get('amount_total') or 0.0
        return dict(totals)

    @api.model
    def _read_sales_totals_by_partner_since(self, partner_ids, cutoff):
        """Aggregate SO + POS amount_total since cutoff, all companies.

        sudo() is required so company record rules on pos.order / sale.order
        do not hide other sucursales. Exposes aggregates only, not orders.
        """
        if not partner_ids:
            return {}
        totals = defaultdict(float)
        order_specs = (
            ('pos.order', POS_ORDER_STATES),
            ('sale.order', SALE_ORDER_STATES),
        )
        extra_domain = [('date_order', '>=', cutoff)]
        for model_name, states in order_specs:
            if model_name not in self.env:
                continue
            domain = [
                ('partner_id', 'in', partner_ids),
                ('state', 'in', list(states)),
            ] + extra_domain
            groups = self.env[model_name].sudo().read_group(
                domain,
                ['amount_total:sum'],
                ['partner_id'],
                lazy=False,
            )
            for group in groups:
                partner_ref = group.get('partner_id')
                if partner_ref:
                    totals[partner_ref[0]] += group.get('amount_total') or 0.0
        return dict(totals)

    @api.model
    def _recompute_total_sales_amount_for_partners(self, partner_ids):
        partners = self.browse(partner_ids).exists()
        if partners:
            self.env.add_to_compute(self._fields['total_sales_amount'], partners)
            self.env.add_to_compute(self._fields['sales_last_6_months'], partners)
            self.env.add_to_compute(self._fields['sales_last_6_months_avg'], partners)

    @api.model
    def _cron_recompute_sales_last_6_months(self):
        """Daily refresh of rolling 6-month totals (not called on upgrade)."""
        batch_size = 500
        partner_ids = self.search([('primary_company_id', '!=', False)]).ids
        for index in range(0, len(partner_ids), batch_size):
            self._recompute_total_sales_amount_for_partners(
                partner_ids[index:index + batch_size],
            )

    @api.model
    def _recompute_all_total_sales_amounts(self):
        """Optional batch recompute of sales totals (not called on upgrade)."""
        partner_ids = self.search([]).ids
        self._recompute_total_sales_amount_for_partners(partner_ids)

    @api.model
    def _sql_backfill_primary_company(self):
        """One-time fill for empty sucursal: highest POS+SO amount, latest sale on ties.

        Does not overwrite an existing primary_company_id.
        """
        self.env.cr.execute("""
            UPDATE res_partner AS partner
            SET primary_company_id = ranked.company_id
            FROM (
                SELECT DISTINCT ON (agg.partner_id)
                       agg.partner_id,
                       agg.company_id
                FROM (
                    SELECT
                        orders.partner_id,
                        orders.company_id,
                        SUM(orders.amount_total) AS amount,
                        MAX(orders.date_order) AS latest
                    FROM (
                        SELECT
                            partner_id,
                            company_id,
                            amount_total,
                            date_order
                        FROM pos_order
                        WHERE state IN ('paid', 'done', 'invoiced')
                          AND partner_id IS NOT NULL
                          AND company_id IS NOT NULL
                        UNION ALL
                        SELECT
                            partner_id,
                            company_id,
                            amount_total,
                            date_order
                        FROM sale_order
                        WHERE state IN ('sale', 'done')
                          AND partner_id IS NOT NULL
                          AND company_id IS NOT NULL
                    ) AS orders
                    GROUP BY orders.partner_id, orders.company_id
                ) AS agg
                ORDER BY agg.partner_id, agg.amount DESC, agg.latest DESC
            ) AS ranked
            WHERE partner.id = ranked.partner_id
              AND partner.primary_company_id IS NULL
        """)

    @api.model
    def create_from_ui(self, partner):
        """Mark new POS customers as customers and assign sucursal once."""
        partner = dict(partner)
        partner_id = partner.get('id')
        if not partner_id:
            if not partner.get('customer_rank'):
                partner['customer_rank'] = 1
            company_id = partner.get('primary_company_id') or self.env.company.id
            partner['primary_company_id'] = int(company_id)
        else:
            partner.pop('primary_company_id', None)
        return super().create_from_ui(partner)

    def write(self, vals):
        """Keep an already assigned sucursal (POS create or psql backfill)."""
        if 'primary_company_id' not in vals:
            return super().write(vals)
        if self.env.context.get('alta_mayoristas_backfill'):
            return super().write(vals)
        locked = self.filtered('primary_company_id')
        unlocked = self - locked
        result = True
        if locked:
            locked_vals = dict(vals)
            locked_vals.pop('primary_company_id')
            if locked_vals:
                result = super(ResPartner, locked).write(locked_vals)
        if unlocked:
            result = super(ResPartner, unlocked).write(vals)
        return result

    @api.model
    def _normalize_pricelist_name(self, name):
        """Compare names ignoring case, accents, and a trailing (MXN)."""
        normalized = (name or '').strip()
        if normalized.endswith(' (MXN)'):
            normalized = normalized[:-6].strip()
        decomposed = unicode_normalize('NFD', normalized)
        without_marks = ''.join(
            char for char in decomposed if category(char) != 'Mn'
        )
        return without_marks.casefold()

    @api.model
    def _pricelist_name_matches(self, actual_name, required_name):
        """Exact normalized match; público lists also match the word publico."""
        actual = self._normalize_pricelist_name(actual_name)
        required = self._normalize_pricelist_name(required_name)
        if actual == required:
            return True
        if 'publico' in required.split():
            return 'publico' in actual.split()
        return False

    @api.model
    def _pricelist_matches_customer_type(self, pricelist, customer_type):
        """True when the selected pricelist name is valid for customer_type."""
        required_name = CUSTOMER_TYPE_PRICELIST_NAME.get(customer_type)
        if not required_name or not pricelist:
            return False
        return self._pricelist_name_matches(pricelist.name, required_name)

    @api.model
    def action_bulk_set_customer_type(
            self, partner_ids, customer_type=False, pricelist_id=False):
        """Bulk-assign customer_type and/or pricelist from the classifier list."""
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(
                _('You do not have permission to classify customers.')
            )
        if not partner_ids:
            raise UserError(_('Seleccione al menos un contacto.'))
        pricelist_id = int(pricelist_id) if pricelist_id else False
        if customer_type:
            if customer_type not in VALID_CUSTOMER_TYPES:
                raise UserError(_(
                    'Seleccione Mayorista, Público General, Distribuidores '
                    'o Mayorista dormido.'
                ))
            if not pricelist_id:
                raise UserError(_(
                    'Seleccione la lista de precios que corresponde al tipo de cliente.'
                ))
            # sudo: dropdown may show a shared/other-company list the POS user
            # can read via search_read but not browse under company record rules.
            pricelist = self.env['product.pricelist'].sudo().browse(
                pricelist_id
            ).exists()
            if not pricelist:
                raise UserError(_('Seleccione una lista de precios válida.'))
            if not self._pricelist_matches_customer_type(pricelist, customer_type):
                raise UserError(_(
                    'La lista de precios no corresponde al tipo de cliente.'
                ))
            vals = {
                'customer_type': customer_type,
                'property_product_pricelist': pricelist.id,
            }
        elif pricelist_id:
            pricelist = self.env['product.pricelist'].browse(pricelist_id).exists()
            if not pricelist:
                raise UserError(_('Seleccione una lista de precios válida.'))
            vals = {'property_product_pricelist': pricelist.id}
        else:
            raise UserError(_(
                'Seleccione un tipo de cliente o una lista de precios.'
            ))
        partners = self.browse(partner_ids).exists()
        partners.write(vals)
        count = len(partners)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                # pylint: disable=translation-not-lazy
                'message': _('Se actualizaron %s contacto(s).') % count,
                'type': 'success',
                'sticky': False,
            },
        }
