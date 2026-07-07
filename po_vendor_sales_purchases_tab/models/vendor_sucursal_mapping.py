# -*- coding: utf-8 -*-
from odoo import fields, models


class VendorSucursalMapping(models.Model):
    _name = 'vendor.sucursal.mapping'
    _description = 'Sheet Sucursal to Company Mapping'
    _order = 'sucursal'

    sucursal = fields.Char(string='Sucursal', required=True, index=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        ondelete='restrict',
        index=True,
    )

    _sql_constraints = [
        (
            'sucursal_uniq',
            'unique(sucursal)',
            'This sucursal is already mapped to a company.',
        ),
    ]
