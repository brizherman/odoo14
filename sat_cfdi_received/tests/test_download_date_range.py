# -*- coding: utf-8 -*-
from datetime import datetime

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.sat_cfdi_received.services.download_date_range import validate_download_date_range


@tagged('post_install', '-at_install', 'sat_cfdi_received')
class TestDownloadDateRange(TransactionCase):
    def test_rejects_cross_month_range(self):
        with self.assertRaises(ValidationError):
            validate_download_date_range(
                self.env['sat.download.request'],
                datetime(2026, 8, 1, 0, 0, 0),
                datetime(2026, 9, 1, 0, 0, 0),
            )

    def test_accepts_same_month_range(self):
        validate_download_date_range(
            self.env['sat.download.request'],
            datetime(2026, 8, 1, 0, 0, 0),
            datetime(2026, 8, 31, 23, 59, 59),
        )
