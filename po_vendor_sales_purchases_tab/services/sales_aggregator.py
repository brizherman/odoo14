# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import date, datetime, time, timedelta

import pytz
from odoo import fields

from .sync_engine import months_in_window, window_start_date
from .vendor_matcher import VendorMatcher

TZ_TIJUANA = pytz.timezone('America/Tijuana')
UNASSIGNED_DEPARTMENT_ID = 0
UNASSIGNED_DEPARTMENT_NAME = 'Sin asignar'

SALE_ORDER_STATES = ('sale', 'done')
POS_ORDER_STATES = ('paid', 'done', 'invoiced')


def local_day_range_utc_naive(start_d, end_d):
    """Inclusive local calendar days in America/Tijuana -> naive UTC datetimes."""
    start_local = TZ_TIJUANA.localize(datetime.combine(start_d, time.min))
    end_local = TZ_TIJUANA.localize(datetime.combine(end_d, time(23, 59, 59)))
    return (
        start_local.astimezone(pytz.UTC).replace(tzinfo=None),
        end_local.astimezone(pytz.UTC).replace(tzinfo=None),
    )


def _month_date_bounds(month_label, window_start, window_end):
    year, month = map(int, month_label.split('-'))
    month_start = date(year, month, 1)
    if month == 12:
        month_end = date(year, 12, 31)
    else:
        month_end = date(year, month + 1, 1) - timedelta(days=1)
    start_d = max(month_start, window_start)
    end_d = min(month_end, window_end)
    if start_d > end_d:
        return None, None
    return start_d, end_d


def _empty_matrix(warning=False, warning_message=False):
    return {
        'departments': [],
        'months': [],
        'cells': {},
        'total': 0.0,
        'has_warning': bool(warning),
        'warning': warning_message or False,
    }


