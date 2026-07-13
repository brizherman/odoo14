# -*- coding: utf-8 -*-
"""Wrapper around SAT Descarga Masiva v1.5 via cfdiclient."""
import base64
import logging
import re

from odoo import _

from odoo.addons.sat_cfdi_received.services.rfc_utils import normalize_rfc, require_rfc
from odoo.addons.sat_cfdi_received.services.secret_store import decrypt_secret
from odoo.addons.sat_cfdi_received.services.zip_security import ZipSecurityError, extract_xmls_from_zip

_logger = logging.getLogger(__name__)

SAT_HTTP_RETRIES = 2
SAT_HTTP_TIMEOUT = 60
SAT_HTTP_TIMEOUT_DOWNLOAD = 90

try:
    from requests.exceptions import ConnectTimeout, ConnectionError as RequestsConnectionError
    from requests.exceptions import ReadTimeout
except ImportError:
    ReadTimeout = ConnectTimeout = RequestsConnectionError = Exception

SAT_STATUS_SUCCESS = '5000'
SAT_STATUS_LIFETIME_LIMIT = '5002'
SAT_STATUS_NO_DATA = '5004'
SAT_STATUS_DUPLICATE = '5005'

REQUEST_STATE_ACCEPTED = '1'
REQUEST_STATE_PROCESSING = '2'
REQUEST_STATE_DONE = '3'
REQUEST_STATE_ERROR = '4'
REQUEST_STATE_REJECTED = '5'
REQUEST_STATE_EXPIRED = '6'

REQUEST_STATE_LABELS = {
    REQUEST_STATE_ACCEPTED: 'accepted',
    REQUEST_STATE_PROCESSING: 'processing',
    REQUEST_STATE_DONE: 'done',
    REQUEST_STATE_ERROR: 'error',
    REQUEST_STATE_REJECTED: 'error',
    REQUEST_STATE_EXPIRED: 'error',
}


class SatClientError(Exception):
    """Base SAT client error."""


class SatAuthError(SatClientError):
    """FIEL authentication failed."""


class SatLifetimeLimitError(SatClientError):
    """SAT error 5002 — request limit for date range exceeded."""


class SatNoDataError(SatClientError):
    """SAT error 5004 — no CFDIs found for the range."""


class SatDuplicateRequestError(SatClientError):
    """SAT error 5005 — duplicate request for the same range."""


class SatRequestError(SatClientError):
    """Generic SAT request/verification error."""


class SatTimeoutError(SatClientError):
    """SAT did not respond within the allowed time (retryable)."""


class SatZipSecurityError(SatClientError):
    """Unsafe ZIP package from SAT download."""


def _import_cfdiclient():
    try:
        from cfdiclient import (
            Autenticacion,
            DescargaMasiva,
            Fiel,
            SolicitaDescargaRecibidos,
            VerificaSolicitudDescarga,
        )
    except ImportError as exc:
        raise SatClientError(
            _('El paquete Python cfdiclient no está instalado. '
              'Ejecute: pip install -r requirements.txt')
        ) from exc
    return Autenticacion, DescargaMasiva, Fiel, SolicitaDescargaRecibidos, VerificaSolicitudDescarga


def decode_binary_field(value):
    """Decode an Odoo Binary field value to raw bytes."""
    if not value:
        return None
    if isinstance(value, bytes):
        return base64.b64decode(value)
    return base64.b64decode(value.encode('utf-8'))


def rfc_from_certificate(cer_bytes):
    """Extract Mexican RFC from a FIEL certificate (DER or PEM)."""
    from OpenSSL import crypto

    try:
        cer_der = _ensure_der_certificate(cer_bytes)
        cert = crypto.load_certificate(crypto.FILETYPE_ASN1, cer_der)
    except Exception:
        return False
    rfc_pattern = re.compile(r'([A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3})')
    for component in cert.get_subject().get_components():
        value = component[1].decode('utf-8', errors='ignore').upper()
        match = rfc_pattern.search(value)
        if match:
            return normalize_rfc(match.group(1))
    return False


def _ensure_der_certificate(cer_bytes):
    from OpenSSL import crypto

    try:
        crypto.load_certificate(crypto.FILETYPE_ASN1, cer_bytes)
        return cer_bytes
    except crypto.Error:
        return crypto.dump_certificate(
            crypto.FILETYPE_ASN1,
            crypto.load_certificate(crypto.FILETYPE_PEM, cer_bytes),
        )


