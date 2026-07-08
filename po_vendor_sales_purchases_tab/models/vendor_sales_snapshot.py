# -*- coding: utf-8 -*-
from odoo import fields, models


class VendorSalesSnapshot(models.Model):
    _name = 'vendor.sales.snapshot'
    _description = 'Instantánea de ventas del proveedor por mes y departamento'
    _order = 'month desc, classification_department_id, id desc'

    partner_id = fields.Many2one(
        'res.partner',
        string='Proveedor',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Empresa',
        required=True,
        ondelete='cascade',
        index=True,
    )
    classification_department_id = fields.Many2one(
        'product.classification.department',
        string='Departamento',
        required=True,
        ondelete='restrict',
        index=True,
    )
    month = fields.Date(
        string='Mes',
        required=True,
        help='Primer día del mes calendario',
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Moneda',
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )
    amount_total = fields.Monetary(
        string='Monto total',
        currency_field='currency_id',
        help='Total de ventas con impuestos incluidos',
    )
    computed_at = fields.Datetime(
        string='Calculado el',
        index=True,
        help='Cuándo se escribió esta fila durante Sincronizar OC.',
    )

    _sql_constraints = [
        (
            'partner_company_dept_month_uniq',
            'unique(partner_id, company_id, classification_department_id, month)',
            'Ya existe una instantánea de ventas para este proveedor, empresa, departamento y mes.',
        ),
    ]