class SalesAggregator:
    """Live SO + POS sales matrix by month x classification department."""

    def __init__(self, env, reference_date=None):
        self.env = env
        self.reference_date = reference_date
        self.vendor_matcher = VendorMatcher(env)

    def _reference_today(self):
        if self.reference_date is not None:
            return self.reference_date
        return fields.Date.context_today(self.env.user)

    def _products_for_classification_vendor(self, classification_vendor):
        Product = self.env['product.product']
        if not classification_vendor:
            return Product.browse()
        templates = self.env['product.template'].search([
            ('classification_vendor', '=', classification_vendor.id),
        ])
        if not templates:
            return Product.browse()
        return Product.search([('product_tmpl_id', 'in', templates.ids)])

    def _department_catalog(self, products):
        departments = {}
        for product in products:
            dept = product.product_tmpl_id.classification_department
            if dept:
                departments[dept.id] = dept.name
            else:
                departments[UNASSIGNED_DEPARTMENT_ID] = UNASSIGNED_DEPARTMENT_NAME
        if not departments:
            departments[UNASSIGNED_DEPARTMENT_ID] = UNASSIGNED_DEPARTMENT_NAME
        return departments

    def _product_department_map(self, products):
        mapping = {}
        for product in products:
            dept = product.product_tmpl_id.classification_department
            if dept:
                mapping[product.id] = (dept.id, dept.name)
            else:
                mapping[product.id] = (
                    UNASSIGNED_DEPARTMENT_ID,
                    UNASSIGNED_DEPARTMENT_NAME,
                )
        return mapping

    def _sum_sale_lines(self, company_id, product_ids, start_utc, end_utc):
        if not product_ids:
            return {}
        domain = [
            ('order_id.state', 'in', list(SALE_ORDER_STATES)),
            ('order_id.company_id', '=', company_id),
            ('order_id.date_order', '>=', fields.Datetime.to_string(start_utc)),
            ('order_id.date_order', '<=', fields.Datetime.to_string(end_utc)),
            ('display_type', '=', False),
            ('product_id', 'in', product_ids),
        ]
        totals = defaultdict(float)
        groups = self.env['sale.order.line'].read_group(
            domain,
            ['price_total', 'product_id'],
            ['product_id'],
            lazy=False,
        )
        for group in groups:
            product = group.get('product_id')
            if not product:
                continue
            totals[product[0]] += float(group.get('price_total') or 0.0)
        return totals

    def _sum_pos_lines(self, company_id, product_ids, start_utc, end_utc):
        if not product_ids:
            return {}
        domain = [
            ('order_id.state', 'in', list(POS_ORDER_STATES)),
            ('order_id.company_id', '=', company_id),
            ('order_id.date_order', '>=', fields.Datetime.to_string(start_utc)),
            ('order_id.date_order', '<=', fields.Datetime.to_string(end_utc)),
            ('product_id', 'in', product_ids),
        ]
        totals = defaultdict(float)
        groups = self.env['pos.order.line'].read_group(
            domain,
            ['price_subtotal_incl', 'product_id'],
            ['product_id'],
            lazy=False,
        )
        for group in groups:
            product = group.get('product_id')
            if not product:
                continue
            totals[product[0]] += float(group.get('price_subtotal_incl') or 0.0)
        return totals

    def _merge_product_totals(self, *maps):
        merged = defaultdict(float)
        for product_map in maps:
            for product_id, amount in product_map.items():
                merged[product_id] += amount
        return merged

    def _init_cells(self, departments, month_labels):
        cells = {}
        for dept_id in departments:
            cells[str(dept_id)] = {month: 0.0 for month in month_labels}
            cells[str(dept_id)]['TOTAL'] = 0.0
        return cells

    def compute_matrix(self, partner_id, company_id):
        partner = self.env['res.partner'].browse(partner_id)
        company = self.env['res.company'].browse(company_id)
        if not partner or not company:
            return _empty_matrix()

        classification_vendor, vendor_warning = self.vendor_matcher.resolve_classification_vendor(
            partner
        )
        if vendor_warning:
            return _empty_matrix(
                warning=True,
                warning_message=vendor_warning,
            )

        products = self._products_for_classification_vendor(classification_vendor)
        departments = self._department_catalog(products)
        product_departments = self._product_department_map(products)
        product_ids = products.ids

        today = self._reference_today()
        window_start = window_start_date(today)
        month_labels = months_in_window(reference_date=today)
        display_months = month_labels + ['TOTAL']
        cells = self._init_cells(departments, display_months)
        grand_total = 0.0

        for month_label in month_labels:
            start_d, end_d = _month_date_bounds(month_label, window_start, today)
            if not start_d:
                continue
            start_utc, end_utc = local_day_range_utc_naive(start_d, end_d)
            product_totals = self._merge_product_totals(
                self._sum_sale_lines(company.id, product_ids, start_utc, end_utc),
                self._sum_pos_lines(company.id, product_ids, start_utc, end_utc),
            )
            for product_id, amount in product_totals.items():
                dept_id, _dept_name = product_departments.get(
                    product_id,
                    (UNASSIGNED_DEPARTMENT_ID, UNASSIGNED_DEPARTMENT_NAME),
                )
                dept_key = str(dept_id)
                if dept_key not in cells:
                    cells[dept_key] = {month: 0.0 for month in display_months}
                    cells[dept_key]['TOTAL'] = 0.0
                cells[dept_key][month_label] += amount
                cells[dept_key]['TOTAL'] += amount
                grand_total += amount

        department_rows = [
            {'id': dept_id, 'name': name}
            for dept_id, name in sorted(departments.items(), key=lambda item: item[1].lower())
        ]

        has_warning = False
        warning_message = False
        if not products:
            has_warning = True
            warning_message = (
                'No se encontraron productos para el proveedor de clasificación "%s".'
                % classification_vendor.name
            )
        elif grand_total == 0.0:
            has_warning = True
            warning_message = (
                'No se encontraron ventas para este proveedor en el período '
                '(mes actual y 3 meses anteriores).'
            )
        elif any(cells[str(dept_id)]['TOTAL'] == 0.0 for dept_id in departments):
            has_warning = True
            warning_message = 'Algunos departamentos no tienen ventas en el período seleccionado.'

        return {
            'departments': department_rows,
            'months': display_months,
            'cells': cells,
            'total': grand_total,
            'has_warning': has_warning,
            'warning': warning_message,
        }


def compute_sales_matrix(env, partner_id, company_id, reference_date=None):
    """Return month x department sales totals for a PO vendor and company."""
    aggregator = SalesAggregator(env, reference_date=reference_date)
    return aggregator.compute_matrix(partner_id, company_id)
