# -*- coding: utf-8 -*-
"""Encrypted storage helpers for FIEL secrets."""
import base64
import hashlib
import logging

from odoo import _

_logger = logging.getLogger(__name__)

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:
    Fernet = None
    InvalidToken = Exception


def _fernet_key_from_secret(secret):
    """Derive a Fernet-compatible key from the Odoo database secret."""
    digest = hashlib.sha256(str(secret).encode('utf-8')).digest()
    return base64.urlsafe_b64encode(digest)


def _get_fernet(env):
    if Fernet is None:
        raise RuntimeError(_('Se requiere el paquete Python cryptography para cifrar la contraseña FIEL.'))
    secret = env['ir.config_parameter'].sudo().get_param('database.secret')
    if not secret:
        raise RuntimeError(_('No está configurado el secreto de la base de datos; no se puede cifrar la contraseña FIEL.'))
    return Fernet(_fernet_key_from_secret(secret))


def encrypt_secret(env, plaintext):
    """Encrypt a secret string for database storage."""
    if not plaintext:
        return False
    fernet = _get_fernet(env)
    token = fernet.encrypt(str(plaintext).encode('utf-8'))
    return token.decode('ascii')


def decrypt_secret(env, ciphertext):
    """Decrypt a stored secret string."""
    if not ciphertext:
        return False
    fernet = _get_fernet(env)
    try:
        return fernet.decrypt(str(ciphertext).encode('ascii')).decode('utf-8')
    except InvalidToken:
        _logger.warning('FIEL password decryption failed (invalid token).')
        return False


def sanitize_exception_message(message):
    """Remove values that look like secrets from user-facing error text."""
    if not message:
        return message
    text = str(message)
    for marker in ('password', 'token', 'Bearer ', '.key', '.cer'):
        if marker.lower() in text.lower():
            return _('La operación falló por un error de credenciales o de comunicación con el SAT.')
    return text
