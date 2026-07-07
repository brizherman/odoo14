# -*- coding: utf-8 -*-
"""
Payment block parser for Google Sheets tab "Pagos Proveedores".

Reads non-normalized CSV exports where one payment row may cover multiple
invoice rows above it. Credit notes (NC*, NOTA DE CREDITO) subtract from
the block total. Rows without No. Factura act as block separators.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Sequence, Tuple

TOLERANCE = Decimal('0.01')

SPANISH_MONTHS = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
    'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
    'septiembre': 9, 'setiembre': 9, 'octubre': 10,
    'noviembre': 11, 'diciembre': 12,
}

COLUMN_ALIASES = {
    'proveedor': ('Proveedor',),
    'proveedor_2': ('Proveedor 2',),
    'sucursal': ('Ubicacion', 'Ubicación', 'Sucursal'),
    'no_factura': ('No. Factura', 'No Factura'),
    'fecha': ('Fecha',),
    'vence': ('Vence',),
    'total_factura': ('Total de Factura',),
    'total_pago': ('Total de pago',),
    'fecha_pago': ('Fecha de pago',),
}


@dataclass
class ParsedInvoice:
    proveedor: str
    proveedor_2: str
    sucursal: str
    no_factura: str
    fecha: Optional[date]
    vence: Optional[date]
    total_factura: Decimal
    pagado: bool
    fecha_pago: Optional[date]
    monto_pago_grupo: Optional[Decimal]
    facturas_en_grupo: int
    block_valid: bool
    warning_message: str
    sheet_row: int
    is_credit_note: bool = False


@dataclass
class ParseResult:
    invoices: List[ParsedInvoice] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)


def _normalize_header(value: str) -> str:
  return (value or '').strip()


def _build_column_map(headers: Sequence[str]) -> Dict[str, int]:
  normalized = {_normalize_header(h): i for i, h in enumerate(headers)}
  col: Dict[str, int] = {}
  for key, names in COLUMN_ALIASES.items():
    for name in names:
      if name in normalized:
        col[key] = normalized[name]
        break
  required = ('proveedor', 'sucursal', 'no_factura', 'total_factura', 'total_pago', 'fecha_pago')
  missing = [k for k in required if k not in col]
  if missing:
    raise ValueError('Missing required columns: %s (found: %s)' % (missing, list(normalized.keys())))
  for optional in ('proveedor_2', 'fecha', 'vence'):
    if optional not in col:
      col[optional] = -1
  return col


def parse_money(value: str) -> Optional[Decimal]:
  if value is None:
    return None
  text = str(value).strip()
  if not text or text in ('-', '#REF!', '#N/A'):
    return None
  text = text.replace('$', '').replace(',', '').strip()
  if not text:
    return None
  try:
    return Decimal(text)
  except (InvalidOperation, ValueError):
    return None


def _parse_spanish_date(text: str) -> Optional[date]:
  text = (text or '').strip().lower()
  if not text:
    return None
  match = re.match(r'^(\d{1,2})\s+([a-záéíóúñ]+)(?:\s+(\d{4}))?$', text)
  if match:
    day = int(match.group(1))
    month_name = match.group(2)
    month_name = ''.join(
      c for c in unicodedata.normalize('NFD', month_name)
      if unicodedata.category(c) != 'Mn'
    )
    month = SPANISH_MONTHS.get(month_name)
    if month:
      year = int(match.group(3)) if match.group(3) else 2026
      return date(year, month, day)
  parts = text.split('/')
  if len(parts) == 3:
    try:
      day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
      return date(year, month, day)
    except ValueError:
      return None
  return None


def parse_date(value: str) -> Optional[date]:
  if not value:
    return None
  return _parse_spanish_date(str(value).strip())


def _cell(row: Sequence[str], index: int) -> str:
  if index < 0 or index >= len(row):
    return ''
  return row[index]


def _pad_row(row: List[str], width: int) -> List[str]:
  while len(row) <= width:
    row.append('')
  return row


def _is_credit_note(sucursal: str, no_factura: str, proveedor_2: str) -> bool:
  sucursal_u = (sucursal or '').strip().upper()
  no_u = (no_factura or '').strip().upper()
  prov2_u = (proveedor_2 or '').strip().upper()
  if sucursal_u in ('NOTA DE CREDITO', 'NOTA DE CRÉDITO'):
    return True
  if no_u.startswith('NC'):
    return True
  if no_u.startswith('RF/'):
    return True
  if 'NOTA DE CREDITO' in prov2_u or 'NOTA DE CRÉDITO' in prov2_u:
    return True
  return False


def _signed_amount(total: Decimal, is_credit: bool) -> Decimal:
  amount = abs(total)
  return -amount if is_credit else amount


def _find_header_row(rows: Sequence[Sequence[str]]) -> int:
  for i, row in enumerate(rows):
    if row and _normalize_header(row[0]) == 'Proveedor':
      return i
  raise ValueError('Could not find header row starting with "Proveedor"')


def _collect_payment_block(raw_rows: List[List[str]], pay_idx: int, col: Dict[str, int]) -> List[int]:
  block = [pay_idx]
  j = pay_idx - 1
  while j >= 0:
    row = _pad_row(raw_rows[j], max(col.values()))
    if parse_money(_cell(row, col['total_pago'])) is not None:
      break
    if not _cell(row, col['no_factura']).strip():
      break
    block.insert(0, j)
    j -= 1
  return block


def _block_signed_total(raw_rows: List[List[str]], block_indices: Sequence[int], col: Dict[str, int]) -> Decimal:
  total = Decimal('0')
  for idx in block_indices:
    row = _pad_row(raw_rows[idx], max(col.values()))
    amount = parse_money(_cell(row, col['total_factura']))
    if amount is None:
      continue
    sucursal = _cell(row, col['sucursal']).strip()
    no_factura = _cell(row, col['no_factura']).strip()
    proveedor_2 = _cell(row, col['proveedor_2']).strip()
    is_credit = _is_credit_note(sucursal, no_factura, proveedor_2)
    total += _signed_amount(amount, is_credit)
  return total


def parse_sheet_rows(
  rows: Sequence[Sequence[str]],
  *,
  header_row_index: Optional[int] = None,
  sheet_row_offset: int = 0,
) -> ParseResult:
  header_idx = header_row_index if header_row_index is not None else _find_header_row(rows)
  headers = [_normalize_header(h) for h in rows[header_idx]]
  col = _build_column_map(headers)

  raw_rows = [list(r) for r in rows[header_idx + 1:]]
  result = ParseResult()
  current_proveedor = ''

  invoice_rows: List[Tuple[int, List[str]]] = []
  for i, row in enumerate(raw_rows):
    row = _pad_row(row, max(col.values()))
    raw_rows[i] = row
    if _cell(row, col['proveedor']).strip():
      current_proveedor = _cell(row, col['proveedor']).strip()
    if not _cell(row, col['no_factura']).strip():
      continue
    invoice_rows.append((i, row))

  paid_keys: Dict[Tuple[str, str], int] = {}
  block_assignments: Dict[int, dict] = {}

  for i, row in invoice_rows:
    pago = parse_money(_cell(row, col['total_pago']))
    if pago is None:
      continue
    block_idx = _collect_payment_block(raw_rows, i, col)
    block_sum = _block_signed_total(raw_rows, block_idx, col)
    block_valid = abs(block_sum - pago) <= TOLERANCE
    warning = ''
    if not block_valid:
      warning = (
        'Payment block sum mismatch: invoices net %(sum).2f != payment %(pay).2f '
        '(block size %(n)s, sheet rows %(rows)s)'
      ) % {
        'sum': float(block_sum),
        'pay': float(pago),
        'n': len(block_idx),
        'rows': ', '.join(str(header_idx + sheet_row_offset + 2 + b) for b in block_idx),
      }
      result.warnings.append(warning)

    fecha_pago = parse_date(_cell(row, col['fecha_pago']))
    for b in block_idx:
      block_assignments[b] = {
        'pagado': True,
        'fecha_pago': fecha_pago,
        'monto_pago_grupo': pago,
        'facturas_en_grupo': len(block_idx),
        'block_valid': block_valid,
        'warning_message': warning,
      }

  seen_keys: Dict[Tuple[str, str], int] = {}
  for i, row in invoice_rows:
    sucursal = _cell(row, col['sucursal']).strip() or 'SIN_SUCURSAL'
    no_factura = _cell(row, col['no_factura']).strip()
    key = (sucursal, no_factura)
    sheet_line = header_idx + sheet_row_offset + 2 + i

    if key in seen_keys:
      result.warnings.append(
        'Duplicate (sucursal, no_factura)=%s — last row wins (lines %s and %s)'
        % (key, seen_keys[key], sheet_line)
      )
    seen_keys[key] = sheet_line

    total = parse_money(_cell(row, col['total_factura'])) or Decimal('0')
    proveedor_2 = _cell(row, col['proveedor_2']).strip()
    is_credit = _is_credit_note(sucursal, no_factura, proveedor_2)
    assignment = block_assignments.get(i, {})

    proveedor = _cell(row, col['proveedor']).strip() or current_proveedor
    fecha = parse_date(_cell(row, col['fecha'])) if col['fecha'] >= 0 else None
    vence = parse_date(_cell(row, col['vence'])) if col['vence'] >= 0 else None

    invoice = ParsedInvoice(
      proveedor=proveedor,
      proveedor_2=proveedor_2,
      sucursal=sucursal,
      no_factura=no_factura,
      fecha=fecha,
      vence=vence,
      total_factura=total,
      pagado=assignment.get('pagado', False),
      fecha_pago=assignment.get('fecha_pago'),
      monto_pago_grupo=assignment.get('monto_pago_grupo'),
      facturas_en_grupo=assignment.get('facturas_en_grupo', 0),
      block_valid=assignment.get('block_valid', True) if assignment else True,
      warning_message=assignment.get('warning_message', ''),
      sheet_row=sheet_line,
      is_credit_note=is_credit,
    )
    result.invoices.append(invoice)
    if invoice.pagado:
      paid_keys[key] = sheet_line

  result.stats = {
    'invoice_rows': len(result.invoices),
    'paid': sum(1 for inv in result.invoices if inv.pagado),
    'unpaid': sum(1 for inv in result.invoices if not inv.pagado),
    'block_warnings': sum(1 for inv in result.invoices if inv.warning_message),
    'credit_notes': sum(1 for inv in result.invoices if inv.is_credit_note),
  }
  return result


def parse_csv_file(path: str, encoding: str = 'utf-8-sig') -> ParseResult:
  with open(path, newline='', encoding=encoding) as handle:
    rows = list(csv.reader(handle))
  return parse_sheet_rows(rows)


def invoices_to_csv_rows(invoices: Sequence[ParsedInvoice]) -> List[List[str]]:
  headers = [
    'sheet_row', 'proveedor', 'proveedor_2', 'sucursal', 'no_factura',
    'fecha', 'vence', 'total_factura', 'pagado', 'fecha_pago',
    'monto_pago_grupo', 'facturas_en_grupo', 'block_valid',
    'is_credit_note', 'warning_message',
  ]
  rows = [headers]
  for inv in invoices:
    rows.append([
      str(inv.sheet_row),
      inv.proveedor,
      inv.proveedor_2,
      inv.sucursal,
      inv.no_factura,
      inv.fecha.isoformat() if inv.fecha else '',
      inv.vence.isoformat() if inv.vence else '',
      str(inv.total_factura),
      '1' if inv.pagado else '0',
      inv.fecha_pago.isoformat() if inv.fecha_pago else '',
      str(inv.monto_pago_grupo) if inv.monto_pago_grupo is not None else '',
      str(inv.facturas_en_grupo),
      '1' if inv.block_valid else '0',
      '1' if inv.is_credit_note else '0',
      inv.warning_message,
    ])
  return rows
