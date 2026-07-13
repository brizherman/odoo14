# -*- coding: utf-8 -*-
from datetime import datetime
from unittest.mock import MagicMock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.sat_cfdi_received.services.sat_client import (
    SatAuthError,
    SatClient,
    SatDuplicateRequestError,
    SatLifetimeLimitError,
    SatNoDataError,
    SatTimeoutError,
    REQUEST_STATE_ACCEPTED,
    REQUEST_STATE_DONE,
    REQUEST_STATE_PROCESSING,
    SAT_HTTP_RETRIES,
    SAT_HTTP_TIMEOUT,
    SAT_HTTP_TIMEOUT_DOWNLOAD,
    _check_cod_estatus,
)


@tagged('post_install', '-at_install', 'sat_cfdi_received')
class TestSatClient(TransactionCase):
    def test_check_cod_estatus_success(self):
        _check_cod_estatus('5000', 'OK')

    def test_check_cod_estatus_no_data(self):
        with self.assertRaises(SatNoDataError):
            _check_cod_estatus('5004', 'No data')

    def test_check_cod_estatus_lifetime_limit(self):
        with self.assertRaises(SatLifetimeLimitError):
            _check_cod_estatus('5002', 'Limit exceeded')

    def test_check_cod_estatus_duplicate(self):
        with self.assertRaises(SatDuplicateRequestError):
            _check_cod_estatus('5005', 'Duplicate')

    @patch('odoo.addons.sat_cfdi_received.services.sat_client._import_cfdiclient')
    def test_authenticate_success(self, mock_import):
        mock_auth_cls = MagicMock()
        mock_auth = mock_auth_cls.return_value
        mock_auth.obtener_token.return_value = 'test-token-123'
        mock_fiel_cls = MagicMock()
        mock_import.return_value = (mock_auth_cls, MagicMock(), mock_fiel_cls, MagicMock(), MagicMock())

        client = SatClient(b'cer', b'key', 'pass', 'GMA121221Q79')
        token = client.authenticate()
        self.assertEqual(token, 'test-token-123')
        mock_auth_cls.assert_called_once()

    @patch('odoo.addons.sat_cfdi_received.services.sat_client._import_cfdiclient')
    def test_authenticate_failure(self, mock_import):
        mock_auth_cls = MagicMock()
        mock_auth_cls.return_value.obtener_token.side_effect = ValueError('bad key')
        mock_import.return_value = (mock_auth_cls, MagicMock(), MagicMock(), MagicMock(), MagicMock())

        client = SatClient(b'cer', b'key', 'wrong', 'GMA121221Q79')
        with self.assertRaises(SatAuthError):
            client.authenticate()

    @patch('odoo.addons.sat_cfdi_received.services.sat_client._import_cfdiclient')
    def test_request_received_download(self, mock_import):
        mock_solicita_cls = MagicMock()
        mock_solicita = mock_solicita_cls.return_value
        mock_solicita.solicitar_descarga.return_value = {
            'id_solicitud': 'REQ-001',
            'cod_estatus': '5000',
            'mensaje': 'OK',
        }
        mock_import.return_value = (MagicMock(), MagicMock(), MagicMock(), mock_solicita_cls, MagicMock())

        client = SatClient(b'cer', b'key', 'pass', 'GMA121221Q79')
        client._token = 'token'
        client._fiel = MagicMock()

        date_from = datetime(2026, 7, 1, 0, 0, 0)
        date_to = datetime(2026, 7, 10, 23, 59, 59)
        req_id = client.request_received_download(date_from, date_to)
        self.assertEqual(req_id, 'REQ-001')

    @patch('odoo.addons.sat_cfdi_received.services.sat_client._import_cfdiclient')
    def test_check_request_status_processing(self, mock_import):
        mock_verifica_cls = MagicMock()
        mock_verifica = mock_verifica_cls.return_value
        mock_verifica.verificar_descarga.return_value = {
            'cod_estatus': '5000',
            'codigo_estado_solicitud': '5000',
            'estado_solicitud': REQUEST_STATE_PROCESSING,
            'mensaje': '',
            'paquetes': [],
            'numero_cfdis': '0',
        }
        mock_import.return_value = (MagicMock(), MagicMock(), MagicMock(), MagicMock(), mock_verifica_cls)

        client = SatClient(b'cer', b'key', 'pass', 'GMA121221Q79')
        client._token = 'token'
        client._fiel = MagicMock()

        status = client.check_request_status('REQ-001')
        self.assertEqual(status['internal_state'], 'processing')
        self.assertEqual(status['package_ids'], [])

    @patch('odoo.addons.sat_cfdi_received.services.sat_client._import_cfdiclient')
    def test_check_request_status_accepted_not_error(self, mock_import):
        """Regression: CodigoEstadoSolicitud 5000 must not be treated as workflow state."""
        mock_verifica_cls = MagicMock()
        mock_verifica = mock_verifica_cls.return_value
        mock_verifica.verificar_descarga.return_value = {
            'cod_estatus': '5000',
            'codigo_estado_solicitud': '5000',
            'estado_solicitud': REQUEST_STATE_ACCEPTED,
            'mensaje': 'Solicitud Aceptada',
            'paquetes': [],
            'numero_cfdis': '0',
        }
        mock_import.return_value = (MagicMock(), MagicMock(), MagicMock(), MagicMock(), mock_verifica_cls)

        client = SatClient(b'cer', b'key', 'pass', 'GMA121221Q79')
        client._token = 'token'
        client._fiel = MagicMock()

        status = client.check_request_status('REQ-001')
        self.assertEqual(status['internal_state'], 'accepted')
        self.assertEqual(status['message'], 'Solicitud Aceptada')
        self.assertEqual(status['result_code'], '5000')

    @patch('odoo.addons.sat_cfdi_received.services.sat_client._import_cfdiclient')
    def test_check_request_status_unknown_state(self, mock_import):
        mock_verifica_cls = MagicMock()
        mock_verifica = mock_verifica_cls.return_value
        mock_verifica.verificar_descarga.return_value = {
            'cod_estatus': '5000',
            'codigo_estado_solicitud': '5000',
            'estado_solicitud': '99',
            'mensaje': '',
            'paquetes': [],
            'numero_cfdis': '0',
        }
        mock_import.return_value = (MagicMock(), MagicMock(), MagicMock(), MagicMock(), mock_verifica_cls)

        client = SatClient(b'cer', b'key', 'pass', 'GMA121221Q79')
        client._token = 'token'
        client._fiel = MagicMock()

        status = client.check_request_status('REQ-001')
        self.assertEqual(status['internal_state'], 'error')
        self.assertIn('estatus de solicitud SAT desconocido', status['message'])

    @patch('odoo.addons.sat_cfdi_received.services.sat_client._import_cfdiclient')
    def test_check_request_status_done(self, mock_import):
        mock_verifica_cls = MagicMock()
        mock_verifica = mock_verifica_cls.return_value
        mock_verifica.verificar_descarga.return_value = {
            'cod_estatus': '5000',
            'codigo_estado_solicitud': '5000',
            'estado_solicitud': REQUEST_STATE_DONE,
            'mensaje': '',
            'paquetes': ['PKG-001'],
            'numero_cfdis': '2',
        }
        mock_import.return_value = (MagicMock(), MagicMock(), MagicMock(), MagicMock(), mock_verifica_cls)

        client = SatClient(b'cer', b'key', 'pass', 'GMA121221Q79')
        client._token = 'token'
        client._fiel = MagicMock()

        status = client.check_request_status('REQ-001')
        self.assertEqual(status['internal_state'], 'done')
        self.assertEqual(status['package_ids'], ['PKG-001'])

    @patch('odoo.addons.sat_cfdi_received.services.sat_client._import_cfdiclient')
    def test_download_package(self, mock_import):
        import base64

        mock_descarga_cls = MagicMock()
        mock_descarga = mock_descarga_cls.return_value
        mock_descarga.descargar_paquete.return_value = {
            'cod_estatus': '5000',
            'mensaje': 'OK',
            'paquete_b64': base64.b64encode(b'PK\x03\x04fake').decode('ascii'),
        }
        mock_import.return_value = (MagicMock(), mock_descarga_cls, MagicMock(), MagicMock(), MagicMock())

        client = SatClient(b'cer', b'key', 'pass', 'GMA121221Q79')
        client._token = 'token'
        client._fiel = MagicMock()

        data = client.download_package('PKG-001')
        self.assertEqual(data, b'PK\x03\x04fake')
        mock_descarga_cls.assert_called_once_with(client._fiel, timeout=SAT_HTTP_TIMEOUT_DOWNLOAD)

    @patch('odoo.addons.sat_cfdi_received.services.sat_client._import_cfdiclient')
    def test_check_request_status_retries_twice_on_timeout(self, mock_import):
        from requests.exceptions import ReadTimeout

        mock_verifica_cls = MagicMock()
        mock_verifica = mock_verifica_cls.return_value
        mock_verifica.verificar_descarga.side_effect = ReadTimeout('slow')
        mock_import.return_value = (MagicMock(), MagicMock(), MagicMock(), MagicMock(), mock_verifica_cls)

        client = SatClient(b'cer', b'key', 'pass', 'GMA121221Q79')
        client._token = 'token'
        client._fiel = MagicMock()

        with self.assertRaises(SatTimeoutError):
            client.check_request_status('REQ-001')

        self.assertEqual(mock_verifica.verificar_descarga.call_count, SAT_HTTP_RETRIES)
        mock_verifica_cls.assert_called_once_with(client._fiel, timeout=SAT_HTTP_TIMEOUT)