def _build_fiel(cer_bytes, key_bytes, password):
    cfdi = _import_cfdiclient()
    Fiel = cfdi[2]
    passphrase = (password or '').encode('utf-8')
    try:
        return Fiel(cer_bytes, key_bytes, passphrase)
    except (ValueError, TypeError) as exc:
        raise SatAuthError(_('Llave FIEL o contraseña inválida.')) from exc
    except Exception as exc:
        _logger.warning('FIEL load failed: %s', type(exc).__name__)
        raise SatAuthError(_('No se pudieron cargar las credenciales FIEL.')) from exc


def _check_cod_estatus(cod_estatus, mensaje):
    """Raise typed exceptions for known SAT CodEstatus values."""
    if cod_estatus == SAT_STATUS_SUCCESS:
        return
    message = mensaje or _('El SAT devolvió el estatus %s') % cod_estatus
    if cod_estatus == SAT_STATUS_LIFETIME_LIMIT:
        raise SatLifetimeLimitError(message)
    if cod_estatus == SAT_STATUS_NO_DATA:
        raise SatNoDataError(message)
    if cod_estatus == SAT_STATUS_DUPLICATE:
        raise SatDuplicateRequestError(message)
    raise SatRequestError(message)


def _map_request_state(state_code):
    if not state_code:
        return 'processing'
    internal = REQUEST_STATE_LABELS.get(state_code)
    if internal is None:
        return 'error'
    return internal


def _retry_sat_call(description, callback):
    """Retry transient SAT/network failures before surfacing a timeout to the user."""
    last_exc = None
    for attempt in range(1, SAT_HTTP_RETRIES + 1):
        try:
            return callback()
        except (ReadTimeout, ConnectTimeout, RequestsConnectionError) as exc:
            last_exc = exc
            _logger.warning(
                '%s failed (%s), attempt %s/%s',
                description,
                type(exc).__name__,
                attempt,
                SAT_HTTP_RETRIES,
            )
    raise SatTimeoutError(
        _('El SAT no respondió a tiempo. Espere unos minutos y haga clic en Sincronizar desde el SAT de nuevo.')
    ) from last_exc


