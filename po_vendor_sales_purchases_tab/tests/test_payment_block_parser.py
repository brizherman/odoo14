# -*- coding: utf-8 -*-
import csv
import io
import os
from decimal import Decimal

from odoo.tests import tagged
from odoo.tests.common import BaseCase

from odoo.addons.po_vendor_sales_purchases_tab.scripts.po_vendor_sheet_parser.parser import (
    parse_csv_file,
    parse_date,
    parse_money,
    parse_sheet_rows,
)
from odoo.addons.po_vendor_sales_purchases_tab.services import payment_block_parser


FIXTURES = os.path.join(
    os.path.dirname(__file__),
    '..',
    'scripts',
    'fixtures',
)

SAMPLE_HEADER = (
    'Proveedor,Proveedor 2,Ubicacion,No. Factura,Fecha,Vence,Total de Factura,'
    'Total de pago,Fecha de pago,Saldo x proveedor\n'
)


def _fixture(name):
    return os.path.join(FIXTURES, name)


@tagged('post_install', '-at_install', 'po_vendor_sales_purchases_tab')
class TestPaymentBlockParserHelpers(BaseCase):
    def test_parse_money(self):
        self.assertEqual(parse_money(' $ 1,288.16 '), Decimal('1288.16'))
        self.assertIsNone(parse_money(''))
        self.assertIsNone(parse_money('#REF!'))

    def test_parse_date_slash(self):
        self.assertEqual(str(parse_date('12/6/2026')), '2026-06-12')

    def test_parse_date_spanish(self):
        self.assertEqual(str(parse_date('4 junio')), '2026-06-04')
        self.assertEqual(str(parse_date('22 junio')), '2026-06-22')


@tagged('post_install', '-at_install', 'po_vendor_sales_purchases_tab')
class TestPaymentBlockParser(BaseCase):
    def _parse(self, body):
        text = SAMPLE_HEADER + body
        rows = list(csv.reader(io.StringIO(text)))
        return parse_sheet_rows(rows)

    def test_single_unpaid_invoice(self):
        result = self._parse(
            'VENDOR,,RIO,INV-001,1/6/2026,15/6/2026,$100.00,,,\n'
        )
        self.assertEqual(len(result.invoices), 1)
        inv = result.invoices[0]
        self.assertFalse(inv.pagado)
        self.assertEqual(inv.total_factura, Decimal('100.00'))

    def test_two_invoice_paid_block(self):
        result = self._parse(
            'AVANCE,,RIO,FV1002702746,14/5/2026,28/5/2026,$923.97,,,\n'
            'AVANCE,,INSURGENTES,FV1002726320,1/6/2026,16/6/2026,"$1,288.16","$2,212.13",12/6/2026,\n'
        )
        self.assertEqual(len(result.invoices), 2)
        for inv in result.invoices:
            self.assertTrue(inv.pagado)
            self.assertEqual(inv.fecha_pago.isoformat(), '2026-06-12')
            self.assertEqual(inv.monto_pago_grupo, Decimal('2212.13'))
            self.assertEqual(inv.facturas_en_grupo, 2)
            self.assertTrue(inv.block_valid)

    def test_block_sum_mismatch_flags_warning(self):
        result = self._parse(
            'VENDOR,,RIO,INV-A,1/6/2026,15/6/2026,$100.00,,,\n'
            'VENDOR,,RIO,INV-B,2/6/2026,16/6/2026,$200.00,$500.00,10/6/2026,\n'
        )
        inv_b = result.invoices[1]
        self.assertTrue(inv_b.pagado)
        self.assertFalse(inv_b.block_valid)
        self.assertIn('desajuste', inv_b.warning_message.lower())

    def test_separator_row_breaks_block(self):
        result = self._parse(
            'CORP,,RIO,INV50205,17/4/2026,22/5/2026,"$1,502.17",,,\n'
            'CORP,,INSURGENTES,INV50214,17/4/2026,22/5/2026,"$11,807.63",,,\n'
            'CORP,,,,,,,,,\n'
            'OTHER,,RIO,OTHER-001,1/6/2026,15/6/2026,$50.00,$50.00,8/6/2026,\n'
        )
        other = result.invoices[-1]
        self.assertEqual(other.no_factura, 'OTHER-001')
        self.assertTrue(other.block_valid)
        self.assertEqual(other.facturas_en_grupo, 1)

    def test_credit_notes_subtract_in_block(self):
        result = self._parse(
            'GRANMARK,REGALOS,INSURGENTES,SS2220926,23/4/2026,7/6/2026,"$12,763.80",,,\n'
            'GRANMARK,,NOTA DE CREDITO,NC678692,11/6/2026,26/7/2026,$638.19,,,\n'
            'GRANMARK,REGALOS,INSURGENTES,SS2221172,27/4/2026,11/6/2026,"$25,027.51",,,\n'
            'GRANMARK,,NOTA DE CREDITO,NC678697,11/6/2026,26/7/2026,"$1,251.37","$35,901.75",24 junio,\n'
        )
        nc = [i for i in result.invoices if i.no_factura == 'NC678697'][0]
        self.assertTrue(nc.pagado)
        self.assertTrue(nc.block_valid)
        self.assertEqual(nc.monto_pago_grupo, Decimal('35901.75'))

    def test_duplicate_key_warning(self):
        result = self._parse(
            'VENDOR,,RIO,DUP-001,1/6/2026,15/6/2026,$100.00,,,\n'
            'VENDOR,,RIO,DUP-001,2/6/2026,16/6/2026,$200.00,,,\n'
        )
        self.assertTrue(any('Duplicado' in w for w in result.warnings))
        self.assertEqual(result.invoices[-1].total_factura, Decimal('200.00'))

    def test_odoo_adapter_parse_dict_rows(self):
        dict_rows = [{
            'Proveedor': 'VENDOR',
            'Proveedor 2': '',
            'Ubicacion': 'RIO',
            'No. Factura': 'INV-001',
            'Fecha': '1/6/2026',
            'Vence': '15/6/2026',
            'Total de Factura': '$100.00',
            'Total de pago': '',
            'Fecha de pago': '',
        }]
        result = payment_block_parser.parse_dict_rows(dict_rows)
        self.assertEqual(len(result.invoices), 1)
        self.assertFalse(result.invoices[0].pagado)


