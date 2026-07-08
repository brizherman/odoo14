# -*- coding: utf-8 -*-
from odoo import fields, models


class VendorSucursalMapping(models.Model):
    _name = 'vendor.sucursal.mapping'
    _description = 'Mapeo de sucursal de hoja a empresa de Odoo'
    _order = 'sucursal'

    sucursal = fields.Char(string='Sucursal', required=True, index=True)
    company_id = fields.Many2one(
        'res.company',
        string='Empresa',
        required=True,
        ondelete='restrict',
        index=True,
    )

    _sql_constraints = [
        (
            'sucursal_uniq',
            'unique(sucursal)',
            'Esta sucursal ya está mapeada a una empresa.',
        ),
    ]
