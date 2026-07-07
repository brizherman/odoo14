# -*- coding: utf-8 -*-
import re
import unicodedata


def normalize_match_string(value):
    """Lowercase, strip accents, remove spaces and punctuation."""
    text = (value or '').strip().lower()
    text = unicodedata.normalize('NFD', text)
    text = ''.join(char for char in text if unicodedata.category(char) != 'Mn')
    text = re.sub(r'[^a-z0-9]+', '', text)
    return text


def fuzzy_vendor_match(sheet_name, candidate_name):
    """Match when both names contain convergram and mexico after normalization."""
    sheet_norm = normalize_match_string(sheet_name)
    candidate_norm = normalize_match_string(candidate_name)
    if 'convergram' not in sheet_norm or 'mexico' not in sheet_norm:
        return False
    return 'convergram' in candidate_norm and 'mexico' in candidate_norm


class VendorMatcher:
    """Resolve sheet proveedor strings to Odoo partners and classification vendors."""

    def __init__(self, env):
        self.env = env
        self.Partner = env['res.partner']
        self.Mapping = env['vendor.sheet.mapping']
        self.ClassificationVendor = env['product.classification.vendor']

    def resolve_partner(self, sheet_proveedor):
        """Return (partner, warning_message). Partner is empty when unmatched."""
        sheet_name = (sheet_proveedor or '').strip()
        if not sheet_name:
            return self.Partner.browse(), 'Missing sheet proveedor value.'

        mapping = self.Mapping.search([('sheet_proveedor', '=', sheet_name)], limit=1)
        if mapping:
            return mapping.partner_id, None

        candidates = self.Partner.search([
            '|', ('name', 'ilike', 'convergram'), ('name', 'ilike', 'mexico'),
        ])
        matches = candidates.filtered(
            lambda partner: fuzzy_vendor_match(sheet_name, partner.name)
        )
        if len(matches) == 1:
            return matches, None
        if len(matches) > 1:
            return self.Partner.browse(), (
                'Multiple fuzzy vendor matches for "%s". Add a manual mapping.' % sheet_name
            )
        return self.Partner.browse(), (
            'Unmapped proveedor "%s". Add a manual mapping or verify fuzzy tokens.' % sheet_name
        )

    def resolve_classification_vendor(self, partner):
        """Return (classification_vendor, warning_message)."""
        if not partner:
            return self.ClassificationVendor.browse(), 'No partner to resolve classification vendor.'

        mapping = self.Mapping.search([
            ('partner_id', '=', partner.id),
            ('classification_vendor_id', '!=', False),
        ], limit=1)
        if mapping:
            return mapping.classification_vendor_id, None

        candidates = self.ClassificationVendor.search([])
        matches = candidates.filtered(
            lambda vendor: fuzzy_vendor_match(partner.name, vendor.name)
        )
        if len(matches) == 1:
            return matches, None
        if len(matches) > 1:
            return self.ClassificationVendor.browse(), (
                'Multiple classification vendors match partner "%s". Add a manual mapping.'
                % partner.name
            )
        return self.ClassificationVendor.browse(), (
            'No classification vendor match for partner "%s".' % partner.name
        )
