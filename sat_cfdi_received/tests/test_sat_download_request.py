# -*- coding: utf-8 -*-
from datetime import datetime
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.sat_cfdi_received.models.sat_security import SAT_FROM_PACKAGE_CTX
from odoo.addons.sat_cfdi_received.services.sat_client import SatNoDataError, SatTimeoutError


@tagged('post_install', '-at_install', 'sat_cfdi_received')
class TestSatDownloadRequest(TransactionCase):
    def setUp(self):
        super().setUp()
        import base64
        self.env.company.write({
            'sat_fiel_cer': base64.b64encode(b'cer'),
            'sat_fiel_key': base64.b64encode(b'key'),
            'sat_fiel_password': 'pass',
        })

    def _request_vals(self):
        return {
            'date_from': datetime(2026, 7, 1, 0, 0, 0),
            'date_to': datetime(2026, 7, 10, 23, 59, 59),
            'company_id': self.env.company.id,
        }

    def test_date_range_minimum_two_seconds(self):
        with self.assertRaises(ValidationError):
            self.env['sat.download.request'].create({
                'date_from': datetime(2026, 7, 1, 0, 0, 0),
                'date_to': datetime(2026, 7, 1, 0, 0, 1),
                'company_id': self.env.company.id,
            })

    def test_date_range_must_be_same_month(self):
        with self.assertRaises(ValidationError):
            self.env['sat.download.request'].create({
                'date_from': datetime(2026, 7, 15, 0, 0, 0),
                'date_to': datetime(2026, 8, 1, 0, 0, 0),
                'company_id': self.env.company.id,
            })

    def test_date_range_same_month_is_valid(self):
        request = self.env['sat.download.request'].create({
            'date_from': datetime(2026, 5, 15, 0, 0, 0),
            'date_to': datetime(2026, 5, 31, 23, 59, 59),
            'company_id': self.env.company.id,
        })
        self.assertTrue(request.id)

    @patch('odoo.addons.sat_cfdi_received.models.sat_download_request.SatClient')
    def test_submit_no_data_sets_no_data_state(self, mock_client_cls):
        mock_client = mock_client_cls.from_company.return_value
        mock_client.request_received_download.side_effect = SatNoDataError('No CFDIs found')

        request = self.env['sat.download.request'].create(self._request_vals())
        request.action_submit()
        self.assertEqual(request.state, 'no_data')
        self.assertFalse(request.error_message)

    @patch('odoo.addons.sat_cfdi_received.models.sat_download_request.SatClient')
    def test_check_status_unknown_state_sets_error(self, mock_client_cls):
        mock_client = mock_client_cls.from_company.return_value
        mock_client.check_request_status.return_value = {
            'internal_state': 'error',
            'package_ids': [],
            'message': 'Código de estatus de solicitud SAT desconocido: 99',
        }

        request = self.env['sat.download.request'].create(dict(self._request_vals(), state='requested'))
        request.sat_request_id = 'REQ-UNKNOWN'
        request.action_check_status()
        self.assertEqual(request.state, 'error')
        self.assertIn('estatus de solicitud SAT desconocido', request.error_message)

    @patch('odoo.addons.sat_cfdi_received.models.sat_download_request.SatClient')
    def test_timeout_keeps_pollable_state(self, mock_client_cls):
        mock_client = mock_client_cls.from_company.return_value
        mock_client.check_request_status.side_effect = SatTimeoutError(
            'El SAT no respondió a tiempo. Espere unos minutos y haga clic en Sincronizar desde el SAT de nuevo.'
        )

        request = self.env['sat.download.request'].create(dict(
            self._request_vals(),
            state='requested',
            sat_request_id='REQ-TIMEOUT',
        ))
        request.action_check_status()
        self.assertEqual(request.state, 'requested')
        self.assertIn('no respondió a tiempo', request.error_message)

    @patch('odoo.addons.sat_cfdi_received.models.sat_download_request.SatClient')
    def test_submit_blocked_when_sat_request_id_exists(self, mock_client_cls):
        request = self.env['sat.download.request'].create(dict(
            self._request_vals(),
            state='error',
            sat_request_id='REQ-EXISTING',
        ))
        with self.assertRaises(UserError):
            request.action_submit()
        mock_client_cls.from_company.assert_not_called()

    def test_reset_request_clears_sat_link(self):
        request = self.env['sat.download.request'].create(dict(
            self._request_vals(),
            state='error',
            sat_request_id='REQ-RESET',
            error_message='Old message',
        ))
        request.action_reset_request()
        self.assertEqual(request.state, 'draft')
        self.assertFalse(request.sat_request_id)
        self.assertFalse(request.error_message)

    @patch('odoo.addons.sat_cfdi_received.models.sat_download_request.SatClient.from_company')
    def test_process_packages_skips_duplicate_uuid(self, mock_from_company):
        import io
        import zipfile

        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    Fecha="2026-07-05T10:30:00" Total="100.00" Moneda="MXN">
    <cfdi:Emisor Rfc="ABC010101ABC" Nombre="Dup Supplier"/>
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
            UUID="DUP-UUID-0001-0000-000000000001"/>
    </cfdi:Complemento>
</cfdi:Comprobante>
"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('a.xml', xml)
            archive.writestr('b.xml', xml)
        zip_bytes = buffer.getvalue()

        mock_client = mock_from_company.return_value
        mock_client.download_package.return_value = zip_bytes

        self.env['sat.cfdi.received'].with_context(
            **{SAT_FROM_PACKAGE_CTX: True}
        ).create({
            'invoice_date': '2026-07-05',
            'supplier_name': 'Existing',
            'total': 100.0,
            'uuid': 'DUP-UUID-0001-0000-000000000001',
            'company_id': self.env.company.id,
        })

        request = self.env['sat.download.request'].create(dict(
            self._request_vals(),
            state='processing',
            package_ids='["PKG-001"]',
        ))
        request.action_process_packages()
        self.assertEqual(request.state, 'done')
        self.assertEqual(request.records_count, 0)
        count = self.env['sat.cfdi.received'].search_count([
            ('uuid', '=', 'DUP-UUID-0001-0000-000000000001'),
        ])
        self.assertEqual(count, 1)
