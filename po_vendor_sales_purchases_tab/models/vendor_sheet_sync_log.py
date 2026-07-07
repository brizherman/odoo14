# -*- coding: utf-8 -*-
from odoo import fields, models


class VendorSheetSyncLog(models.Model):
    _name = 'vendor.sheet.sync.log'
    _description = 'Vendor Sheet Sync Log'
    _order = 'sync_date desc, id desc'

    sync_date = fields.Datetime(
        string='Sync Date',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='User',
        required=True,
        default=lambda self: self.env.user,
        ondelete='restrict',
        index=True,
    )
    rows_created = fields.Integer(string='Rows Created', default=0)
    rows_updated = fields.Integer(string='Rows Updated', default=0)
    warnings_count = fields.Integer(string='Warnings', default=0)
    duration_seconds = fields.Float(string='Duration (seconds)')
    warning_details = fields.Text(string='Warning Details')
    state = fields.Selection(
        selection=[
            ('success', 'Success'),
            ('error', 'Error'),
        ],
        string='State',
        required=True,
        default='success',
        index=True,
    )
