# -*- coding: utf-8 -*-
import re
import unicodedata

FUZZY_MIN_SCORE = 60
FUZZY_CLEAR_WIN_MARGIN = 15

STOP_WORDS = frozenset({
    'de', 'del', 'la', 'el', 'los', 'las', 'y', 'en', 'the', 'and',
    'sa', 'cv', 's', 'a', 'c', 'b', 'rl', 'cia', 'inc', 'ltd', 'llc',
    'corp', 'mexico', 'mx',
})


def normalize_match_string(value):
    """Lowercase, strip accents, remove spaces and punctuation."""
    text = (value or '').strip().lower()
    text = unicodedata.normalize('NFD', text)
    text = ''.join(char for char in text if unicodedata.category(char) != 'Mn')
    text = re.sub(r'[^a-z0-9]+', '', text)
    return text


def extract_match_tokens(value):
    text = (value or '').strip().lower()
    text = unicodedata.normalize('NFD', text)
    text = ''.join(char for char in text if unicodedata.category(char) != 'Mn')
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    tokens = []
    for token in text.split():
        if len(token) <= 2 or token in STOP_WORDS:
            continue
        tokens.append(token)
    return tokens


def fuzzy_match_score(left_name, right_name):
    """Return 0-100 similarity score between two vendor names."""
    left_norm = normalize_match_string(left_name)
    right_norm = normalize_match_string(right_name)
    if not left_norm or not right_norm:
        return 0
    if left_norm == right_norm:
        return 100
    if left_norm in right_norm or right_norm in left_norm:
        return 90

    left_tokens = extract_match_tokens(left_name)
    right_tokens = extract_match_tokens(right_name)
    if not left_tokens or not right_tokens:
        return 0

    right_set = set(right_tokens)
    matched = 0
    for token in left_tokens:
        if token in right_set:
            matched += 1
            continue
        for other in right_tokens:
            if len(token) >= 4 and (token in other or other in token):
                matched += 1
                break

    score = (matched / max(len(left_tokens), len(right_tokens))) * 80
    if left_tokens[0] == right_tokens[0]:
        score += 10
    return min(int(score), 95)


def fuzzy_vendor_match(left_name, right_name, min_score=FUZZY_MIN_SCORE):
    """Return True when two vendor names are similar enough to auto-match."""
    return fuzzy_match_score(left_name, right_name) >= min_score


def _pick_unique_fuzzy_match(scored_matches, label, multiple_warning_template):
    if not scored_matches:
        return None, None

    scored_matches.sort(
        key=lambda item: (-item[0], item[1].display_name or item[1].name)
    )
    top_score, top_record = scored_matches[0]
    if len(scored_matches) == 1:
        return top_record, None

    second_score = scored_matches[1][0]
    if top_score - second_score >= FUZZY_CLEAR_WIN_MARGIN:
        return top_record, None

    names = ', '.join(
        record.display_name or record.name
        for _score, record in scored_matches[:5]
    )
    return None, multiple_warning_template % (label, names)


class VendorMatcher:
    """Resolve sheet proveedor strings to Odoo partners and classification vendors."""

    def __init__(self, env):
        self.env = env
        self.Partner = env['res.partner']
        self.Mapping = env['vendor.sheet.mapping']
        self.ClassificationVendor = env['product.classification.vendor']

    def _score_fuzzy_matches(self, source_name, candidates):
        scored = []
        for candidate in candidates:
            score = fuzzy_match_score(source_name, candidate.name)
            if score >= FUZZY_MIN_SCORE:
                scored.append((score, candidate))
        return scored

    def resolve_partner(self, sheet_proveedor):
        """Return (partner, warning_message). Partner is empty when unmatched."""
        sheet_name = (sheet_proveedor or '').strip()
        if not sheet_name:
            return self.Partner.browse(), 'Falta el valor de proveedor en la hoja.'

        mapping = self.Mapping.search([('sheet_proveedor', '=', sheet_name)], limit=1)
        if mapping:
            return mapping.partner_id, None

        suppliers = self.Partner.search([
            ('supplier_rank', '>', 0),
            ('active', '=', True),
        ])
        scored_matches = self._score_fuzzy_matches(sheet_name, suppliers)
        partner, warning = _pick_unique_fuzzy_match(
            scored_matches,
            sheet_name,
            'Múltiples coincidencias aproximadas de proveedor para "%s": %s. Agregue un mapeo manual.',
        )
        if partner:
            return partner, None
        if warning:
            return self.Partner.browse(), warning
        return self.Partner.browse(), (
            'Proveedor sin mapear "%s". Agregue un mapeo manual.' % sheet_name
        )

    def resolve_classification_vendor(self, partner):
        """Return (classification_vendor, warning_message)."""
        if not partner:
            return self.ClassificationVendor.browse(), 'No hay contacto para resolver el proveedor de clasificación.'

        mapping = self.Mapping.search([
            ('partner_id', '=', partner.id),
            ('classification_vendor_id', '!=', False),
        ], limit=1)
        if mapping:
            return mapping.classification_vendor_id, None

        candidates = self.ClassificationVendor.search([])
        scored_matches = self._score_fuzzy_matches(partner.name, candidates)
        class_vendor, warning = _pick_unique_fuzzy_match(
            scored_matches,
            partner.name,
            'Múltiples proveedores de clasificación coinciden con el contacto "%s": %s. Agregue un mapeo manual.',
        )
        if class_vendor:
            return class_vendor, None
        if warning:
            return self.ClassificationVendor.browse(), warning
        return self.ClassificationVendor.browse(), (
            'No hay coincidencia de proveedor de clasificación para el contacto "%s".' % partner.name
        )
