# -*- coding: utf-8 -*-
import json
import time
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_date, formatLang

from odoo.addons.po_vendor_sales_purchases_tab.services.sync_engine import (
    months_in_window,
    window_start_date,
)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    vendor_tab_last_sync = fields.Datetime(
        string='Última sincronización global de la pestaña',
        compute='_compute_vendor_tab_sync_info',
        readonly=True,
    )
    vendor_tab_po_last_sync = fields.Datetime(
        string='Última sincronización de OC de la pestaña',
        readonly=True,
        copy=False,
    )
    vendor_tab_warning = fields.Text(
        string='Advertencia de la pestaña',
        compute='_compute_vendor_tab_sync_info',
        readonly=True,
    )
    vendor_tab_po_stale_warning = fields.Text(
        string='Advertencia de datos de OC desactualizados',
        compute='_compute_vendor_tab_sync_info',
        readonly=True,
    )
    vendor_sheet_invoice_ids = fields.One2many(
        'vendor.sheet.invoice',
        compute='_compute_vendor_sheet_invoice_ids',
        string='Facturas de hoja de proveedor',
        readonly=True,
    )
    vendor_sheet_purchases_html = fields.Html(
        string='Tabla de compras de hoja de proveedor',
        compute='_compute_vendor_sheet_purchases_html',
        sanitize=False,
        readonly=True,
    )
    vendor_sales_matrix = fields.Text(
        string='Matriz de ventas del proveedor',
        compute='_compute_vendor_sales_matrix',
        readonly=True,
        help='Estructura JSON de totales de ventas por mes y departamento.',
    )
    vendor_sales_matrix_html = fields.Html(
        string='Tabla de matriz de ventas del proveedor',
        compute='_compute_vendor_sales_matrix',
        sanitize=False,
        readonly=True,
    )
    vendor_sales_matrix_warning = fields.Text(
        string='Advertencia de matriz de ventas',
        compute='_compute_vendor_sales_matrix',
        readonly=True,
    )

    @api.model
    def _vendor_sheet_invoice_date_from(self):
        return window_start_date(fields.Date.context_today(self))

    def _render_sales_matrix_html(self, matrix):
        departments = matrix.get('departments') or []
        months = matrix.get('months') or []
        cells = matrix.get('cells') or {}
        if not departments:
            return '<p class="text-muted">No hay datos de ventas disponibles para este proveedor.</p>'

        currency = self.company_id.currency_id
        column_totals = {month: 0.0 for month in months}
        rows = ['<table class="table table-sm table-bordered table-striped o_vendor_sales_matrix">']
        rows.append('<thead><tr><th>Departamento</th>')
        for month in months:
            rows.append('<th class="text-right">%s</th>' % month)
        rows.append('</tr></thead><tbody>')
        for dept in departments:
            dept_key = str(dept['id'])
            row_cells = cells.get(dept_key, {})
            rows.append('<tr><td>%s</td>' % dept['name'])
            for month in months:
                amount = row_cells.get(month, 0.0)
                column_totals[month] += amount
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
        rows.append('</tbody><tfoot><tr class="font-weight-bold o_vendor_sales_grand_total">')
        rows.append('<td>%s</td>' % 'Total general')
        for month in months:
            if month == 'TOTAL':
                amount = matrix.get('total', column_totals.get('TOTAL', 0.0))
            else:
                amount = column_totals.get(month, 0.0)
            rows.append(
                '<td class="text-right">%s</td>'
                % formatLang(
                    self.env,
                    amount,
                    monetary=True,
                    currency_obj=currency,
                )
            )
        rows.append('</tr></tfoot></table>')
        return ''.join(rows)

    def _source_month_label(self, source_month):
        if not source_month or len(source_month) != 7:
            return 'Sin mes de origen'
        year, month = source_month.split('-')
        month_start = fields.Date.from_string('%s-%s-01' % (year, month))
        return format_date(self.env, month_start, date_format='MMMM yyyy')

    def _render_purchases_by_month_html(self, invoices):
        if not invoices:
            return '<p class="text-muted">No hay facturas de compra en el período (mes actual y 3 meses anteriores).</p>'

        currency = self.company_id.currency_id
        by_month = {}
        for invoice in invoices:
            month_key = invoice.source_month or ''
            by_month.setdefault(month_key, []).append(invoice)

        month_keys = sorted(by_month.keys(), reverse=True)
        grand_total = sum(invoice.total_factura or 0.0 for invoice in invoices)
        parts = []
        for month_key in month_keys:
            month_invoices = sorted(
                by_month[month_key],
                key=lambda inv: (inv.fecha or fields.Date.from_string('1900-01-01'), inv.no_factura or ''),
                reverse=True,
            )
            label = self._source_month_label(month_key)
            month_total = sum(inv.total_factura or 0.0 for inv in month_invoices)
            parts.append('<details class="o_vendor_purchases_month mb-2">')
            parts.append(
                '<summary class="font-weight-bold">%s (%s) &mdash; %s</summary>'
                % (
                    label,
                    len(month_invoices),
                    formatLang(
                        self.env,
                        month_total,
                        monetary=True,
                        currency_obj=currency,
                    ),
                )
            )
            parts.append(
                '<table class="table table-sm table-bordered table-striped mb-0 mt-1">'
            )
            parts.append(
                '<thead><tr>'
                '<th>%s</th><th>%s</th><th>%s</th>'
                '<th class="text-right">%s</th><th>%s</th><th>%s</th>'
                '</tr></thead><tbody>'
                % (
                    'No. Factura',
                    'Fecha',
                    'Vence',
                    'Total de Factura',
                    'Pagado',
                    'Fecha de Pago',
                )
            )
            for invoice in month_invoices:
                parts.append(
                    '<tr>'
                    '<td>%s</td>'
                    '<td>%s</td>'
                    '<td>%s</td>'
                    '<td class="text-right">%s</td>'
                    '<td>%s</td>'
                    '<td>%s</td>'
                    '</tr>'
                    % (
                        invoice.no_factura or '',
                        format_date(self.env, invoice.fecha) if invoice.fecha else '',
                        format_date(self.env, invoice.vence) if invoice.vence else '',
                        formatLang(
                            self.env,
                            invoice.total_factura or 0.0,
                            monetary=True,
                            currency_obj=currency,
                        ),
                        'Sí' if invoice.pagado else 'No',
                        format_date(self.env, invoice.fecha_pago) if invoice.fecha_pago else '',
                    )
                )
            parts.append('</tbody></table></details>')
        parts.append(
            '<div class="o_vendor_purchases_grand_total text-right font-weight-bold mt-2 pt-2 border-top">'
            '%s: %s <span class="text-muted">(%s %s)</span>'
            '</div>'
            % (
                'Total general',
                formatLang(
                    self.env,
                    grand_total,
                    monetary=True,
                    currency_obj=currency,
                ),
                len(invoices),
                'facturas',
            )
        )
        return ''.join(parts)

    def _vendor_sheet_invoice_window_domain(self):
        today = fields.Date.context_today(self)
        return [
            '|',
            ('fecha', '>=', window_start_date(today)),
            ('source_month', 'in', months_in_window(today)),
        ]

    def _vendor_sheet_invoices_for_po(self):
        self.ensure_one()
        if not self.partner_id or not self.company_id:
            return self.env['vendor.sheet.invoice'].browse()
        return self.env['vendor.sheet.invoice'].search([
            ('partner_id', '=', self.partner_id.id),
            ('company_id', '=', self.company_id.id),
        ] + self._vendor_sheet_invoice_window_domain(), order='fecha desc, no_factura, id desc')

    @api.depends('partner_id', 'company_id')
    def _compute_vendor_sheet_invoice_ids(self):
        for order in self:
            order.vendor_sheet_invoice_ids = order._vendor_sheet_invoices_for_po()

    @api.depends('partner_id', 'company_id', 'vendor_tab_po_last_sync', 'vendor_tab_last_sync')
    def _compute_vendor_sheet_purchases_html(self):
        for order in self:
            order.vendor_sheet_purchases_html = order._render_purchases_by_month_html(
                order._vendor_sheet_invoices_for_po(),
            )

    @api.depends('vendor_tab_po_last_sync', 'partner_id', 'company_id')
    def _compute_vendor_tab_sync_info(self):
        SyncLog = self.env['vendor.sheet.sync.log']
        last_global_log = SyncLog.search([
            ('sync_type', '=', 'global'),
        ], order='sync_date desc', limit=1)
        stale_threshold = fields.Datetime.now() - timedelta(hours=24)
        for order in self:
            if last_global_log:
                order.vendor_tab_last_sync = last_global_log.sync_date
                if last_global_log.warnings_count:
                    order.vendor_tab_warning = (
                        'La última sincronización global tuvo %(count)s advertencia(s). '
                        'Consulte el registro de sincronización para más detalles.'
                        % {'count': last_global_log.warnings_count}
                    )
                elif last_global_log.state == 'error':
                    order.vendor_tab_warning = last_global_log.warning_details or (
                        'La última sincronización global terminó con errores.'
                    )
                else:
                    order.vendor_tab_warning = False
            else:
                order.vendor_tab_last_sync = False
                order.vendor_tab_warning = False

            if not order.partner_id or not order.company_id:
                order.vendor_tab_po_stale_warning = False
                continue

            po_sync = order.vendor_tab_po_last_sync
            global_sync = order.vendor_tab_last_sync
            is_stale = (
                not po_sync
                or (global_sync and po_sync < global_sync)
                or po_sync < stale_threshold
            )
            if is_stale:
                order.vendor_tab_po_stale_warning = (
                    'Los datos de la OC pueden estar desactualizados — haga clic en Sincronizar OC.'
                )
            else:
                order.vendor_tab_po_stale_warning = False

    @api.depends('partner_id', 'company_id', 'vendor_tab_po_last_sync')
    def _compute_vendor_sales_matrix(self):
        from odoo.addons.po_vendor_sales_purchases_tab.services.sales_snapshot import (
            get_sales_matrix_for_po,
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
                matrix = get_sales_matrix_for_po(
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

    def _invalidate_vendor_tab_fields(self):
        self.invalidate_cache([
            'vendor_sales_matrix',
            'vendor_sales_matrix_html',
            'vendor_sales_matrix_warning',
            'vendor_sheet_invoice_ids',
            'vendor_sheet_purchases_html',
            'vendor_tab_last_sync',
            'vendor_tab_warning',
            'vendor_tab_po_stale_warning',
        ])

    def _sync_notification(self, title, message, notification_type, sticky=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notification_type,
                'sticky': sticky,
            },
        }

    def action_sync_global_vendor_sheets(self):
        """Fetch Google Sheets and update purchase staging for all vendors and branches."""
        from odoo.addons.po_vendor_sales_purchases_tab.services.sync_engine import run_global_sync

        result = run_global_sync(
            self.env,
            triggered_by_user=self.env.user,
            refresh_sales_snapshots=False,
        )
        self._invalidate_vendor_tab_fields()
        if result.get('error'):
            message = 'Error en sincronización global: %s' % result['error']
            notification_type = 'danger'
        else:
            total_rows = result.get('created', 0) + result.get('updated', 0)
            warning_count = len(result.get('warnings') or [])
            mappings_created = result.get('mappings_created', 0)
            message = (
                'Sincronización global: %(rows)s facturas, %(warnings)s advertencias, '
                '%(mappings)s proveedores nuevos en mapeos.'
                % {
                    'rows': total_rows,
                    'warnings': warning_count,
                    'mappings': mappings_created,
                }
            )
            notification_type = 'warning' if warning_count else 'success'

        return self._sync_notification(
            'Sincronizar global',
            message,
            notification_type,
            sticky=bool(result.get('error')),
        )

    def action_sync_po_vendor_tab(self):
        """Refresh sales snapshot and purchase panel for this PO vendor and branch."""
        self.ensure_one()
        if not self.partner_id or not self.company_id:
            raise UserError('Indique un proveedor y una empresa antes de sincronizar esta pestaña de OC.')

        from odoo.addons.po_vendor_sales_purchases_tab.services.sales_snapshot import (
            recompute_sales_snapshot,
        )

        start = time.time()
        sync_time = fields.Datetime.now()
        recompute_sales_snapshot(
            self.env,
            self.partner_id.id,
            self.company_id.id,
            sync_time=sync_time,
        )
        self.write({'vendor_tab_po_last_sync': sync_time})
        duration = time.time() - start
        self.env['vendor.sheet.sync.log'].sudo().create({
            'sync_date': sync_time,
            'user_id': self.env.user.id,
            'duration_seconds': duration,
            'state': 'success',
            'sync_type': 'po',
            'po_id': self.id,
        })
        self._invalidate_vendor_tab_fields()
        message = (
            'Paneles de OC actualizados para %(vendor)s @ %(branch)s.'
            % {
                'vendor': self.partner_id.display_name,
                'branch': self.company_id.display_name,
            }
        )
        return self._sync_notification('Sincronizar OC', message, 'success')
