from datetime import datetime
from unittest.mock import patch

from odoo.exceptions import ValidationError

from .common import CustomerDataCommon


class TestPartnerData(CustomerDataCommon):
    def test_confirm_does_not_refresh_dates(self):
        before = self.partner.read()[0]
        data = self.save({})
        for name in ("name", "mobile", "customer_type"):
            key = "pos_%s_updated_at" % name
            self.assertEqual(data[key], before[key])
        self.assertEqual(
            data["pos_pricelist_updated_at"],
            self.partner._pos_pricelist_date(),
        )

    def test_only_changed_field_date_moves(self):
        old_name = self.partner.pos_name_updated_at
        old_type = self.partner.pos_customer_type_updated_at
        moment = datetime(2030, 1, 2, 3, 4, 5)
        with patch("odoo.fields.Datetime.now", return_value=moment):
            self.save({"mobile": "6647654321"})
        self.assertEqual(self.partner.pos_mobile_updated_at, moment)
        self.assertEqual(self.partner.pos_name_updated_at, old_name)
        self.assertEqual(self.partner.pos_customer_type_updated_at, old_type)

    def test_batch_create_and_noop_backend_write(self):
        partners = self.Partner.create([{"name": "Batch A"}, {"name": "Batch B"}])
        self.assertTrue(all(partners.mapped("pos_name_updated_at")))
        self.assertFalse(any(partners.mapped("pos_mobile_updated_at")))
        old = self.partner.pos_name_updated_at
        self.partner.write({"name": self.partner.name})
        self.assertEqual(self.partner.pos_name_updated_at, old)

    def test_history_and_old_dates(self):
        # SQL represents a pre-installation record; never done by application code.
        self.env.cr.execute("""
            UPDATE res_partner SET pos_name_updated_at = NULL,
                pos_mobile_updated_at = '2021-01-01 00:00:00',
                pos_pricelist_evidence = NULL WHERE id = %s
        """, [self.partner.id])
        self.partner.invalidate_cache()
        data = self.save({})
        self.assertFalse(data["pos_name_updated_at"])
        self.assertFalse(data["pos_pricelist_updated_at"])
        self.assertEqual(data["pos_mobile_updated_at"], datetime(2021, 1, 1))

    def test_all_types_reuse_existing_correspondence(self):
        for customer_type, price in (
            ("mayorista", self.wholesale_price),
            ("distribuidores", self.distributor_price),
            ("publico_general", self.public_price),
            ("mayorista_dormido", self.public_price),
        ):
            data = self.save({
                "customer_type": customer_type,
                "property_product_pricelist": price.id,
            })
            self.assertEqual(data["customer_type"], customer_type)
            self.assertEqual(data["property_product_pricelist"][0], price.id)

    def test_invalid_values_do_not_partially_save(self):
        for changes in (
            {"name": "  "}, {"mobile": " "}, {"mobile": False},
            {"customer_type": False}, {"customer_type": "invalid"},
            {"property_product_pricelist": False},
            {"property_product_pricelist": self.wholesale_price.id},
            {"name": "Changed", "mobile": " "},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.save(changes)
            self.assertEqual(self.partner.name, "Review customer")

    def test_phone_does_not_replace_mobile(self):
        partner = self.Partner.create({
            "name": "Phone only", "phone": "6641234567",
            "customer_type": "publico_general",
            "property_product_pricelist": self.public_price.id,
        })
        with self.assertRaisesRegex(ValidationError, "WhatsApp"):
            self.save({}, partner=partner)

    def test_unedited_concurrent_field_is_preserved(self):
        self.partner.write({"name": "New backend name"})
        data = self.save({"mobile": "6640000000"})
        self.assertEqual(data["name"], "New backend name")

    def test_pricelist_date_changes_only_with_effective_value(self):
        old = self.partner._pos_pricelist_date()
        self.partner.write({"property_product_pricelist": self.public_price.id})
        self.assertEqual(self.partner._pos_pricelist_date(), old)
        moment = datetime(2030, 2, 3, 4, 5, 6)
        with patch("odoo.fields.Datetime.now", return_value=moment):
            self.partner.write({"property_product_pricelist": self.wholesale_price.id})
        self.assertEqual(self.partner._pos_pricelist_date(), "2030-02-03 04:05:06")

    def test_pricing_source_change_invalidates_evidence(self):
        self.assertTrue(self.partner._pos_pricelist_date())
        self.public_price.write({"sequence": self.public_price.sequence + 1})
        self.assertFalse(self.partner._pos_pricelist_date())

    def test_reverse_country_group_round_trip_invalidates_evidence(self):
        group = self.env["res.country.group"].create({
            "name": "Transient price region",
        })
        partner = self.Partner.create({"name": "Reverse relation review"})
        self.assertTrue(partner._pos_pricelist_date())
        group.write({"pricelist_ids": [(4, self.public_price.id)]})
        group.write({"pricelist_ids": [(3, self.public_price.id)]})
        self.assertFalse(partner._pos_pricelist_date())

    def test_default_effective_pricelist_is_accepted(self):
        self.env["ir.property"]._set_default(
            "property_product_pricelist", "res.partner", self.public_price,
            company=self.env.company,
        )
        partner = self.Partner.create({
            "name": "Default price customer", "mobile": "6641111111",
            "customer_type": "publico_general",
        })
        data = self.save({}, partner=partner)
        self.assertEqual(data["property_product_pricelist"][0], self.public_price.id)

    def test_default_round_trip_does_not_revive_old_date(self):
        properties = self.env["ir.property"]
        properties._set_default(
            "property_product_pricelist", "res.partner", self.public_price,
            company=self.env.company,
        )
        partner = self.Partner.create({"name": "Default round trip"})
        self.assertTrue(partner._pos_pricelist_date())
        properties._set_default(
            "property_product_pricelist", "res.partner", self.wholesale_price,
            company=self.env.company,
        )
        properties._set_default(
            "property_product_pricelist", "res.partner", self.public_price,
            company=self.env.company,
        )
        self.assertEqual(partner.property_product_pricelist, self.public_price)
        self.assertFalse(partner._pos_pricelist_date())

    def test_no_effective_pricelist_rejected(self):
        self.env["product.pricelist"].search([]).write({"active": False})
        self.partner.invalidate_cache(["property_product_pricelist"])
        self.assertFalse(self.partner.property_product_pricelist)
        with self.assertRaisesRegex(ValidationError, "Tarifa"):
            self.save({})

    def test_country_changes_follow_effective_pricelist(self):
        country = self.env["res.country"].create({"name": "Review land", "code": "XR"})
        group = self.env["res.country.group"].create({
            "name": "Review region", "country_ids": [(6, 0, country.ids)],
        })
        regional_price = self.public_price.copy({
            "country_group_ids": [(6, 0, group.ids)], "sequence": -100,
        })
        partner = self.Partner.create({"name": "Country review"})
        self.assertNotEqual(partner.property_product_pricelist, regional_price)
        moment = datetime(2030, 3, 4, 5, 6, 7)
        with patch("odoo.fields.Datetime.now", return_value=moment):
            partner.write({"country_id": country.id})
        self.assertEqual(partner.property_product_pricelist, regional_price)
        self.assertEqual(partner._pos_pricelist_date(), "2030-03-04 05:06:07")

    def test_commercial_children_follow_price_changes(self):
        company = self.partner.copy({"is_company": True})
        child = self.Partner.create({"name": "Review child", "parent_id": company.id})
        moment = datetime(2030, 4, 5, 6, 7, 8)
        with patch("odoo.fields.Datetime.now", return_value=moment):
            company.write({"property_product_pricelist": self.wholesale_price.id})
        self.assertEqual(child.property_product_pricelist, self.wholesale_price)
        self.assertEqual(child._pos_pricelist_date(), "2030-04-05 06:07:08")

    def test_post_write_failure_rolls_back(self):
        def interrupted_save(recordset, values):
            recordset.browse(values["id"]).write({"name": values["name"]})
            raise ValidationError("Simulated inherited failure")

        with patch.object(type(self.Partner), "create_from_ui", interrupted_save):
            with self.assertRaisesRegex(ValidationError, "Simulated"):
                self.save({"name": "Should roll back"})
        self.assertEqual(self.partner.name, "Review customer")

    def test_company_dates_do_not_cross(self):
        other = self.env["res.company"].create({"name": "Other review company"})
        partner_other = self.partner.with_company(other)
        self.assertFalse(partner_other._pos_pricelist_date())
        first_date = self.partner._pos_pricelist_date()
        price = self.public_price.copy({"name": "Other price", "company_id": other.id})
        partner_other.write({"property_product_pricelist": price.id})
        self.assertEqual(self.partner._pos_pricelist_date(), first_date)
        self.assertTrue(partner_other._pos_pricelist_date())
