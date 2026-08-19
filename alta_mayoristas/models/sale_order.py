# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods,protected-access,duplicate-code
"""Recompute partner sales totals when sale orders change."""
from odoo import api, models

from .res_partner import SALE_ORDER_STATES

_SALES_RECOMPUTE_FIELDS = frozenset({
    'state', 'amount_total', 'partner_id', 'company_id', 'date_order',
})
_COUNTED_SALE_STATES = frozenset(SALE_ORDER_STATES)


class SaleOrder(models.Model):
    """Trigger partner total_sales_amount refresh on sale order changes."""

    _inherit = 'sale.order'

    def _trigger_partner_sales_recompute(self, partner_ids):
        partner_ids = list(set(partner_ids))
        if partner_ids:
            self.env['res.partner']._recompute_total_sales_amount_for_partners(partner_ids)

    def write(self, vals):
        """Refresh partner totals when relevant order fields change."""
        partners_before = []
        if _SALES_RECOMPUTE_FIELDS & set(vals):
            partners_before = self.mapped('partner_id').ids
        res = super().write(vals)
        if _SALES_RECOMPUTE_FIELDS & set(vals):
            partners_after = self.mapped('partner_id').ids
            self._trigger_partner_sales_recompute(partners_before + partners_after)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        """Refresh partner totals for new confirmed sale orders."""
        orders = super().create(vals_list)
        counted = orders.filtered(lambda o: o.state in _COUNTED_SALE_STATES)
        if counted:
            self._trigger_partner_sales_recompute(counted.mapped('partner_id').ids)
        return orders

    def unlink(self):
        """Refresh partner totals after deleting counted sale orders."""
        partner_ids = self.filtered(
            lambda o: o.state in _COUNTED_SALE_STATES
        ).mapped('partner_id').ids
        res = super().unlink()
        self._trigger_partner_sales_recompute(partner_ids)
        return res
