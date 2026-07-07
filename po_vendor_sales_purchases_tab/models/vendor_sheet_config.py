# -*- coding: utf-8 -*-
from odoo import api, fields, models


class VendorSheetConfig(models.Model):
    _name = 'vendor.sheet.config'
    _description = 'Vendor Google Sheet Configuration'

    name = fields.Char(string='Name', default='Vendor Sheet Configuration', required=True)
    google_service_account_json = fields.Text(
        string='Google Service Account JSON',
        help='Service account credentials JSON for Google Sheets API access.',
    )
    sheet_month_ids = fields.One2many(
        'vendor.sheet.month',
        'config_id',
        string='Monthly Workbooks',
    )

    @api.model
    def get_singleton(self):
        """Return the single configuration record, creating it if needed."""
        config = self.search([], limit=1)
        if not config:
            config = self.create({'name': 'Vendor Sheet Configuration'})
        return config


class VendorSheetMonth(models.Model):
    _name = 'vendor.sheet.month'
    _description = 'Vendor Sheet Monthly Workbook'
    _order = 'name desc'

    config_id = fields.Many2one(
        'vendor.sheet.config',
        string='Configuration',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char(
        string='Month',
        required=True,
        help='Calendar month label, e.g. 2026-07',
        index=True,
    )
    spreadsheet_id = fields.Char(string='Spreadsheet ID')
    synced_once = fields.Boolean(string='Synced Once', default=False)
    last_sync = fields.Datetime(string='Last Sync')
