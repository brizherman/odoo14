# -*- coding: utf-8 -*-
from datetime import date

from odoo import fields

from .sales_aggregator import (
    UNASSIGNED_DEPARTMENT_ID,
    UNASSIGNED_DEPARTMENT_NAME,
    compute_sales_matrix,
)
from .sync_engine import months_in_window, window_start_date


def _reference_today(env, reference_date=None):
    if reference_date is not None:
        return reference_date
    return fields.Date.context_today(env.user)


def _get_unassigned_department(env):
    Department = env['product.classification.department']
    unassigned = Department.search([
        ('name', '=', UNASSIGNED_DEPARTMENT_NAME),
    ], limit=1)
    if not unassigned:
        unassigned = Department.create({'name': UNASSIGNED_DEPARTMENT_NAME})
    return unassigned


def _department_record(env, dept_id):
    if dept_id and dept_id != UNASSIGNED_DEPARTMENT_ID:
        return env['product.classification.department'].browse(dept_id)
    return _get_unassigned_department(env)


def _snapshot_dept_key(classification_department, unassigned_department):
    if classification_department == unassigned_department:
        return str(UNASSIGNED_DEPARTMENT_ID), UNASSIGNED_DEPARTMENT_NAME
    return str(classification_department.id), classification_department.name


def recompute_sales_snapshot(env, partner_id, company_id, reference_date=None, sync_time=None):
    """Compute live sales matrix and persist rows for one vendor + company."""
    matrix = compute_sales_matrix(
        env,
        partner_id,
        company_id,
        reference_date=reference_date,
    )
    Snapshot = env['vendor.sales.snapshot'].sudo()
    sync_time = sync_time or fields.Datetime.now()
    today = _reference_today(env, reference_date)
    month_labels = months_in_window(reference_date=today)
    unassigned_department = _get_unassigned_department(env)

    Snapshot.search([
        ('partner_id', '=', partner_id),
        ('company_id', '=', company_id),
    ]).unlink()

    if matrix.get('has_warning') and not matrix.get('departments'):
        return 0

    vals_list = []
    for dept_row in matrix.get('departments') or []:
        dept_record = _department_record(env, dept_row['id'])
        dept_key = str(dept_row['id'])
        row_cells = (matrix.get('cells') or {}).get(dept_key, {})
        for month_label in month_labels:
            year, month = map(int, month_label.split('-'))
            vals_list.append({
                'partner_id': partner_id,
                'company_id': company_id,
                'classification_department_id': dept_record.id,
                'month': date(year, month, 1),
                'amount_total': float(row_cells.get(month_label) or 0.0),
                'computed_at': sync_time,
            })

    if vals_list:
        Snapshot.create(vals_list)
    return len(vals_list)


def _sales_snapshot_targets(env, reference_date=None):
    today = _reference_today(env, reference_date)
    date_from = window_start_date(today)
    companies = env['vendor.sucursal.mapping'].mapped('company_id')
    if not companies:
        companies = env['res.company'].search([])

    mapping_partners = env['vendor.sheet.mapping'].mapped('partner_id')
    invoice_partners = env['vendor.sheet.invoice'].sudo().search([
        ('partner_id', '!=', False),
        ('fecha', '>=', date_from),
    ]).mapped('partner_id')
    partners = mapping_partners | invoice_partners
    return partners, companies


def recompute_all_sales_snapshots(env, reference_date=None, sync_time=None):
    """Refresh sales snapshots for mapped vendors across branch companies."""
    sync_time = sync_time or fields.Datetime.now()
    partners, companies = _sales_snapshot_targets(env, reference_date=reference_date)
    rows_written = 0
    for partner in partners:
        for company in companies:
            rows_written += recompute_sales_snapshot(
                env,
                partner.id,
                company.id,
                reference_date=reference_date,
                sync_time=sync_time,
            )
    return rows_written


def matrix_from_snapshot(env, partner_id, company_id, reference_date=None):
    """Build the PO tab matrix JSON from stored snapshots, or None if empty."""
    today = _reference_today(env, reference_date)
    window_start = window_start_date(today)
    month_labels = months_in_window(reference_date=today)
    display_months = month_labels + ['TOTAL']

    snapshots = env['vendor.sales.snapshot'].search([
        ('partner_id', '=', partner_id),
        ('company_id', '=', company_id),
        ('month', '>=', window_start),
    ])
    if not snapshots:
        return None

    unassigned_department = _get_unassigned_department(env)
    departments = {}
    cells = {}
    grand_total = 0.0

    for snapshot in snapshots:
        dept_key, dept_name = _snapshot_dept_key(
            snapshot.classification_department_id,
            unassigned_department,
        )
        departments[int(dept_key) if dept_key.isdigit() else UNASSIGNED_DEPARTMENT_ID] = dept_name
        if dept_key not in cells:
            cells[dept_key] = {month: 0.0 for month in display_months}
            cells[dept_key]['TOTAL'] = 0.0
        month_label = snapshot.month.strftime('%Y-%m')
        amount = float(snapshot.amount_total or 0.0)
        if month_label in cells[dept_key]:
            cells[dept_key][month_label] += amount
            cells[dept_key]['TOTAL'] += amount
            grand_total += amount

    department_rows = [
        {'id': dept_id, 'name': name}
        for dept_id, name in sorted(departments.items(), key=lambda item: item[1].lower())
    ]

    has_warning = False
    warning_message = False
    if grand_total == 0.0:
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


def get_sales_matrix_for_po(env, partner_id, company_id, reference_date=None):
    """Read cached snapshot when available; otherwise return an empty-state matrix."""
    matrix = matrix_from_snapshot(
        env,
        partner_id,
        company_id,
        reference_date=reference_date,
    )
    if matrix is not None:
        return matrix

    today = _reference_today(env, reference_date)
    month_labels = months_in_window(reference_date=today)
    return {
        'departments': [],
        'months': month_labels + ['TOTAL'],
        'cells': {},
        'total': 0.0,
        'has_warning': True,
        'warning': 'No hay datos de ventas en caché para este proveedor y sucursal — haga clic en Sincronizar OC.',
    }