@tagged('post_install', '-at_install', 'po_vendor_sales_purchases_tab')
class TestPaymentBlockParserFixtures(BaseCase):
    def test_junio_fixture_parses(self):
        if not os.path.isfile(_fixture('pagos_proveedores_junio_2026.csv')):
            self.skipTest('June fixture missing')
        result = parse_csv_file(_fixture('pagos_proveedores_junio_2026.csv'))
        self.assertGreater(result.stats['invoice_rows'], 400)
        self.assertGreater(result.stats['paid'], 0)
        self.assertGreater(result.stats['unpaid'], 0)

    def test_avance_block_from_junio(self):
        if not os.path.isfile(_fixture('pagos_proveedores_junio_2026.csv')):
            self.skipTest('June fixture missing')
        result = parse_csv_file(_fixture('pagos_proveedores_junio_2026.csv'))
        by_no = {i.no_factura: i for i in result.invoices}
        self.assertTrue(by_no['FV1002702746'].pagado)
        self.assertTrue(by_no['FV1002726320'].pagado)
        self.assertFalse(by_no['FV1002748472'].pagado)
        self.assertEqual(by_no['FV1002726320'].monto_pago_grupo, Decimal('2212.13'))

    def test_corporacion_impresora_block_from_junio(self):
        if not os.path.isfile(_fixture('pagos_proveedores_junio_2026.csv')):
            self.skipTest('June fixture missing')
        result = parse_csv_file(_fixture('pagos_proveedores_junio_2026.csv'))
        by_no = {i.no_factura: i for i in result.invoices}
        inv50230 = by_no['INV50230']
        self.assertTrue(inv50230.pagado)
        self.assertTrue(inv50230.block_valid)
        self.assertEqual(inv50230.monto_pago_grupo, Decimal('114849.37'))
        self.assertEqual(inv50230.facturas_en_grupo, 5)

    def test_julio_has_unpaid_invoices(self):
        if not os.path.isfile(_fixture('pagos_proveedores_julio_2026.csv')):
            self.skipTest('July fixture missing')
        result = parse_csv_file(_fixture('pagos_proveedores_julio_2026.csv'))
        self.assertGreater(result.stats['unpaid'], 0)
