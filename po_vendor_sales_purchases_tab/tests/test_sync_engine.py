# -*- coding: utf-8 -*-
from datetime import date
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.po_vendor_sales_purchases_tab.services.sync_engine import (
    months_in_window,
    months_to_sync,
    run_global_sync,
    window_start_date,
)


def _invoice_row(no_factura, fecha, total, total_pago='', fecha_pago='', sucursal='RIO'):
    return {
        'Proveedor': 'Test Vendor',
        'Proveedor 2': '',
        'Ubicacion': sucursal,
        'No. Factura': no_factura,
        'Fecha': fecha,
        'Vence': fecha,
        'Total de Factura': total,
        'Total de pago': total_pago,
        'Fecha de pago': fecha_pago,
    }


def _ensure_month(env, config, name, spreadsheet_id, synced_once=False):
    """Create or update a month workbook row (safe on DBs with existing config)."""
    Month = env['vendor.sheet.month']
    month_rec = Month.search([
        ('config_id', '=', config.id),
        ('name', '=', name),
    ], limit=1)
    vals = {
        'spreadsheet_id': spreadsheet_id,
        'synced_once': synced_once,
    }
    if month_rec:
        month_rec.write(vals)
        return month_rec
    return Month.create({
        'config_id': config.id,
        'name': name,
        **vals,
    })


@tagged('post_install', '-at_install', 'po_vendor_sales_purchases_tab')
class TestSyncEngineHelpers(TransactionCase):
    def test_months_in_window(self):
        ref = date(2026, 7, 8)
        months = months_in_window(reference_date=ref)
        self.assertEqual(months, ['2026-04', '2026-05', '2026-06', '2026-07'])
        self.assertEqual(window_start_date(ref), date(2026, 4, 1))

    def test_months_in_window_year_boundary(self):
        ref = date(2026, 1, 15)
        months = months_in_window(reference_date=ref)
        self.assertEqual(months, ['2025-10', '2025-11', '2025-12', '2026-01'])
        self.assertEqual(window_start_date(ref), date(2025, 10, 1))

    def test_months_to_sync_skips_closed_synced_month(self):
        config = self.env['vendor.sheet.config'].get_singleton()
        june = _ensure_month(self.env, config, '2026-06', 'sheet-june', synced_once=True)
        _ensure_month(self.env, config, '2026-07', 'sheet-july', synced_once=False)
        window = ['2026-05', '2026-06', '2026-07']
        result = months_to_sync(config.sheet_month_ids, window, '2026-07')
        self.assertIn('2026-07', result)
        self.assertNotIn('2026-06', result)
        self.assertNotIn(june.name, [m for m in result if m != '2026-07' and june.synced_once])


