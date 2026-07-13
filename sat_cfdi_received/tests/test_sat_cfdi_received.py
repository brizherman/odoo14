# -*- coding: utf-8 -*-
from datetime import date

from odoo.exceptions import AccessError
from psycopg2 import IntegrityError

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.sat_cfdi_received.models.sat_security import SAT_FROM_PACKAGE_CTX


@tagged('post_install', '-at_install', 'sat_cfdi_received')
class TestSatCfdiReceived(TransactionCase):
    def _create_cfdi(self, vals):
        return self.env['sat.cfdi.received'].with_context(
            **{SAT_FROM_PACKAGE_CTX: True}
        ).create(vals)

    def test_create_record(self):
        record = self._create_cfdi({
            'invoice_date': date(2026, 7, 5),
            'supplier_name': 'Proveedor ABC SA de CV',
            'total': 15432.50,
            'uuid': 'A1B2C3D4-E5F6-7890-ABCD-EF1234567890',
            'supplier_rfc': 'ABC010101ABC',
            'currency': 'MXN',
            'company_id': self.env.company.id,
        })
        self.assertTrue(record.id)
        self.assertEqual(record.supplier_name, 'Proveedor ABC SA de CV')

    def test_direct_create_blocked_without_sat_context(self):
        with self.assertRaises(AccessError):
            self.env['sat.cfdi.received'].create({
                'invoice_date': date(2026, 7, 5),
                'supplier_name': 'Blocked',
                'total': 1.0,
                'uuid': 'BLOCKED-UUID-0001-0000-000000000001',
                'company_id': self.env.company.id,
            })

    def test_duplicate_uuid_skipped(self):
        Cfdi = self.env['sat.cfdi.received']
        vals = {
            'invoice_date': date(2026, 7, 5),
            'supplier_name': 'Proveedor ABC SA de CV',
            'total': 100.0,
            'uuid': 'DUPLICATE-UUID-0001-0000-000000000001',
            'company_id': self.env.company.id,
        }
        self._create_cfdi(vals)
        existing = Cfdi.search([
            ('company_id', '=', self.env.company.id),
            ('uuid', '=', vals['uuid']),
        ])
        self.assertEqual(len(existing), 1)

        with self.assertRaises(IntegrityError):
            with self.cr.savepoint():
                self._create_cfdi(vals)

    def test_create_from_sat_package_skips_duplicate(self):
        vals = {
            'invoice_date': date(2026, 7, 5),
            'supplier_name': 'Proveedor ABC SA de CV',
            'total': 100.0,
            'uuid': 'PACKAGE-DUP-0001-0000-000000000001',
            'company_id': self.env.company.id,
        }
        Cfdi = self.env['sat.cfdi.received']
        _, created_first = Cfdi.create_from_sat_package(vals, b'<xml/>')
        _, created_second = Cfdi.create_from_sat_package(vals, b'<xml/>')
        self.assertTrue(created_first)
        self.assertFalse(created_second)

    def test_export_csv_selected_records(self):
        Cfdi = self.env['sat.cfdi.received']
        r1 = self._create_cfdi({
            'invoice_date': date(2026, 7, 5),
            'supplier_name': 'Proveedor ABC, SA de CV',
            'total': 15432.50,
            'uuid': 'EXPORT-UUID-0001-0000-000000000001',
            'company_id': self.env.company.id,
        })
        r2 = self._create_cfdi({
            'invoice_date': date(2026, 7, 8),
            'supplier_name': 'Suministros XYZ',
            'total': 8200.00,
            'uuid': 'EXPORT-UUID-0002-0000-000000000002',
            'company_id': self.env.company.id,
        })
        action = (r1 + r2).action_export_csv()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertIn('/web/content/', action['url'])
