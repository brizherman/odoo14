# -*- coding: utf-8 -*-
from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    compra_minima = fields.Float(
        string='Compra Minima',
        digits=(16, 2),
        default=0.0,
    )
