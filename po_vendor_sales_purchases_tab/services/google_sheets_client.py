# -*- coding: utf-8 -*-
import json
import logging

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

SCOPES = ('https://www.googleapis.com/auth/spreadsheets.readonly',)
DEFAULT_TAB_NAME = 'Pagos Proveedores'


class GoogleSheetsClient:
    """Read-only Google Sheets client using the module configuration."""

    def __init__(self, env):
        self.env = env

    def _get_service_account_info(self):
        config = self.env['vendor.sheet.config'].get_singleton()
        raw_json = (config.google_service_account_json or '').strip()
        if not raw_json:
            raise UserError(
                'El JSON de la cuenta de servicio de Google no está configurado. '
                'Abra la configuración de hoja de proveedor y pegue las credenciales.'
            )
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise UserError(
                'El JSON de la cuenta de servicio de Google no es válido. '
                'Pegue el archivo JSON completo de Google Cloud.'
            ) from exc

    def _get_tab_name(self, tab_name=None):
        if tab_name:
            name = tab_name.strip()
        else:
            config = self.env['vendor.sheet.config'].get_singleton()
            name = (config.sheet_tab_name or DEFAULT_TAB_NAME).strip()
        if not name:
            raise UserError(
                'El nombre de pestaña de hoja no está configurado. '
                'Abra la configuración de hoja de proveedor y establezca el nombre de pestaña.'
            )
        return name

    @staticmethod
    def _format_sheet_range(tab_name):
        """Quote tab names for Google Sheets A1 notation (required when name has spaces)."""
        escaped = tab_name.replace("'", "''")
        return "'%s'" % escaped

    @staticmethod
    def _list_sheet_titles(spreadsheet_meta):
        return [
            sheet['properties']['title']
            for sheet in spreadsheet_meta.get('sheets', [])
            if sheet.get('properties', {}).get('title') is not None
        ]

    @staticmethod
    def _resolve_tab_title(sheet_titles, configured_name):
        """Match configured tab name to an actual worksheet title."""
        if configured_name in sheet_titles:
            return configured_name

        normalized = configured_name.strip()
        stripped_matches = [
            title for title in sheet_titles
            if title.strip() == normalized
        ]
        if len(stripped_matches) == 1:
            return stripped_matches[0]
        if len(stripped_matches) > 1:
            raise UserError(
                'Múltiples pestañas de hoja coinciden con "%s": %s'
                % (configured_name, ', '.join(stripped_matches))
            )

        available = ', '.join(repr(title) for title in sheet_titles)
        raise UserError(
            'No se encontró la pestaña de hoja "%s". Pestañas disponibles: %s'
            % (configured_name, available)
        )

    def _get_spreadsheet_meta(self, service, spreadsheet_id):
        return service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields='sheets.properties.title',
        ).execute()

    def _resolve_tab_for_spreadsheet(self, service, spreadsheet_id, tab_name):
        meta = self._get_spreadsheet_meta(service, spreadsheet_id)
        sheet_titles = self._list_sheet_titles(meta)
        return self._resolve_tab_title(sheet_titles, tab_name)

    def _build_service(self):
        try:
            credentials = service_account.Credentials.from_service_account_info(
                self._get_service_account_info(),
                scopes=SCOPES,
            )
            return build(
                'sheets',
                'v4',
                credentials=credentials,
                cache_discovery=False,
            )
        except UserError:
            raise
        except Exception as exc:
            _logger.exception('Google Sheets authentication failed')
            raise UserError(
                'Error de autenticación con Google Sheets: %s' % exc
            ) from exc

    @staticmethod
    def _find_header_row(values, tab_name):
        for index, row in enumerate(values):
            if row and str(row[0]).strip() == 'Proveedor':
                return index
        raise UserError(
            'No se encontró la fila de encabezado que comienza con "Proveedor" en la pestaña "%s".'
            % tab_name
        )

    @staticmethod
    def _values_to_dict_rows(values, header_row_index):
        headers = [str(cell).strip() for cell in values[header_row_index]]
        dict_rows = []
        for row in values[header_row_index + 1:]:
            row_data = {}
            for col_index, header in enumerate(headers):
                if not header:
                    continue
                row_data[header] = row[col_index] if col_index < len(row) else ''
            dict_rows.append(row_data)
        return dict_rows

    def fetch_sheet_rows(self, spreadsheet_id, tab_name=None):
        """Fetch sheet values and return rows as dicts keyed by column header."""
        if not spreadsheet_id:
            raise UserError(
                'Falta el ID de hoja de cálculo para el libro de trabajo mensual seleccionado.'
            )

        tab_name = self._get_tab_name(tab_name)

        try:
            service = self._build_service()
            resolved_tab = self._resolve_tab_for_spreadsheet(
                service,
                spreadsheet_id,
                tab_name,
            )
            sheet_range = self._format_sheet_range(resolved_tab)
            result = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=sheet_range,
            ).execute()
        except HttpError as exc:
            _logger.exception('Google Sheets API request failed for %s', spreadsheet_id)
            status = getattr(exc.resp, 'status', None)
            if status == 403:
                message = (
                    'Acceso denegado a Google Sheets. Comparta la hoja de cálculo con el '
                    'correo de la cuenta de servicio de sus credenciales JSON.'
                )
            elif status == 404:
                message = 'Hoja de cálculo de Google no encontrada: %s' % spreadsheet_id
            elif status == 400 and 'Unable to parse range' in str(exc):
                try:
                    service = self._build_service()
                    meta = self._get_spreadsheet_meta(service, spreadsheet_id)
                    available = ', '.join(
                        repr(title) for title in self._list_sheet_titles(meta)
                    )
                    message = (
                        'No se encontró la pestaña de hoja "%s" en la hoja de cálculo %s. '
                        'Pestañas disponibles: %s'
                    ) % (tab_name, spreadsheet_id, available)
                except Exception:
                    message = 'Error de API de Google Sheets: %s' % exc
            else:
                message = 'Error de API de Google Sheets: %s' % exc
            raise UserError(message) from exc
        except UserError:
            raise
        except Exception as exc:
            _logger.exception('Google Sheets fetch failed for %s', spreadsheet_id)
            raise UserError('Error al obtener datos de Google Sheets: %s' % exc) from exc

        values = result.get('values', [])
        if not values:
            return []

        header_row_index = self._find_header_row(values, resolved_tab)
        return self._values_to_dict_rows(values, header_row_index)

    def fetch_sheet_values(self, spreadsheet_id, tab_name=None):
        """Return raw 2D values from the sheet (including header row)."""
        dict_rows = self.fetch_sheet_rows(spreadsheet_id, tab_name=tab_name)
        if not dict_rows:
            return []

        headers = list(dict_rows[0].keys())
        values = [headers]
        for row in dict_rows:
            values.append([row.get(header, '') for header in headers])
        return values
