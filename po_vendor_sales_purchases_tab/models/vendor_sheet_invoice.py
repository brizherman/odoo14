# -*- coding: utf-8 -*-
from odoo import fields, models


class VendorSheetInvoice(models.Model):
    _name = 'vendor.sheet.invoice'
    _description = 'Factura de hoja de proveedor (staging de compras)'
    _order = 'fecha desc, no_factura, id desc'

    sucursal = fields.Char(string='Sucursal', index=True)
    company_id = fields.Many2one(
        'res.company',
        string='Empresa',
        index=True,
        ondelete='set null',
    )
    proveedor = fields.Char(string='Proveedor (hoja)')
    partner_id = fields.Many2one(
        'res.partner',
        string='Proveedor',
        index=True,
        ondelete='set null',
    )
    no_factura = fields.Char(string='No. Factura', required=True, index=True)
    fecha = fields.Date(string='Fecha', index=True)
    vence = fields.Date(string='Vence')
    currency_id = fields.Many2one(
        'res.currency',
        string='Moneda',
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )
    total_factura = fields.Monetary(string='Total de Factura', currency_field='currency_id')
    pagado = fields.Boolean(string='Pagado', default=False)
    fecha_pago = fields.Date(string='Fecha de Pago')
    monto_pago_grupo = fields.Monetary(
        string='Monto pago grupo',
        currency_field='currency_id',
    )
    facturas_en_grupo = fields.Integer(string='Facturas en grupo')
    source_month = fields.Char(string='Mes de origen', help='p. ej. 2026-07')
    sheet_row = fields.Integer(string='Fila de hoja')
    block_valid = fields.Boolean(string='Bloque válido', default=True)
    warning_message = fields.Text(string='Advertencia')
    last_sync = fields.Datetime(string='Última sincronización')

    _sql_constraints = [
        (
            'sucursal_no_factura_uniq',
            'unique(sucursal, no_factura)',
            'El número de factura debe ser único por sucursal.',
        ),
    ]
