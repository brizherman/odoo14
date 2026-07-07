# -*- coding: utf-8 -*-
import logging
import time
from datetime import datetime, timedelta

import pytz
from odoo import fields, _
from odoo.exceptions import UserError

from .google_sheets_client import GoogleSheetsClient
from .payment_block_parser import parse_dict_rows
from .sucursal_matcher import SucursalMatcher
from .vendor_matcher import VendorMatcher

_logger = logging.getLogger(__name__)

TZ_TIJUANA = pytz.timezone('America/Tijuana')
MONTH_FMT = '%Y-%m'


def _today_tijuana(reference_date=None):
    if reference_date is not None:
        return reference_date
    return datetime.now(TZ_TIJUANA).date()


def months_in_90_day_window(reference_date=None):
    """Return YYYY-MM labels for months overlapping the rolling 90-day window."""
    today = _today_tijuana(reference_date)
    date_from = today - timedelta(days=90)
    year, month = date_from.year, date_from.month
    end_year, end_month = today.year, today.month
    months = []
    while (year, month) <= (end_year, end_month):
        months.append('%04d-%02d' % (year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


def current_month_label(reference_date=None):
    today = _today_tijuana(reference_date)
    return today.strftime(MONTH_FMT)


def months_to_sync(month_records, months_in_window, current_month):
    """Return month labels to fetch: unsynced closed months plus current month."""
    record_by_name = {rec.name: rec for rec in month_records}
    to_sync = []
    for month_label in months_in_window:
        if month_label == current_month:
            to_sync.append(month_label)
            continue
        record = record_by_name.get(month_label)
        if record and not record.synced_once:
            to_sync.append(month_label)
    return to_sync


def _decimal_to_float(value):
    if value is None:
        return 0.0
    return float(value)


class SyncEngine:
    """Global Google Sheets sync: closed-month-once + current-month-always."""

    def __init__(self, env, sheets_client=None, reference_date=None):
        self.env = env
        self.sheets_client = sheets_client or GoogleSheetsClient(env)
        self.reference_date = reference_date
        self.sucursal_matcher = SucursalMatcher(env)
        self.vendor_matcher = VendorMatcher(env)
        self.warnings = []
        self.created = 0
        self.updated = 0

    def _add_warning(self, message):
        self.warnings.append(message)

    def _get_month_record(self, config, month_label):
        return config.sheet_month_ids.filtered(lambda month: month.name == month_label)[:1]

    def _fetch_month_data(self, config, months):
        """Fetch and parse all target months before any staging writes."""
        fetched = {}
        for month_label in months:
            month_rec = self._get_month_record(config, month_label)
            if not month_rec:
                self._add_warning(
                    'Month workbook "%s" is not configured; skipped.' % month_label
                )
                continue
            if not month_rec.spreadsheet_id:
                self._add_warning(
                    'Spreadsheet ID missing for month "%s"; skipped.' % month_label
                )
                continue

            dict_rows = self.sheets_client.fetch_sheet_rows(month_rec.spreadsheet_id)
            parse_result = parse_dict_rows(dict_rows)
            for warning in parse_result.warnings:
                self._add_warning('[%s] %s' % (month_label, warning))
            fetched[month_label] = {
                'record': month_rec,
                'parse_result': parse_result,
            }
        return fetched

    def _build_invoice_vals(self, parsed, source_month, company, partner, sync_time):
        warning_parts = []
        if parsed.warning_message:
            warning_parts.append(parsed.warning_message)

        return {
            'sucursal': parsed.sucursal,
            'company_id': company.id,
            'proveedor': parsed.proveedor,
            'partner_id': partner.id if partner else False,
            'no_factura': parsed.no_factura,
            'fecha': parsed.fecha,
            'vence': parsed.vence,
            'total_factura': _decimal_to_float(parsed.total_factura),
            'pagado': parsed.pagado,
            'fecha_pago': parsed.fecha_pago,
            'monto_pago_grupo': (
                _decimal_to_float(parsed.monto_pago_grupo)
                if parsed.monto_pago_grupo is not None
                else 0.0
            ),
            'facturas_en_grupo': parsed.facturas_en_grupo,
            'source_month': source_month,
            'sheet_row': parsed.sheet_row,
            'block_valid': parsed.block_valid,
            'warning_message': '\n'.join(warning_parts) if warning_parts else False,
            'last_sync': sync_time,
        }

    def _upsert_invoices(self, parse_result, source_month, sync_time):
        Invoice = self.env['vendor.sheet.invoice'].sudo()
        for parsed in parse_result.invoices:
            company, sucursal_warning = self.sucursal_matcher.resolve_company(parsed.sucursal)
            if sucursal_warning:
                self._add_warning(
                    '[%s] %s' % (parsed.no_factura or source_month, sucursal_warning)
                )
                continue

            partner, vendor_warning = self.vendor_matcher.resolve_partner(parsed.proveedor)
            if vendor_warning:
                self._add_warning(
                    '[%s] %s' % (parsed.no_factura, vendor_warning)
                )

            vals = self._build_invoice_vals(
                parsed, source_month, company, partner, sync_time
            )
            if vendor_warning:
                existing_warning = vals.get('warning_message') or ''
                vals['warning_message'] = '\n'.join(
                    part for part in (existing_warning, vendor_warning) if part
                )

            existing = Invoice.search([
                ('sucursal', '=', parsed.sucursal),
                ('no_factura', '=', parsed.no_factura),
            ], limit=1)
            if existing:
                existing.write(vals)
                self.updated += 1
            else:
                Invoice.create(vals)
                self.created += 1

    def _mark_month_synced(self, month_rec, sync_time):
        month_rec.write({
            'last_sync': sync_time,
            'synced_once': True,
        })

    def _write_sync_log(self, user, sync_time, duration, state='success', error_message=None):
        details = error_message
        if not details and self.warnings:
            details = '\n'.join(self.warnings)
        self.env['vendor.sheet.sync.log'].sudo().create({
            'sync_date': sync_time,
            'user_id': user.id,
            'rows_created': self.created,
            'rows_updated': self.updated,
            'warnings_count': len(self.warnings),
            'duration_seconds': duration,
            'warning_details': details,
            'state': state,
        })

    def run(self, triggered_by_user=None):
        start = time.time()
        user = triggered_by_user or self.env.user
        sync_time = fields.Datetime.now()
        config = self.env['vendor.sheet.config'].get_singleton()
        current_month = current_month_label(self.reference_date)
        window_months = months_in_90_day_window(self.reference_date)
        target_months = months_to_sync(
            config.sheet_month_ids,
            window_months,
            current_month,
        )

        try:
            if target_months:
                fetched = self._fetch_month_data(config, target_months)
                for month_label, payload in fetched.items():
                    self._upsert_invoices(
                        payload['parse_result'],
                        month_label,
                        sync_time,
                    )
                    self._mark_month_synced(payload['record'], sync_time)
        except UserError as exc:
            duration = time.time() - start
            self._write_sync_log(
                user,
                sync_time,
                duration,
                state='error',
                error_message=str(exc),
            )
            return {
                'created': self.created,
                'updated': self.updated,
                'warnings': self.warnings,
                'error': str(exc),
            }

        duration = time.time() - start
        self._write_sync_log(user, sync_time, duration, state='success')
        return {
            'created': self.created,
            'updated': self.updated,
            'warnings': self.warnings,
            'error': None,
        }


def run_global_sync(env, triggered_by_user=None, sheets_client=None, reference_date=None):
    """Run global vendor sheet sync and return summary counters."""
    engine = SyncEngine(
        env,
        sheets_client=sheets_client,
        reference_date=reference_date,
    )
    return engine.run(triggered_by_user=triggered_by_user)
