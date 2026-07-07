#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone CLI for Pagos Proveedores payment block parser (task 3.5).

Usage:
  source venv/bin/activate
  python scripts/payment_block_parser_standalone.py \\
    scripts/fixtures/pagos_proveedores_junio_2026.csv \\
    -o output/pagos_proveedores_junio_normalized.csv

  # Multiple files (e.g. cross-month upsert preview):
  python scripts/payment_block_parser_standalone.py junio.csv julio.csv -o merged.csv
"""

from __future__ import print_function

import argparse
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from po_vendor_sheet_parser import parse_csv_file
from po_vendor_sheet_parser.parser import invoices_to_csv_rows


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Parse Pagos Proveedores CSV exports into normalized invoice rows.',
    )
    parser.add_argument(
        'csv_files',
        nargs='+',
        help='One or more CSV exports of the Pagos Proveedores tab',
    )
    parser.add_argument(
        '-o', '--output',
        help='Write normalized CSV to this path (default: stdout)',
    )
    parser.add_argument(
        '--warnings-only',
        action='store_true',
        help='Print only warnings to stderr',
    )
    args = parser.parse_args(argv)

    all_invoices = []
    all_warnings = []
    stats_total = {
        'files': 0,
        'invoice_rows': 0,
        'paid': 0,
        'unpaid': 0,
        'block_warnings': 0,
    }

    for path in args.csv_files:
        if not os.path.isfile(path):
            sys.stderr.write('File not found: %s\n' % path)
            return 1
        result = parse_csv_file(path)
        stats_total['files'] += 1
        for key in ('invoice_rows', 'paid', 'unpaid', 'block_warnings'):
            stats_total[key] += result.stats.get(key, 0)
        prefix = os.path.basename(path)
        for w in result.warnings:
            all_warnings.append('[%s] %s' % (prefix, w))
        all_invoices.extend(result.invoices)

    # Cross-file duplicate keys (upsert preview)
    seen = {}
    for inv in all_invoices:
        key = (inv.sucursal, inv.no_factura)
        if key in seen:
            prev = seen[key]
            all_warnings.append(
                'Cross-file duplicate %s: row %s overwritten by row %s (pagado %s -> %s)'
                % (key, prev.sheet_row, inv.sheet_row, prev.pagado, inv.pagado)
            )
        seen[key] = inv

    if args.warnings_only:
        for w in all_warnings:
            print(w, file=sys.stderr)
        return 0

    rows = invoices_to_csv_rows(list(seen.values()) if len(args.csv_files) > 1 else all_invoices)

    if args.output:
        out_dir = os.path.dirname(args.output)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.output, 'w', newline='', encoding='utf-8') as handle:
            csv.writer(handle).writerows(rows)
        print('Wrote %s invoices to %s' % (len(rows) - 1, args.output), file=sys.stderr)
    else:
        writer = csv.writer(sys.stdout)
        writer.writerows(rows)

    print(
        'Parsed %(files)s file(s): %(invoice_rows)s invoices, %(paid)s paid, '
        '%(unpaid)s unpaid, %(block_warnings)s block warning(s), %(warn)s total warning(s)'
        % {
            'files': stats_total['files'],
            'invoice_rows': stats_total['invoice_rows'],
            'paid': stats_total['paid'],
            'unpaid': stats_total['unpaid'],
            'block_warnings': stats_total['block_warnings'],
            'warn': len(all_warnings),
        },
        file=sys.stderr,
    )
    for w in all_warnings[:20]:
        print('  WARN: %s' % w, file=sys.stderr)
    if len(all_warnings) > 20:
        print('  ... and %s more warnings' % (len(all_warnings) - 20), file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
