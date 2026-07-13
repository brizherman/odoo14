# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.sat_cfdi_received.services.secret_store import (
    decrypt_secret,
    encrypt_secret,
    sanitize_exception_message,
)


@tagged('post_install', '-at_install', 'sat_cfdi_received')
class TestSecretStore(TransactionCase):
    def test_encrypt_decrypt_roundtrip(self):
        plaintext = 'my-secret-password'
        encrypted = encrypt_secret(self.env, plaintext)
        self.assertNotEqual(encrypted, plaintext)
        self.assertEqual(decrypt_secret(self.env, encrypted), plaintext)

    def test_decrypt_invalid_token_returns_false(self):
        self.assertFalse(decrypt_secret(self.env, 'not-a-valid-token'))

    def test_sanitize_exception_message_strips_secrets(self):
        sanitized = sanitize_exception_message('Invalid password for token Bearer abc123')
        self.assertNotIn('password', sanitized.lower())
        self.assertNotIn('token', sanitized.lower())

    def test_fiel_password_not_stored_plaintext(self):
        company = self.env.company
        company.write({'sat_fiel_password': 'super-secret'})
        self.assertTrue(company.sat_fiel_password_enc)
        self.assertNotEqual(company.sat_fiel_password_enc, 'super-secret')
        self.assertEqual(company._get_sat_fiel_password(), 'super-secret')

    def test_fiel_fields_restricted_to_manager(self):
        field = self.env['res.company']._fields['sat_fiel_password_enc']
        self.assertIn('group_sat_manager', field.groups)
