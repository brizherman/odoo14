# -*- coding: utf-8 -*-
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.sat_cfdi_received.models.sat_security import check_sat_manager
from odoo.addons.sat_cfdi_received.services.download_date_range import validate_download_date_range
from odoo.addons.sat_cfdi_received.services.rfc_utils import rfc_from_vat
from odoo.addons.sat_cfdi_received.services.sat_client import (
    SatClient,
    SatClientError,
    SatNoDataError,
    SatTimeoutError,
)
from odoo.addons.sat_cfdi_received.services.xml_parser import XmlParserError, parse_received_cfdi

_logger = logging.getLogger(__name__)


class SatDownloadRequest(models.Model):
    _name = 'sat.download.request'
    _description = 'Solicitud de descarga de CFDIs del SAT'
    _order = 'create_date desc, id desc'

    name = fields.Char(
        string='Referencia',
        compute='_compute_name',
        store=True,
    )
    date_from = fields.Datetime(string='Desde', required=True)
    date_to = fields.Datetime(string='Hasta', required=True)
    state = fields.Selection(
        selection=[
            ('draft', 'Borrador'),
            ('requested', 'Solicitado'),
            ('processing', 'En proceso'),
            ('done', 'Completado'),
            ('no_data', 'Sin CFDIs encontrados'),
            ('error', 'Error'),
        ],
        string='Estado',
        default='draft',
        required=True,
    )
    sat_request_id = fields.Char(string='ID de solicitud SAT', readonly=True, copy=False)
    package_ids = fields.Text(string='IDs de paquetes', readonly=True, copy=False)
    has_packages = fields.Boolean(string='Tiene paquetes', compute='_compute_has_packages', store=True)
    records_count = fields.Integer(string='Registros creados', readonly=True, default=0)
    error_message = fields.Text(string='Mensaje de estado', readonly=True, copy=False)
    last_check_date = fields.Datetime(string='Última consulta', readonly=True, copy=False)
    company_id = fields.Many2one(
        'res.company',
        string='Empresa',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    cfdi_ids = fields.One2many(
        'sat.cfdi.received',
        'download_request_id',
        string='CFDIs recibidos',
        readonly=True,
    )

    _sql_constraints = [
        (
            'date_range_check',
            'CHECK(date_from < date_to)',
            'La fecha inicial debe ser anterior a la fecha final.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        check_sat_manager(self.env)
        return super().create(vals_list)

    def write(self, vals):
        allowed = {'state', 'sat_request_id', 'package_ids', 'has_packages', 'records_count',
                   'error_message', 'last_check_date'}
        if set(vals) - allowed:
            check_sat_manager(self.env)
        return super().write(vals)

    @api.constrains('date_from', 'date_to')
    def _check_date_range(self):
        for record in self:
            validate_download_date_range(record, record.date_from, record.date_to)

    @api.depends('date_from', 'date_to', 'company_id')
    def _compute_name(self):
        for record in self:
            if record.date_from and record.date_to:
                date_from = fields.Datetime.to_string(record.date_from)[:10]
                date_to = fields.Datetime.to_string(record.date_to)[:10]
                record.name = '%s → %s' % (date_from, date_to)
            else:
                record.name = _('Descarga SAT')

    @api.depends('package_ids')
    def _compute_has_packages(self):
        for record in self:
            record.has_packages = bool(record._get_package_ids())

    def _get_sat_client(self):
        self.ensure_one()
        if not self.company_id.sat_fiel_configured:
            raise UserError(_('Configure la FIEL en la empresa %s antes de descargar.') % self.company_id.name)
        if self.company_id.sat_fiel_rfc_mismatch:
            raise UserError(_('El RFC del certificado FIEL no coincide con el RFC de la empresa.'))
        return SatClient.from_company(self.company_id)

    def _set_package_ids(self, package_list):
        self.package_ids = json.dumps(package_list or [])

    def _get_package_ids(self):
        self.ensure_one()
        if not self.package_ids:
            return []
        try:
            return json.loads(self.package_ids)
        except (TypeError, ValueError):
            return []

    def _waiting_message(self):
        return _(
            'Solicitud enviada al SAT. Los paquetes pueden tardar unos minutos en prepararse. '
            'Haga clic en Sincronizar desde el SAT más tarde.'
        )

    def _apply_status_result(self, status):
        """Apply SAT poll result and optionally download packages."""
        self.ensure_one()
        internal = status['internal_state']
        if internal in ('processing', 'accepted'):
            self.write({
                'state': 'processing',
                'error_message': status.get('message') or self._waiting_message(),
                'last_check_date': fields.Datetime.now(),
            })
            return

        if internal == 'done':
            self._set_package_ids(status['package_ids'])
            self.write({'last_check_date': fields.Datetime.now()})
            if status['package_ids']:
                self.write({'state': 'processing', 'error_message': False})
                self.action_process_packages()
            else:
                self.write({
                    'state': 'done',
                    'records_count': 0,
                    'error_message': status.get('message') or False,
                })
            return

        if internal == 'error':
            self.write({
                'state': 'error',
                'error_message': status.get('message') or _('El SAT reportó un error para esta solicitud.'),
                'last_check_date': fields.Datetime.now(),
            })

    def action_submit(self):
        check_sat_manager(self.env)
        for record in self:
            if record.state not in ('draft', 'error'):
                continue
            if record.sat_request_id:
                raise UserError(_(
                    'Esta solicitud ya fue enviada al SAT (ID: %s). '
                    'Use Sincronizar desde el SAT para consultar el estatus, o Reiniciar para comenzar de nuevo.'
                ) % record.sat_request_id)
            record.error_message = False
            try:
                client = record._get_sat_client()
                rfc = record.company_id._sat_fiel_rfc() or rfc_from_vat(record.company_id.vat)
                sat_id = client.request_received_download(
                    record.date_from,
                    record.date_to,
                    rfc_receptor=rfc,
                )
            except SatNoDataError:
                record.write({
                    'state': 'no_data',
                    'records_count': 0,
                    'error_message': False,
                })
                continue
            except SatClientError as exc:
                record.write({
                    'state': 'error',
                    'error_message': str(exc),
                })
                continue
            except Exception as exc:
                _logger.warning(
                    'SAT submit failed for request %s: %s',
                    record.id,
                    type(exc).__name__,
                )
                record.write({
                    'state': 'error',
                    'error_message': _('Error inesperado al enviar la solicitud al SAT.'),
                })
                continue

            record.write({
                'sat_request_id': sat_id,
                'state': 'requested',
                'package_ids': False,
                'records_count': 0,
                'error_message': record._waiting_message(),
            })
        return True

    def action_check_status(self):
        check_sat_manager(self.env)
        for record in self:
            if not record.sat_request_id:
                raise UserError(_('No hay ID de solicitud SAT. Envíe la descarga primero.'))
            if record.state in ('done', 'draft', 'no_data'):
                continue
            previous_state = record.state if record.state in ('requested', 'processing') else 'requested'
            try:
                client = record._get_sat_client()
                status = client.check_request_status(record.sat_request_id)
            except SatTimeoutError as exc:
                record.write({
                    'state': previous_state,
                    'error_message': str(exc),
                    'last_check_date': fields.Datetime.now(),
                })
                continue
            except SatClientError as exc:
                record.write({
                    'state': 'error',
                    'error_message': str(exc),
                    'last_check_date': fields.Datetime.now(),
                })
                continue
            except Exception as exc:
                _logger.warning(
                    'SAT status check failed for request %s: %s',
                    record.id,
                    type(exc).__name__,
                )
                record.write({
                    'state': 'error',
                    'error_message': _('Error inesperado al consultar el estatus en el SAT.'),
                    'last_check_date': fields.Datetime.now(),
                })
                continue

            record._apply_status_result(status)
        return True

    def action_check_and_download(self):
        """Poll SAT and import received CFDIs when ready (manual workflow)."""
        check_sat_manager(self.env)
        self.action_check_status()
        return True

    def action_reset_request(self):
        """Clear SAT linkage so a fresh submit can be sent."""
        check_sat_manager(self.env)
        for record in self:
            if record.state == 'done' and record.records_count:
                raise UserError(_('No se puede reiniciar una solicitud completada que ya creó registros.'))
        self.write({
            'state': 'draft',
            'sat_request_id': False,
            'package_ids': False,
            'records_count': 0,
            'error_message': False,
            'last_check_date': False,
        })
        return True

    def action_process_packages(self):
        check_sat_manager(self.env)
        CfdiReceived = self.env['sat.cfdi.received']

        for record in self:
            packages = record._get_package_ids()
            if not packages:
                continue

            created = 0
            skipped = 0
            errors = []
            try:
                client = record._get_sat_client()
            except (SatClientError, UserError) as exc:
                record.write({'state': 'error', 'error_message': str(exc)})
                continue

            for package_id in packages:
                package_errors = []
                package_created = 0
                package_skipped = 0
                try:
                    zip_bytes = client.download_package(package_id)
                    xml_list = SatClient.extract_xmls_from_zip(zip_bytes)
                except SatTimeoutError as exc:
                    errors.append(_('Paquete %s: %s') % (package_id, exc))
                    record.write({
                        'state': 'processing',
                        'error_message': str(exc),
                        'last_check_date': fields.Datetime.now(),
                    })
                    continue
                except SatClientError as exc:
                    errors.append(_('Paquete %s: %s') % (package_id, exc))
                    continue
                except Exception as exc:
                    _logger.warning(
                        'Package download failed for %s: %s',
                        package_id,
                        type(exc).__name__,
                    )
                    errors.append(_('No se pudo descargar el paquete %s.') % package_id)
                    continue

                for xml_bytes in xml_list:
                    try:
                        parsed = parse_received_cfdi(xml_bytes)
                    except XmlParserError as exc:
                        package_errors.append(str(exc))
                        continue

                    if not parsed.get('uuid'):
                        continue

                    vals = {
                        'invoice_date': parsed.get('invoice_date'),
                        'supplier_name': parsed.get('supplier_name'),
                        'total': parsed.get('total'),
                        'uuid': parsed['uuid'],
                        'supplier_rfc': parsed.get('supplier_rfc'),
                        'currency': parsed.get('currency'),
                        'company_id': record.company_id.id,
                        'download_request_id': record.id,
                    }
                    try:
                        _, was_created = CfdiReceived.create_from_sat_package(vals, xml_bytes)
                    except Exception as exc:
                        _logger.warning(
                            'CFDI create failed for UUID %s: %s',
                            parsed['uuid'],
                            type(exc).__name__,
                        )
                        package_errors.append(_('No se pudo almacenar el CFDI %s.') % parsed['uuid'])
                        continue

                    if was_created:
                        package_created += 1
                    else:
                        package_skipped += 1

                created += package_created
                skipped += package_skipped
                if package_errors:
                    errors.append(_('Paquete %s: %s') % (package_id, '; '.join(package_errors[:5])))

            vals = {
                'records_count': record.records_count + created,
                'last_check_date': fields.Datetime.now(),
            }
            if errors and created == 0 and skipped == 0:
                vals['state'] = 'error'
                vals['error_message'] = '\n'.join(errors[:20])
            elif errors:
                vals['state'] = 'done'
                vals['error_message'] = '\n'.join(errors[:20])
            else:
                vals['state'] = 'done'
                vals['error_message'] = False
            record.write(vals)
        return True
