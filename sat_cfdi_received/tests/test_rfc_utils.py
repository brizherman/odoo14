# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.sat_cfdi_received.services.rfc_utils import (
    normalize_rfc,
    require_rfc,
    rfc_from_vat,
    validate_rfc,
)
from odoo.addons.sat_cfdi_received.services.sat_client import rfc_from_certificate


@tagged('post_install', '-at_install', 'sat_cfdi_received')
class TestRfcUtils(TransactionCase):
    def test_normalize_rfc_strips_mx_prefix(self):
        self.assertEqual(normalize_rfc('MXGMA121221Q79'), 'GMA121221Q79')

    def test_normalize_rfc_uppercases(self):
        self.assertEqual(normalize_rfc('gma121221q79'), 'GMA121221Q79')

    def test_validate_rfc_valid(self):
        self.assertTrue(validate_rfc('GMA121221Q79'))

    def test_validate_rfc_invalid(self):
        self.assertFalse(validate_rfc('INVALID'))

    def test_rfc_from_vat_with_mx_prefix(self):
        self.assertEqual(rfc_from_vat('MXGMA121221Q79'), 'GMA121221Q79')

    def test_rfc_from_vat_without_prefix(self):
        self.assertEqual(rfc_from_vat('GMA121221Q79'), 'GMA121221Q79')

    def test_require_rfc_raises_on_invalid(self):
        with self.assertRaises(ValueError):
            require_rfc('NOTRFC')

    def test_rfc_from_certificate_failure_returns_false(self):
        self.assertFalse(rfc_from_certificate(b'not-a-certificate'))
