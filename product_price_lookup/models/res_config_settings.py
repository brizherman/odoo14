# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods
"""Point of Sale settings for the price lookup slots."""
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Expose the active company's lookup slots on Point of Sale settings."""

    _inherit = 'res.config.settings'

    price_lookup_currency_id = fields.Many2one(
        related='company_id.currency_id',
        string='Moneda',
    )
    price_lookup_publico_general_pricelist_id = fields.Many2one(
        related='company_id.price_lookup_publico_general_pricelist_id',
        string='Público General',
        readonly=False,
    )
    price_lookup_mayorista_pricelist_id = fields.Many2one(
        related='company_id.price_lookup_mayorista_pricelist_id',
        string='Mayorista',
        readonly=False,
    )
    price_lookup_distribuidores_pricelist_id = fields.Many2one(
        related='company_id.price_lookup_distribuidores_pricelist_id',
        string='Distribuidores',
        readonly=False,
    )
