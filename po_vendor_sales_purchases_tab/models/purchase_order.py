# -*- coding: utf-8 -*-
import json
from datetime import timedelta

from odoo import api, fields, models, _


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    vendor_tab_last_sync = fields.Datetime(
        string='Vendor Tab Last Sync',
        compute='_compute_vendor_tab_sync_info',
        readonly=True,
    )
    vendor_tab_warning = fields.Text(
        string='Vendor Tab Warning',
        compute='_compute_vendor_tab_sync_info',
        readonly=True,
    )
    vendor_sheet_invoice_ids = fields.One2many(
        'vendor.sheet.invoice',
        compute='_compute_vendor_sheet_invoice_ids',
        string='Vendor Sheet Invoices',
        readonly=True,
    )
    vendor_sales_matrix = fields.Text(
        string='Vendor Sales Matrix',
        compute='_compute_vendor_sales_matrix',
        readonly=True,
        help='JSON structure for month x department sales totals (wired in task 5.0).',
    )

    @api.model
    def _vendor_sheet_invoice_date_from(self):
        return fields.Date.context_today(self) - timedelta(days=90)

    @api.depends('partner_id', 'company_id')
    def _compute_vendor_sheet_invoice_ids(self):
        Invoice = self.env['vendor.sheet.invoice']
        date_from = self._vendor_sheet_invoice_date_from()
        for order in self:
            if order.partner_id and order.company_id:
                order.vendor_sheet_invoice_ids = Invoice.search([
                    ('partner_id', '=', order.partner_id.id),
                    ('company_id', '=', order.company_id.id),
                    ('fecha', '>=', date_from),
                ])
            else:
                order.vendor_sheet_invoice_ids = Invoice.browse()

    @api.depends('partner_id', 'company_id')
    def _compute_vendor_tab_sync_info(self):
        SyncLog = self.env['vendor.sheet.sync.log']
        last_log = SyncLog.search([], order='sync_date desc', limit=1)
        for order in self:
            if last_log:
                order.vendor_tab_last_sync = last_log.sync_date
                if last_log.warnings_count:
                    order.vendor_tab_warning = _(
                        'Last sync had %(count)s warning(s). See sync log for details.',
                        count=last_log.warnings_count,
                    )
                elif last_log.state == 'error':
                    order.vendor_tab_warning = last_log.warning_details or _(
                        'Last sync finished with errors.',
                    )
                else:
                    order.vendor_tab_warning = False
            else:
                order.vendor_tab_last_sync = False
                order.vendor_tab_warning = False

    @api.depends('partner_id', 'company_id')
    def _compute_vendor_sales_matrix(self):
        empty_matrix = {
            'departments': [],
            'months': [],
            'cells': {},
            'total': 0.0,
        }
        for order in self:
            # Populated by sales_aggregator in task 5.0.
            order.vendor_sales_matrix = json.dumps(empty_matrix)

    def action_sync_vendor_sheet_data(self):
        """Trigger global Google Sheets sync. Wired to sync_engine in task 4.0."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync'),
                'message': _('Vendor sheet sync is not wired yet (task 4.0).'),
                'type': 'warning',
                'sticky': False,
            },
        }
