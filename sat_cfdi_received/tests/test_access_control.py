# -*- coding: utf-8 -*-
from datetime import date, datetime
from unittest.mock import patch

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.sat_cfdi_received.models.sat_security import SAT_FROM_PACKAGE_CTX


@tagged('post_install', '-at_install', 'sat_cfdi_received')
class TestSatAccessControl(TransactionCase):
    def setUp(self):
        super().setUp()
        self.group_user = self.env.ref('sat_cfdi_received.group_sat_user')
        self.group_manager = self.env.ref('sat_cfdi_received.group_sat_manager')
        self.sat_user = self.env['res.users'].create({
            'name': 'SAT User Test',
            'login': 'sat_user_test_%s_%s' % (self.env.cr.dbname, self.id()),
            'email': 'sat_user_test@example.com',
            'groups_id': [(6, 0, [self.group_user.id])],
        })
        self.sat_manager = self.env['res.users'].create({
            'name': 'SAT Manager Test',
            'login': 'sat_manager_test_%s_%s' % (self.env.cr.dbname, self.id()),
            'email': 'sat_manager_test@example.com',
            'groups_id': [(6, 0, [self.group_manager.id])],
        })

    def _cfdi_vals(self):
        return {
            'invoice_date': date(2026, 7, 5),
            'supplier_name': 'Proveedor ABC SA de CV',
            'total': 100.0,
            'uuid': 'ACCESS-UUID-0001-0000-000000000001',
            'company_id': self.env.company.id,
        }

    def test_sat_user_cannot_create_cfdi_directly(self):
        Cfdi = self.env['sat.cfdi.received'].with_user(self.sat_user)
        with self.assertRaises(AccessError):
            Cfdi.create(self._cfdi_vals())

    def test_sat_user_can_read_and_export_cfdi(self):
        cfdi = self.env['sat.cfdi.received'].with_context(
            **{SAT_FROM_PACKAGE_CTX: True}
        ).create(self._cfdi_vals())
        read = self.env['sat.cfdi.received'].with_user(self.sat_user).browse(cfdi.id)
        self.assertTrue(read.exists())
        action = read.action_export_csv()
        self.assertEqual(action['type'], 'ir.actions.act_url')

    def test_sat_user_cannot_create_download_request(self):
        Request = self.env['sat.download.request'].with_user(self.sat_user)
        with self.assertRaises(AccessError):
            Request.create({
                'date_from': datetime(2026, 7, 1, 0, 0, 0),
                'date_to': datetime(2026, 7, 10, 23, 59, 59),
                'company_id': self.env.company.id,
            })

    def test_sat_user_cannot_submit_download_request(self):
        request = self.env['sat.download.request'].create({
            'date_from': datetime(2026, 7, 1, 0, 0, 0),
            'date_to': datetime(2026, 7, 10, 23, 59, 59),
            'company_id': self.env.company.id,
        })
        with self.assertRaises(AccessError):
            request.with_user(self.sat_user).action_submit()

    def test_sat_manager_can_create_download_request(self):
        Request = self.env['sat.download.request'].with_user(self.sat_manager)
        request = Request.create({
            'date_from': datetime(2026, 7, 1, 0, 0, 0),
            'date_to': datetime(2026, 7, 10, 23, 59, 59),
            'company_id': self.env.company.id,
        })
        self.assertTrue(request.id)

    @patch('odoo.addons.sat_cfdi_received.models.sat_download_request.SatClient')
    def test_sat_manager_can_submit_download_request(self, mock_client_cls):
        import base64

        self.env.company.write({
            'sat_fiel_cer': base64.b64encode(b'cer'),
            'sat_fiel_key': base64.b64encode(b'key'),
            'sat_fiel_password': 'pass',
        })
        mock_client = mock_client_cls.from_company.return_value
        mock_client.request_received_download.return_value = 'REQ-ACCESS-001'

        request = self.env['sat.download.request'].with_user(self.sat_manager).create({
            'date_from': datetime(2026, 7, 1, 0, 0, 0),
            'date_to': datetime(2026, 7, 10, 23, 59, 59),
            'company_id': self.env.company.id,
        })
        request.action_submit()
        self.assertEqual(request.state, 'requested')

    def test_sat_user_cannot_run_download_wizard(self):
        Wizard = self.env['sat.download.wizard'].with_user(self.sat_user)
        with self.assertRaises(AccessError):
            Wizard.create({
                'date_from': datetime(2026, 7, 1, 0, 0, 0),
                'date_to': datetime(2026, 7, 10, 23, 59, 59),
                'company_id': self.env.company.id,
            })
