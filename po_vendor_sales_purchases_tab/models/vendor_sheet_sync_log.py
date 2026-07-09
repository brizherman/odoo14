# -*- coding: utf-8 -*-
from odoo import fields, models


class VendorSheetSyncLog(models.Model):
    _name = 'vendor.sheet.sync.log'
    _description = 'Registro de sincronización de hoja de proveedor'
    _order = 'sync_date desc, id desc'

    sync_date = fields.Datetime(
        string='Fecha de sincronización',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Usuario',
        required=True,
        default=lambda self: self.env.user,
        ondelete='restrict',
        index=True,
    )
    rows_created = fields.Integer(string='Filas creadas', default=0)
    rows_updated = fields.Integer(string='Filas actualizadas', default=0)
    mappings_created = fields.Integer(string='Mapeos creados', default=0)
    warnings_count = fields.Integer(string='Advertencias', default=0)
    duration_seconds = fields.Float(string='Duración (segundos)')
    warning_details = fields.Text(string='Detalles de advertencias')
    state = fields.Selection(
        selection=[
            ('success', 'Éxito'),
            ('error', 'Error'),
        ],
        string='Estado',
        required=True,
        default='success',
        index=True,
    )
    sync_type = fields.Selection(
        selection=[
            ('global', 'Global'),
            ('po', 'OC'),
        ],
        string='Tipo de sincronización',
        required=True,
        default='global',
        index=True,
    )
    po_id = fields.Many2one(
        'purchase.order',
        string='Orden de compra',
        ondelete='set null',
        index=True,
    )
