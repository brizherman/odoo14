# -*- coding: utf-8 -*-
from odoo import fields, models


class VendorSheetMapping(models.Model):
    _name = 'vendor.sheet.mapping'
    _description = 'Sheet Proveedor to Vendor Mapping'
    _order = 'sheet_proveedor'

    sheet_proveedor = fields.Char(string='Sheet Proveedor', required=True, index=True)
    partner_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        required=True,
        ondelete='restrict',
        index=True,
    )
    classification_vendor_id = fields.Many2one(
        'product.classification.vendor',
        string='Classification Vendor',
        ondelete='set null',
    )

    _sql_constraints = [
        (
            'sheet_proveedor_uniq',
            'unique(sheet_proveedor)',
            'This sheet proveedor name is already mapped.',
        ),
    ]
