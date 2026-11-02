# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods
"""Price-list slots shown by the price lookup. These are not wholesale slots."""
from odoo import fields, models


class ResCompany(models.Model):
    """Three optional price lists for the counter lookup."""

    _inherit = 'res.company'

    price_lookup_publico_general_pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Público General',
        help='Lista que la consulta muestra como Público General. '
             'Vacío oculta esa etiqueta. No cambia la lista del ticket.',
    )
    price_lookup_mayorista_pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Mayorista',
        help='Lista que la consulta muestra como Mayorista. '
             'Vacío oculta esa etiqueta. No cambia la lista del ticket.',
    )
    price_lookup_distribuidores_pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Distribuidores',
        help='Lista que la consulta muestra como Distribuidores. '
             'Vacío oculta esa etiqueta. No cambia la lista del ticket.',
    )
