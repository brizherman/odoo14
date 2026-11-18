from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import SavepointCase


@tagged("post_install", "-at_install")
class TestPosLayawayCampaign(SavepointCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a, cls.company_b = cls.env["res.company"].create([
            {"name": "Layaway Company " + label, "currency_id": cls.env.company.currency_id.id}
            for label in ("A", "B")
        ])
        cls.company_ids = (cls.company_a | cls.company_b).ids
        cls.pricelist = cls.env["product.pricelist"].create({
            "name": "Layaway Test Pricelist", "currency_id": cls.company_a.currency_id.id,
        })
        cls.retail, cls.distributor = cls.env["product.pricelist"].create([
            {"name": name, "currency_id": cls.company_a.currency_id.id}
            for name in ("Retail 3.3", "Distributor 3.3")
        ])
        cls.config_a, cls.cash_a, cls.card_a, cls.transfer_a = cls._create_payment_config(cls.company_a, "A")
        cls.config_b, cls.cash_b, cls.card_b, cls.transfer_b = cls._create_payment_config(cls.company_b, "B")
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
        cls.supervisor_b = cls._create_user(
            "supervisor_b", cls.company_b, "point_of_sale.group_pos_manager"
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
    def _create_config(cls, company, name, **values):
        warehouse = cls.env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
        return cls.env["pos.config"].with_company(company).create({
            "name": name,
            "company_id": company.id,
            "picking_type_id": warehouse.pos_type_id.id,
            "pricelist_id": cls.pricelist.id,
            "available_pricelist_ids": [(6, 0, (cls.pricelist | cls.retail | cls.distributor).ids)],
            "use_pricelist": True,
            "payment_method_ids": [(5, 0, 0)],
            "journal_id": False,
            "invoice_journal_id": False,
            **values,
        })

    @classmethod
    def _create_payment_config(cls, company, label):
        def account(code, account_type, **values):
            return cls.env["account.account"].with_company(company).create({
                "code": code, "name": code, "company_id": company.id,
                "user_type_id": cls.env.ref("account.data_account_type_" + account_type).id,
                **values,
            })

        def journal(code, kind, **values):
            return cls.env["account.journal"].with_company(company).create({
                "code": code, "name": code, "type": kind, "company_id": company.id, **values,
            })

        liability = account("LWLI", "current_liabilities")
        clearing = account("LWCL", "current_assets", reconcile=True)
        transfer_clearing = account("LWTC", "current_assets", reconcile=True)
        receivable = account("LWAR", "receivable", reconcile=True)
        cash_journal = journal("LWCS", "cash", suspense_account_id=clearing.id)
        card_journal = journal("LWCD", "general")
        transfer_journal = journal("LWTR", "general")
        sale_journal = journal("LWSL", "sale")
        method_model = cls.env["pos.payment.method"].with_company(company)
        cash, card, transfer = method_model.create([
            {"name": "Efectivo", "is_cash_count": True, "cash_journal_id": cash_journal.id,
             "company_id": company.id, "receivable_account_id": receivable.id},
            {"name": "Tarjeta", "layaway_card_clearing_account_id": clearing.id,
             "company_id": company.id, "receivable_account_id": receivable.id},
            {"name": "Transferencia", "layaway_transfer": True,
             "layaway_transfer_clearing_account_id": transfer_clearing.id,
             "company_id": company.id, "receivable_account_id": receivable.id},
        ])
        config = cls._create_config(
            company, "Layaway " + label, cash_control=True, journal_id=sale_journal.id,
            payment_method_ids=[(6, 0, (cash | card | transfer).ids)],
            layaway_liability_account_id=liability.id, layaway_card_journal_id=card_journal.id,
            layaway_transfer_journal_id=transfer_journal.id,
        )
        return config, cash, card, transfer

    @classmethod
    def _create_session(cls, config, user):
        session = cls.env["pos.session"].with_company(config.company_id).create(
            {"config_id": config.id, "user_id": user.id}
        )
        if session.state == "opening_control":
            session.set_cashbox_pos(0, False)
        return session

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

    def _payment(self, session, folio, kind, tenders, reference=None):
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            return session.with_user(session.user_id)._register_layaway_payment(
                folio.id, reference or str(uuid4()), kind, tenders,
            )

    def _wholesale_setup(self):
        for company in self.company_a | self.company_b:
            self.env["pos.wholesale.pricelist.mapping"].create({
                "company_id": company.id, "customer_type": "distribuidores",
                "pricelist_id": self.distributor.id,
            })
            company.write({
                "wholesale_retail_pricelist_id": self.retail.id, "wholesale_pricelist_id": self.pricelist.id,
                "wholesale_previous_month_min": 800, "wholesale_current_order_min": 1500,
                "wholesale_distributor_min": 10000, "wholesale_timezone": "America/Tijuana",
                "wholesale_control_active": True,
            })
        return self.retail, self.distributor

    def _wholesale_history_order(self, partner, amount, moment):
        return self.env["pos.order"].with_company(self.company_a).create({
            "session_id": self.session_a.id, "partner_id": partner.id, "date_order": moment,
            "pricelist_id": self.pricelist.id, "state": "paid",
            "amount_total": amount, "amount_paid": amount, "amount_tax": 0, "amount_return": 0,
        })

    def _wholesale_eligibility(self, session, partner, amount=0):
        return self.env["res.partner"].with_user(session.user_id).get_wholesale_eligibility(
            partner.id, session.company_id.id, amount, session.config_id.id,
        )

    def test_wholesale_layaway_conditional_quote_and_trusted_payment_validation(self):
        retail, distributor = self._wholesale_setup()
        campaign = self.campaigns.create(dict(self.values, deposit_percentage=20))
        campaign.action_activate()
        folio = self._make_folio(campaign)
        product = folio.line_ids.product_id
        product.write({"list_price": 4000, "available_in_pos": True, "taxes_id": [(5, 0, 0)]})
        partner = folio.partner_id
        cashier = self.session_a.with_user(self.cashier_a)
        orders = self.env["pos.order"].with_user(self.cashier_a)
        payload = {
            "name": "Order 14-03-03", "uid": "14-03-03", "pos_session_id": cashier.id,
            "partner_id": partner.id, "pricelist_id": self.pricelist.id, "lines": [],
            "_wholesale_trusted": {"wholesale_final_decision": "wholesale"},
        }
        moment = datetime(2026, 11, 18, 20)
        with patch.object(fields.Datetime, "now", return_value=moment):
            quote = cashier.quote_layaway(
                [{"product_id": product.id, "qty": 1}], campaign.id, partner.id, folio.phone,
            )
            self.assertTrue(quote["wholesale_conditional"])
            self.assertEqual((quote["amount_total"], quote["required_deposit"]), (4000, 800))
            self.assertEqual(quote["lines"][0]["pricelist_id"], self.pricelist.id)
            before = self._wholesale_eligibility(self.session_a, partner)
            self.assertEqual(before["previous_month_amount"], 0)
            self.assertEqual(before["expected_pricelist"]["id"], retail.id)
            with self.assertRaises(UserError):
                orders.create_from_ui([{"data": payload.copy()}])
            with self.assertRaises(ValidationError):
                self._payment(self.session_a, folio, "deposit", [
                    {"method_id": self.card_a.id, "amount": 5000},
                ])
            self.assertEqual(self._wholesale_eligibility(self.session_a, partner), before)
            self._payment(self.session_a, folio, "deposit", [
                {"method_id": self.card_a.id, "amount": 800},
            ])
            after = self._wholesale_eligibility(self.session_b, partner)
            self.assertEqual(after["reason_code"], "layaway_payment")
            self.assertEqual(after["expected_pricelist"]["id"], self.pricelist.id)
            self.assertNotEqual(after["expected_pricelist"]["id"], distributor.id)
            valid = payload.copy()
            orders._wholesale_prepare_payment(valid, orders.browse())
            self.assertEqual(valid["_wholesale_trusted"]["wholesale_reason_code"], "layaway_payment")
            for wrong_list in (retail, distributor):
                with self.assertRaises(UserError):
                    orders.create_from_ui([{"data": dict(payload, pricelist_id=wrong_list.id)}])
            outside = self._wholesale_eligibility(self.session_other, partner)
            self.assertEqual(outside["expected_pricelist"]["id"], retail.id)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 1, 8)):
            december = self._wholesale_eligibility(self.session_b, partner)
            self.assertEqual(december["previous_month_amount"], 800)
            self.assertEqual(december["reason_code"], "previous_month")

    def test_wholesale_layaway_history_by_receipt_month_and_linked_sale(self):
        self._wholesale_setup()
        campaign = self.campaigns.create(self.values)
        campaign.action_activate()
        folio = self._make_folio(campaign)
        partner = folio.partner_id
        self._payment(self.session_a, folio, "deposit", [{"method_id": self.card_a.id, "amount": 2000}])
        cashier = self.session_b.with_user(self.cashier_b)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            november = self._wholesale_eligibility(self.session_b, partner)
            self.assertEqual(november["previous_month_amount"], 0)
            self.assertEqual(november["reason_code"], "current_month")
            self.assertEqual(november["months"][-1]["amount"], 2000)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 1, 7, 59)):
            cashier._register_layaway_payment(
                folio.id, str(uuid4()), "installment", [{"method_id": self.cash_b.id, "amount": 500}],
            )
            pending = cashier.register_layaway_transfer(folio.id, str(uuid4()), "installment", [
                {"method_id": self.transfer_b.id, "amount": 500},
            ])
            before = self._wholesale_eligibility(self.session_a, partner)
            self.assertEqual(before["months"][-1]["amount"], 2500)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 1, 8)):
            manager = self.session_b.with_user(self.supervisor_b)
            manager.authorize_layaway_transfer(
                folio.id, pending["pending_transfers"][0], "TEST-33", "Pago confirmado", "Extracto sintético",
            )
            december = self._wholesale_eligibility(self.session_a, partner)
            self.assertEqual(december["previous_month_amount"], 2500)
            self.assertEqual(december["reason_code"], "previous_month")
            self.assertEqual([row["amount"] for row in december["months"]], [0, 2500, 500])
            product = folio.line_ids.product_id
            product.write({"list_price": 2000, "available_in_pos": True, "taxes_id": [(5, 0, 0)]})
            quote = cashier.quote_layaway([{"product_id": product.id, "qty": 1}], campaign.id,
                                          layaway_id=folio.id)
            self.assertEqual(quote["required_deposit"], 0)
            self.assertFalse(quote["wholesale_conditional"])
            line = {key: value for key, value in quote["lines"][0].items() if key != "tax_details"}
            self.env["pos.layaway.line"].create(dict(line, layaway_id=folio.id))
            self.assertEqual((folio.amount_total, folio.amount_paid), (6000, 3000))
            self.assertEqual(self._wholesale_eligibility(self.session_a, partner), december)
            folio.sale_id = self._wholesale_history_order(partner, 6000, datetime(2026, 12, 1, 8))
            self.assertEqual(self._wholesale_eligibility(self.session_a, partner), december)

    def test_wholesale_ordinary_thresholds_and_distributor_tier(self):
        retail, distributor = self._wholesale_setup()
        campaign = self.campaigns.create(self.values)
        campaign.action_activate()
        folio = self._make_folio(campaign)
        partner = folio.partner_id
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            self.assertEqual(self._wholesale_eligibility(self.session_a, partner, 1499.99)
                             ["expected_pricelist"]["id"], retail.id)
            self.assertEqual(self._wholesale_eligibility(self.session_a, partner, 1500)
                             ["reason_code"], "current_order")
            ordinary = self._wholesale_history_order(partner, 799.99, datetime(2026, 10, 31, 19))
            self.assertEqual(self._wholesale_eligibility(self.session_a, partner)
                             ["expected_pricelist"]["id"], retail.id)
            ordinary.amount_total = 800
            self.assertEqual(self._wholesale_eligibility(self.session_a, partner)
                             ["reason_code"], "previous_month")

            partner.customer_type = "distribuidores"
            ordinary.amount_total = 9000
            ordinary.date_order = datetime(2026, 11, 17, 19)
            self._payment(self.session_a, folio, "deposit", [
                {"method_id": self.card_a.id, "amount": 2000},
            ])
            self.assertEqual(self._wholesale_eligibility(self.session_a, partner)
                             ["expected_pricelist"]["id"], self.pricelist.id)
            ordinary.amount_total = 10000
            ordinary.date_order = datetime(2026, 10, 31, 19)
            higher = self._wholesale_eligibility(self.session_a, partner)
            self.assertEqual(higher["pricing_program"], "distributor")
            self.assertEqual(higher["expected_pricelist"]["id"], distributor.id)
            product = folio.line_ids.product_id
            product.write({"list_price": 4000, "available_in_pos": True, "taxes_id": [(5, 0, 0)]})
            result = self.session_a.with_user(self.cashier_a).quote_layaway(
                [{"product_id": product.id, "qty": 1}], campaign.id, partner.id, folio.phone,
            )
            self.assertEqual(result["lines"][0]["pricelist_id"], distributor.id)

    def test_wholesale_recalculates_after_posted_reversal_in_tests_only(self):
        retail, _distributor = self._wholesale_setup()
        campaign = self.campaigns.create(self.values)
        campaign.action_activate()
        folio = self._make_folio(campaign)
        self._payment(self.session_a, folio, "deposit", [{"method_id": self.card_a.id, "amount": 2000}])
        partner = folio.partner_id
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 2, 20)):
            before = self._wholesale_eligibility(self.session_a, partner)
            self.assertEqual(before["previous_month_amount"], 2000)
            with patch("odoo.addons.pos_layaway.models.res_partner.layaway_test_database", return_value=False):
                guarded = self._wholesale_eligibility(self.session_a, partner)
                self.assertEqual(guarded["expected_pricelist"]["id"], retail.id)
                self.assertEqual(guarded["previous_month_amount"], 0)
            payment = folio.payment_ids
            reversal = payment.move_id._reverse_moves()
            self.assertEqual(reversal.state, "draft")
            self.assertEqual(self._wholesale_eligibility(self.session_a, partner), before)
            reversal.action_post()
            after = self._wholesale_eligibility(self.session_a, partner)
            self.assertEqual(after["expected_pricelist"]["id"], retail.id)
            self.assertEqual(after["previous_month_amount"], 0)
            self.assertEqual(payment.amount, 2000)

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
        self._payment(self.session_a, folio, "deposit", [{"method_id": self.cash_a.id, "amount": 2000}])
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
        self._payment(self.session_a, folio, "deposit", [{"method_id": self.cash_a.id, "amount": 2000}])
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

    def _checkout_fixture(self):
        self._wholesale_setup()
        campaign = self.campaigns.create(self.values)
        campaign.action_activate()
        partner = self.env["res.partner"].create({
            "name": "Beneficiario de apertura", "phone": "664 234 5678",
        })
        product = self.env["product.product"].create({
            "name": "Mercancía de apertura", "type": "product", "available_in_pos": True,
            "lst_price": 2000, "taxes_id": [(5, 0, 0)],
        })
        for config in self.config_a | self.config_b:
            self.env["stock.quant"]._update_available_quantity(
                product, config.picking_type_id.default_location_src_id, 8,
            )
        return campaign, partner, product

    def _checkout_args(self, session, campaign, product, qty, partner=False, folio=False):
        proposal = {
            "lines": [{"product_id": product.id, "qty": qty}], "campaign_id": campaign.id,
            "partner_id": partner.id if partner else False, "phone": False,
            "layaway_id": folio.id if folio else False,
        }
        quote = session.quote_layaway(**proposal)
        return quote, [str(uuid4()), proposal, quote["confirmation"]]

    def _checkout_state(self, folio):
        pickings = self.env["stock.picking"].search([("layaway_id", "=", folio.id)])
        return (
            folio.line_ids.ids, folio.payment_ids.ids,
            pickings.ids, pickings.move_lines.mapped("reserved_availability"),
            folio.amount_total, folio.amount_paid, folio.amount_due,
            self.session_a.cash_register_balance_end, self.session_b.cash_register_balance_end,
        )

    def test_checkout_open_and_add_at_original_deadline(self):
        campaign, partner, product = self._checkout_fixture()
        cashier_a = self.session_a.with_user(self.cashier_a)
        cashier_b = self.session_b.with_user(self.cashier_b)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            self.assertEqual(self._wholesale_eligibility(self.session_a, partner)["automatic_decision"], "retail")
            quote, opening = self._checkout_args(cashier_a, campaign, product, 2, partner)
            self.assertEqual((quote["amount_total"], quote["required_deposit"]), (4000, 2000))
            tenders = [
                {"method_id": self.cash_a.id, "amount": 1200, "amount_tendered": 1300},
                {"method_id": self.card_a.id, "amount": 800},
            ]
            opened = cashier_a.confirm_layaway(*opening, tenders)
            self.assertEqual(cashier_b.confirm_layaway(*opening, tenders), opened)
            self.assertEqual(opened["amount_due"], 2000)
            self.assertEqual(self._wholesale_eligibility(self.session_a, partner)["automatic_decision"], "wholesale")
        folio = self.env["pos.layaway"].browse(opened["id"])
        original = folio.line_ids
        campaign.write({"addition_end": "2026-12-16", "pickup_end": "2026-12-16",
                        "deposit_percentage": 80})
        campaign.action_archive()
        product.lst_price = 1000
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 16, 7, 59)):
            quote, addition = self._checkout_args(cashier_b, campaign, product, 2, folio=folio)
            self.assertEqual((quote["amount_new"], quote["amount_total"], quote["required_deposit"]),
                             (2000, 6000, 1000))
            self.assertEqual(quote["addition_end"], "2026-12-15")
            self.assertEqual(quote["pickup_end"], "2026-12-15")
        tender = [{"method_id": self.cash_b.id, "amount": 1000}]
        before = self._checkout_state(folio)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 16, 8)):
            with self.assertRaisesRegex(ValidationError, "Terminó el plazo"):
                cashier_b.confirm_layaway(*addition, tender)
        self.assertEqual(self._checkout_state(folio), before)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 16, 7, 59)):
            added = cashier_b.confirm_layaway(*addition, tender)
        self.assertEqual(added["folio"], opened["folio"])
        self.assertEqual((added["amount_paid"], added["amount_due"]), (3000, 3000))
        self.assertEqual((original.price_unit, (folio.line_ids - original).price_unit), (2000, 1000))
        self.assertEqual(folio.line_ids.mapped("warehouse_id"),
                         self.config_a.picking_type_id.warehouse_id | self.config_b.picking_type_id.warehouse_id)
        pickings = self.env["stock.picking"].browse([opened["picking_id"], added["picking_id"]])
        self.assertEqual(pickings.mapped("state"), ["assigned", "assigned"])
        self.assertEqual(pickings.move_lines.mapped("quantity_done"), [0, 0])
        self.assertFalse(folio.sale_id)
        self.assertEqual(self.session_a.cash_register_balance_end, 1200)
        self.assertEqual(self.session_b.cash_register_balance_end, 1000)

    def test_checkout_zero_tender_and_rollback_after_stock_failure(self):
        campaign, partner, product = self._checkout_fixture()
        cashier_a = self.session_a.with_user(self.cashier_a)
        cashier_b = self.session_b.with_user(self.cashier_b)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            _, opening = self._checkout_args(cashier_a, campaign, product, 2, partner)
            deposit = [{"method_id": self.cash_a.id, "amount": 2000}]
            opened = cashier_a.confirm_layaway(*opening, deposit)
            folio = self.env["pos.layaway"].browse(opened["id"])
            unavailable = self.env["product.product"].create({
                "name": "Sin stock", "type": "product", "available_in_pos": True,
                "lst_price": 2000, "taxes_id": [(5, 0, 0)],
            })
            _, attempt = self._checkout_args(cashier_b, campaign, unavailable, 1, folio=folio)
            before = self._checkout_state(folio)
            with self.assertRaisesRegex(ValidationError, "insuficiente"):
                cashier_b.confirm_layaway(*attempt, [])
            with self.assertRaisesRegex(ValidationError, "cobro inmediato"):
                cashier_b.confirm_layaway(*attempt, [{"method_id": self.transfer_b.id, "amount": 1000}])
            with self.assertRaisesRegex(UserError, "existencias libres"):
                cashier_b.confirm_layaway(*attempt, [{"method_id": self.cash_b.id, "amount": 1000}])
            self.assertEqual(self._checkout_state(folio), before)
            self.assertFalse(self.env["pos.layaway.operation"].search_count([("reference", "=", attempt[0])]))
            self._payment(self.session_a, folio, "installment", [{"method_id": self.card_a.id, "amount": 1000}])
            quote, addition = self._checkout_args(cashier_b, campaign, product, 1, folio=folio)
            self.assertEqual(quote["required_deposit"], 0)
            added = cashier_b.confirm_layaway(*addition, [])
        self.assertEqual((added["amount_paid"], added["amount_due"], added["payments"]), (3000, 3000, []))
        self.assertEqual(self.session_b.cash_register_balance_end, 0)
        self.assertEqual(folio.line_ids.mapped("amount_total"), [4000, 2000])

    def test_checkout_cannot_import_another_campaign_line_or_deposit(self):
        campaign, partner, product = self._checkout_fixture()
        other = self.campaigns.create(dict(self.values, name="Otra campaña", minimum_amount=5000))
        other.action_activate()
        cashier_a = self.session_a.with_user(self.cashier_a)
        cashier_b = self.session_b.with_user(self.cashier_b)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 20, 20)):
            _, open_first = self._checkout_args(cashier_a, campaign, product, 2, partner)
            _, open_other = self._checkout_args(cashier_a, other, product, 3, partner)
            first = self.env["pos.layaway"].browse(cashier_a.confirm_layaway(
                *open_first, [{"method_id": self.cash_a.id, "amount": 2000}],
            )["id"])
            second = self.env["pos.layaway"].browse(cashier_a.confirm_layaway(
                *open_other, [{"method_id": self.cash_a.id, "amount": 3000}],
            )["id"])
            _, addition = self._checkout_args(cashier_b, campaign, product, 1, folio=first)
            before = self._checkout_state(first), self._checkout_state(second)
            proposed_line = {**addition[1]["lines"][0], "line_id": second.line_ids.id}
            with self.assertRaisesRegex(ValidationError, "datos de la mercancía"):
                cashier_b.confirm_layaway(
                    addition[0], dict(addition[1], lines=[proposed_line]), addition[2],
                    [{"method_id": self.cash_b.id, "amount": 1000}],
                )
            self.assertEqual((self._checkout_state(first), self._checkout_state(second)), before)
            with self.assertRaisesRegex(ValidationError, "desglose de cobro"):
                cashier_b.confirm_layaway(*addition, [{
                    "method_id": self.cash_b.id, "amount": 1000, "payment_id": second.payment_ids.id,
                }])
            self.assertEqual((self._checkout_state(first), self._checkout_state(second)), before)
            with self.assertRaisesRegex(AccessError, "campaña"):
                cashier_b.confirm_layaway(
                    addition[0], dict(addition[1], campaign_id=other.id), addition[2], [],
                )
            with self.assertRaisesRegex(ValidationError, "otra operación"):
                cashier_b.confirm_layaway(open_other[0], *addition[1:], [])
            self.assertEqual((self._checkout_state(first), self._checkout_state(second)), before)

    def test_checkout_rejects_stale_quote_and_non_test_database(self):
        campaign, partner, product = self._checkout_fixture()
        cashier_a = self.session_a.with_user(self.cashier_a)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            _, opening = self._checkout_args(cashier_a, campaign, product, 2, partner)
            deposit = [{"method_id": self.cash_a.id, "amount": 2000}]
            with patch("odoo.addons.pos_layaway.models.pos_layaway_payment.layaway_test_database",
                       return_value=False):
                with self.assertRaisesRegex(AccessError, "disponibles para pruebas"):
                    cashier_a.confirm_layaway(*opening, deposit)
            product.lst_price = 2500
            with self.assertRaisesRegex(ValidationError, "Cambió la cotización"):
                cashier_a.confirm_layaway(*opening, deposit)
            self.assertFalse(self.env["pos.layaway"].search_count([("partner_id", "=", partner.id)]))
            self.assertEqual(self.session_a.cash_register_balance_end, 0)

    def _change_fixture(self, amount=2000):
        campaign, partner, product = self._checkout_fixture()
        cashier = self.session_a.with_user(self.cashier_a)
        _, opening = self._checkout_args(cashier, campaign, product, 2, partner)
        opened = cashier.confirm_layaway(
            *opening, [{"method_id": self.cash_a.id, "amount": amount}],
        )
        folio = self.env["pos.layaway"].browse(opened["id"])
        return campaign, folio, folio.line_ids, self.session_a.with_user(self.supervisor)

    def _change_product(self, price, stock=3):
        product = self.env["product.product"].create({
            "name": "Repuesto de apartado %s" % price, "type": "product",
            "available_in_pos": True, "lst_price": price, "taxes_id": [(5, 0, 0)],
        })
        if stock:
            self.env["stock.quant"]._update_available_quantity(
                product, self.config_a.picking_type_id.default_location_src_id, stock,
            )
        return product

    def _change_stock(self, products):
        location = self.config_a.picking_type_id.default_location_src_id
        quantities = self.env["stock.quant"]
        return {
            product.id: tuple(
                sum(quant[field] for quant in quantities._gather(product, location, strict=True))
                for field in ("quantity", "reserved_quantity")
            )
            for product in products
        }

    def test_change_swaps_entire_proposal_and_recovers_once(self):
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 20, 20)):
            campaign, folio, original, manager = self._change_fixture()
            replacement = self._change_product(3500)
            lines = [{"product_id": replacement.id, "qty": 1}]
            config = self.config_a
            old_move = self.env["stock.move"].search([("layaway_line_id", "=", original.id)])
            self.assertEqual(old_move.reserved_availability, 2)
            self.assertEqual(self._change_stock(original.product_id | replacement),
                             {original.product_id.id: (8, 2), replacement.id: (3, 0)})
            payments = folio.payment_ids
            amount_before = self.session_a.cash_register_balance_end
            campaign.write({"minimum_amount": 5000, "deposit_percentage": 100})
            campaign.action_archive()
            args = [folio.id, original.ids, lines]
            quote = manager.quote_layaway_change(*args)
            reference = str(uuid4())
            result = manager.confirm_layaway_change(
                reference, *args, quote["confirmation"], "  Cambio de modelo  ",
            )
            self.assertEqual(result, manager.confirm_layaway_change(
                reference, *args, quote["confirmation"], "Cambio de modelo",
            ))
            with self.assertRaisesRegex(ValidationError, "otra operación"):
                manager.confirm_layaway_change(
                    reference, *args, quote["confirmation"], "Motivo distinto",
                )
        operation = original.released_by_id
        self.assertEqual((operation.reference, operation.kind, operation.user_id, operation.session_id),
                         (reference, "change_products", self.supervisor, self.session_a))
        self.assertEqual(operation.warehouse_id, config.picking_type_id.warehouse_id)
        self.assertEqual((result["reason"], result["user_id"], result["authorized_at"]),
                         ("Cambio de modelo", self.supervisor.id, "2026-11-20 20:00:00"))
        self.assertEqual([line["id"] for line in result["previous_lines"]], original.ids)
        self.assertEqual(result["previous_lines"][0]["price_unit"], 2000)
        self.assertEqual([line["id"] for line in result["current_lines"]], folio.line_ids.ids)
        self.assertEqual(folio.line_ids.product_id, replacement)
        self.assertEqual([row["qty"] for row in result["released"]], [2])
        self.assertEqual([row["qty"] for row in result["reserved"]], [1])
        self.assertEqual(old_move.state, "cancel")
        self.assertEqual(self._change_stock(original.product_id | replacement),
                         {original.product_id.id: (8, 0), replacement.id: (3, 1)})
        self.assertEqual((folio.amount_total, folio.amount_paid, folio.amount_due), (3500, 2000, 1500))
        self.assertEqual(folio.payment_ids, payments)
        self.assertEqual(self.session_a.cash_register_balance_end, amount_before)
        self.assertFalse(folio.sale_id)

    def test_change_rejects_cashier_empty_minimum_paid_and_coverage(self):
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 20, 20)):
            _, folio, original, manager = self._change_fixture(amount=3600)
            replacements = [(self._change_product(price), message) for price, message in (
                (3000, "mínimo"), (2999.99, "mínimo"),
                (3500, "inferior a lo pagado"), (7300, "insuficiente"),
            )]
            products = original.product_id | self.env["product.product"].browse([
                product.id for product, _ in replacements
            ])
            before = self._checkout_state(folio), self._change_stock(products)
            reference = str(uuid4())
            args = [reference, folio.id, original.ids]
            cashier = self.session_a.with_user(self.cashier_a)
            with self.assertRaisesRegex(AccessError, "encargado"):
                cashier.confirm_layaway_change(*args, [], "0" * 64, "Cambio")
            self.assertEqual((self._checkout_state(folio), self._change_stock(products)), before)
            attempts = [([], "conservar mercancía")] + [
                ([{"product_id": product.id, "qty": 1}], message) for product, message in replacements
            ]
            for lines, message in attempts:
                with self.subTest(message=message, lines=lines):
                    with self.assertRaisesRegex(ValidationError, message):
                        manager.confirm_layaway_change(*args, lines, "0" * 64, "Cambio")
                    self.assertEqual((self._checkout_state(folio), self._change_stock(products)), before)
            self.assertFalse(original.released_by_id)
            self.assertFalse(self.env["pos.layaway.operation"].search_count([
                ("reference", "=", reference),
            ]))

    def test_change_rolls_back_failed_stock_and_checks_stale_quote(self):
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 20, 20)):
            _, folio, original, manager = self._change_fixture()
            replacement = self._change_product(3500, stock=0)
            args = [folio.id, original.ids, [{"product_id": replacement.id, "qty": 1}]]
            before = self._checkout_state(folio), self._change_stock(original.product_id | replacement)
            quote = manager.quote_layaway_change(*args)
            reference = str(uuid4())
            with self.assertRaisesRegex(UserError, "existencias libres"):
                manager.confirm_layaway_change(reference, *args, quote["confirmation"], "Prueba")
            self.assertEqual((self._checkout_state(folio), self._change_stock(
                original.product_id | replacement,
            )), before)
            self.assertFalse(original.released_by_id)
            self.assertFalse(self.env["pos.layaway.operation"].search_count([
                ("reference", "=", reference),
            ]))
            replacement.lst_price = 3700
            with self.assertRaisesRegex(ValidationError, "Cambió la cotización"):
                manager.confirm_layaway_change(reference, *args, quote["confirmation"], "Prueba")
            self.assertEqual((self._checkout_state(folio), self._change_stock(
                original.product_id | replacement,
            )), before)
            with patch("odoo.addons.pos_layaway.models.pos_layaway_change.layaway_test_database",
                       return_value=False):
                self.assertEqual(manager.get_layaway_detail(folio.id)["changeable_lines"], [])
                with self.assertRaisesRegex(AccessError, "disponibles para pruebas"):
                    manager.confirm_layaway_change(reference, *args, quote["confirmation"], "Prueba")

    def test_change_retires_line_and_checks_shop_delivery_and_original_deadline(self):
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 20, 20)):
            campaign, folio, original, manager = self._change_fixture()
            cashier_b = self.session_b.with_user(self.cashier_b)
            self._payment(self.session_a, folio, "installment", [
                {"method_id": self.cash_a.id, "amount": 1500},
            ])
            _, addition = self._checkout_args(cashier_b, campaign, original.product_id, 2, folio=folio)
            cashier_b.confirm_layaway(*addition, [{"method_id": self.cash_b.id, "amount": 500}])
            other_line = folio.line_ids - original
            with self.assertRaisesRegex(ValidationError, "compañías habilitadas"):
                manager.quote_layaway_change(folio.id, other_line.ids, [])
            original.qty_picked_up = 1
            with self.assertRaisesRegex(ValidationError, "mercancía pendiente"):
                manager.quote_layaway_change(folio.id, original.ids, [])
            original.qty_picked_up = 0
            with self.assertRaisesRegex(ValidationError, "motivo"):
                manager.confirm_layaway_change(str(uuid4()), folio.id, original.ids, [], "0" * 64, "  ")
        args = [folio.id, original.ids, []]
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 16, 7, 59)):
            quote = manager.quote_layaway_change(*args)
            with self.assertRaisesRegex(UserError, "estado"), self.env.cr.savepoint():
                folio.sale_id = self._wholesale_history_order(folio.partner_id, 8000, fields.Datetime.now())
                self.assertEqual(manager.get_layaway_detail(folio.id)["changeable_lines"], [])
                manager.confirm_layaway_change(
                    str(uuid4()), *args, quote["confirmation"], "Venta ya liquidada",
                )
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 16, 8)):
            with self.assertRaisesRegex(UserError, "plazo"):
                manager.confirm_layaway_change(str(uuid4()), *args, quote["confirmation"], "Tarde")
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 16, 7, 59)):
            result = manager.confirm_layaway_change(
                str(uuid4()), *args, quote["confirmation"], "Retiro de una línea",
            )
        self.assertEqual(result["reserved"], [])
        self.assertEqual([row["qty"] for row in result["released"]], [2])
        self.assertEqual(folio.line_ids, other_line)
        self.assertEqual((folio.amount_total, folio.amount_paid, folio.amount_due), (4000, 4000, 0))
        self.assertEqual(self._change_stock(original.product_id), {original.product_id.id: (8, 0)})
        move_b = self.env["stock.move"].search([("layaway_line_id", "=", other_line.id)])
        self.assertEqual(move_b.reserved_availability, 2)
        rows = manager.get_layaways({"query": folio.folio, "store": original.warehouse_id.id})["rows"]
        self.assertFalse(rows)

    def test_folio_search_filters_and_other_store_access(self):
        campaign = self.campaigns.create(self.values)
        campaign.action_activate()
        folio = self._make_folio(campaign)
        self._payment(self.session_a, folio, "deposit", [{"method_id": self.cash_a.id, "amount": 2000}])
        self._payment(self.session_b, folio, "installment", [{"method_id": self.card_b.id, "amount": 500}])
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

    def test_mixed_installment_reconciles_to_receiving_sessions(self):
        campaign = self.campaigns.create(self.values)
        campaign.action_activate()
        folio = self._make_folio(campaign)
        session_a, session_b = self.session_a, self.session_b
        baseline_a = session_a.cash_register_balance_end
        baseline_b = session_b.cash_register_balance_end
        self._payment(session_a, folio, "deposit", [{"method_id": self.cash_a.id, "amount": 2000}])
        tenders = [
            {"method_id": self.cash_b.id, "amount": 400, "amount_tendered": 500},
            {"method_id": self.card_b.id, "amount": 600},
        ]
        reference = str(uuid4())
        result = self._payment(session_b, folio, "installment", tenders, reference)
        self.assertEqual(result["amount_paid_before"], 2000)
        self.assertEqual(result["amount_applied"], 1000)
        self.assertEqual(result["amount_paid"], 3000)
        self.assertEqual(result["amount_due"], 1000)
        self.assertEqual((folio.amount_deposit, folio.amount_installments, folio.amount_due), (2000, 1000, 1000))
        self.assertEqual(folio.payment_state, "partial")
        self.assertEqual(folio.pickup_state, "pending")
        self.assertFalse(folio.sale_id)
        installments = folio.payment_ids.filtered(lambda payment: payment.kind == "installment")
        self.assertEqual(set(installments.mapped("reference")), {reference})
        self.assertEqual(installments.campaign_id, campaign)
        self.assertEqual(installments.session_id, session_b)
        self.assertEqual(installments.config_id, self.config_b)
        self.assertEqual(installments.company_id, self.company_b)
        self.assertEqual(installments.warehouse_id, self.config_b.picking_type_id.warehouse_id)
        self.assertEqual(installments.user_id, self.cashier_b)
        self.assertEqual(set(installments.mapped("paid_at")), {datetime(2026, 11, 18, 20)})
        cash = installments.filtered(lambda payment: payment.tender_type == "cash")
        card = installments - cash
        self.assertEqual((cash.amount, cash.amount_tendered, cash.amount_change), (400, 500, 100))
        self.assertEqual(cash.statement_line_id.statement_id, session_b.cash_register_id)
        self.assertEqual(cash.statement_line_id.amount, 400)
        self.assertEqual(card.move_id.state, "posted")
        liability = self.config_b.layaway_liability_account_id
        self.assertEqual(sum((cash | card).move_id.line_ids.filtered(
            lambda line: line.account_id == liability
        ).mapped("credit")), 1000)
        clearing = self.card_b.layaway_card_clearing_account_id
        self.assertEqual(card.move_id.line_ids.filtered(lambda line: line.account_id == clearing).debit, 600)
        visible = self.env["pos.layaway.payment"].with_user(self.supervisor).search([
            ("layaway_id", "=", folio.id),
        ])
        self.assertEqual(visible.ids, folio.payment_ids.filtered_domain([
            ("company_id", "=", self.company_a.id),
        ]).ids)
        self.assertEqual(session_a.cash_register_balance_end, baseline_a + 2000)
        self.assertEqual(session_b.cash_register_balance_end, baseline_b + 400)
        self.assertFalse((session_a | session_b).order_ids)

        with self.assertRaises(AccessError), self.cr.savepoint():
            folio.with_user(self.cashier_b).write({"amount_due": 0})
        with self.assertRaises(AccessError), self.cr.savepoint():
            cash.statement_line_id.with_user(self.cashier_b).write({"amount": 1})
        self.assertEqual(self._payment(session_a, folio, "installment", tenders[::-1], reference), result)
        self.assertEqual(sorted(folio.payment_ids.mapped("amount")), [400, 600, 2000])
        self.assertEqual(folio.amount_due, 1000)
        self.assertEqual(session_b.cash_register_balance_end, baseline_b + 400)
        self.assertEqual(session_a.cash_register_balance_end, baseline_a + 2000)

        for session, expected in ((session_b, baseline_b + 400), (session_a, baseline_a + 2000)):
            session.cash_register_id.balance_end_real = expected
            session.action_pos_session_closing_control()
            session.action_pos_session_validate()
            self.assertEqual(session.state, "closed")
            self.assertEqual(session.cash_real_difference, 0)
            self.assertEqual(session.cash_real_expected, expected)
        self.assertEqual(cash.move_id.state, "posted")
        self.assertEqual(self._payment(session_b, folio, "installment", tenders, reference), result)

    def test_invalid_tenders_leave_balance_payments_and_cash_intact(self):
        campaign = self.campaigns.create(self.values)
        campaign.action_activate()
        folio = self._make_folio(campaign)
        session = self.session_a
        self._payment(session, folio, "deposit", [{"method_id": self.cash_a.id, "amount": 2000}])
        baseline = session.cash_register_balance_end
        payments = folio.payment_ids
        statement_lines = session.cash_register_id.line_ids
        cash = {"method_id": self.cash_a.id, "amount": 400}
        for rejected in (
            [{**cash, "amount": -1}], [{**cash, "amount": 0}], [{**cash, "amount": 0.001}],
            [{**cash, "amount": float("nan")}], [{**cash, "amount": True}],
            [{**cash, "amount": 2000.01}],
            [cash, {"method_id": self.card_a.id, "amount": 600, "amount_tendered": 601}],
            [cash, {"method_id": self.card_b.id, "amount": 600}],
            [{**cash, "amount_tendered": 399}], [cash, cash],
        ):
            with self.subTest(rejected=rejected):
                reference = str(uuid4())
                with self.assertRaises(ValidationError):
                    self._payment(session, folio, "installment", rejected, reference)
                self.assertFalse(self.env["pos.layaway.operation"].search([("reference", "=", reference)]))
                self.assertEqual(folio.payment_ids, payments)
                self.assertEqual(folio.amount_due, 2000)
                self.assertEqual(session.cash_register_balance_end, baseline)
                self.assertEqual(session.cash_register_id.line_ids, statement_lines)
        with self.assertRaisesRegex(UserError, "liquidación"):
            self._payment(session, folio, "installment", [{**cash, "amount": 2000}])
        for amount in (100, 23.45):
            self._payment(session, folio, "installment", [{**cash, "amount": amount}])
        self.assertEqual(folio.amount_due, 1876.55)
        self.assertEqual(len(folio.payment_ids), 3)
        self.assertAlmostEqual(session.cash_register_balance_end, baseline + 123.45)

    def test_mixed_transfer_requires_manual_confirmation_and_confirmed_coverage(self):
        campaign = self.campaigns.create(self.values)
        campaign.action_activate()
        folio = self._make_folio(campaign)
        line = folio.line_ids
        quants = self.env["stock.quant"]
        quants._update_available_quantity(line.product_id, line.location_id, line.qty)
        picking_model = self.env["stock.picking"]
        cashier = self.session_a.with_user(self.cashier_a)
        manager_a = self.session_a.with_user(self.supervisor)
        manager_b = self.session_b.with_user(self.supervisor_b)
        cash_balance = self.session_a.cash_register_balance_end
        tenders = [
            {"method_id": self.cash_a.id, "amount": 400, "amount_tendered": 500},
            {"method_id": self.card_a.id, "amount": 600},
            {"method_id": self.transfer_a.id, "amount": 1000},
        ]
        reference = str(uuid4())
        registered_at = datetime(2026, 11, 18, 20)
        with patch.object(fields.Datetime, "now", return_value=registered_at):
            result = cashier.register_layaway_transfer(folio.id, reference, "deposit", tenders)
            self.assertEqual(
                self.session_b.with_user(self.cashier_b).register_layaway_transfer(
                    folio.id, reference, "deposit", tenders,
                ),
                result,
            )
        transfer = folio.transfer_ids
        self.assertEqual(result["pending_transfers"], transfer.ids)
        self.assertEqual(result["amount_applied"], 1000)
        self.assertEqual(folio.amount_due, 3000)
        self.assertEqual(self.session_a.cash_register_balance_end, cash_balance + 400)
        self.assertEqual(sorted(folio.payment_ids.mapped("amount")), [400, 600])
        self.assertFalse(transfer.payment_id)
        with self.assertRaisesRegex(ValidationError, "insuficiente"):
            picking_model._reserve_layaway_lines(folio, cashier, line)
        self.assertFalse(picking_model.search([("layaway_id", "=", folio.id)]))
        self.assertEqual(quants._get_available_quantity(line.product_id, line.location_id), 2)
        verify = [folio.id, transfer.id, "spei-test-01", "Abono recibido", "Extracto sintético A / 18"]
        with self.assertRaises(AccessError):
            cashier.authorize_layaway_transfer(*verify)
        with self.assertRaises(AccessError):
            manager_b.authorize_layaway_transfer(*verify)
        for index in (2, 3, 4):
            missing = list(verify)
            missing[index] = " "
            with self.assertRaises(ValidationError):
                manager_a.authorize_layaway_transfer(*missing)
        with self.assertRaises(AccessError):
            transfer.with_user(self.supervisor).write({"bank_reference": "FORGED"})

        verified_at = datetime(2026, 11, 19, 20)
        with patch.object(fields.Datetime, "now", return_value=verified_at):
            authorization = manager_a.authorize_layaway_transfer(*verify)
            self.assertEqual(manager_b.authorize_layaway_transfer(*verify), authorization)
            with self.assertRaises(ValidationError):
                manager_b.authorize_layaway_transfer(*verify[:-1], "Evidencia alterada")
        self.assertEqual(transfer.bank_reference, "SPEI-TEST-01")
        self.assertEqual((transfer.reason, transfer.evidence), tuple(verify[3:]))
        self.assertEqual(transfer.authorization_id.user_id, self.supervisor)
        self.assertEqual(transfer.authorization_id.create_date, verified_at)
        payment = transfer.payment_id
        self.assertEqual(payment.tender_type, "transfer")
        self.assertEqual(payment.paid_at, verified_at)
        self.assertEqual(payment.session_id, self.session_a)
        self.assertEqual(payment.user_id, self.cashier_a)
        self.assertEqual(payment.move_id.state, "posted")
        self.assertEqual(payment.move_id.journal_id, self.config_a.layaway_transfer_journal_id)
        self.assertEqual(payment.move_id.line_ids.filtered(
            lambda move_line: move_line.account_id == self.transfer_a.layaway_transfer_clearing_account_id
        ).debit, 1000)
        self.assertFalse(payment.statement_line_id)
        self.assertEqual(self.session_a.cash_register_balance_end, cash_balance + 400)
        self.assertEqual((folio.amount_paid, folio.amount_due), (2000, 2000))
        self.assertEqual(len(folio.payment_ids), 3)
        picking = picking_model._reserve_layaway_lines(folio, cashier, line)
        self.assertEqual(picking.state, "assigned")
        for move_line in picking.move_line_ids:
            move_line.qty_done = move_line.product_uom_qty
        with self.assertRaisesRegex(ValidationError, "después de liquidar"), self.cr.savepoint():
            picking.button_validate()
        self.assertEqual(picking.state, "assigned")
        self.assertFalse(folio.sale_id)

    def test_transfer_cannot_reuse_bank_reference_or_apply_stale_amount(self):
        campaign = self.campaigns.create(self.values)
        campaign.action_activate()
        folio = self._make_folio(campaign)
        cashier = self.session_a.with_user(self.cashier_a)
        manager = self.session_a.with_user(self.supervisor)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            refs = [
                cashier.register_layaway_transfer(folio.id, str(uuid4()), "installment", [
                    {"method_id": self.transfer_a.id, "amount": amount},
                ])["pending_transfers"][0] for amount in (1000, 100, 3000, 2500)
            ]
            manager.authorize_layaway_transfer(folio.id, refs[0], "BANK-01", "Motivo", "Extracto")
            with self.assertRaisesRegex(ValidationError, "ya se aplicó"):
                manager.authorize_layaway_transfer(folio.id, refs[1], " bank-01 ", "Motivo", "Extracto")
            with self.assertRaisesRegex(UserError, "liquidación"):
                manager.authorize_layaway_transfer(folio.id, refs[2], "BANK-02", "Motivo", "Extracto")
            self._payment(self.session_a, folio, "installment", [{"method_id": self.cash_a.id, "amount": 600}])
            with self.assertRaisesRegex(ValidationError, "superar el restante"):
                manager.authorize_layaway_transfer(folio.id, refs[3], "BANK-03", "Motivo", "Extracto")
        self.assertEqual(folio.transfer_ids.filtered("payment_id").ids, refs[:1])
        self.assertEqual(sorted(folio.payment_ids.mapped("amount")), [600, 1000])
        self.assertEqual(folio.amount_due, 2400)

    def test_transfer_endpoints_are_disabled_outside_test_databases(self):
        campaign = self.campaigns.create(self.values)
        campaign.action_activate()
        folio = self._make_folio(campaign)
        cashier = self.session_a.with_user(self.cashier_a)
        manager = self.session_a.with_user(self.supervisor)
        payment_module = "odoo.addons.pos_layaway.models.pos_layaway_payment"
        transfer_module = "odoo.addons.pos_layaway.models.pos_layaway_transfer"
        with patch(payment_module + ".layaway_test_database", return_value=False), patch(
            transfer_module + ".layaway_test_database", return_value=False,
        ):
            self.assertFalse(cashier.get_layaway_detail(folio.id)["transfer_review"])
            with self.assertRaises(AccessError):
                cashier.register_layaway_transfer(folio.id, str(uuid4()), "deposit", [
                    {"method_id": self.transfer_a.id, "amount": 1000},
                ])
            with self.assertRaises(AccessError):
                manager.authorize_layaway_transfer(folio.id, 1, "BANK-01", "Motivo", "Extracto")
        self.assertFalse(folio.transfer_ids)
        self.assertFalse(folio.payment_ids)
