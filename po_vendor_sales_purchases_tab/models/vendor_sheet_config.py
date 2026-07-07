# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

MONTH_SELECTION = [
    ('01', 'January'),
    ('02', 'February'),
    ('03', 'March'),
    ('04', 'April'),
    ('05', 'May'),
    ('06', 'June'),
    ('07', 'July'),
    ('08', 'August'),
    ('09', 'September'),
    ('10', 'October'),
    ('11', 'November'),
    ('12', 'December'),
]


class VendorSheetConfig(models.Model):
    _name = 'vendor.sheet.config'
    _description = 'Vendor Google Sheet Configuration'

    name = fields.Char(string='Name', default='Vendor Sheet Configuration', required=True)
    google_service_account_json = fields.Text(
        string='Google Service Account JSON',
        help='Service account credentials JSON for Google Sheets API access.',
    )
    sheet_tab_name = fields.Char(
        string='Sheet Tab Name',
        default='Pagos Proveedores',
        required=True,
        help='Exact name of the worksheet tab at the bottom of each monthly Google '
             'Spreadsheet (e.g. Pagos Proveedores).',
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
    @api.model
    def _year_selection(self):
        current = fields.Date.context_today(self).year
        return [(str(year), str(year)) for year in range(current - 2, current + 3)]

    year = fields.Selection(
        selection='_year_selection',
        string='Year',
        required=True,
        default=lambda self: str(fields.Date.context_today(self).year),
    )
    month = fields.Selection(
        selection=MONTH_SELECTION,
        string='Month',
        required=True,
        default=lambda self: fields.Date.context_today(self).strftime('%m'),
    )
    name = fields.Char(
        string='Month Key',
        compute='_compute_name',
        store=True,
        readonly=True,
        help='Internal YYYY-MM label used by sync, e.g. 2026-07',
        index=True,
    )
    spreadsheet_id = fields.Char(string='Spreadsheet ID')
    synced_once = fields.Boolean(string='Synced Once', default=False)
    last_sync = fields.Datetime(string='Last Sync')

    _sql_constraints = [
        (
            'config_month_uniq',
            'unique(config_id, year, month)',
            'This month is already configured.',
        ),
    ]

    @api.depends('year', 'month')
    def _compute_name(self):
        for record in self:
            if record.year and record.month:
                record.name = '%s-%s' % (record.year, record.month)
            else:
                record.name = False

    @api.constrains('year', 'month')
    def _check_year_month(self):
        for record in self:
            if record.year and (int(record.year) < 2000 or int(record.year) > 2100):
                raise ValidationError('Year must be between 2000 and 2100.')

    @api.model
    def _normalize_year_vals(self, vals):
        year = vals.get('year')
        if year is not None and year is not False:
            vals['year'] = str(int(year))
        return vals

    @api.model
    def _parse_name_vals(self, vals):
        """Support legacy/test creates that still pass name='YYYY-MM'."""
        name = vals.get('name')
        if name and ('year' not in vals or 'month' not in vals):
            parts = name.split('-')
            if len(parts) == 2 and len(parts[0]) == 4 and len(parts[1]) == 2:
                vals.setdefault('year', parts[0])
                vals.setdefault('month', parts[1])
        return self._normalize_year_vals(vals)

    @api.model_create_multi
    def create(self, vals_list):
        prepared = [self._parse_name_vals(dict(vals)) for vals in vals_list]
        return super(VendorSheetMonth, self).create(prepared)

    def write(self, vals):
        vals = self._parse_name_vals(dict(vals))
        return super(VendorSheetMonth, self).write(vals)

    def _auto_init(self):
        res = super(VendorSheetMonth, self)._auto_init()
        self.env.cr.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'vendor_sheet_month'
              AND column_name = 'year'
        """)
        if self.env.cr.fetchone():
            self.env.cr.execute("""
                UPDATE vendor_sheet_month
                SET year = split_part(name, '-', 1),
                    month = split_part(name, '-', 2)
                WHERE name IS NOT NULL
                  AND name ~ '^[0-9]{4}-[0-9]{2}$'
                  AND (year IS NULL OR month IS NULL OR month = '')
            """)
        return res
