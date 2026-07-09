# -*- coding: utf-8 -*-
from odoo import api, fields, models


class VendorSheetMapping(models.Model):
    _name = 'vendor.sheet.mapping'
    _description = 'Mapeo de proveedor de hoja a proveedor de Odoo'
    _order = 'sheet_proveedor'

    sheet_proveedor = fields.Char(string='Proveedor en hoja', required=True, index=True)
    partner_id = fields.Many2one(
        'res.partner',
        string='Proveedor',
        ondelete='restrict',
        index=True,
    )
    classification_vendor_id = fields.Many2one(
        'product.classification.vendor',
        string='Proveedor de clasificación',
        ondelete='set null',
    )
    is_assigned = fields.Boolean(
        string='Asignado',
        compute='_compute_is_assigned',
        store=True,
    )

    @api.depends('partner_id')
    def _compute_is_assigned(self):
        for mapping in self:
            mapping.is_assigned = bool(mapping.partner_id)

    def _strip_assignment_warning(self, warning_message):
        if not warning_message:
            return False
        remaining = [
            line for line in warning_message.split('\n')
            if 'pendiente de asignación' not in line
        ]
        return '\n'.join(remaining) if remaining else False

    def _backfill_staging_invoices(self):
        """Link staged invoices when a sheet proveedor is assigned to a partner."""
        Invoice = self.env['vendor.sheet.invoice'].sudo()
        for mapping in self:
            if not mapping.partner_id or not mapping.sheet_proveedor:
                continue
            invoices = Invoice.search([
                ('proveedor', '=', mapping.sheet_proveedor),
                '|',
                ('partner_id', '=', False),
                ('partner_id', '!=', mapping.partner_id.id),
            ])
            for invoice in invoices:
                vals = {'partner_id': mapping.partner_id.id}
                cleared = mapping._strip_assignment_warning(invoice.warning_message)
                if cleared != invoice.warning_message:
                    vals['warning_message'] = cleared
                invoice.write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        records = super(VendorSheetMapping, self).create(vals_list)
        records.filtered('partner_id')._backfill_staging_invoices()
        return records

    def write(self, vals):
        res = super(VendorSheetMapping, self).write(vals)
        if 'partner_id' in vals:
            self._backfill_staging_invoices()
        return res

    _sql_constraints = [
        (
            'sheet_proveedor_uniq',
            'unique(sheet_proveedor)',
            'Este nombre de proveedor en hoja ya está mapeado.',
        ),
    ]
