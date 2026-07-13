# -*- coding: utf-8 -*-
import base64
import csv
import io
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.sat_cfdi_received.models.sat_security import SAT_FROM_PACKAGE_CTX, check_sat_manager


class SatCfdiReceived(models.Model):
    _name = 'sat.cfdi.received'
    _description = 'CFDI recibido del SAT'
    _order = 'invoice_date desc, id desc'

    invoice_date = fields.Date(string='Fecha de factura', index=True)
    supplier_name = fields.Char(string='Proveedor', index=True)
    total = fields.Float(string='Total', digits=(16, 2))
    uuid = fields.Char(string='UUID', required=True, index=True)
    supplier_rfc = fields.Char(string='RFC del proveedor', index=True)
    currency = fields.Char(string='Moneda')
    company_id = fields.Many2one(
        'res.company',
        string='Empresa',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    download_request_id = fields.Many2one(
        'sat.download.request',
        string='Solicitud de descarga',
        ondelete='set null',
        index=True,
    )
    xml_attachment_id = fields.Many2one(
        'ir.attachment',
        string='Archivo XML adjunto',
        compute='_compute_xml_attachment',
        store=False,
    )

    _sql_constraints = [
        (
            'uuid_company_uniq',
            'unique(company_id, uuid)',
            'Ya existe un CFDI recibido con este UUID para esta empresa.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get(SAT_FROM_PACKAGE_CTX):
            raise AccessError(_(
                'Los registros de CFDI recibido solo pueden crearse desde paquetes de descarga del SAT.'
            ))
        return super().create(vals_list)

    def write(self, vals):
        check_sat_manager(self.env)
        return super().write(vals)

    def unlink(self):
        check_sat_manager(self.env)
        return super().unlink()

    def _compute_xml_attachment(self):
        Attachment = self.env['ir.attachment']
        for record in self:
            attachment = Attachment.search([
                ('res_model', '=', 'sat.cfdi.received'),
                ('res_id', '=', record.id),
            ], limit=1, order='id desc')
            record.xml_attachment_id = attachment

    @api.model
    def create_from_sat_package(self, vals, xml_bytes):
        """Create a received CFDI from SAT package data, skipping duplicate UUIDs."""
        existing = self.search([
            ('company_id', '=', vals['company_id']),
            ('uuid', '=', vals['uuid']),
        ], limit=1)
        if existing:
            return existing, False

        cfdi = self.with_context(**{SAT_FROM_PACKAGE_CTX: True}).create(vals)
        if xml_bytes:
            self.env['ir.attachment'].create({
                'name': '%s.xml' % vals['uuid'],
                'res_model': 'sat.cfdi.received',
                'res_id': cfdi.id,
                'type': 'binary',
                'datas': base64.b64encode(xml_bytes),
                'mimetype': 'application/xml',
            })
        return cfdi, True

    def action_export_csv(self):
        """Export selected records to CSV (UTF-8 with BOM)."""
        records = self
        if not records:
            active_ids = self.env.context.get('active_ids') or []
            if not active_ids:
                raise UserError(_('Seleccione al menos un registro para exportar.'))
            records = self.browse(active_ids)

        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(['invoice_date', 'supplier_name', 'total'])

        for rec in records.sorted(key=lambda r: (r.invoice_date or date.min, r.id)):
            invoice_date = rec.invoice_date.strftime('%Y-%m-%d') if rec.invoice_date else ''
            writer.writerow([invoice_date, rec.supplier_name or '', '%.2f' % (rec.total or 0.0)])

        csv_content = '\ufeff' + output.getvalue()
        filename = 'sat_received_cfdi_%s.csv' % date.today().strftime('%Y-%m-%d')
        attachment = self.env['ir.attachment'].sudo().create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(csv_content.encode('utf-8')),
            'mimetype': 'text/csv',
            'res_model': 'sat.cfdi.received',
            'res_id': records[0].id if records else False,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }
