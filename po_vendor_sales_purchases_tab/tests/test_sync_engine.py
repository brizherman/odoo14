# -*- coding: utf-8 -*-
from datetime import date
from unittest.mock import MagicMock

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.po_vendor_sales_purchases_tab.services.sync_engine import (
    months_in_90_day_window,
    months_to_sync,
    run_global_sync,
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


@tagged('post_install', '-at_install', 'po_vendor_sales_purchases_tab')
class TestSyncEngineHelpers(TransactionCase):
    def test_months_in_90_day_window(self):
        ref = date(2026, 7, 7)
        months = months_in_90_day_window(reference_date=ref)
        self.assertEqual(months[0], '2026-04')
        self.assertEqual(months[-1], '2026-07')

    def test_months_to_sync_skips_closed_synced_month(self):
        Month = self.env['vendor.sheet.month']
        config = self.env['vendor.sheet.config'].get_singleton()
        june = Month.create({
            'config_id': config.id,
            'name': '2026-06',
            'spreadsheet_id': 'sheet-june',
            'synced_once': True,
        })
        july = Month.create({
            'config_id': config.id,
            'name': '2026-07',
            'spreadsheet_id': 'sheet-july',
            'synced_once': False,
        })
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
        self.env['vendor.sucursal.mapping'].create({
            'sucursal': 'RIO',
            'company_id': self.company.id,
        })
        self.env['vendor.sheet.mapping'].create({
            'sheet_proveedor': 'Test Vendor',
            'partner_id': self.vendor.id,
        })
        self.config = self.env['vendor.sheet.config'].get_singleton()
        self.Month = self.env['vendor.sheet.month']
        self.Invoice = self.env['vendor.sheet.invoice']
        self.SyncLog = self.env['vendor.sheet.sync.log']

    def _create_month(self, name, spreadsheet_id, synced_once=False):
        return self.Month.create({
            'config_id': self.config.id,
            'name': name,
            'spreadsheet_id': spreadsheet_id,
            'synced_once': synced_once,
        })

    def _mock_client(self, sheet_data):
        client = MagicMock()
        client.fetch_sheet_rows.side_effect = (
            lambda spreadsheet_id, tab_name='Pagos Proveedores': sheet_data.get(spreadsheet_id, [])
        )
        return client

    def test_closed_month_synced_once_then_skipped(self):
        ref = date(2026, 7, 15)
        june = self._create_month('2026-06', 'sheet-june', synced_once=False)
        july = self._create_month('2026-07', 'sheet-july', synced_once=False)
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
        self._create_month('2026-06', 'sheet-june', synced_once=True)
        self._create_month('2026-07', 'sheet-july', synced_once=True)
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
        self._create_month('2026-07', 'sheet-july', synced_once=True)
        self._create_month('2026-08', 'sheet-august', synced_once=False)
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
        self._create_month('2026-07', 'sheet-july', synced_once=False)
        client = MagicMock()
        client.fetch_sheet_rows.side_effect = UserError('Google Sheets API error')

        before_logs = self.SyncLog.search_count([])
        result = run_global_sync(
            self.env,
            sheets_client=client,
            reference_date=ref,
        )
        self.assertEqual(result['error'], 'Google Sheets API error')
        self.assertEqual(self.Invoice.search_count([]), 0)
        self.assertEqual(self.SyncLog.search_count([]), before_logs + 1)
        last_log = self.SyncLog.search([], order='sync_date desc', limit=1)
        self.assertEqual(last_log.state, 'error')

    def test_unmapped_sucursal_skips_row_with_warning(self):
        ref = date(2026, 7, 15)
        self._create_month('2026-07', 'sheet-july', synced_once=False)
        client = self._mock_client({
            'sheet-july': [_invoice_row('INV-X', '1/7/2026', '$50.00', sucursal='UNKNOWN')],
        })

        result = run_global_sync(
            self.env,
            sheets_client=client,
            reference_date=ref,
        )
        self.assertEqual(self.Invoice.search_count([]), 0)
        self.assertEqual(len(result['warnings']), 1)
        self.assertIn('Unmapped sucursal', result['warnings'][0])
