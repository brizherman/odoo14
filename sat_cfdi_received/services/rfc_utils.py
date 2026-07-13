# -*- coding: utf-8 -*-
"""RFC normalization and validation for SAT requests."""
import re

from odoo import _

RFC_PATTERN = re.compile(r'^[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3}$')


def normalize_rfc(value):
    """Strip optional MX VAT prefix, whitespace, and uppercase an RFC value."""
    if not value:
        return False
    normalized = str(value).strip().upper()
    if normalized.startswith('MX'):
        normalized = normalized[2:].strip()
    return normalized or False


def validate_rfc(value):
    """Return True when value is a syntactically valid Mexican RFC."""
    normalized = normalize_rfc(value)
    if not normalized:
        return False
    return bool(RFC_PATTERN.match(normalized))


def rfc_from_vat(vat):
    """Normalize a company VAT field to RFC, or return False if invalid."""
    normalized = normalize_rfc(vat)
    if normalized and validate_rfc(normalized):
        return normalized
    return False


def require_rfc(value, label=None):
    """Normalize and validate an RFC, raising ValueError when invalid."""
    normalized = normalize_rfc(value)
    if not normalized:
        raise ValueError(_('Se requiere RFC para %(label)s.') % {
            'label': label or 'solicitud SAT',
        })
    if not validate_rfc(normalized):
        raise ValueError(_('Formato de RFC inválido para %(label)s: %(value)s') % {
            'label': label or 'solicitud SAT',
            'value': normalized,
        })
    return normalized
