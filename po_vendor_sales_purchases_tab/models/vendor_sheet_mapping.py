# -*- coding: utf-8 -*-
from odoo import fields, models


class VendorSheetMapping(models.Model):
    _name = 'vendor.sheet.mapping'
    _description = 'Mapeo de proveedor de hoja a proveedor de Odoo'
    _order = 'sheet_proveedor'

    sheet_proveedor = fields.Char(string='Proveedor en hoja', required=True, index=True)
    partner_id = fields.Many2one(
        'res.partner',
        string='Proveedor',
        required=True,
        ondelete='restrict',
        index=True,
    )
    classification_vendor_id = fields.Many2one(
        'product.classification.vendor',
        string='Proveedor de clasificación',
        ondelete='set null',
    )

    _sql_constraints = [
        (
            'sheet_proveedor_uniq',
            'unique(sheet_proveedor)',
            'Este nombre de proveedor en hoja ya está mapeado.',
        ),
    ]