@tagged('post_install', '-at_install', 'po_vendor_sales_purchases_tab')
class TestSyncEngine(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.vendor = self.env['res.partner'].create({
            'name': 'Convergram Mexico SA',
            'supplier_rank': 1,
        })
        SucursalMapping = self.env['vendor.sucursal.mapping']
        self.sucursal_mapping = SucursalMapping.search([
            ('sucursal', '=', 'RIO'),
        ], limit=1)
        if not self.sucursal_mapping:
            self.sucursal_mapping = SucursalMapping.create({
                'sucursal': 'RIO',
                'company_id': self.company.id,
            })
        VendorMapping = self.env['vendor.sheet.mapping']
        self.vendor_mapping = VendorMapping.search([
            ('sheet_proveedor', '=', 'Test Vendor'),
        ], limit=1)
        if not self.vendor_mapping:
            self.vendor_mapping = VendorMapping.create({
                'sheet_proveedor': 'Test Vendor',
                'partner_id': self.vendor.id,
            })
        self.config = self.env['vendor.sheet.config'].get_singleton()
        self.Month = self.env['vendor.sheet.month']
        self.Invoice = self.env['vendor.sheet.invoice']
        self.SyncLog = self.env['vendor.sheet.sync.log']

    def _prepare_months(self, reference_date, month_specs):
        """Configure only the months under test; skip others in the analysis window."""
        window = months_in_window(reference_date=reference_date)
        for month_label in window:
            if month_label in month_specs:
                spreadsheet_id, synced_once = month_specs[month_label]
                _ensure_month(
                    self.env,
                    self.config,
                    month_label,
                    spreadsheet_id,
                    synced_once=synced_once,
                )
                continue
            month_rec = self.Month.search([
                ('config_id', '=', self.config.id),
                ('name', '=', month_label),
            ], limit=1)
            if month_rec:
                month_rec.write({'synced_once': True})

    def _mock_client(self, sheet_data):
        client = MagicMock()
        client.fetch_sheet_rows.side_effect = (
            lambda spreadsheet_id, tab_name='Pagos Proveedores': sheet_data.get(spreadsheet_id, [])
        )
        return client

    def test_closed_month_synced_once_then_skipped(self):
        ref = date(2026, 7, 15)
        self._prepare_months(ref, {
            '2026-06': ('sheet-june', False),
            '2026-07': ('sheet-july', False),
        })
        june = self.Month.search([
            ('config_id', '=', self.config.id),
            ('name', '=', '2026-06'),
        ], limit=1)
        july = self.Month.search([
            ('config_id', '=', self.config.id),
            ('name', '=', '2026-07'),
        ], limit=1)
        sheet_data = {
            'sheet-june': [_invoice_row('JUN-001', '1/6/2026', '$100.00')],
            'sheet-july': [_invoice_row('JUL-001', '1/7/2026', '$200.00')],
        }
        client = self._mock_client(sheet_data)

        first = run_global_sync(
            self.env,
            sheets_client=client,
            reference_date=ref,
        )
        self.assertIsNone(first['error'])
        self.assertEqual(first['created'], 2)
        self.assertTrue(june.synced_once)
        self.assertTrue(july.synced_once)
        self.assertEqual(client.fetch_sheet_rows.call_count, 2)

        client.fetch_sheet_rows.reset_mock()
        second = run_global_sync(
            self.env,
            sheets_client=client,
            reference_date=ref,
        )
        self.assertIsNone(second['error'])
        self.assertEqual(second['created'], 0)
        self.assertEqual(second['updated'], 1)
        client.fetch_sheet_rows.assert_called_once_with('sheet-july')

    def test_current_month_resynced_every_run(self):
        ref = date(2026, 7, 15)
        self._prepare_months(ref, {
            '2026-06': ('sheet-june', True),
            '2026-07': ('sheet-july', True),
        })
        client = self._mock_client({
            'sheet-july': [_invoice_row('JUL-002', '5/7/2026', '$300.00')],
        })

        run_global_sync(self.env, sheets_client=client, reference_date=ref)
        run_global_sync(self.env, sheets_client=client, reference_date=ref)

        self.assertEqual(client.fetch_sheet_rows.call_count, 2)
        self.assertEqual(
            client.fetch_sheet_rows.call_args_list[0][0][0],
            'sheet-july',
        )

    def test_upsert_updates_payment_state_agd_200(self):
        ref = date(2026, 8, 15)
        self._prepare_months(ref, {
            '2026-07': ('sheet-july', True),
            '2026-08': ('sheet-august', False),
        })
        self.Invoice.create({
            'sucursal': 'RIO',
            'company_id': self.company.id,
            'proveedor': 'Test Vendor',
            'partner_id': self.vendor.id,
            'no_factura': 'AGD-200',
            'fecha': date(2026, 7, 28),
            'total_factura': 500.0,
            'pagado': False,
            'source_month': '2026-07',
        })
        client = self._mock_client({
            'sheet-august': [
                _invoice_row('AGD-200', '28/7/2026', '$500.00'),
                _invoice_row(
                    'AGD-201',
                    '1/8/2026',
                    '$500.00',
                    '$1000.00',
                    '15/8/2026',
                ),
            ],
        })

        result = run_global_sync(
            self.env,
            sheets_client=client,
            reference_date=ref,
        )
        self.assertIsNone(result['error'])
        invoice = self.Invoice.search([
            ('sucursal', '=', 'RIO'),
            ('no_factura', '=', 'AGD-200'),
        ], limit=1)
        self.assertTrue(invoice.pagado)
        self.assertEqual(invoice.fecha_pago, date(2026, 8, 15))
        self.assertEqual(invoice.monto_pago_grupo, 1000.0)
        self.assertEqual(invoice.facturas_en_grupo, 2)
        self.assertEqual(invoice.source_month, '2026-08')
        self.assertEqual(result['created'], 1)
        self.assertEqual(result['updated'], 1)
        client.fetch_sheet_rows.assert_called_once_with('sheet-august')

    def test_google_api_failure_aborts_sync(self):
        ref = date(2026, 7, 15)
        self._prepare_months(ref, {
            '2026-07': ('sheet-july', False),
        })
        before_invoices = self.Invoice.search_count([
            ('no_factura', 'in', ['JUN-001', 'JUL-001', 'JUL-002', 'AGD-200', 'INV-X']),
        ])
        client = MagicMock()
        client.fetch_sheet_rows.side_effect = UserError('Google Sheets API error')

        before_logs = self.SyncLog.search_count([])
        result = run_global_sync(
            self.env,
            sheets_client=client,
            reference_date=ref,
        )
        self.assertEqual(result['error'], 'Google Sheets API error')
        self.assertEqual(self.Invoice.search_count([
            ('no_factura', 'in', ['JUN-001', 'JUL-001', 'JUL-002', 'AGD-200', 'INV-X']),
        ]), before_invoices)
        self.assertEqual(self.SyncLog.search_count([]), before_logs + 1)
        last_log = self.SyncLog.search([], order='sync_date desc', limit=1)
        self.assertEqual(last_log.state, 'error')

    def test_global_sync_does_not_write_sales_snapshots(self):
        ref = date(2026, 7, 15)
        self._prepare_months(ref, {
            '2026-07': ('sheet-july', False),
        })
        client = self._mock_client({
            'sheet-july': [_invoice_row('JUL-001', '1/7/2026', '$200.00')],
        })
        Snapshot = self.env['vendor.sales.snapshot']
        before = Snapshot.search_count([])

        result = run_global_sync(
            self.env,
            sheets_client=client,
            reference_date=ref,
            refresh_sales_snapshots=False,
        )
        self.assertIsNone(result['error'])
        self.assertEqual(Snapshot.search_count([]), before)

        last_log = self.SyncLog.search([], order='sync_date desc', limit=1)
        self.assertEqual(last_log.sync_type, 'global')

    def test_global_sync_can_refresh_sales_when_requested(self):
        ref = date(2026, 7, 15)
        self._prepare_months(ref, {
            '2026-07': ('sheet-july', False),
        })
        client = self._mock_client({
            'sheet-july': [_invoice_row('JUL-001', '1/7/2026', '$200.00')],
        })

        with patch(
            'odoo.addons.po_vendor_sales_purchases_tab.services.sales_snapshot.recompute_all_sales_snapshots',
            return_value=3,
        ) as mock_recompute:
            run_global_sync(
                self.env,
                sheets_client=client,
                reference_date=ref,
                refresh_sales_snapshots=True,
            )
        mock_recompute.assert_called_once()

    def test_unmapped_sucursal_skips_row_with_warning(self):
        ref = date(2026, 7, 15)
        self._prepare_months(ref, {
            '2026-07': ('sheet-july', False),
        })
        before_invoices = self.Invoice.search_count([('no_factura', '=', 'INV-X')])
        client = self._mock_client({
            'sheet-july': [_invoice_row('INV-X', '1/7/2026', '$50.00', sucursal='UNKNOWN')],
        })

        result = run_global_sync(
            self.env,
            sheets_client=client,
            reference_date=ref,
        )
        self.assertEqual(self.Invoice.search_count([('no_factura', '=', 'INV-X')]), before_invoices)
        self.assertEqual(len(result['warnings']), 1)
        self.assertIn('Sucursal sin mapear', result['warnings'][0])

    def test_global_sync_creates_mapping_stub_for_new_proveedor(self):
        ref = date(2026, 7, 15)
        self._prepare_months(ref, {
            '2026-07': ('sheet-july', False),
        })
        self.env['vendor.sheet.mapping'].search([
            ('sheet_proveedor', '=', 'New Sheet Vendor'),
        ]).unlink()
        client = self._mock_client({})
        client.fetch_sheet_rows.side_effect = (
            lambda spreadsheet_id, tab_name='Pagos Proveedores': [
                dict(_invoice_row('INV-NEW', '1/7/2026', '$50.00'), Proveedor='New Sheet Vendor'),
            ]
        )

        result = run_global_sync(
            self.env,
            sheets_client=client,
            reference_date=ref,
        )
        self.assertIsNone(result['error'])
        stub = self.env['vendor.sheet.mapping'].search([
            ('sheet_proveedor', '=', 'New Sheet Vendor'),
        ], limit=1)
        self.assertTrue(stub)
        self.assertFalse(stub.partner_id)
        self.assertGreaterEqual(result['mappings_created'], 1)

    def test_global_sync_stub_creation_is_idempotent(self):
        ref = date(2026, 7, 15)
        self._prepare_months(ref, {
            '2026-07': ('sheet-july', False),
        })
        self.env['vendor.sheet.mapping'].search([
            ('sheet_proveedor', '=', 'Repeat Vendor'),
        ]).unlink()
        client = self._mock_client({})
        client.fetch_sheet_rows.side_effect = (
            lambda spreadsheet_id, tab_name='Pagos Proveedores': [
                dict(_invoice_row('INV-R1', '1/7/2026', '$50.00'), Proveedor='Repeat Vendor'),
            ]
        )

        first = run_global_sync(
            self.env,
            sheets_client=client,
            reference_date=ref,
        )
        stub = self.env['vendor.sheet.mapping'].search([
            ('sheet_proveedor', '=', 'Repeat Vendor'),
        ], limit=1)
        self.assertTrue(stub)
        self.assertFalse(stub.partner_id)
        self.assertGreaterEqual(first['mappings_created'], 1)

        second = run_global_sync(
            self.env,
            sheets_client=client,
            reference_date=ref,
        )
        stubs = self.env['vendor.sheet.mapping'].search([
            ('sheet_proveedor', '=', 'Repeat Vendor'),
        ])
        self.assertEqual(len(stubs), 1)
        self.assertFalse(stubs.partner_id)
        self.assertEqual(second['mappings_created'], 0)

    def test_global_sync_does_not_modify_existing_mapping(self):
        ref = date(2026, 7, 15)
        self._prepare_months(ref, {
            '2026-07': ('sheet-july', False),
        })
        existing = self.env['vendor.sheet.mapping'].create({
            'sheet_proveedor': 'Assigned Vendor',
            'partner_id': self.vendor.id,
        })
        client = self._mock_client({})
        client.fetch_sheet_rows.side_effect = (
            lambda spreadsheet_id, tab_name='Pagos Proveedores': [
                dict(_invoice_row('INV-A1', '1/7/2026', '$50.00'), Proveedor='Assigned Vendor'),
            ]
        )

        run_global_sync(
            self.env,
            sheets_client=client,
            reference_date=ref,
        )
        mapping = self.env['vendor.sheet.mapping'].browse(existing.id)
        self.assertEqual(mapping.partner_id, self.vendor)
        self.assertEqual(
            self.env['vendor.sheet.mapping'].search_count([
                ('sheet_proveedor', '=', 'Assigned Vendor'),
            ]),
            1,
        )

    def test_global_sync_creates_two_stubs_for_two_new_proveedores(self):
        ref = date(2026, 7, 15)
        self._prepare_months(ref, {
            '2026-07': ('sheet-july', False),
        })
        self.env['vendor.sheet.mapping'].search([
            ('sheet_proveedor', 'in', ['Vendor Alpha', 'Vendor Beta']),
        ]).unlink()
        client = self._mock_client({})
        client.fetch_sheet_rows.side_effect = (
            lambda spreadsheet_id, tab_name='Pagos Proveedores': [
                dict(_invoice_row('INV-A', '1/7/2026', '$50.00'), Proveedor='Vendor Alpha'),
                dict(_invoice_row('INV-B', '1/7/2026', '$60.00'), Proveedor='Vendor Beta'),
            ]
        )

        result = run_global_sync(
            self.env,
            sheets_client=client,
            reference_date=ref,
        )
        self.assertGreaterEqual(result['mappings_created'], 2)
        self.assertEqual(
            self.env['vendor.sheet.mapping'].search_count([
                ('sheet_proveedor', 'in', ['Vendor Alpha', 'Vendor Beta']),
                ('partner_id', '=', False),
            ]),
            2,
        )

    def test_global_sync_creates_stub_from_historical_staging(self):
        ref = date(2026, 7, 15)
        self._prepare_months(ref, {
            '2026-06': ('sheet-june', True),
            '2026-07': ('sheet-july', True),
        })
        historic_name = 'Historic Staging Only Vendor 20260708'
        self.env['vendor.sheet.mapping'].search([
            ('sheet_proveedor', '=', historic_name),
        ]).unlink()
        self.Invoice.create({
            'sucursal': 'RIO',
            'company_id': self.company.id,
            'proveedor': historic_name,
            'partner_id': False,
            'no_factura': 'HIST-001',
            'fecha': date(2026, 5, 1),
            'total_factura': 100.0,
            'source_month': '2026-05',
        })
        client = self._mock_client({
            'sheet-july': [_invoice_row('JUL-ONLY', '1/7/2026', '$10.00')],
        })

        run_global_sync(
            self.env,
            sheets_client=client,
            reference_date=ref,
        )
        stub = self.env['vendor.sheet.mapping'].search([
            ('sheet_proveedor', '=', historic_name),
        ], limit=1)
        self.assertTrue(stub)
        self.assertFalse(stub.partner_id)
