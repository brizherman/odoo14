# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods,protected-access
"""Extend res.partner with POS/backend customer type classification."""
from collections import defaultdict
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare, float_is_zero

SALE_ORDER_STATES = ('sale', 'done')
POS_ORDER_STATES = ('paid', 'done', 'invoiced')
VALID_CUSTOMER_TYPES = ('mayorista', 'publico_general')
_AMOUNT_PREC = 2
_DATETIME_MIN = datetime.min


class ResPartner(models.Model):
    """Add mayorista / público general customer type and sales totals."""

    _inherit = 'res.partner'

    customer_type = fields.Selection(
        selection=[
            ('mayorista', _('Mayorista')),
            ('publico_general', _('Público General')),
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
        compute='_compute_primary_company_id',
        store=True,
        index=True,
    )
    phone_display = fields.Char(
        string='Phone',
        compute='_compute_phone_display',
    )

    @api.depends('phone', 'mobile')
    def _compute_phone_display(self):
        for partner in self:
            partner.phone_display = partner.phone or partner.mobile or ''

    @api.depends()
    def _compute_total_sales_amount(self):
        totals = self.sudo()._read_sales_totals_by_partner(self.ids)
        for partner in self:
            partner.total_sales_amount = totals.get(partner.id, 0.0)

    @api.depends()
    def _compute_primary_company_id(self):
        mapping = self.sudo()._read_primary_company_by_partner(self.ids)
        for partner in self:
            partner.primary_company_id = mapping.get(partner.id) or False

    @api.model
    def _to_order_datetime(self, value):
        if not value:
            return _DATETIME_MIN
        if isinstance(value, datetime):
            return value.replace(tzinfo=None) if value.tzinfo else value
        return fields.Datetime.to_datetime(value) or _DATETIME_MIN

    @api.model
    def _select_primary_company_id(self, company_stats):
        """Pick company with highest amount; latest sale wins ties.

        ``company_stats`` maps company id to ``{'amount': float, 'latest': datetime}``.
        """
        best_company = False
        best_amount = 0.0
        best_latest = _DATETIME_MIN
        for company_id, data in company_stats.items():
            if not company_id:
                continue
            amount = data.get('amount') or 0.0
            latest = data.get('latest') or _DATETIME_MIN
            amount_cmp = float_compare(amount, best_amount, precision_digits=_AMOUNT_PREC)
            if amount_cmp > 0 or (
                amount_cmp == 0
                and not float_is_zero(amount, precision_digits=_AMOUNT_PREC)
                and latest > best_latest
            ):
                best_company = company_id
                best_amount = amount
                best_latest = latest
        return best_company

    @api.model
    def _read_sales_by_partner_company(self, partner_ids):
        """Sum POS + SO amounts and latest date_order per partner/company."""
        stats = defaultdict(lambda: defaultdict(lambda: {
            'amount': 0.0,
            'latest': _DATETIME_MIN,
        }))
        if not partner_ids:
            return stats
        order_specs = (
            ('pos.order', POS_ORDER_STATES),
            ('sale.order', SALE_ORDER_STATES),
        )
        for model_name, states in order_specs:
            if model_name not in self.env:
                continue
            groups = self.env[model_name].read_group(
                [
                    ('partner_id', 'in', partner_ids),
                    ('state', 'in', list(states)),
                    ('company_id', '!=', False),
                ],
                ['amount_total:sum', 'date_order:max'],
                ['partner_id', 'company_id'],
                lazy=False,
            )
            for group in groups:
                partner_ref = group.get('partner_id')
                company_ref = group.get('company_id')
                if not partner_ref or not company_ref:
                    continue
                partner_id = partner_ref[0]
                company_id = company_ref[0]
                bucket = stats[partner_id][company_id]
                bucket['amount'] += group.get('amount_total') or 0.0
                latest = self._to_order_datetime(group.get('date_order'))
                if latest > bucket['latest']:
                    bucket['latest'] = latest
        return stats

    @api.model
    def _read_primary_company_by_partner(self, partner_ids):
        stats = self._read_sales_by_partner_company(partner_ids)
        return {
            partner_id: self._select_primary_company_id(company_stats)
            for partner_id, company_stats in stats.items()
        }

    @api.model
    def _read_sales_totals_by_partner(self, partner_ids):
        """Aggregate SO + POS amount_total grouped by order partner_id."""
        totals = {}
        for partner_id, company_stats in self._read_sales_by_partner_company(
            partner_ids
        ).items():
            totals[partner_id] = sum(
                data.get('amount') or 0.0 for data in company_stats.values()
            )
        return totals

    @api.model
    def _recompute_total_sales_amount_for_partners(self, partner_ids):
        partners = self.browse(partner_ids).exists()
        if partners:
            self.env.add_to_compute(self._fields['total_sales_amount'], partners)
            self.env.add_to_compute(self._fields['primary_company_id'], partners)

    @api.model
    def _recompute_all_total_sales_amounts(self):
        """Batch recompute after module install or upgrade."""
        partner_ids = self.search([]).ids
        self._recompute_total_sales_amount_for_partners(partner_ids)

    @api.model
    def create_from_ui(self, partner):
        """Mark new POS customers so they appear in Customers (customer_rank > 0)."""
        if not partner.get('id') and not partner.get('customer_rank'):
            partner = dict(partner, customer_rank=1)
        return super().create_from_ui(partner)

    @api.model
    def action_bulk_set_customer_type(self, partner_ids, customer_type):
        """Bulk-assign customer_type from the classifier list view."""
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(
                _('You do not have permission to classify customers.')
            )
        if not partner_ids:
            raise UserError(_('Seleccione al menos un contacto.'))
        if customer_type not in VALID_CUSTOMER_TYPES:
            raise UserError(_('Seleccione Mayorista o Público General.'))
        partners = self.browse(partner_ids).exists()
        partners.write({'customer_type': customer_type})
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
