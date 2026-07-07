# -*- coding: utf-8 -*-
from odoo import fields, models


class VendorSheetInvoice(models.Model):
    _name = 'vendor.sheet.invoice'
    _description = 'Vendor Sheet Invoice (Purchases Staging)'
    _order = 'fecha desc, no_factura, id desc'

    sucursal = fields.Char(string='Sucursal', index=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        index=True,
        ondelete='set null',
    )
    proveedor = fields.Char(string='Proveedor (Sheet)')
    partner_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        index=True,
        ondelete='set null',
    )
    no_factura = fields.Char(string='No. Factura', required=True, index=True)
    fecha = fields.Date(string='Fecha', index=True)
    vence = fields.Date(string='Vence')
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )
    total_factura = fields.Monetary(string='Total de Factura', currency_field='currency_id')
    pagado = fields.Boolean(string='Pagado', default=False)
    fecha_pago = fields.Date(string='Fecha de Pago')
    monto_pago_grupo = fields.Monetary(
        string='Monto Pago Grupo',
        currency_field='currency_id',
    )
    facturas_en_grupo = fields.Integer(string='Facturas en Grupo')
    source_month = fields.Char(string='Source Month', help='e.g. 2026-07')
    sheet_row = fields.Integer(string='Sheet Row')
    block_valid = fields.Boolean(string='Block Valid', default=True)
    warning_message = fields.Text(string='Warning')
    last_sync = fields.Datetime(string='Last Sync')

    _sql_constraints = [
        (
            'sucursal_no_factura_uniq',
            'unique(sucursal, no_factura)',
            'Invoice number must be unique per sucursal.',
        ),
    ]
