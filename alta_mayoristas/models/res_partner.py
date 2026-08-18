# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods
"""Extend res.partner with POS/backend customer type classification."""
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

SALE_ORDER_STATES = ('sale', 'done')
POS_ORDER_STATES = ('paid', 'done', 'invoiced')
VALID_CUSTOMER_TYPES = ('mayorista', 'publico_general')


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
        totals = self._read_sales_totals_by_partner(self.ids)
        for partner in self:
            partner.total_sales_amount = totals.get(partner.id, 0.0)

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
    def _recompute_total_sales_amount_for_partners(self, partner_ids):
        partners = self.browse(partner_ids).exists()
        if partners:
            self.env.add_to_compute(self._fields['total_sales_amount'], partners)

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
