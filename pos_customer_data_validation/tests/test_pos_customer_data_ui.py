from odoo import tools
from odoo.tests import HttpCase, tagged

from .ui_fixture import create_ui_fixture


@tagged("post_install", "-at_install", "-standard", "pos_customer_ui")
class TestPosCustomerDataUI(HttpCase):
    def test_customer_review_tour(self):
        if not tools.config["http_enable"]:
            self.skipTest("UI tour requires HTTP; run the documented HTTP command")
        fixture = create_ui_fixture(self.env)
        # Odoo 14 browser_js authenticates using the login as the password.
        self.env["res.users"].search([
            ("login", "=", fixture["login"]),
        ]).password = fixture["login"]
        self.start_tour(
            "/pos/ui?config_id=%s" % fixture["config_id"],
            "CustomerDataValidationTour", login=fixture["login"],
        )
        orders = self.env["pos.order"].search([
            ("session_id.config_id", "=", fixture["config_id"]),
        ])
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders.partner_id.id, fixture["historical_id"])
        partner = self.env["res.partner"].browse(fixture["historical_id"])
        partner.invalidate_cache()
        self.assertFalse(partner.pos_name_updated_at)
        self.assertEqual(str(partner.pos_mobile_updated_at), "2021-01-01 12:00:00")
