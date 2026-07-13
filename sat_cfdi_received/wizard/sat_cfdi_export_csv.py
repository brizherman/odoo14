# -*- coding: utf-8 -*-
from odoo import models


class SatCfdiExportCsv(models.TransientModel):
    _name = 'sat.cfdi.export.csv'
    _description = 'Exportar CFDIs recibidos del SAT a CSV'

    def action_export(self):
        active_ids = self.env.context.get('active_ids') or []
        records = self.env['sat.cfdi.received'].browse(active_ids)
        return records.action_export_csv()
