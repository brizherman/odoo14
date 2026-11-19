from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import new_test_user

from .common import CustomerDataCommon


class TestCustomerDataSecurity(CustomerDataCommon):
    def test_extra_fields_and_forged_dates(self):
        for key in ("company_id", "pos_mobile_updated_at", "pos_pricelist_evidence"):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                self.save({key: False})
        partner = self.partner.with_user(self.cashier)
        for key in ("pos_name_updated_at", "pos_mobile_updated_at",
                    "pos_customer_type_updated_at", "pos_pricelist_evidence"):
            with self.subTest(key=key), self.assertRaises(AccessError):
                partner.write({key: False})
            with self.assertRaises(AccessError):
                partner.create({"name": "Forgery", key: False})

    def test_non_pos_user_denied(self):
        user = new_test_user(self.env, login="review_non_pos", groups="base.group_user")
        with self.assertRaises(AccessError):
            self.save({}, user=user)

    def test_internal_pricing_counters_cannot_be_forged(self):
        with self.assertRaises(AccessError):
            self.public_price.write({"pos_customer_data_revision": 0})
        with self.assertRaises(AccessError):
            self.env.company.write({"pos_customer_pricing_revision": 0})

    def test_context_defaults_cannot_forge_evidence(self):
        with self.assertRaises(AccessError):
            self.Partner.with_user(self.cashier).with_context(
                default_pos_mobile_updated_at="2030-01-01 00:00:00",
            ).create({"name": "Forged default date"})
        with self.assertRaises(AccessError):
            self.env["product.pricelist"].with_context(
                default_pos_customer_data_revision=100,
            ).create({"name": "Forged default revision"})

    def test_config_record_rule_is_respected(self):
        self.env["ir.rule"].create({
            "name": "Deny review configuration",
            "model_id": self.env["ir.model"]._get_id("pos.config"),
            "domain_force": "[('id', '!=', %s)]" % self.config.id,
        })
        with self.assertRaises(AccessError):
            self.save({})

    def test_pricelist_record_rule_is_respected(self):
        self.env["ir.rule"].create({
            "name": "Deny review pricelist",
            "model_id": self.env["ir.model"]._get_id("product.pricelist"),
            "domain_force": "[('id', '!=', %s)]" % self.public_price.id,
        })
        with self.assertRaises(AccessError):
            self.save({})

    def test_contact_record_rule_is_respected(self):
        self.env["ir.rule"].create({
            "name": "Deny review customer",
            "model_id": self.env["ir.model"]._get_id("res.partner"),
            "domain_force": "[('id', '!=', %s)]" % self.partner.id,
        })
        with self.assertRaises(AccessError):
            self.save({"name": "Denied"})
        with self.assertRaises(AccessError):
            self.Partner.with_user(self.cashier).pos_customer_data_read(
                self.partner.id, self.config.id,
            )

    def test_unavailable_and_foreign_pricelist_rejected(self):
        other = self.env["res.company"].create({"name": "Foreign review company"})
        price = self.public_price.copy({"company_id": other.id})
        with self.assertRaises(ValidationError):
            self.save({"property_product_pricelist": price.id})
        unavailable = self.public_price.copy()
        with self.assertRaises(ValidationError):
            self.save({"property_product_pricelist": unavailable.id})

    def test_foreign_config_denied(self):
        other = self.env["res.company"].create({"name": "Denied review company"})
        config = self.env["pos.config"].with_company(other).create({
            "name": "Denied POS",
        })
        with self.assertRaises(AccessError):
            self.Partner.with_user(self.cashier).pos_customer_data_save(
                self.partner.id, config.id, {},
            )

    def test_missing_ids_rejected(self):
        for partner_id, config_id in ((0, self.config.id), (self.partner.id, 0)):
            with self.assertRaises(AccessError):
                self.Partner.with_user(self.cashier).pos_customer_data_read(
                    partner_id, config_id,
                )

    def test_register_switch_blocks_review_only_for_the_selected_register(self):
        other = self.config.copy({"name": "Caja sin revisión"})
        self.assertFalse(other.customer_data_review_enabled)
        partners = self.Partner.with_user(self.cashier)
        with self.assertRaisesRegex(AccessError, "apagada"):
            partners.pos_customer_data_read(self.partner.id, other.id)
        with self.assertRaisesRegex(AccessError, "apagada"):
            partners.pos_customer_data_save(self.partner.id, other.id, {"mobile": "6649990000"})
        self.assertEqual(self.partner.mobile, "6641234567")
        with self.assertRaises(AccessError):
            self.config.with_user(self.cashier).write({"customer_data_review_enabled": False})
        partners.pos_customer_data_read(self.partner.id, self.config.id)
        self.config.customer_data_review_enabled = False
        with self.assertRaisesRegex(AccessError, "apagada"):
            partners.pos_customer_data_save(self.partner.id, self.config.id, {})
