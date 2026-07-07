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

# -*- coding: utf-8 -*-
import json
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.tools.misc import formatLang


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
        help='JSON structure for month x department sales totals.',
    )
    vendor_sales_matrix_html = fields.Html(
        string='Vendor Sales Matrix Table',
        compute='_compute_vendor_sales_matrix',
        sanitize=False,
        readonly=True,
    )
    vendor_sales_matrix_warning = fields.Text(
        string='Vendor Sales Matrix Warning',
        compute='_compute_vendor_sales_matrix',
        readonly=True,
    )

    @api.model
    def _vendor_sheet_invoice_date_from(self):
        return fields.Date.context_today(self) - timedelta(days=90)

    def _render_sales_matrix_html(self, matrix):
        departments = matrix.get('departments') or []
        months = matrix.get('months') or []
        cells = matrix.get('cells') or {}
        if not departments:
            return '<p class="text-muted">No sales data available for this vendor.</p>'

        currency = self.company_id.currency_id
        rows = ['<table class="table table-sm table-bordered table-striped o_vendor_sales_matrix">']
        rows.append('<thead><tr><th>Department</th>')
        for month in months:
            rows.append('<th class="text-right">%s</th>' % month)
        rows.append('</tr></thead><tbody>')
        for dept in departments:
            dept_key = str(dept['id'])
            row_cells = cells.get(dept_key, {})
            rows.append('<tr><td>%s</td>' % dept['name'])
            for month in months:
                amount = row_cells.get(month, 0.0)
                rows.append(
                    '<td class="text-right">%s</td>'
                    % formatLang(
                        self.env,
                        amount,
                        monetary=True,
                        currency_obj=currency,
                    )
                )
            rows.append('</tr>')
        rows.append('</tbody></table>')
        return ''.join(rows)

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
        from odoo.addons.po_vendor_sales_purchases_tab.services.sales_aggregator import (
            compute_sales_matrix,
        )

        empty_matrix = {
            'departments': [],
            'months': [],
            'cells': {},
            'total': 0.0,
            'has_warning': False,
            'warning': False,
        }
        for order in self:
            if order.partner_id and order.company_id:
                matrix = compute_sales_matrix(
                    self.env,
                    order.partner_id.id,
                    order.company_id.id,
                )
            else:
                matrix = empty_matrix
            order.vendor_sales_matrix = json.dumps(matrix)
            order.vendor_sales_matrix_warning = (
                matrix.get('warning') if matrix.get('has_warning') else False
            )
            order.vendor_sales_matrix_html = order._render_sales_matrix_html(matrix)

    def action_sync_vendor_sheet_data(self):
        """Trigger global Google Sheets sync for all vendors and branches."""
        from odoo.addons.po_vendor_sales_purchases_tab.services.sync_engine import run_global_sync

        result = run_global_sync(self.env, triggered_by_user=self.env.user)
        if result.get('error'):
            message = _('Sync failed: %s') % result['error']
            notification_type = 'danger'
        else:
            total_rows = result.get('created', 0) + result.get('updated', 0)
            warning_count = len(result.get('warnings') or [])
            message = _(
                'Synced %(rows)s invoices, %(warnings)s warnings.',
                rows=total_rows,
                warnings=warning_count,
            )
            notification_type = 'warning' if warning_count else 'success'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync'),
                'message': message,
                'type': notification_type,
                'sticky': bool(result.get('error')),
            },
        }
