from datetime import datetime
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import SavepointCase


@tagged("post_install", "-at_install")
class TestPosLayawayCampaign(SavepointCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env["res.company"].create({
            "name": "Layaway Company B", "currency_id": cls.company_a.currency_id.id,
        })
        cls.company_ids = (cls.company_a | cls.company_b).ids
        cls.pricelist = cls.env["product.pricelist"].create({
            "name": "Layaway Test Pricelist", "currency_id": cls.company_a.currency_id.id,
        })
        cls.config_a = cls._create_config(cls.company_a, "Layaway A")
        cls.config_b = cls._create_config(cls.company_b, "Layaway B")
        cls.config_other = cls._create_config(cls.company_a, "Nonparticipating POS")
        cls.cashier_a = cls._create_user(
            "cashier_a", cls.company_a, "point_of_sale.group_pos_user"
        )
        cls.cashier_b = cls._create_user(
            "cashier_b", cls.company_b, "point_of_sale.group_pos_user"
        )
        cls.supervisor = cls._create_user(
            "supervisor", cls.company_a, "point_of_sale.group_pos_manager"
        )
        cls.manager = cls._create_user(
            "manager", cls.company_a | cls.company_b, "pos_layaway.group_layaway_campaign_manager"
        )
        cls.session_a = cls._create_session(cls.config_a, cls.cashier_a)
        cls.session_b = cls._create_session(cls.config_b, cls.cashier_b)
        cls.session_other = cls._create_session(cls.config_other, cls.cashier_a)
        cls.campaigns = cls.env["pos.layaway.campaign"].with_user(cls.manager).with_context(
            allowed_company_ids=cls.company_ids
        )
        cls.values = {
            "name": "Apartados Navidad 2026",
            "pos_config_ids": [(6, 0, (cls.config_a | cls.config_b).ids)],
            "currency_id": cls.company_a.currency_id.id,
            "timezone": "America/Tijuana",
            "opening_start": "2026-11-18",
            "opening_end": "2026-11-30",
            "addition_end": "2026-12-15",
            "pickup_end": "2026-12-15",
            "credit_end": "2027-01-31",
            "minimum_amount": 3000,
            "deposit_percentage": 50,
        }

    @classmethod
    def _create_user(cls, purpose, companies, group):
        return cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Layaway Test " + purpose,
            "login": "layaway_test_" + purpose,
            "company_id": companies[0].id,
            "company_ids": [(6, 0, companies.ids)],
            "groups_id": [(6, 0, [
                cls.env.ref("base.group_user").id, cls.env.ref(group).id,
            ])],
        })

    @classmethod
    def _create_config(cls, company, name):
        warehouse = cls.env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
        return cls.env["pos.config"].with_company(company).create({
            "name": name,
            "company_id": company.id,
            "picking_type_id": warehouse.pos_type_id.id,
            "pricelist_id": cls.pricelist.id,
            "available_pricelist_ids": [(6, 0, cls.pricelist.ids)],
            "payment_method_ids": [(5, 0, 0)],
            "journal_id": False,
            "invoice_journal_id": False,
        })

    @classmethod
    def _create_session(cls, config, user):
        return cls.env["pos.session"].with_company(config.company_id).create(
            {"config_id": config.id, "user_id": user.id}
        )

    def test_campaign_lifecycle(self):
        christmas = self.campaigns.create(self.values)
        copy = christmas.copy({
            "opening_start": "2026-11-20", "opening_end": "2026-12-01", "minimum_amount": 5000,
        })
        self.assertEqual(christmas.state, "draft")
        self.assertEqual(copy.state, "draft")
        self.assertNotEqual(christmas.code, copy.code)
        boxes = self.config_a | self.config_b
        self.assertEqual(christmas.warehouse_ids, boxes.picking_type_id.warehouse_id)
        self.assertEqual(copy.minimum_amount, 5000)
        self.assertNotEqual(christmas.opening_start, copy.opening_start)
        christmas.action_activate()
        self.assertEqual(christmas.state, "active")
        self.assertEqual(christmas.copy().state, "draft")
        christmas.action_archive()
        self.assertEqual(christmas.state, "archived")
        with self.assertRaises(ValidationError):
            christmas.action_activate()

    def test_validation(self):
        for updates, error in (
            ({"opening_start": "2026-12-01"}, ValidationError),
            ({"timezone": "Invalid/Timezone"}, ValueError),
            ({"minimum_amount": -1}, ValidationError),
            ({"deposit_percentage": 0}, ValidationError),
            ({"deposit_percentage": 101}, ValidationError),
            ({"pos_config_ids": [(5, 0, 0)]}, ValidationError),
            ({"state": "active"}, ValidationError),
        ):
            with self.subTest(updates=updates), self.assertRaises(error), self.cr.savepoint():
                self.campaigns.create(dict(self.values, **updates))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.campaigns.create({
                key: value for key, value in self.values.items() if key != "deposit_percentage"
            })
        full_deposit = self.campaigns.create(dict(self.values, deposit_percentage=100))
        self.assertEqual(full_deposit.deposit_percentage, 100)

    def test_company_and_role_access(self):
        draft = self.campaigns.create(self.values)
        for role in (self.cashier_a, self.supervisor):
            as_role = self.env["pos.layaway.campaign"].with_user(role)
            self.assertFalse(as_role.search([("id", "=", draft.id)]))
            with self.assertRaises(AccessError):
                as_role.create(self.values)
            with self.assertRaises(AccessError):
                as_role.browse(draft.id).action_activate()
            with self.assertRaises(AccessError):
                as_role.browse(draft.id).write({"minimum_amount": 5000})
            with self.assertRaises(AccessError):
                as_role.browse(draft.id).write({"state": "active"})
            with self.assertRaises(AccessError):
                as_role.browse(draft.id).action_archive()
        with self.assertRaises(AccessError):
            draft.with_context(allowed_company_ids=self.company_a.ids).action_activate()
        draft.action_activate()
        with self.assertRaises(AccessError):
            self.session_b.with_user(self.cashier_a).get_layaway_campaigns()

    def test_opening_and_participation(self):
        first = self.campaigns.create(self.values)
        second = first.copy({"opening_start": "2026-11-20", "minimum_amount": 5000})
        (first | second).action_activate()
        session_a = self.session_a.with_user(self.cashier_a)
        session_b = self.session_b.with_user(self.cashier_b)
        other = self.session_other.with_user(self.cashier_a)
        for utc_now, expected in (
            (datetime(2026, 11, 18, 7, 59), []),
            (datetime(2026, 11, 18, 8), first.ids),
            (datetime(2026, 11, 20, 8), (first | second).ids),
            (datetime(2026, 12, 1, 7, 59), (first | second).ids),
            (datetime(2026, 12, 1, 8), []),
        ):
            clock = patch.object(fields.Datetime, "now", return_value=utc_now)
            with self.subTest(utc_now=utc_now), clock:
                for session in (session_a, session_b):
                    choices = session.get_layaway_campaigns()
                    self.assertEqual([row["id"] for row in choices], expected)
                self.assertFalse(other.get_layaway_campaigns())
        second.action_archive()
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 25, 12)):
            self.assertEqual([row["id"] for row in session_a.get_layaway_campaigns()], first.ids)

    def _make_folio(self, campaign):
        partner = self.env["res.partner"].create({"name": "Beneficiario Identificado"})
        product = self.env["product.product"].create({"name": "Producto de prueba", "type": "product"})
        picking_type = self.config_a.picking_type_id
        folio = self.env["pos.layaway"].sudo()._create_folio(
            self.session_a.with_user(self.cashier_a), campaign, partner, partner.name,
            "664 123 4567", datetime(2026, 11, 18, 8),
            [{
                "product_id": product.id, "product_name": product.name, "qty": 2,
                "price_unit": 2000, "amount_total": 4000, "amount_tax": 0,
                "warehouse_id": picking_type.warehouse_id.id,
                "location_id": picking_type.default_location_src_id.id,
            }],
        )
        return folio

    def test_folio_snapshots_original_agreement(self):
        campaign = self.campaigns.create(self.values)
        campaign.action_activate()
        folio = self._make_folio(campaign)
        another = self._make_folio(campaign)
        self.assertNotEqual(folio.folio, another.folio)
        self.assertEqual(folio.opened_on.isoformat(), "2026-11-18")
        self.assertEqual(folio.user_id, self.cashier_a)
        self.assertEqual(folio.warehouse_id, self.config_a.picking_type_id.warehouse_id)
        self.assertEqual(folio.payment_state, "unpaid")
        self.assertEqual(folio.pickup_state, "pending")
        campaign.write({"name": "Nuevo nombre", "minimum_amount": 5000, "deposit_percentage": 80})
        campaign.action_archive()
        self.assertEqual(folio.campaign_name, self.values["name"])
        self.assertEqual(folio.minimum_amount, 3000)
        self.assertEqual(folio.deposit_percentage, 50)
        self.assertEqual(folio.amount_due, 4000)
        self.assertEqual(folio.pickup_end.isoformat(), self.values["pickup_end"])
        with self.assertRaises(Exception) as raised, self.cr.savepoint():
            campaign.sudo().unlink()
        self.assertEqual(getattr(raised.exception, "pgcode", None), "23503")
        with self.assertRaises(AccessError):
            folio.with_user(self.cashier_a).write({"amount_deposit": 4000})
        with self.assertRaises(ValidationError):
            folio.write({"deposit_percentage": 80})

    def test_operation_replays_result_and_rolls_back_failure(self):
        campaign = self.campaigns.create(self.values)
        campaign.action_activate()
        folio = self._make_folio(campaign)
        operations = self.env["pos.layaway.operation"].sudo()
        session = self.session_a.with_user(self.cashier_a)
        other = self.session_b.with_user(self.cashier_b)
        reference = "e68952d7-95dc-465a-924c-ffa33572ac95"
        calls = []

        def fail():
            folio.line_ids.qty_picked_up = 1
            raise ValidationError("Simulated failure")

        def confirm():
            calls.append(True)
            folio.line_ids.qty_picked_up = 1
            return folio, {"folio": folio.folio, "pending": folio.line_ids.qty_pending}

        with self.assertRaises(ValidationError):
            operations._confirm(session, reference, "fixture", {}, fail, folio)
        self.assertEqual(folio.line_ids.qty_picked_up, 0)
        self.assertFalse(operations.search([("reference", "=", reference)]))
        result = operations._confirm(session, reference, "fixture", {}, confirm, folio)
        self.assertEqual(operations._confirm(other, reference, "fixture", {}, confirm, folio), result)
        self.assertEqual(calls, [True])
        operation = operations.search([("reference", "=", reference)])
        self.assertEqual(operation.user_id, self.cashier_a)
        self.assertEqual(operation.session_id, self.session_a)
        self.assertEqual(operation.warehouse_id, folio.warehouse_id)
        self.assertEqual(folio.pickup_state, "partial")
        self.assertEqual(folio.payment_state, "unpaid")
        with self.assertRaises(ValidationError):
            operations._confirm(other, reference, "fixture", {"changed": True}, confirm, folio)
        with self.assertRaises(ValidationError):
            operation.unlink()

    def test_server_quote_dates_minimum_and_contact(self):
        first = self.campaigns.create(self.values)
        second = first.copy({"minimum_amount": 5000})
        (first | second).action_activate()
        self.company_a.wholesale_pricelist_id = self.pricelist
        product = self.env["product.product"].create({
            "name": "Quote Product", "type": "product", "available_in_pos": True,
            "taxes_id": [(5, 0, 0)],
        })
        customer = self.env["res.partner"].create({
            "name": "Client with name", "phone": "664 123 4567",
            "customer_type": "publico_general",
        })
        generic = self.env["res.partner"].create({"name": "Público en general"})
        session = self.session_a.with_user(self.cashier_a)
        lines = [{"product_id": product.id, "qty": 1}]

        def quote(moment, campaign, partner=customer, phone=False):
            with patch.object(fields.Datetime, "now", return_value=moment):
                return session.quote_layaway(lines, campaign.id, partner.id, phone)

        start = datetime(2026, 11, 18, 8)
        end = datetime(2026, 12, 1, 7, 59)
        for campaign, minimum in ((first, 3000), (second, 5000)):
            for total in (minimum - 0.01, minimum, minimum + 0.01):
                product.lst_price = total
                with self.subTest(campaign=minimum, total=total):
                    if total <= minimum:
                        with self.assertRaisesRegex(ValidationError, "superar el mínimo"):
                            quote(start, campaign)
                    else:
                        for moment in (start, end):
                            result = quote(moment, campaign)
                            self.assertEqual(result["amount_total"], total)
                            self.assertEqual(result["required_deposit"], minimum / 2 + 0.01)
        for moment in (datetime(2026, 11, 18, 7, 59), datetime(2026, 12, 1, 8)):
            with self.assertRaisesRegex(ValidationError, "no está abierta"):
                quote(moment, first)
        with self.assertRaisesRegex(ValidationError, "beneficiario"):
            quote(start, first, generic, "664 123 4567")
        with self.assertRaisesRegex(ValidationError, "teléfono"):
            quote(start, first, customer, "invalid")
        for customer_type in ("mayorista_dormido", "distribuidores"):
            customer.customer_type = customer_type
            customer.active = False
            self.assertEqual(quote(start, first)["partner_id"], customer.id)

    def test_server_quotes_addition_using_only_current_price_on_new_lines(self):
        campaign = self.campaigns.create(self.values)
        campaign.action_activate()
        self.company_b.wholesale_pricelist_id = self.pricelist
        folio = self._make_folio(campaign)
        folio.amount_deposit = 2000
        campaign.write({"deposit_percentage": 80})
        campaign.action_archive()
        product = folio.line_ids.product_id
        tax = self.env["account.tax"].with_company(self.company_b).create({
            "name": "Tax test 16%", "amount": 16, "type_tax_use": "sale",
            "company_id": self.company_b.id,
        })
        product.write({"lst_price": 2000, "available_in_pos": True, "taxes_id": [(6, 0, tax.ids)]})
        lines = [{"product_id": product.id, "qty": 1}]
        session = self.session_b.with_user(self.cashier_b)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 16, 7, 59)):
            result = session.quote_layaway(lines, campaign.id, layaway_id=folio.id)
        self.assertEqual(result["amount_previous"], 4000)
        self.assertEqual(result["lines"][0]["amount_tax"], 320)
        self.assertEqual(result["amount_new"], 2320)
        self.assertEqual(result["amount_total"], 6320)
        self.assertEqual(result["required_deposit"], 1160)
        self.assertEqual(result["pickup_end"], "2026-12-15")
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 16, 8)):
            with self.assertRaisesRegex(ValidationError, "Terminó el plazo"):
                session.quote_layaway(lines, campaign.id, layaway_id=folio.id)
        self.assertEqual(folio.line_ids.price_unit, 2000)
        self.assertEqual(folio.amount_total, 4000)

    def test_shop_reservation_keeps_last_unit_and_releases_it(self):
        campaign = self.campaigns.create(self.values)
        campaign.action_activate()
        folio = self._make_folio(campaign)
        line = folio.line_ids
        quant_model = self.env["stock.quant"]
        quant_model._update_available_quantity(line.product_id, line.location_id, line.qty)
        session = self.session_a.with_user(self.cashier_a)
        picking = self.env["stock.picking"].sudo()._reserve_layaway_lines(folio, session, line)
        self.assertEqual(picking.state, "assigned")
        self.assertEqual(picking.move_lines.reserved_availability, line.qty)
        self.assertEqual(picking.move_lines.quantity_done, 0)
        self.assertEqual(quant_model._get_available_quantity(line.product_id, line.location_id), 0)
        with self.assertRaisesRegex(UserError, "ya tiene una reserva"):
            self.env["stock.picking"].sudo()._reserve_layaway_lines(folio, session, line)
        with self.assertRaises(UserError):
            self.env["stock.picking"].sudo()._reserve_layaway_lines(
                folio, self.session_b.with_user(self.cashier_b), line,
            )
        picking.action_cancel()
        self.assertEqual(quant_model._get_available_quantity(line.product_id, line.location_id), 2)

    def test_folio_search_filters_and_other_store_access(self):
        campaign = self.campaigns.create(self.values)
        campaign.action_activate()
        folio = self._make_folio(campaign)
        folio.amount_deposit = 2000
        folio.amount_installments = 500
        folio.line_ids.qty_picked_up = 1
        campaign.action_archive()
        a = self.session_a.with_user(self.cashier_a)
        b = self.session_b.with_user(self.cashier_b)
        filters = {
            "campaign": campaign.id, "store": folio.warehouse_id.id,
            "from": "2026-11-18", "to": "2026-11-18", "payment_state": "partial",
            "pickup_state": "partial", "expiry": "current",
        }
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 16, 7, 59)):
            for key in (folio.folio, "identificado", "664-123-4567"):
                for session in (a, b):
                    table = session.get_layaways(dict(filters, query=key))
                    self.assertEqual([entry["id"] for entry in table["rows"]], [folio.id])
                    self.assertIn(campaign.id, [entry["id"] for entry in table["campaigns"]])
                    self.assertIn(folio.warehouse_id.id, [entry["id"] for entry in table["stores"]])
            self.assertFalse(a.get_layaways(dict(filters, query="A_FOLIO_%"))["rows"])
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 16, 8)):
            self.assertFalse(a.get_layaways(filters)["rows"])
            self.assertEqual(len(a.get_layaways(dict(filters, expiry="expired"))["rows"]), 1)
            detail = b.get_layaway_detail(folio.id)
        self.assertEqual(detail["lines"][0]["pending"], 1)
        self.assertEqual(detail["amount_total"], 4000)
        self.assertEqual(detail["amount_deposit"], 2000)
        self.assertEqual(detail["amount_installments"], 500)
        self.assertEqual(detail["amount_due"], 1500)
        other = self.session_other.with_user(self.cashier_a)
        self.assertFalse(other.get_layaways()["rows"])
        with self.assertRaises(AccessError):
            other.get_layaway_detail(folio.id)
