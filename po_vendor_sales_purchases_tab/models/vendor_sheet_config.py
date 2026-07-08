# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

MONTH_SELECTION = [
    ('01', 'Enero'),
    ('02', 'Febrero'),
    ('03', 'Marzo'),
    ('04', 'Abril'),
    ('05', 'Mayo'),
    ('06', 'Junio'),
    ('07', 'Julio'),
    ('08', 'Agosto'),
    ('09', 'Septiembre'),
    ('10', 'Octubre'),
    ('11', 'Noviembre'),
    ('12', 'Diciembre'),
]


class VendorSheetConfig(models.Model):
    _name = 'vendor.sheet.config'
    _description = 'Configuración de hoja de Google del proveedor'

    name = fields.Char(
        string='Nombre',
        default='Configuración de hoja de proveedor',
        required=True,
    )
    google_service_account_json = fields.Text(
        string='JSON de cuenta de servicio de Google',
        help='Credenciales JSON de la cuenta de servicio para acceso a la API de Google Sheets.',
    )
    sheet_tab_name = fields.Char(
        string='Nombre de pestaña de hoja',
        default='Pagos Proveedores',
        required=True,
        help='Nombre exacto de la pestaña de la hoja de cálculo en cada libro mensual de Google '
             '(p. ej. Pagos Proveedores).',
    )
    sheet_month_ids = fields.One2many(
        'vendor.sheet.month',
        'config_id',
        string='Libros de trabajo mensuales',
    )

    @api.model
    def get_singleton(self):
        """Return the single configuration record, creating it if needed."""
        config = self.search([], limit=1)
        if not config:
            config = self.create({'name': 'Configuración de hoja de proveedor'})
        return config


class VendorSheetMonth(models.Model):
    _name = 'vendor.sheet.month'
    _description = 'Libro de trabajo mensual de hoja de proveedor'
    _order = 'name desc'

    config_id = fields.Many2one(
        'vendor.sheet.config',
        string='Configuración',
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
        string='Año',
        required=True,
        default=lambda self: str(fields.Date.context_today(self).year),
    )
    month = fields.Selection(
        selection=MONTH_SELECTION,
        string='Mes',
        required=True,
        default=lambda self: fields.Date.context_today(self).strftime('%m'),
    )
    name = fields.Char(
        string='Clave de mes',
        compute='_compute_name',
        store=True,
        readonly=True,
        help='Etiqueta interna AAAA-MM usada por la sincronización, p. ej. 2026-07',
        index=True,
    )
    spreadsheet_id = fields.Char(string='ID de hoja de cálculo')
    synced_once = fields.Boolean(string='Sincronizado una vez', default=False)
    last_sync = fields.Datetime(string='Última sincronización')

    _sql_constraints = [
        (
            'config_month_uniq',
            'unique(config_id, year, month)',
            'Este mes ya está configurado.',
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
                raise ValidationError('El año debe estar entre 2000 y 2100.')

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
