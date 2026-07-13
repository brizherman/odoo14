# -*- coding: utf-8 -*-
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.sat_cfdi_received.models.sat_security import check_sat_manager
from odoo.addons.sat_cfdi_received.services.download_date_range import validate_download_date_range


class SatDownloadWizard(models.TransientModel):
    _name = 'sat.download.wizard'
    _description = 'Asistente de descarga de CFDIs recibidos del SAT'

    date_from = fields.Datetime(string='Desde', required=True)
    date_to = fields.Datetime(string='Hasta', required=True)
    company_id = fields.Many2one(
        'res.company',
        string='Empresa',
        required=True,
        default=lambda self: self.env.company,
    )

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        today = fields.Date.context_today(self)
        first_day = today.replace(day=1)
        defaults.setdefault('date_from', datetime.combine(first_day, datetime.min.time()))
        defaults.setdefault('date_to', datetime.combine(today, datetime.max.time().replace(microsecond=0)))
        return defaults

    @api.constrains('date_from', 'date_to')
    def _check_date_range(self):
        for wizard in self:
            validate_download_date_range(wizard, wizard.date_from, wizard.date_to)

    def action_request_download(self):
        check_sat_manager(self.env)
        self.ensure_one()
        if not self.company_id.sat_fiel_configured:
            raise ValidationError(_('Configure la FIEL en la empresa seleccionada primero.'))

        request = self.env['sat.download.request'].create({
            'date_from': self.date_from,
            'date_to': self.date_to,
            'company_id': self.company_id.id,
            'state': 'draft',
        })
        request.action_submit()
        if request.sat_request_id and request.state == 'requested':
            request.action_check_status()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Solicitud de descarga SAT'),
            'res_model': 'sat.download.request',
            'res_id': request.id,
            'view_mode': 'form',
            'target': 'current',
        }
