# -*- coding: utf-8 -*-
from odoo import api, fields, models


class VendorSheetMapping(models.Model):
    _name = 'vendor.sheet.mapping'
    _description = 'Mapeo de proveedor de hoja a proveedor de Odoo'
    _order = 'sheet_proveedor'

    sheet_proveedor = fields.Char(string='Proveedor en hoja', required=True, index=True)
    partner_id = fields.Many2one(
        'res.partner',
        string='Proveedor',
        ondelete='restrict',
        index=True,
    )
    classification_vendor_id = fields.Many2one(
        'product.classification.vendor',
        string='Proveedor de clasificación',
        ondelete='set null',
    )
    is_assigned = fields.Boolean(
        string='Asignado',
        compute='_compute_is_assigned',
        store=True,
    )

    @api.depends('partner_id')
    def _compute_is_assigned(self):
        for mapping in self:
            mapping.is_assigned = bool(mapping.partner_id)

    _sql_constraints = [
        (
            'sheet_proveedor_uniq',
            'unique(sheet_proveedor)',
            'Este nombre de proveedor en hoja ya está mapeado.',
        ),
    ]
