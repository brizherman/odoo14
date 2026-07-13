# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.sat_cfdi_received.models.sat_security import check_sat_manager
from odoo.addons.sat_cfdi_received.services.sat_client import (
    SatAuthError,
    SatClient,
    SatClientError,
    rfc_from_certificate,
    decode_binary_field,
)
from odoo.addons.sat_cfdi_received.services.rfc_utils import normalize_rfc, rfc_from_vat
from odoo.addons.sat_cfdi_received.services.secret_store import encrypt_secret, decrypt_secret

SAT_FIEL_REFRESH_CTX = 'sat_fiel_metadata_refresh'


class ResCompany(models.Model):
    _inherit = 'res.company'

    sat_fiel_cer = fields.Binary(
        string='Certificado FIEL (.cer)',
        attachment=True,
        groups='sat_cfdi_received.group_sat_manager,base.group_system',
    )
    sat_fiel_key = fields.Binary(
        string='Llave privada FIEL (.key)',
        attachment=True,
        groups='sat_cfdi_received.group_sat_manager,base.group_system',
    )
    sat_fiel_password = fields.Char(
        string='Contraseña FIEL',
        groups='sat_cfdi_received.group_sat_manager,base.group_system',
    )
    sat_fiel_password_enc = fields.Char(
        string='Contraseña FIEL (cifrada)',
        copy=False,
        groups='sat_cfdi_received.group_sat_manager,base.group_system',
    )
    sat_fiel_configured = fields.Boolean(
        string='FIEL configurada',
        readonly=True,
    )
    sat_fiel_cert_rfc = fields.Char(
        string='RFC del certificado',
        readonly=True,
        groups='sat_cfdi_received.group_sat_manager,base.group_system',
    )
    sat_fiel_rfc_mismatch = fields.Boolean(
        string='RFC no coincide',
        readonly=True,
        groups='sat_cfdi_received.group_sat_manager,base.group_system',
    )

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        companies._refresh_sat_fiel_metadata()
        return companies

    def write(self, vals):
        if self.env.context.get(SAT_FIEL_REFRESH_CTX):
            return super().write(vals)
        password = vals.pop('sat_fiel_password', None)
        if password:
            vals['sat_fiel_password_enc'] = encrypt_secret(self.env, password)
        res = super().write(vals)
        if set(vals) & {'sat_fiel_cer', 'sat_fiel_key', 'sat_fiel_password_enc', 'vat'}:
            self._refresh_sat_fiel_metadata()
        return res

    def _fiel_attachment_exists(self, field_name):
        self.ensure_one()
        return bool(self.env['ir.attachment'].sudo().search_count([
            ('res_model', '=', 'res.company'),
            ('res_id', '=', self.id),
            ('res_field', '=', field_name),
        ]))

    def _refresh_sat_fiel_metadata(self):
        """Update stored FIEL metadata without re-decoding binaries on every form read."""
        for company in self:
            cert_rfc = False
            cer_bytes = decode_binary_field(company.sat_fiel_cer)
            if cer_bytes:
                try:
                    cert_rfc = rfc_from_certificate(cer_bytes) or False
                except Exception:
                    cert_rfc = False
            company_vat = rfc_from_vat(company.vat) or normalize_rfc(company.vat)
            mismatch = bool(cert_rfc and company_vat and cert_rfc != company_vat)
            configured = bool(
                company._fiel_attachment_exists('sat_fiel_cer')
                and company._fiel_attachment_exists('sat_fiel_key')
                and company.sat_fiel_password_enc
            )
            company._write({
                'sat_fiel_cert_rfc': cert_rfc,
                'sat_fiel_rfc_mismatch': mismatch,
                'sat_fiel_configured': configured,
            })
            company.invalidate_cache(
                fnames=['sat_fiel_cert_rfc', 'sat_fiel_rfc_mismatch', 'sat_fiel_configured'],
            )

    def _get_sat_fiel_password(self):
        self.ensure_one()
        return decrypt_secret(self.env, self.sat_fiel_password_enc)

    def _sat_fiel_rfc(self):
        self.ensure_one()
        cer_bytes = decode_binary_field(self.sat_fiel_cer)
        if cer_bytes:
            try:
                return rfc_from_certificate(cer_bytes)
            except Exception:
                return False
        return False

    @api.model
    def action_open_sat_fiel_config(self):
        """Open a lightweight FIEL-only company form for the active company."""
        check_sat_manager(self.env)
        company = self.env.company
        view = self.env.ref('sat_cfdi_received.view_company_form_sat_fiel_only')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Configuración FIEL SAT'),
            'res_model': 'res.company',
            'res_id': company.id,
            'view_mode': 'form',
            'views': [(view.id, 'form')],
            'target': 'current',
        }

    def action_sat_test_connection(self):
        check_sat_manager(self.env)
        self.ensure_one()
        if not self.sat_fiel_configured:
            raise UserError(_('Cargue el certificado FIEL, la llave y la contraseña antes de probar.'))

        if self.sat_fiel_rfc_mismatch:
            raise UserError(_(
                'El RFC del certificado (%(cert_rfc)s) no coincide con el RFC de la empresa (%(vat)s).'
            ) % {
                'cert_rfc': self.sat_fiel_cert_rfc,
                'vat': rfc_from_vat(self.vat) or normalize_rfc(self.vat),
            })

        try:
            client = SatClient.from_company(self)
            client.authenticate()
        except SatAuthError as exc:
            raise UserError(str(exc)) from exc
        except SatClientError as exc:
            raise UserError(_('Falló la conexión con el SAT: %s') % exc) from exc
        except Exception:
            raise UserError(_('Falló la conexión con el SAT por un error de red o del servidor.'))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Conexión SAT'),
                'message': _('Autenticación FIEL exitosa. Se obtuvo el token del SAT.'),
                'type': 'success',
                'sticky': False,
            },
        }

    @api.model
    def _migrate_plaintext_fiel_passwords(self):
        """One-time migration from legacy plaintext sat_fiel_password column."""
        self.env.cr.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'res_company' AND column_name = 'sat_fiel_password'
        """)
        if not self.env.cr.fetchone():
            return
        self.env.cr.execute("""
            SELECT id, sat_fiel_password
            FROM res_company
            WHERE sat_fiel_password IS NOT NULL AND sat_fiel_password != ''
        """)
        rows = self.env.cr.fetchall()
        for company_id, plaintext in rows:
            company = self.browse(company_id)
            if company.sat_fiel_password_enc:
                continue
            company.with_context(**{SAT_FIEL_REFRESH_CTX: True}).write({
                'sat_fiel_password_enc': encrypt_secret(company.env, plaintext),
            })
        self.browse([row[0] for row in rows])._refresh_sat_fiel_metadata()