class SatClient:
    """SAT Descarga Masiva v1.5 client using FIEL credentials."""

    def __init__(self, cer_bytes, key_bytes, password, rfc_solicitante):
        self._cer_bytes = cer_bytes
        self._key_bytes = key_bytes
        self._password = password
        self.rfc_solicitante = require_rfc(rfc_solicitante, label='SAT solicitante')
        self._fiel = None
        self._token = None

    @classmethod
    def from_company(cls, company):
        cer = decode_binary_field(company.sat_fiel_cer)
        key = decode_binary_field(company.sat_fiel_key)
        password = company._get_sat_fiel_password()
        if not cer or not key or not password:
            raise SatAuthError(_('Se requieren certificado FIEL, llave y contraseña.'))
        rfc = company._sat_fiel_rfc() or normalize_rfc(company.vat)
        if not rfc:
            raise SatAuthError(_('Se requiere el RFC de la empresa para las solicitudes al SAT.'))
        return cls(cer, key, password, rfc)

    def _get_fiel(self):
        if self._fiel is None:
            self._fiel = _build_fiel(self._cer_bytes, self._key_bytes, self._password)
        return self._fiel

    def authenticate(self):
        """Authenticate with SAT and return a session token."""
        Autenticacion = _import_cfdiclient()[0]
        try:
            auth = Autenticacion(self._get_fiel(), timeout=SAT_HTTP_TIMEOUT)
            self._token = auth.obtener_token()
        except SatClientError:
            raise
        except Exception as exc:
            _logger.warning('SAT authentication failed: %s', type(exc).__name__)
            raise SatAuthError(_('Falló la autenticación con el SAT. Verifique la vigencia de la FIEL y la contraseña.')) from exc
        if not self._token:
            raise SatAuthError(_('El SAT no devolvió un token de autenticación.'))
        return self._token

    def _token_or_authenticate(self):
        if not self._token:
            self.authenticate()
        return self._token

    def request_received_download(self, date_from, date_to, rfc_receptor=None):
        """Request a mass download of received CFDIs. Returns SAT id_solicitud."""
        SolicitaDescargaRecibidos = _import_cfdiclient()[3]
        token = self._token_or_authenticate()
        receptor = require_rfc(rfc_receptor or self.rfc_solicitante, label='RFC receptor')
        try:
            solicitud = SolicitaDescargaRecibidos(self._get_fiel(), timeout=SAT_HTTP_TIMEOUT)
            result = _retry_sat_call(
                'SAT download request',
                lambda: solicitud.solicitar_descarga(
                    token,
                    self.rfc_solicitante,
                    date_from,
                    date_to,
                    rfc_receptor=receptor,
                    tipo_solicitud='CFDI',
                    estado_comprobante='Vigente',
                ),
            )
        except SatClientError:
            raise
        except Exception as exc:
            _logger.warning('SAT download request failed: %s', type(exc).__name__)
            raise SatRequestError(_('Falló la solicitud de descarga al SAT.')) from exc

        _check_cod_estatus(result.get('cod_estatus'), result.get('mensaje'))
        id_solicitud = result.get('id_solicitud')
        if not id_solicitud:
            raise SatRequestError(_('El SAT no devolvió un ID de solicitud.'))
        return id_solicitud

    def check_request_status(self, id_solicitud):
        """Poll SAT for request status. Returns dict with state, packages, errors."""
        VerificaSolicitudDescarga = _import_cfdiclient()[4]
        token = self._token_or_authenticate()
        try:
            verifica = VerificaSolicitudDescarga(self._get_fiel(), timeout=SAT_HTTP_TIMEOUT)
            result = _retry_sat_call(
                'SAT status check',
                lambda: verifica.verificar_descarga(token, self.rfc_solicitante, id_solicitud),
            )
        except SatClientError:
            raise
        except Exception as exc:
            _logger.warning('SAT status check failed: %s', type(exc).__name__)
            raise SatRequestError(_('Falló la consulta de estatus al SAT.')) from exc

        cod_estatus = result.get('cod_estatus')
        if cod_estatus and cod_estatus != SAT_STATUS_SUCCESS:
            _check_cod_estatus(cod_estatus, result.get('mensaje'))

        # EstadoSolicitud is the workflow state (1-6). CodigoEstadoSolicitud is a
        # result code (5000, 5002, ...) and must not drive the Odoo state machine.
        state_code = str(result.get('estado_solicitud') or '')
        internal_state = _map_request_state(state_code)
        message = result.get('mensaje') or ''
        if internal_state == 'error' and state_code and state_code not in REQUEST_STATE_LABELS:
            message = message or _('Código de estatus de solicitud SAT desconocido: %s') % state_code
        return {
            'state_code': state_code,
            'internal_state': internal_state,
            'package_ids': result.get('paquetes') or [],
            'cfdi_count': int(result.get('numero_cfdis') or 0),
            'message': message,
            'status_label': result.get('estado_solicitud') or '',
            'result_code': str(result.get('codigo_estado_solicitud') or ''),
        }

    def download_package(self, id_paquete):
        """Download a ZIP package from SAT. Returns raw ZIP bytes."""
        DescargaMasiva = _import_cfdiclient()[1]
        token = self._token_or_authenticate()
        try:
            descarga = DescargaMasiva(self._get_fiel(), timeout=SAT_HTTP_TIMEOUT_DOWNLOAD)
            result = _retry_sat_call(
                'SAT package download',
                lambda: descarga.descargar_paquete(token, self.rfc_solicitante, id_paquete),
            )
        except SatClientError:
            raise
        except Exception as exc:
            _logger.warning('SAT package download failed: %s', type(exc).__name__)
            raise SatRequestError(_('Falló la descarga del paquete del SAT.')) from exc

        _check_cod_estatus(result.get('cod_estatus'), result.get('mensaje'))
        paquete_b64 = result.get('paquete_b64')
        if not paquete_b64:
            raise SatRequestError(_('El SAT devolvió un paquete vacío.'))
        return base64.b64decode(paquete_b64)

    @staticmethod
    def extract_xmls_from_zip(zip_bytes):
        """Extract XML file contents from a SAT download ZIP."""
        try:
            return extract_xmls_from_zip(zip_bytes)
        except ZipSecurityError as exc:
            raise SatZipSecurityError(str(exc)) from exc
