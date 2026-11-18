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

    def test_receipts_preserve_confirmed_opening_and_additions(self):
        campaign, partner, product = self._checkout_fixture()
        cashier_a = self.session_a.with_user(self.cashier_a)
        cashier_b = self.session_b.with_user(self.cashier_b)
        tax = self.env["account.tax"].with_company(self.company_a).create({
            "name": "IVA sintético 16%", "amount": 16, "price_include": True,
            "company_id": self.company_a.id,
        })
        product.taxes_id = tax
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            _, opening = self._checkout_args(cashier_a, campaign, product, 2, partner)
            tenders = [
                {"method_id": self.cash_a.id, "amount": 1200, "amount_tendered": 1300},
                {"method_id": self.card_a.id, "amount": 800},
            ]
            paid = cashier_a.confirm_layaway(*opening, tenders)
            _, other_opening = self._checkout_args(cashier_a, campaign, product, 2, partner)
            covered = cashier_a.confirm_layaway(
                *other_opening, [{"method_id": self.cash_a.id, "amount": 3000}],
            )
        folios = self.env["pos.layaway"].browse([paid["id"], covered["id"]])
        original = paid["receipt"]
        self.assertEqual(original["cashier"], self.cashier_a.name)
        self.assertEqual(original["register"], self.config_a.name)
        self.assertEqual(original["confirmed_at"], "2026-11-18 12:00:00-08:00")
        self.assertEqual(paid["quote"]["lines"][0]["amount_tax"], 551.72)
        self.assertEqual([(p["method_name"], p["amount"]) for p in paid["payments"]],
                         [("Efectivo", 1200), ("Tarjeta", 800)])

        campaign.write({"name": "Campaña editada", "pickup_end": "2026-12-16"})
        campaign.action_archive()
        partner.name = "Cliente editado"
        product.write({"name": "Mercancía renombrada", "lst_price": 1000})
        self.cashier_a.name = "Caja A editada"
        added = []
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 1, 20)):
            for folio, amount in zip(folios, (1000, 0)):
                _, addition = self._checkout_args(cashier_b, campaign, product, 2, folio=folio)
                added.append(cashier_b.confirm_layaway(
                    *addition, [{"method_id": self.cash_b.id, "amount": amount}] if amount else [],
                ))
        self.assertEqual([item["amount_applied"] for item in added], [1000, 0])
        self.assertEqual([item["amount_due"] for item in added], [3000, 3000])
        self.assertEqual(added[1]["payments"], [])
        self.assertEqual(added[0]["quote"]["lines"][0]["price_unit"], 1000)
        before = [self._checkout_state(folio) for folio in folios]
        self.assertEqual(cashier_b.confirm_layaway(*opening, tenders), paid)
        self.assertEqual(cashier_a._layaway_receipt(paid["id"], paid["reference"], True), (paid, False))
        self.assertEqual(cashier_b._layaway_receipt(paid["id"], paid["reference"], True), (paid, True))
        for folio, addition in zip(folios, added):
            self.assertEqual(cashier_a._layaway_receipt(folio.id, addition["reference"]), (addition, True))
            self.assertEqual(addition["quote"]["pickup_end"], "2026-12-15")
            self.assertEqual(addition["quote"]["contact_name"], "Beneficiario de apertura")
        with self.assertRaises(AccessError):
            self.session_other.with_user(self.cashier_a)._layaway_receipt(paid["id"], paid["reference"])
        with self.assertRaises(AccessError):
            cashier_a._layaway_receipt(covered["id"], paid["reference"])
        self.assertEqual(
            cashier_b.get_layaway_detail(paid["id"])["receipts"],
            [{"reference": result["reference"], "kind": result["receipt"]["kind"], "available": True}
             for result in (paid, added[0])],
        )
        self.assertEqual([self._checkout_state(folio) for folio in folios], before)
        self.assertFalse(folios.mapped("sale_id"))

    def test_installment_from_participant_preserves_stock_and_original_receipt(self):
        campaign, partner, product = self._checkout_fixture()
        cashier_a = self.session_a.with_user(self.cashier_a)
        cashier_b = self.session_b.with_user(self.cashier_b)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            _, opening = self._checkout_args(cashier_a, campaign, product, 2, partner)
            opened = cashier_a.confirm_layaway(
                *opening, [{"method_id": self.cash_a.id, "amount": 2000}],
            )
            folio = self.env["pos.layaway"].browse(opened["id"])
            picking = self.env["stock.picking"].browse(opened["picking_id"])
            reserved_lines = picking.move_line_ids
            self.assertEqual(reserved_lines.mapped("product_uom_qty"), [2])
            before = self.session_b.cash_register_balance_end
            detail = cashier_b.get_layaway_detail(folio.id)
            self.assertIn(self.cash_b.id, [method["id"] for method in detail["installment_methods"]])
            args = [folio.id, str(uuid4()), [
                {"method_id": self.cash_b.id, "amount": 400, "amount_tendered": 500},
                {"method_id": self.card_b.id, "amount": 600},
            ]]
            with patch("odoo.addons.pos_layaway.models.pos_layaway_payment.layaway_test_database",
                       return_value=False), self.assertRaises(AccessError):
                cashier_b.register_layaway_installment(*args)
            with self.assertRaises(AccessError):
                self.session_other.with_user(self.cashier_a).register_layaway_installment(*args)
            result = cashier_b.register_layaway_installment(*args)
            self.assertEqual(cashier_a.register_layaway_installment(*args), result)
            self.assertEqual(self.session_b.cash_register_balance_end, before + 400)
            self.assertEqual((result["amount_paid_before"], result["amount_applied"],
                              result["amount_paid"], result["amount_due"]), (2000, 1000, 3000, 1000))
            self.assertEqual(result["receipt"]["amount_total"], 4000)
            self.assertEqual(result["receipt"]["cashier"], self.cashier_b.name)
            self.assertEqual(result["receipt"]["warehouse"], self.config_b.picking_type_id.warehouse_id.display_name)
            self.assertEqual(result["receipt"]["confirmed_at"], "2026-11-18 12:00:00-08:00")
            self.assertEqual([(p["amount"], p["amount_change"]) for p in result["payments"]],
                             [(400, 100), (600, 0)])
            self.assertEqual(cashier_b._layaway_receipt(folio.id, args[1], True), (result, False))

            transfer = cashier_a.register_layaway_transfer(folio.id, str(uuid4()), "installment", [
                {"method_id": self.transfer_a.id, "amount": 250},
            ])
            with self.assertRaises(AccessError):
                cashier_a._layaway_receipt(folio.id, transfer["reference"])
            authorization = self.session_a.with_user(self.supervisor).authorize_layaway_transfer(
                folio.id, transfer["pending_transfers"][0], "SPEI-34", "Prueba", "Extracto sintético",
            )
            self.assertEqual(authorization["payments"][0]["amount"], 250)
            self.assertEqual(authorization["transfer_reference"], transfer["reference"])
            self.assertEqual(cashier_b._layaway_receipt(folio.id, authorization["reference"]),
                             (authorization, True))
            self.assertEqual([row["kind"] for row in cashier_b.get_layaway_detail(folio.id)["receipts"]],
                             ["open", "installment", "installment"])

        self.assertEqual(cashier_a._layaway_receipt(folio.id, args[1]), (result, True))
        self.assertEqual(folio.amount_due, 750)
        self.assertEqual(picking.move_line_ids, reserved_lines)
        self.assertEqual(reserved_lines.mapped("product_uom_qty"), [2])
        self.assertEqual(reserved_lines.mapped("qty_done"), [0])
        self.assertEqual(picking.state, "assigned")
        self.assertFalse(folio.sale_id)

    def test_receipt_history_handles_operations_before_printing_was_available(self):
        campaign = self.campaigns.create(self.values)
        campaign.action_activate()
        folio = self._make_folio(campaign)
        session = self.session_a.with_user(self.cashier_a)
        reference = str(uuid4())
        legacy_result = {"id": folio.id, "folio": folio.folio, "reference": reference}
        operations = self.env["pos.layaway.operation"].sudo()
        operations._confirm(session, reference, "open", [], lambda: (folio, legacy_result))
        self.assertEqual(session.get_layaway_detail(folio.id)["receipts"], [
            {"reference": reference, "kind": "open", "available": False},
        ])
        with self.assertRaisesRegex(AccessError, "comprobante original"):
            session._layaway_receipt(folio.id, reference)
        self.assertEqual(operations._confirm(session, reference, "open", [], self.fail), legacy_result)

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
            self._configure_layaway_settlement(original.product_id, taxes=False)
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
        self.assertEqual(result["sale_id"], folio.sale_id.id)
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
        with self.assertRaisesRegex(UserError, "reserva"):
            self._payment(session, folio, "installment", [{**cash, "amount": 2000}])
        for amount in (100, 23.45):
            self._payment(session, folio, "installment", [{**cash, "amount": amount}])
        self.assertEqual(folio.amount_due, 1876.55)
        self.assertEqual(len(folio.payment_ids), 3)
        self.assertAlmostEqual(session.cash_register_balance_end, baseline + 123.45)

    def test_payment_correction_refunds_cash_and_keeps_original_receipt(self):
        campaign, partner, product = self._checkout_fixture()
        retail = self.retail
        cashier = self.session_a.with_user(self.cashier_a)
        manager = self.session_a.with_user(self.supervisor)
        day = datetime(2026, 11, 18, 20)
        with patch.object(fields.Datetime, "now", return_value=day):
            _, args = self._checkout_args(cashier, campaign, product, 2, partner)
            opened = cashier.confirm_layaway(*args, [{"method_id": self.cash_a.id, "amount": 2000}])
        folio = self.env["pos.layaway"].browse(opened["id"])
        original = folio.payment_ids
        picking = self.env["stock.picking"].browse(opened["picking_id"])
        original_lines = picking.move_line_ids
        original_statement = self.session_a.cash_register_id
        before = original.read(["amount", "method_id", "move_id", "statement_line_id"])
        baseline = self.session_a.cash_register_balance_end
        for values in ({"amount": 10}, {"method_id": self.card_a.id}):
            with self.assertRaises(ValidationError):
                original.with_user(self.supervisor).write(values)
        with self.assertRaises(ValidationError):
            original.with_user(self.supervisor).unlink()
        self.assertEqual(original.read(list(before[0])), before)
        self.assertEqual((folio.amount_due, self.session_a.cash_register_balance_end), (2000, baseline))
        self.assertEqual(folio.payment_ids, original)

        correction = {
            "kind": "refund_payment", "amount": 1300, "reason": "Importe de prueba incorrecto",
            "evidence": "Devolución sintética en efectivo",
        }
        reference = str(uuid4())
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 2, 20)):
            with self.assertRaises(AccessError):
                cashier.correct_layaway_payment(folio.id, original.id, reference, correction)
            with self.assertRaises(AccessError):
                self.session_b.with_user(self.supervisor_b).correct_layaway_payment(
                    folio.id, original.id, reference, correction,
                )
            with patch("odoo.addons.pos_layaway.models.pos_layaway_payment.layaway_test_database",
                       return_value=False), self.assertRaises(AccessError):
                manager.correct_layaway_payment(folio.id, original.id, reference, correction)
            eligibility = self._wholesale_eligibility(self.session_a, partner)
            self.assertEqual(eligibility["previous_month_amount"], 2000)
            result = manager.correct_layaway_payment(folio.id, original.id, reference, correction)
            self.assertEqual(manager.correct_layaway_payment(folio.id, original.id, reference, correction), result)
            with self.assertRaisesRegex(ValidationError, "otra operación"):
                manager.correct_layaway_payment(folio.id, original.id, reference, dict(correction, amount=300))
            with self.assertRaisesRegex(ValidationError, "excede"):
                manager.correct_layaway_payment(folio.id, original.id, str(uuid4()), dict(correction, amount=701))
            eligibility = self._wholesale_eligibility(self.session_a, partner)
            self.assertEqual(eligibility["previous_month_amount"], 700)
            self.assertEqual(eligibility["expected_pricelist"]["id"], retail.id)
            self.assertEqual(cashier._layaway_receipt(folio.id, opened["reference"], True), (opened, False))
        reversal = folio.payment_ids - original
        self.assertEqual(result["reversal_payment_id"], reversal.id)
        self.assertEqual((result["money_returned"], result["corrected_amount"], result["amount_due"]),
                         (1300, 700, 3300))
        self.assertEqual(reversal.amount, -1300)
        self.assertEqual(reversal.corrects_payment_id, original)
        self.assertEqual(reversal.authorization_id.user_id, self.supervisor)
        self.assertEqual(reversal.move_id.reversed_entry_id, original.move_id)
        self.assertEqual(reversal.statement_line_id.statement_id, original_statement)
        self.assertEqual(reversal.statement_line_id.amount, -1300)
        self.assertEqual(original.read(list(before[0])), before)
        self.assertEqual(self.session_a.cash_register_balance_end, baseline - 1300)
        self.assertEqual((folio.amount_paid, folio.amount_due), (700, 3300))
        self.assertEqual(picking.move_line_ids, original_lines)
        self.assertEqual(original_lines.mapped("qty_done"), [0])
        self.assertEqual(picking.state, "assigned")
        original_statement.balance_end_real = baseline - 1300
        self.session_a.action_pos_session_closing_control()
        self.session_a.action_pos_session_validate()
        self.assertEqual((self.session_a.state, self.session_a.cash_real_difference), ("closed", 0))
        self.assertEqual(reversal.move_id.state, "posted")
        history = partner._wholesale_monthly_totals(self.company_a, datetime(2026, 11, 19, 20))
        self.assertEqual(history[-1]["amount"], 2000)

    def test_payment_correction_reclassifies_closed_session_with_linked_sale(self):
        campaign = self.campaigns.create(self.values)
        campaign.action_activate()
        folio = self._make_folio(campaign)
        self._payment(self.session_a, folio, "deposit", [{"method_id": self.cash_a.id, "amount": 2000}])
        initial = self._payment(self.session_b, folio, "installment", [{"method_id": self.card_b.id, "amount": 1000}])
        original = folio.payment_ids.filtered(lambda payment: payment.company_id == self.company_b)
        self.session_b.action_pos_session_closing_control()
        self.session_b.action_pos_session_validate()
        self.assertEqual(self.session_b.state, "closed")
        closed_cash = self.session_b.cash_register_id.line_ids
        total_cash = self.session_b.cash_real_expected
        settlement_at = datetime(2026, 11, 18, 22)
        session_a = self.session_a.with_user(self.cashier_a)
        tender = {"method_id": self.cash_a.id, "amount": 1000, "amount_tendered": 1000, "amount_change": 0}

        def stage_settlement(operation):
            accounting = session_a.sudo().with_company(self.company_a)
            accounting.env["pos.layaway.payment"]._record_tender(
                operation, accounting, folio, "installment", tender,
            )
            return folio, {}

        # Stage the settled state using the payment ledger while the finalization flow is pending.
        with patch.object(fields.Datetime, "now", return_value=settlement_at):
            self.env["pos.layaway.operation"]._confirm(
                session_a, str(uuid4()), "test_settlement", tender, stage_settlement, folio, pass_operation=True,
            )
            folio.sale_id = self._wholesale_history_order(folio.partner_id, 4000, settlement_at)
        self.assertEqual((folio.amount_due, folio.payment_state), (0, "paid"))
        self.assertEqual(folio.sale_id.layaway_ids, folio)
        sale_snapshot = folio.sale_id.read(["amount_total", "state", "lines", "payment_ids"])
        next_session = self._create_session(self.config_b, self.cashier_b)
        manager = next_session.with_user(self.supervisor_b)
        correction = {
            "kind": "reclassify_payment", "method_id": self.transfer_b.id, "reason": "Método de prueba",
            "evidence": "Extracto sintético verificado", "bank_reference": "spei-35-test",
        }
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 2, 20)):
            with self.assertRaisesRegex(UserError, "venta liquidada"):
                manager.correct_layaway_payment(folio.id, original.id, str(uuid4()), {
                    "kind": "refund_payment", "amount": 500, "reason": "Prueba", "evidence": "Prueba",
                })
            with self.assertRaisesRegex(ValidationError, "referencia bancaria"):
                manager.correct_layaway_payment(folio.id, original.id, str(uuid4()),
                                                dict(correction, bank_reference=""))
            reference = str(uuid4())
            result = manager.correct_layaway_payment(folio.id, original.id, reference, correction)
            self.assertEqual(manager.correct_layaway_payment(folio.id, original.id, reference, correction), result)
            with self.assertRaisesRegex(ValidationError, "excede"):
                manager.correct_layaway_payment(folio.id, original.id, str(uuid4()), correction)
            self.assertEqual(manager._layaway_receipt(folio.id, initial["reference"]), (initial, True))
        reversal = self.env["pos.layaway.payment"].browse(result["reversal_payment_id"])
        replacement = self.env["pos.layaway.payment"].browse(result["replacement_payment_id"])
        self.assertEqual(reversal.move_id.reversed_entry_id, original.move_id)
        self.assertEqual((reversal | replacement).corrects_payment_id, original)
        self.assertEqual((reversal | replacement).session_id, self.session_b)
        self.assertEqual((reversal | replacement).operation_id.session_id, next_session)
        self.assertEqual((reversal.amount, replacement.amount, result["money_returned"]), (-1000, 1000, 0))
        self.assertEqual(result["sale_id"], folio.sale_id.id)
        self.assertEqual(folio.sale_id.read(list(sale_snapshot[0])), sale_snapshot)
        self.assertEqual((folio.amount_due, folio.payment_state), (0, "paid"))
        self.assertEqual(original.amount, 1000)
        self.assertEqual(self.session_b.cash_register_id.line_ids, closed_cash)
        self.assertEqual(self.session_b.cash_real_expected, total_cash)
        self.assertFalse(next_session.cash_register_id.line_ids)
        self.assertEqual(self.session_b.state, "closed")
        self.assertEqual(folio.transfer_ids.bank_reference, "SPEI-35-TEST")
        journal_lines = (original | reversal | replacement).move_id.line_ids
        for account, balance in (
            (self.card_b.layaway_card_clearing_account_id, 0),
            (self.transfer_b.layaway_transfer_clearing_account_id, 1000),
            (self.config_b.layaway_liability_account_id, -1000),
        ):
            self.assertEqual(sum(journal_lines.filtered(lambda line: line.account_id == account).mapped("balance")),
                             balance)

    def test_payment_correction_refunds_card_in_current_session(self):
        campaign = self.campaigns.create(self.values)
        campaign.action_activate()
        folio = self._make_folio(campaign)
        self._payment(self.session_a, folio, "deposit", [{"method_id": self.card_a.id, "amount": 2000}])
        original = folio.payment_ids
        self.session_a.action_pos_session_closing_control()
        self.session_a.action_pos_session_validate()
        receiving = self._create_session(self.config_a, self.cashier_a).with_user(self.supervisor)
        correction = {"kind": "refund_payment", "amount": 125, "reason": "Importe", "evidence": "Prueba"}
        result = receiving.correct_layaway_payment(folio.id, original.id, str(uuid4()), correction)
        reversal = self.env["pos.layaway.payment"].browse(result["reversal_payment_id"])
        self.assertEqual((folio.amount_paid, folio.amount_due), (1875, 2125))
        self.assertEqual(reversal.session_id.id, receiving.id)
        self.assertEqual(reversal.move_id.reversed_entry_id, original.move_id)
        self.assertFalse(reversal.statement_line_id)
        self.assertEqual(self.session_a.state, "closed")
        self.assertEqual(reversal.move_id.state, "posted")
        clearing = self.card_a.layaway_card_clearing_account_id
        movements = (original | reversal).move_id.line_ids.filtered(lambda line: line.account_id == clearing)
        self.assertEqual(sorted(movements.mapped("balance")), [-125, 2000])

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
        with self.assertRaisesRegex(AccessError, "desde el apartado"), self.cr.savepoint():
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
            with self.assertRaisesRegex(UserError, "reserva"):
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

    def _settlement_fixture(self):
        campaign, partner, product = self._checkout_fixture()
        self._configure_layaway_settlement(product)
        return campaign, partner, product

    def _configure_layaway_settlement(self, product, taxes=True):
        account_model = self.env["account.account"]
        self.session_b.update_stock_at_closing = True
        self.session_a.update_stock_at_closing = False
        for config in self.config_a | self.config_b:
            company = config.company_id

            def account(code, kind, **kwargs):
                return account_model.create({
                    "code": code, "name": code, "company_id": company.id,
                    "user_type_id": self.env.ref("account.data_account_type_" + kind).id,
                    **kwargs,
                })

            bridge = account("LWBR", "receivable", reconcile=True)
            company.layaway_due_to_account_id = account("LWTO", "current_liabilities")
            company.layaway_due_from_account_id = account("LWFR", "current_assets")
            income = account("LWIN", "revenue")
            product.with_company(company).property_account_income_id = income
            if taxes:
                tax = self.env["account.tax"].with_company(company).create({
                    "name": "IVA sintético 16% incluido", "amount_type": "percent", "amount": 16,
                    "type_tax_use": "sale", "price_include": True, "company_id": company.id,
                })
                product.write({"taxes_id": [(4, tax.id)]})
            config.layaway_application_method_id = self.env["pos.payment.method"].with_company(company).create({
                "name": "Aplicación de cobros de prueba", "receivable_account_id": bridge.id,
                "company_id": company.id, "split_transactions": True, "layaway_application": True,
            })

    def _close_layaway_session(self, session, expected):
        self.assertEqual(session.cash_register_balance_end, expected)
        session.cash_register_id.balance_end_real = expected
        session.action_pos_session_closing_control()
        session.action_pos_session_validate()
        self.assertEqual(session.state, "closed")
        self.assertEqual(session.cash_real_difference, 0)

    def test_settlement_after_cross_shop_addition_and_installments(self):
        campaign, partner, product = self._settlement_fixture()
        a = self.session_a.with_user(self.cashier_a)
        b = self.session_b.with_user(self.cashier_b)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            _, opening = self._checkout_args(a, campaign, product, 2, partner)
            opened = a.confirm_layaway(*opening, [{"method_id": self.cash_a.id, "amount": 2000}])
            folio = self.env["pos.layaway"].browse(opened["id"])
            _, addition = self._checkout_args(b, campaign, product, 1, folio=folio)
            added = b.confirm_layaway(*addition, [{"method_id": self.cash_b.id, "amount": 1000}])
            b.register_layaway_installment(folio.id, str(uuid4()), [
                {"method_id": self.card_b.id, "amount": 1000},
            ])
            self.assertFalse(folio.sale_id)
            pickings = self.env["stock.picking"].browse([opened["picking_id"], added["picking_id"]])
            before = self._checkout_state(folio)
            self._close_layaway_session(self.session_b, 1000)
            ref = str(uuid4())
            args = (folio.id, ref, [{"method_id": self.cash_a.id, "amount": 2000}])
            result = a.register_layaway_installment(*args)
            self.assertEqual(b.register_layaway_installment(*args), result)
            with self.assertRaises(UserError):
                a.register_layaway_installment(folio.id, str(uuid4()), args[-1])
            order = folio.sale_id
            self.assertEqual(order.layaway_ids, folio)
            self.assertEqual((result["sale_id"], result["sale_name"]), (order.id, order.name))
            self.assertEqual(order.amount_tax, 827.58)
            self.assertEqual(order.payment_ids.amount, 6000)
            self.assertEqual((order.amount_total, order.amount_paid, order.state), (6000, 6000, "paid"))
            self.assertEqual(order.lines.mapped("qty"), [2, 1])
            self.assertEqual(len(order.layaway_application_move_ids), 2)
            self.assertEqual(result["settlement"]["amount_previous"], 4000)
            self.assertEqual(result["settlement"]["pickup_state"], "pending")
            self.assertEqual(result["settlement"]["new_payment_ids"], folio.payment_ids[-1:].ids)
            self.assertEqual(result["amount_applied"], 2000)
            self.assertEqual(result["amount_due"], 0)
            ticket, reprint = a._layaway_receipt(folio.id, ref, original=True, final_sale=True)
            self.assertFalse(reprint)
            self.assertEqual(ticket["ticket"]["amount_new"], 2000)
            self.assertEqual(ticket["ticket"]["previous_installments"], 2000)
            self.assertEqual(ticket["ticket"]["previous_deposit"], 2000)
            self.assertEqual(ticket["ticket"]["contact_name"], partner.name)
            self.assertEqual(
                [(line["store"], line["quantity"], line["pending"]) for line in ticket["ticket"]["lines"]],
                [(shop.picking_type_id.warehouse_id.display_name, qty, qty)
                 for shop, qty in [(self.config_a, 2), (self.config_b, 1)]],
            )
            application = order.layaway_application_move_ids
            self.assertEqual(a._layaway_receipt(folio.id, ref, final_sale=True), (ticket, True))
            self.assertEqual(order.layaway_application_move_ids, application)
            operation = self.env["pos.layaway.operation"].search([("reference", "=", ref)])
            legacy = dict(result, settlement=dict(result["settlement"]))
            legacy["settlement"].pop("ticket")
            legacy_ticket = operation._sale_ticket_values(legacy)
            for key, value in ticket["ticket"].items():
                self.assertEqual(legacy_ticket[key], value, key)
            with self.assertRaises(AccessError):
                a._layaway_receipt(folio.id, opened["reference"], final_sale=True)
            with self.assertRaises(AccessError):
                self.session_other.with_user(self.cashier_a)._layaway_receipt(
                    folio.id, ref, final_sale=True,
                )
            self.assertEqual(a.get_layaway_detail(folio.id)["sale_name"], order.name)
            self.assertEqual(self._checkout_state(folio)[2:4], before[2:4])
            monthly = partner._wholesale_monthly_totals(self.company_a, datetime(2026, 11, 19))
            self.assertEqual((monthly[-1]["amount"], monthly[-1]["ordinary_amount"]), (6000, 0))
            with self.assertRaises(UserError):
                order.refund()
            with self.assertRaises(UserError):
                order.action_pos_order_invoice()
            with self.assertRaises(AccessError):
                folio.with_user(self.cashier_a).write({"sale_id": False})

            self._close_layaway_session(self.session_a, 4000)
            self.assertEqual(order.state, "done")
            self.assertFalse(order.picking_ids | (self.session_a | self.session_b).picking_ids)
            self.assertEqual(pickings.mapped("state"), ["assigned", "assigned"])
            self.assertEqual(pickings.move_line_ids.mapped("qty_done"), [0, 0])
            self.assertFalse(pickings.move_lines.stock_valuation_layer_ids)
            self.assertEqual(self._checkout_state(folio)[2:4], before[2:4])
            self.assertEqual(a.register_layaway_installment(*args), result)
            for config in self.config_a | self.config_b:
                liability = config.layaway_liability_account_id
                moves = order.layaway_application_move_ids | folio.payment_ids.move_id
                self.assertEqual(sum(moves.line_ids.filtered_domain([
                    ("account_id", "=", liability.id),
                ]).mapped("balance")), 0)
            bridge = self.config_a.layaway_application_method_id.receivable_account_id
            bridge_lines = (self.session_a.move_id | order.layaway_application_move_ids).line_ids.filtered_domain([
                ("account_id", "=", bridge.id),
            ])
            self.assertEqual(len(bridge_lines), 2)
            self.assertTrue(all(bridge_lines.mapped("reconciled")))
            for company, account, expected in (
                (self.company_a, self.company_a.layaway_due_from_account_id, 2000),
                (self.company_b, self.company_b.layaway_due_to_account_id, -2000),
            ):
                line = order.layaway_application_move_ids.line_ids.filtered_domain([
                    ("account_id", "=", account.id), ("company_id", "=", company.id),
                ])
                self.assertEqual(line.balance, expected)

    def test_settlement_on_initial_payment_and_deferred_close(self):
        campaign, partner, product = self._settlement_fixture()
        b = self.session_b.with_user(self.cashier_b)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            _, request = self._checkout_args(b, campaign, product, 2, partner)
            tender = [{"method_id": self.cash_b.id, "amount": 4000, "amount_tendered": 4100}]
            result = b.confirm_layaway(*request, tender)
            self.assertEqual(b.confirm_layaway(*request, tender), result)
            self.assertEqual(result["settlement"]["amount_previous"], 0)
            self.assertEqual(result["payments"][0]["amount_change"], 100)
            ticket, _ = b._layaway_receipt(result["id"], result["reference"], final_sale=True)
            self.assertEqual(ticket["ticket"]["payments"][0]["amount_change"], 100)
            self.assertIn("final_sale", [
                receipt["kind"] for receipt in b.get_layaway_detail(result["id"])["receipts"]
            ])
            self.assertEqual(b._layaway_receipt(result["id"], result["reference"]), (result, True))
            order = self.env["pos.order"].browse(result["sale_id"])
            self.assertEqual(order.amount_total, 4000)
            self.assertTrue(self.session_b.update_stock_at_closing)
            self._close_layaway_session(self.session_b, 4000)
            self.assertFalse(order.picking_ids | self.session_b.picking_ids)
            picking = self.env["stock.picking"].browse(result["picking_id"])
            self.assertEqual((picking.state, picking.move_lines.reserved_availability), ("assigned", 2))
            self.assertEqual(picking.move_line_ids.qty_done, 0)

    def test_settlement_by_addition_and_transfer_authorization(self):
        campaign, partner, product = self._settlement_fixture()
        a = self.session_a.with_user(self.cashier_a)
        b = self.session_b.with_user(self.cashier_b)
        manager = self.session_a.with_user(self.supervisor)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            _, opening = self._checkout_args(a, campaign, product, 2, partner)
            opened = a.confirm_layaway(*opening, [{"method_id": self.cash_a.id, "amount": 2000}])
            folio = self.env["pos.layaway"].browse(opened["id"])
            _, addition = self._checkout_args(b, campaign, product, 1, folio=folio)
            added = b.confirm_layaway(*addition, [{"method_id": self.card_b.id, "amount": 4000}])
            self.assertEqual((added["amount_due"], folio.sale_id.amount_total), (0, 6000))
            self.assertEqual(b.confirm_layaway(*addition, [{"method_id": self.card_b.id, "amount": 4000}]), added)

            _, opening = self._checkout_args(a, campaign, product, 2, partner)
            opened = a.confirm_layaway(*opening, [{"method_id": self.cash_a.id, "amount": 2000}])
            folio = self.env["pos.layaway"].browse(opened["id"])
            pending = a.register_layaway_transfer(folio.id, str(uuid4()), "installment", [
                {"method_id": self.cash_a.id, "amount": 300},
                {"method_id": self.transfer_a.id, "amount": 1700},
            ])
            self.assertEqual(pending["amount_due"], 1700)
            self.assertFalse(folio.sale_id)
            approval = (folio.id, pending["pending_transfers"][0], "LW SETTLE", "Verificada", "Extracto")
            result = manager.authorize_layaway_transfer(*approval)
            self.assertEqual(manager.authorize_layaway_transfer(*approval), result)
            self.assertEqual(result["settlement"]["amount_previous"], 2300)
            self.assertEqual((result["amount_due"], folio.sale_id.amount_total), (0, 4000))
            ticket, _ = a._layaway_receipt(folio.id, result["reference"], final_sale=True)
            self.assertEqual(ticket["ticket"]["cashier"], manager.env.user.name)
            self.assertEqual(ticket["ticket"]["payments"][0]["method_name"], self.transfer_a.name)

    def test_settlement_explicit_amount_and_rollback_if_reservation_changes(self):
        campaign, partner, product = self._settlement_fixture()
        a = self.session_a.with_user(self.cashier_a)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            _, opening = self._checkout_args(a, campaign, product, 2, partner)
            result = a.confirm_layaway(*opening, [{"method_id": self.cash_a.id, "amount": 2000}])
            folio = self.env["pos.layaway"].browse(result["id"])
            with self.assertRaisesRegex(ValidationError, "restante completo"):
                a.settle_layaway(folio.id, str(uuid4()), [{"method_id": self.cash_a.id, "amount": 100}])

            picking = self.env["stock.picking"].browse(result["picking_id"])
            picking.do_unreserve()
            before = self._checkout_state(folio)
            reference = str(uuid4())
            args = (folio.id, reference, [{"method_id": self.cash_a.id, "amount": 2000}])
            with self.assertRaisesRegex(UserError, "reserva"):
                a.settle_layaway(*args)
            self.assertEqual(self._checkout_state(folio), before)
            self.assertFalse(folio.sale_id)
            picking.action_assign()
            settled = a.settle_layaway(*args)
            self.assertEqual(settled["sale_id"], folio.sale_id.id)

    def test_settlement_when_authorized_change_reduces_total_to_paid_amount(self):
        campaign, partner, product = self._settlement_fixture()
        a = self.session_a.with_user(self.cashier_a)
        manager = self.session_a.with_user(self.supervisor)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            _, opening = self._checkout_args(a, campaign, product, 3, partner)
            result = a.confirm_layaway(*opening, [{"method_id": self.cash_a.id, "amount": 4000}])
            folio = self.env["pos.layaway"].browse(result["id"])
            plan = [folio.id, folio.line_ids.ids, [{"product_id": product.id, "qty": 2}]]
            quote = manager.quote_layaway_change(*plan)
            args = [str(uuid4()), *plan, quote["confirmation"], "Ajuste al importe ya cubierto"]
            adjusted = manager.confirm_layaway_change(*args)
            self.assertEqual(manager.confirm_layaway_change(*args), adjusted)
            self.assertEqual(adjusted["sale_id"], folio.sale_id.id)
            self.assertEqual((folio.amount_due, folio.sale_id.amount_total), (0, 4000))
            self.assertEqual(adjusted["settlement"]["amount_previous"], 4000)
            self.assertEqual(adjusted["settlement"]["new_payment_ids"], [])
            ticket, _ = a._layaway_receipt(folio.id, adjusted["reference"], final_sale=True)
            self.assertEqual(ticket["ticket"]["amount_new"], 0)
            self.assertEqual(ticket["ticket"]["payments"], [])
            self.assertIn("final_sale", [
                receipt["kind"] for receipt in a.get_layaway_detail(folio.id)["receipts"]
            ])
            self.assertEqual(len(folio.payment_ids), 1)
            self.assertEqual(self.session_a.cash_register_balance_end, 4000)

    def _adjustment_fixture(self):
        campaign, partner, product = self._settlement_fixture()
        replacement = self._change_product(4000)
        for company in self.company_a | self.company_b:
            replacement.with_company(company).property_account_income_id = (
                product.with_company(company).property_account_income_id
            )
            partner.with_company(company).property_account_receivable_id = (
                self.env["account.account"].search([
                    ("company_id", "=", company.id), ("code", "=", "LWAR"),
                ], limit=1)
            )
            journal = self.env["account.journal"].with_company(company).create({
                "name": "Ajuste de apartado sintético", "code": "LWAD",
                "type": "sale", "company_id": company.id,
            })
            if "edi_format_ids" in journal._fields:
                journal.edi_format_ids = [(5, 0, 0)]
            config = (self.config_a | self.config_b).filtered(lambda pos: pos.company_id == company)
            config.layaway_adjustment_journal_id = journal
        replacement.taxes_id = product.taxes_id
        a = self.session_a.with_user(self.cashier_a)
        _, opening = self._checkout_args(a, campaign, product, 2, partner)
        result = a.confirm_layaway(*opening, [{"method_id": self.cash_a.id, "amount": 4000}])
        folio = self.env["pos.layaway"].browse(result["id"])
        return campaign, folio, product, replacement, result

    def test_sale_adjustment_swaps_adds_collects_and_reclassifies(self):
        moment = datetime(2026, 11, 20, 20)
        with patch.object(fields.Datetime, "now", return_value=moment):
            campaign, folio, product, replacement, opening = self._adjustment_fixture()
            initial_ticket = self.session_a.with_user(self.cashier_a)._layaway_receipt(
                folio.id, opening["reference"], final_sale=True,
            )
            self._close_layaway_session(self.session_a, 4000)
            sale = folio.sale_id
            sale_snapshot = sale.read(["amount_total", "amount_tax", "payment_ids", "lines", "state"])
            closing_snapshot = self.session_a.move_id.line_ids.read(["debit", "credit", "account_id"])
            next_a = self._create_session(self.config_a, self.cashier_a)
            manager = next_a.with_user(self.supervisor)
            a = next_a.with_user(self.cashier_a)
            b = self.session_b.with_user(self.cashier_b)
            original = folio.line_ids
            proposal = [folio.id, original.ids, [{"product_id": replacement.id, "qty": 1}]]
            quote = manager.quote_layaway_change(*proposal)
            change = [str(uuid4()), *proposal, quote["confirmation"], "Sustitución al mismo precio"]
            with self.assertRaises(AccessError):
                a.confirm_layaway_change(*change)
            swap = manager.confirm_layaway_change(*change)
            self.assertEqual(manager.confirm_layaway_change(*change), swap)
            self.assertEqual(swap["sale_adjustment"]["amount"], 0)
            self.assertEqual((folio.amount_total, folio.amount_paid, folio.amount_due), (4000, 4000, 0))
            self.assertEqual(
                self._change_stock(product | replacement), {product.id: (8, 0), replacement.id: (3, 1)},
            )
            swap_move = self.env["account.move"].browse(swap["sale_adjustment"]["id"])
            self.assertEqual(swap_move.invoice_line_ids.product_id, product | replacement)
            self.assertEqual(set(swap_move.invoice_line_ids.mapped("quantity")), {-2, 1})
            self.assertEqual(swap_move.layaway_adjustment_id.reference, change[0])

        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 15, 20)):
            quote, addition = self._checkout_args(b, campaign, product, 1, folio=folio)
            self.assertEqual((quote["required_deposit"], quote["amount_due"]), (0, 2000))
            added = b.confirm_layaway(*addition, [])
            self.assertEqual(a.confirm_layaway(*addition, []), added)
            self.assertEqual(added["sale_id"], sale.id)
            difference = self.env["account.move"].browse(added["sale_adjustment"]["id"])
            self.assertEqual((difference.amount_total, difference.amount_tax), (2000, 275.86))
            self.assertEqual((difference.invoice_origin, difference.company_id), (sale.name, self.company_a))
            self.assertEqual((folio.amount_due, difference.amount_residual), (2000, 2000))
            with self.assertRaisesRegex(ValidationError, "Cambió la cotización"):
                b.confirm_layaway(str(uuid4()), *addition[1:], [])
            with self.assertRaisesRegex(UserError, "desde el apartado"):
                difference._reverse_moves()
            current = folio.line_ids.filtered(lambda line: line.product_id == replacement)
            smaller = self._change_product(1500)
            with self.assertRaisesRegex(ValidationError, "inferior a lo pagado"):
                manager.quote_layaway_change(folio.id, current.ids, [{"product_id": smaller.id, "qty": 1}])
            pickings = self.env["stock.picking"].search([
                ("layaway_id", "=", folio.id), ("state", "=", "assigned"),
            ])
            for session in (a, b):
                block = session.get_layaway_detail(folio.id)["pickup"]["lines"]
                with self.assertRaisesRegex(ValidationError, "después de liquidar"):
                    session.confirm_layaway_pickup(
                        folio.id, str(uuid4()), {"kind": "holder", "identity_verified": True}, block,
                    )
            for picking in pickings:
                with self.assertRaisesRegex(ValidationError, "después de liquidar"), self.env.cr.savepoint():
                    picking.move_line_ids.qty_done = 1
                    picking._action_done()
            self.assertEqual(pickings.mapped("state"), ["assigned", "assigned"])
            monthly = folio.partner_id._wholesale_monthly_totals(self.company_a)
            self.assertEqual([row["amount"] for row in monthly[-2:]], [4000, 0])
            args = (folio.id, str(uuid4()), [
                {"method_id": self.cash_b.id, "amount": 500},
                {"method_id": self.card_b.id, "amount": 1500},
            ])
            result = b.settle_layaway(*args)
            self.assertEqual(a.settle_layaway(*args), result)
            self.assertEqual((result["amount_due"], result["sale_id"], difference.amount_residual), (0, sale.id, 0))
            self.assertEqual(result["adjustment_payment"]["adjustment_ids"], difference.ids)
            self.assertEqual(len(folio._layaway_adjustment_moves()), 2)
            self.assertEqual(len(b.get_layaway_detail(folio.id)["sale_adjustments"]), 2)
            self.assertEqual(folio.sale_id.read(list(sale_snapshot[0])), sale_snapshot)
            self.assertEqual(self.session_a.move_id.line_ids.read(list(closing_snapshot[0])), closing_snapshot)
            self.assertEqual(a._layaway_receipt(folio.id, opening["reference"])[0], opening)
            self.assertNotEqual(set(folio.line_ids.mapped("product_id").ids), {product.id})
            self.assertEqual(
                b._layaway_receipt(folio.id, opening["reference"], final_sale=True), initial_ticket,
            )
            with self.assertRaises(AccessError):
                b._layaway_receipt(folio.id, result["reference"], final_sale=True)
            self.assertFalse(pickings.move_lines.stock_valuation_layer_ids)
            self.assertFalse(any(pickings.move_line_ids.mapped("qty_done")))
            self._close_layaway_session(self.session_b, 500)
            next_b = self._create_session(self.config_b, self.cashier_b)
            manager_b = next_b.with_user(self.supervisor_b)
            payment = folio.payment_ids.filtered(lambda line: line.method_id == self.card_b)
            correction = {
                "kind": "reclassify_payment", "method_id": self.transfer_b.id,
                "bank_reference": "LW37 CORRECTION", "reason": "Método corregido", "evidence": "Extracto",
            }
            corrected = manager_b.correct_layaway_payment(folio.id, payment.id, str(uuid4()), correction)
            self.assertEqual((corrected["money_returned"], corrected["amount_due"]), (0, 0))
            self.assertEqual(corrected["sale_id"], sale.id)
            self.assertEqual((payment.amount, difference.amount_residual), (1500, 0))
            monthly = folio.partner_id._wholesale_monthly_totals(self.company_a)
            self.assertEqual([row["amount"] for row in monthly[-2:]], [4000, 2000])
            self.assertEqual([row["ordinary_amount"] for row in monthly[-2:]], [0, 0])

    def test_sale_adjustment_rejects_delivered_and_expired_and_reconciles_credit(self):
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 20, 20)):
            campaign, folio, product, replacement, opening = self._adjustment_fixture()
            a = self.session_a.with_user(self.cashier_a)
            manager = self.session_a.with_user(self.supervisor)
            b = self.session_b.with_user(self.cashier_b)
            manager_b = self.session_b.with_user(self.supervisor_b)
            original = folio.line_ids
            original_picking = self.env["stock.picking"].browse(opening["picking_id"])
            self.env["stock.quant"]._update_available_quantity(
                replacement, b.config_id.picking_type_id.default_location_src_id, 1,
            )
            _, addition = self._checkout_args(b, campaign, replacement, 1, folio=folio)
            added = b.confirm_layaway(*addition, [])
            added_line = folio.line_ids - original
            lines = [{"product_id": product.id, "qty": 1}]
            quote = manager_b.quote_layaway_change(folio.id, added_line.ids, lines)
            removed = manager_b.confirm_layaway_change(
                str(uuid4()), folio.id, added_line.ids, lines, quote["confirmation"],
                "Reduce la adición todavía pendiente",
            )
            invoice, credit = self.env["account.move"].browse([
                added["sale_adjustment"]["id"], removed["sale_adjustment"]["id"],
            ])
            self.assertEqual((folio.amount_due, invoice.amount_residual), (2000, 2000))
            self.assertEqual((credit.move_type, credit.amount_total, credit.amount_residual), ("out_refund", 2000, 0))
            pending = a.register_layaway_transfer(folio.id, str(uuid4()), "installment", [
                {"method_id": self.transfer_a.id, "amount": 2000},
            ])
            self.assertEqual(pending["amount_due"], 2000)
            approved = manager.authorize_layaway_transfer(
                folio.id, pending["pending_transfers"][0], "LW37 DIFF", "Verificada", "Extracto",
            )
            self.assertEqual((approved["amount_due"], invoice.amount_residual), (0, 0))
            a.confirm_layaway_pickup(
                folio.id, str(uuid4()), {"kind": "holder", "identity_verified": True},
                [{"id": original.id, "qty": original.qty}],
            )
            self.assertEqual(folio.pickup_state, "partial")
            self.assertEqual(original_picking.state, "done")
            with self.assertRaisesRegex(ValidationError, "mercancía pendiente"):
                manager.quote_layaway_change(folio.id, original.ids, lines)
            _, after_pickup = self._checkout_args(a, campaign, product, 1, folio=folio)
            self.assertEqual(a.confirm_layaway(*after_pickup, [])["amount_due"], 2000)
            debt = self._checkout_state(folio)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 16, 20)):
            with self.assertRaisesRegex(ValidationError, "Terminó el plazo"):
                self._checkout_args(a, campaign, product, 1, folio=folio)
            pending_lines = (folio.line_ids - original).ids
            with self.assertRaisesRegex(UserError, "plazo"):
                manager.quote_layaway_change(folio.id, pending_lines, lines)
            self.assertEqual(self._checkout_state(folio), debt)

    def test_pickup_requires_identity_local_block_and_full_reservation(self):
        campaign, partner, product = self._settlement_fixture()
        a = self.session_a.with_user(self.cashier_a)
        b = self.session_b.with_user(self.cashier_b)
        other = self.session_other.with_user(self.cashier_a)
        holder = {"kind": "holder", "identity_verified": True}
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            _, opening = self._checkout_args(a, campaign, product, 2, partner)
            result = a.confirm_layaway(*opening, [{"method_id": self.cash_a.id, "amount": 2000}])
            folio = self.env["pos.layaway"].browse(result["id"])
            picking = self.env["stock.picking"].browse(result["picking_id"])
            _, addition = self._checkout_args(b, campaign, product, 1, folio=folio)
            b.confirm_layaway(*addition, [{"method_id": self.cash_b.id, "amount": 1000}])
            lines = a.get_layaway_detail(folio.id)["pickup"]["lines"]
            with self.assertRaisesRegex(ValidationError, "después de liquidar"):
                a.confirm_layaway_pickup(folio.id, str(uuid4()), holder, lines)
            a.settle_layaway(folio.id, str(uuid4()), [{"method_id": self.cash_a.id, "amount": 3000}])
            before = self._checkout_state(folio)
            with self.assertRaises(AccessError):
                other.confirm_layaway_pickup(folio.id, str(uuid4()), holder, lines)
            with self.assertRaisesRegex(ValidationError, "verificaste su identidad"):
                a.confirm_layaway_pickup(folio.id, str(uuid4()), {"kind": "holder"}, lines)
            with patch("odoo.addons.pos_layaway.models.pos_layaway_pickup.layaway_test_database",
                       return_value=False), self.assertRaisesRegex(AccessError, "solo está disponible"):
                a.confirm_layaway_pickup(folio.id, str(uuid4()), holder, lines)
            with self.assertRaisesRegex(ValidationError, "autorizado previamente"):
                a.confirm_layaway_pickup(folio.id, str(uuid4()), {
                    "kind": "authorized", "identity_verified": True, "authorization_reference": str(uuid4()),
                }, lines)
            with self.assertRaisesRegex(ValidationError, "bloque pendiente"):
                b.confirm_layaway_pickup(folio.id, str(uuid4()), holder, lines)
            for qty in (1, 3):
                with self.assertRaisesRegex(ValidationError, "bloque pendiente"):
                    a.confirm_layaway_pickup(folio.id, str(uuid4()), holder, [dict(lines[0], qty=qty)])
            with self.assertRaisesRegex(AccessError, "desde el apartado"):
                picking.button_validate()
            with self.assertRaisesRegex(AccessError, "desde el apartado"), self.cr.savepoint():
                picking.move_line_ids.qty_done = 2
                picking.with_context(layaway_pickup_guard=True)._action_done()
            with self.assertRaisesRegex(UserError, "reserva"), self.cr.savepoint():
                picking.move_lines._do_unreserve()
                a.confirm_layaway_pickup(folio.id, str(uuid4()), holder, lines)
            with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 16, 8)):
                with self.assertRaisesRegex(UserError, "Terminó el plazo"):
                    a.confirm_layaway_pickup(folio.id, str(uuid4()), holder, lines)
            self.assertEqual(self._checkout_state(folio), before)
            self.assertEqual(folio.pickup_state, "pending")
            self.assertFalse(picking.move_line_ids.filtered("qty_done"))
            self.assertFalse(a.get_layaway_detail(folio.id)["pickup"]["history"])

    def test_pickup_by_holder_then_registered_recipient_keeps_the_original_sale(self):
        campaign, partner, product = self._settlement_fixture()
        a = self.session_a.with_user(self.cashier_a)
        b = self.session_b.with_user(self.cashier_b)
        manager_b = self.session_b.with_user(self.supervisor_b)
        authorized = self.env["res.partner"].create({"name": "Persona autorizada de prueba"})
        for company in self.company_a | self.company_b:
            product.with_company(company).standard_price = 100
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            _, opening = self._checkout_args(a, campaign, product, 2, partner)
            result = a.confirm_layaway(*opening, [{"method_id": self.cash_a.id, "amount": 2000}])
            folio = self.env["pos.layaway"].browse(result["id"])
            _, addition = self._checkout_args(b, campaign, product, 1, folio=folio)
            b.confirm_layaway(*addition, [{"method_id": self.cash_b.id, "amount": 1000}])
            a.settle_layaway(folio.id, str(uuid4()), [{"method_id": self.cash_a.id, "amount": 3000}])
            sale = folio.sale_id
            before = self._checkout_state(folio)
            auth_args = (folio.id, str(uuid4()), authorized.id)
            with self.assertRaises(AccessError):
                b.register_layaway_pickup_authorization(*auth_args)
            registration = manager_b.register_layaway_pickup_authorization(*auth_args)
            self.assertEqual(manager_b.register_layaway_pickup_authorization(*auth_args), registration)
            authorized.name = "Nombre editado tras el registro"
            holder = {"kind": "holder", "identity_verified": True}
            a_args = (folio.id, str(uuid4()), holder, a.get_layaway_detail(folio.id)["pickup"]["lines"])
            first = a.confirm_layaway_pickup(*a_args)
            self.assertEqual(first["recipient"]["partner_id"], partner.id)
            self.assertEqual(first["cashier"], self.cashier_a.name)
            self.assertEqual(first["confirmed_at"], "2026-11-18 12:00:00-08:00")
            self.assertEqual(first["pickup_state"], "partial")
            self.assertEqual([line["qty"] for line in first["pending"]], [1])
            b_detail = b.get_layaway_detail(folio.id)["pickup"]
            self.assertEqual(b_detail["authorizations"], [registration])
            self.assertEqual(b_detail["history"], [first])
            recipient = {
                "kind": "authorized", "identity_verified": True, "authorization_reference": auth_args[1],
            }
            second = b.confirm_layaway_pickup(folio.id, str(uuid4()), recipient, b_detail["lines"])
            self.assertEqual(second["recipient"], dict(registration, kind="authorized", identity_verified=True))
            self.assertEqual(second["pickup_state"], "done")
            self.assertFalse(second["pending"])
            self.assertEqual(b.confirm_layaway_pickup(*a_args), first)
            with self.assertRaisesRegex(ValidationError, "bloque pendiente"):
                a.confirm_layaway_pickup(a_args[0], str(uuid4()), *a_args[2:])
            history = a.get_layaway_detail(folio.id)["pickup"]["history"]
            self.assertCountEqual(history, [first, second])
            self.assertEqual((folio.sale_id, sale.layaway_ids), (sale, folio))
            self.assertEqual(self._checkout_state(folio)[4:], before[4:])
            self.assertEqual(folio.payment_ids.ids, before[1])
            for collected, company, qty in ((first, self.company_a, 2), (second, self.company_b, 1)):
                picking = self.env["stock.picking"].browse(collected["picking_ids"])
                self.assertEqual(picking.state, "done")
                self.assertEqual(sum(picking.move_line_ids.mapped("qty_done")), qty)
                valuation = picking.move_lines.stock_valuation_layer_ids
                self.assertEqual((valuation.company_id, valuation.quantity), (company, -qty))
                with self.assertRaises(AccessError):
                    picking.move_line_ids.qty_done = qty + 1

    def test_expiry_review_preserves_paid_reservations_and_authorizes_late_pickups(self):
        campaign, partner, product = self._settlement_fixture()
        a = self.session_a.with_user(self.cashier_a)
        b = self.session_b.with_user(self.cashier_b)
        manager = self.session_a.with_user(self.supervisor)
        holder = {"kind": "holder", "identity_verified": True}
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            _, opening = self._checkout_args(a, campaign, product, 2, partner)
            opened = a.confirm_layaway(*opening, [{"method_id": self.cash_a.id, "amount": 2000}])
            folio = self.env["pos.layaway"].browse(opened["id"])
            _, addition = self._checkout_args(b, campaign, product, 1, folio=folio)
            added = b.confirm_layaway(*addition, [{"method_id": self.cash_b.id, "amount": 1000}])
            a.settle_layaway(folio.id, str(uuid4()), [{"method_id": self.cash_a.id, "amount": 3000}])
        remote = self.env["stock.picking"].browse(added["picking_id"])
        sale = folio.sale_id
        before = self._checkout_state(folio)
        keep = (folio.id, str(uuid4()), "keep_reserved", "Revisadas ambas tiendas.")
        authorize = (folio.id, str(uuid4()), "authorize_late_pickup", "Reserva completa verificada.")
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 16, 7, 59, 59)):
            self.assertFalse(manager.get_layaways({"expiry": "expired"})["rows"])
            self.assertTrue(a.get_layaway_detail(folio.id)["pickup"]["available"])
            with self.assertRaisesRegex(UserError, "vencido"):
                manager.review_expired_layaway(*keep)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 16, 8)):
            expired = manager.get_layaways({"expiry": "expired"})
            self.assertTrue(expired["can_review_expired"])
            self.assertEqual([row["id"] for row in expired["rows"]], folio.ids)
            detail = a.get_layaway_detail(folio.id)
            self.assertFalse(detail["expiry_review"]["can_review"])
            self.assertFalse(detail["pickup"]["available"])
            lines = detail["pickup"]["lines"]
            with self.assertRaises(AccessError):
                a.review_expired_layaway(*keep)
            with self.assertRaises(AccessError):
                self.session_other.with_user(self.supervisor).review_expired_layaway(*keep)
            with patch("odoo.addons.pos_layaway.models.pos_layaway_pickup.layaway_test_database",
                       return_value=False), self.assertRaises(AccessError):
                manager.review_expired_layaway(*keep)
            with self.assertRaisesRegex(ValidationError, "observaciones"):
                manager.review_expired_layaway(*keep[:3], "  ")
            review = manager.review_expired_layaway(*keep)
            self.assertEqual(manager.review_expired_layaway(*keep), review)
            self.assertEqual((review["reviewer"], review["reviewed_at"], review["notes"], review["resolution"]),
                             (self.supervisor.name, "2026-12-16 00:00:00-08:00", keep[3], keep[2]))
            with self.assertRaisesRegex(UserError, "requiere autorización"):
                a.confirm_layaway_pickup(folio.id, str(uuid4()), holder, lines)
            with self.assertRaisesRegex(UserError, "reserva"), self.cr.savepoint():
                remote.do_unreserve()
                manager.review_expired_layaway(*authorize)
            self.assertEqual(self._checkout_state(folio), before)
            authorization = manager.review_expired_layaway(*authorize)
            revoked = manager.review_expired_layaway(
                folio.id, str(uuid4()), "keep_reserved", "Revisión posterior.",
            )
            self.assertFalse(a.get_layaway_detail(folio.id)["pickup"]["available"])
            with self.assertRaisesRegex(UserError, "requiere autorización"):
                a.confirm_layaway_pickup(folio.id, str(uuid4()), holder, lines)
            self.assertEqual(manager.review_expired_layaway(*authorize), authorization)
            new_args = (folio.id, str(uuid4()), *authorize[2:])
            new_auth = manager.review_expired_layaway(*new_args)
            with self.assertRaisesRegex(UserError, "reserva"), self.cr.savepoint():
                remote.do_unreserve()
                a.confirm_layaway_pickup(folio.id, str(uuid4()), holder, lines)
            self.assertEqual(self._checkout_state(folio), before)
            first_args = (folio.id, str(uuid4()), holder, lines)
            first = a.confirm_layaway_pickup(*first_args)
            self.assertEqual((first["pickup_state"], first["late_authorization"]), ("partial", new_args[1]))
            self.assertEqual(b.confirm_layaway_pickup(*first_args), first)
            second = b.confirm_layaway_pickup(folio.id, str(uuid4()), holder, first["pending"])
            self.assertEqual((second["pickup_state"], second["late_authorization"]), ("done", new_args[1]))
            self.assertFalse(manager.get_layaways({"expiry": "expired"})["rows"])
            self.assertEqual(manager.get_layaway_detail(folio.id)["expiry_review"], {
                "can_review": False, "can_convert": False, "credit_end": str(folio.credit_end),
                "history": [review, authorization, revoked, new_auth],
            })
            self.assertEqual(manager.review_expired_layaway(*new_args), new_auth)
            with self.assertRaisesRegex(UserError, "pendiente"):
                manager.review_expired_layaway(folio.id, str(uuid4()), *keep[2:])
            snapshot, _ = b._layaway_receipt(folio.id, first["reference"], pickup=True)
            self.assertEqual(snapshot["late_authorization"], new_args[1])
        self.assertEqual(folio.sale_id, sale)
        self.assertEqual(folio.payment_ids.ids, before[1])
        self.assertEqual(self._checkout_state(folio)[4:], before[4:])

    def test_expiry_rejects_debt_and_voluntary_cancellation_before_and_after_payment(self):
        campaign, partner, product = self._settlement_fixture()
        cashier = self.session_a.with_user(self.cashier_a)
        manager = self.session_a.with_user(self.supervisor)
        unpaid, paid = self.env["pos.layaway"], self.env["pos.layaway"]
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            for liquidate in (False, True):
                _, opening = self._checkout_args(cashier, campaign, product, 2, partner)
                opened = cashier.confirm_layaway(*opening, [{"method_id": self.cash_a.id, "amount": 2000}])
                folio = self.env["pos.layaway"].browse(opened["id"])
                if liquidate:
                    cashier.settle_layaway(folio.id, str(uuid4()), [{"method_id": self.cash_a.id, "amount": 2000}])
                    paid = folio
                else:
                    unpaid = folio
                before = self._checkout_state(folio)
                with self.assertRaisesRegex(ValidationError, "conservar mercancía"):
                    manager.quote_layaway_change(folio.id, folio.line_ids.ids, [])
                with self.assertRaisesRegex(ValidationError, "conserva el historial"):
                    folio.with_user(self.supervisor).unlink()
                self.assertEqual(self._checkout_state(folio), before)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 16, 8)):
            before = {folio.id: self._checkout_state(folio) for folio in unpaid | paid}
            for folio in unpaid | paid:
                with self.assertRaisesRegex(ValidationError, "resolución"):
                    manager.review_expired_layaway(folio.id, str(uuid4()), "cancel", "Lo solicitó el titular.")
                manager.review_expired_layaway(folio.id, str(uuid4()), "keep_reserved", "Consulta del titular.")
                self.assertEqual(self._checkout_state(folio), before[folio.id])
            with self.assertRaisesRegex(ValidationError, "después de liquidar"):
                manager.review_expired_layaway(
                    unpaid.id, str(uuid4()), "authorize_late_pickup", "Aún tiene deuda.",
                )
            self.assertEqual((unpaid.amount_due, paid.amount_due), (2000, 0))
            self.assertFalse(unpaid.sale_id)
            self.assertTrue(paid.sale_id)
            for folio in unpaid | paid:
                self.assertEqual(len(manager.get_layaway_detail(folio.id)["expiry_review"]["history"]), 1)

    def test_expiry_credit_releases_both_shops_and_preserves_net_payments(self):
        campaign, partner, product = self._checkout_fixture()
        a = self.session_a.with_user(self.cashier_a)
        b = self.session_b.with_user(self.cashier_b)
        manager = self.session_a.with_user(self.supervisor)
        remote_manager = self.session_b.with_user(self.supervisor_b)
        correction = {"kind": "refund_payment", "amount": 100, "reason": "Importe incorrecto",
                      "evidence": "Devolución sintética en efectivo"}
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            _, opening = self._checkout_args(a, campaign, product, 2, partner)
            opened = a.confirm_layaway(*opening, [{"method_id": self.cash_a.id, "amount": 2000}])
            folio = self.env["pos.layaway"].browse(opened["id"])
            _, addition = self._checkout_args(b, campaign, product, 1, folio=folio)
            added = b.confirm_layaway(*addition, [{"method_id": self.cash_b.id, "amount": 1000}])
            b.register_layaway_installment(folio.id, str(uuid4()), [
                {"method_id": self.card_b.id, "amount": 500},
            ])
            pending = b.register_layaway_transfer(folio.id, str(uuid4()), "installment", [
                {"method_id": self.transfer_b.id, "amount": 300},
            ])["pending_transfers"][0]
            manager.correct_layaway_payment(folio.id, folio.payment_ids[0].id, str(uuid4()), correction)

        pickings = self.env["stock.picking"].browse([opened["picking_id"], added["picking_id"]])
        lines, payments = folio.line_ids, folio.payment_ids
        args = (folio.id, str(uuid4()), "convert_to_credit", "Vencimiento revisado en ambas tiendas.")
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 16, 7, 59, 59)):
            with self.assertRaisesRegex(UserError, "vencido"):
                manager.review_expired_layaway(*args)

        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 16, 8)):
            self.assertTrue(manager.get_layaway_detail(folio.id)["expiry_review"]["can_convert"])
            self.assertFalse(a.get_layaway_detail(folio.id)["expiry_review"]["can_convert"])
            with self.assertRaises(AccessError):
                a.review_expired_layaway(*args)
            disabled = "odoo.addons.pos_layaway.models.pos_layaway_pickup.layaway_test_database"
            with patch(disabled, return_value=False), self.assertRaises(AccessError):
                manager.review_expired_layaway(*args)
            before = self._checkout_state(folio)
            wholesale_before = self._wholesale_eligibility(self.session_a, partner)
            self.assertEqual(wholesale_before["previous_month_amount"], 3400)
            manager.review_expired_layaway(folio.id, str(uuid4()), "keep_reserved", "Pendiente de confirmar.")
            self.assertEqual(self._checkout_state(folio), before)
            self.assertFalse(folio.expiry_credit_id)

            cancel = type(pickings).action_cancel

            def fail_in_b(records):
                if records.company_id == self.company_b:
                    raise UserError("Synthetic cancellation failure")
                return cancel(records)

            with patch.object(type(pickings), "action_cancel", fail_in_b), self.assertRaisesRegex(
                UserError, "Synthetic cancellation failure",
            ):
                manager.review_expired_layaway(*args)
            self.assertEqual(self._checkout_state(folio), before)
            self.assertEqual(pickings.mapped("state"), ["assigned", "assigned"])
            self.assertFalse(folio.expiry_credit_id)

            result = manager.review_expired_layaway(*args)
            self.assertEqual(remote_manager.review_expired_layaway(*args), result)
            with self.assertRaisesRegex(UserError, "vencido"):
                remote_manager.review_expired_layaway(folio.id, str(uuid4()), *args[2:])
            self.assertEqual(self._wholesale_eligibility(self.session_a, partner), wholesale_before)
            self.assertFalse(manager.get_layaways({"expiry": "expired"})["rows"])
            detail = b.get_layaway_detail(folio.id)
            self.assertEqual(detail["expiry_credit"], result["credit"])
            self.assertEqual(detail["expiry_review"]["history"][-1], result)
            self.assertFalse(detail["transfer_review"]["transfers"][0]["can_approve"])
            with self.assertRaisesRegex(UserError, "no admite abonos"):
                remote_manager.authorize_layaway_transfer(folio.id, pending, "SYN-44", "Prueba", "Extracto")
            with self.assertRaisesRegex(UserError, "saldo por vencimiento"):
                manager.correct_layaway_payment(folio.id, payments[0].id, str(uuid4()), correction)

        credit = folio.expiry_credit_id
        self.assertEqual((credit.partner_id, credit.campaign_id), (partner, campaign))
        self.assertEqual((credit.reason, credit.expires_on, credit.amount), (args[-1], folio.credit_end, 3400))
        self.assertEqual(credit.operation_id.user_id, self.supervisor)
        self.assertEqual(result["debt_released"], 2600)
        self.assertEqual([line["qty"] for line in result["released_lines"]], [2, 1])
        self.assertEqual(lines.released_by_id, credit.operation_id)
        self.assertFalse(folio.line_ids or folio.sale_id or pickings.move_line_ids)
        self.assertEqual((folio.amount_due, folio.amount_paid), (0, 3400))
        self.assertEqual((folio.payment_state, folio.pickup_state), ("converted", "released"))
        self.assertEqual(pickings.mapped("state"), ["cancel", "cancel"])
        self.assertEqual(folio.payment_ids, payments)
        self.assertEqual(self._checkout_state(folio)[-2:], before[-2:])
        self.assertEqual(credit.search_count([("layaway_id", "=", folio.id)]), 1)
        for picking in pickings:
            self.assertEqual(self.env["stock.quant"]._get_available_quantity(product, picking.location_id), 8)

    def test_expiry_credit_rejects_folios_with_a_sale_or_delivery(self):
        campaign, partner, product = self._settlement_fixture()
        cashier = self.session_a.with_user(self.cashier_a)
        manager = self.session_a.with_user(self.supervisor)
        sold = []
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            for collect in (False, True):
                _, opening = self._checkout_args(cashier, campaign, product, 2, partner)
                opened = cashier.confirm_layaway(*opening, [{"method_id": self.cash_a.id, "amount": 2000}])
                folio = self.env["pos.layaway"].browse(opened["id"])
                cashier.settle_layaway(folio.id, str(uuid4()), [{"method_id": self.cash_a.id, "amount": 2000}])
                if collect:
                    cashier.confirm_layaway_pickup(folio.id, str(uuid4()), {
                        "kind": "holder", "identity_verified": True,
                    }, cashier.get_layaway_detail(folio.id)["pickup"]["lines"])
                sold.append(folio)
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 12, 16, 8)):
            for folio, error in zip(sold, ("sin venta ni entregas", "vencido")):
                before = self._checkout_state(folio)
                self.assertFalse(manager.get_layaway_detail(folio.id)["expiry_review"]["can_convert"])
                with self.assertRaisesRegex(UserError, error):
                    manager.review_expired_layaway(folio.id, str(uuid4()), "convert_to_credit", "Prueba")
                self.assertEqual(self._checkout_state(folio), before)
                self.assertFalse(folio.expiry_credit_id)

    def test_settle_and_pickup_is_atomic_and_snapshots_only_the_local_delivery(self):
        campaign, partner, product = self._settlement_fixture()
        a = self.session_a.with_user(self.cashier_a)
        b = self.session_b.with_user(self.cashier_b)
        holder = {"kind": "holder", "identity_verified": True}
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            _, opening = self._checkout_args(a, campaign, product, 2, partner)
            opened = a.confirm_layaway(*opening, [{"method_id": self.cash_a.id, "amount": 2000}])
            folio = self.env["pos.layaway"].browse(opened["id"])
            _, addition = self._checkout_args(b, campaign, product, 1, folio=folio)
            b.confirm_layaway(*addition, [{"method_id": self.cash_b.id, "amount": 1000}])
            lines = a.get_layaway_detail(folio.id)["pickup"]["lines"]
            before = self._checkout_state(folio)
            ref = str(uuid4())
            tenders = [{"method_id": self.cash_a.id, "amount": 3000}]
            failed_recipient = dict(holder, kind="authorized", authorization_reference=str(uuid4()))
            with self.assertRaisesRegex(ValidationError, "autorizado previamente"):
                a.settle_and_pickup_layaway(folio.id, ref, tenders, failed_recipient, lines)
            self.assertEqual(self._checkout_state(folio), before)
            self.assertFalse(folio.sale_id)
            self.assertFalse(self.env["pos.layaway.operation"].search([("reference", "=", ref)]))
            with self.assertRaisesRegex(ValidationError, "bloque pendiente"):
                b.settle_and_pickup_layaway(
                    folio.id, ref, [{"method_id": self.cash_b.id, "amount": 3000}], holder, lines,
                )
            self.assertEqual(self._checkout_state(folio), before)
            args = (folio.id, ref, tenders, holder, lines)
            first = a.settle_and_pickup_layaway(*args)
            self.assertEqual(b.settle_and_pickup_layaway(*args), first)
            self.assertEqual(first["pickup"]["pickup_state"], "partial")
            self.assertEqual(first["pickup"]["pending"], b.get_layaway_detail(folio.id)["pickup"]["lines"])
            self.assertEqual(first["settlement"]["pickup_state"], "partial")
            self.assertEqual([line["pending"] for line in first["settlement"]["lines"]], [0, 1])
            self.assertEqual((folio.sale_id.amount_total, folio.amount_due, len(folio.payment_ids)), (6000, 0, 3))
            self.assertFalse(folio.sale_id.picking_ids)
            self.assertEqual(folio.sale_id.layaway_ids, folio)

            second = b.confirm_layaway_pickup(
                folio.id, str(uuid4()), holder, first["pickup"]["pending"],
            )
            self.assertEqual(second["pickup_state"], "done")
            sale_ticket, reprint = b._layaway_receipt(folio.id, ref, original=True, final_sale=True)
            self.assertTrue(reprint)
            self.assertEqual(sale_ticket["ticket"]["pickup_state"], "partial")
            pickup_ticket, _ = b._layaway_receipt(folio.id, ref, pickup=True)
            self.assertEqual(pickup_ticket["recipient"]["name"], partner.name)
            self.assertEqual(pickup_ticket["pickup_state"], "partial")
            self.assertEqual(pickup_ticket["sale_id"], second["sale_id"])
            self.assertEqual(folio.payment_ids.mapped("amount"), [2000, 1000, 3000])

    def test_relocation_moves_the_reserved_lot_before_pickup_in_another_location(self):
        campaign, partner, product = self._settlement_fixture()
        source = self.config_a.picking_type_id.default_location_src_id
        self.config_a.picking_type_id.warehouse_id.int_type_id.active = True
        warehouse = self.env["stock.warehouse"].with_company(self.company_a).create({
            "name": "Otra tienda de recogida", "code": "REC",
        })
        config = self.config_a.copy({"name": "POS Recogida", "picking_type_id": warehouse.pos_type_id.id})
        destination = config.picking_type_id.default_location_src_id
        session = self._create_session(config, self.cashier_a).with_user(self.cashier_a)
        campaign.write({"pos_config_ids": [(4, config.id)]})
        a = self.session_a.with_user(self.cashier_a)
        supervisor = self.session_a.with_user(self.supervisor)
        lot = self.env["stock.production.lot"].with_company(self.company_a).create({
            "name": "Lote de prueba del traslado", "product_id": product.id,
            "company_id": self.company_a.id,
        })
        product.tracking = "lot"
        quants = self.env["stock.quant"]
        quants._update_available_quantity(product, source, -8)
        quants._update_available_quantity(product, source, 8, lot_id=lot)
        holder = {"kind": "holder", "identity_verified": True}
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 18, 20)):
            _, opening = self._checkout_args(a, campaign, product, 2, partner)
            opened = a.confirm_layaway(*opening, [{"method_id": self.cash_a.id, "amount": 2000}])
            folio = self.env["pos.layaway"].browse(opened["id"])
            before = a.get_layaway_detail(folio.id)["pickup"]
            self.assertFalse(before["destinations"])
            lines = before["lines"]
            args = (folio.id, str(uuid4()), config.id, lines)
            with self.assertRaises(AccessError):
                a.relocate_layaway_block(*args)
            with self.assertRaisesRegex(UserError, "misma compañía"):
                supervisor.relocate_layaway_block(folio.id, str(uuid4()), self.config_b.id, lines)
            with self.assertRaisesRegex(ValidationError, "bloque pendiente"):
                session.settle_and_pickup_layaway(
                    folio.id, str(uuid4()), [{"method_id": self.cash_a.id, "amount": 2000}], holder, lines,
                )
            self.assertFalse(folio.sale_id)
            move = supervisor.relocate_layaway_block(*args)
            self.assertEqual(supervisor.relocate_layaway_block(*args), move)
            transfer = self.env["stock.picking"].browse(move["transfer_id"])
            reservation = self.env["stock.picking"].browse(move["reservation_id"])
            self.assertEqual((transfer.state, transfer.picking_type_code), ("done", "internal"))
            self.assertEqual((transfer.location_id, transfer.location_dest_id), (source, destination))
            self.assertEqual(transfer.move_line_ids.lot_id, lot)
            self.assertEqual(transfer.move_line_ids.qty_done, 2)
            self.assertEqual(reservation.move_lines.move_orig_ids, transfer.move_lines)
            self.assertEqual(reservation.move_line_ids.lot_id, lot)
            self.assertEqual(reservation.move_line_ids.product_qty, 2)
            self.assertEqual((folio.amount_due, folio.pickup_state), (2000, "pending"))
            self.assertFalse(a.get_layaway_detail(folio.id)["pickup"]["lines"])
            self.assertEqual(supervisor._layaway_changeable_lines(folio), folio.line_ids)
            detail = session.get_layaway_detail(folio.id)["pickup"]
            self.assertEqual(detail["relocations"], [move])
            session.settle_layaway(folio.id, str(uuid4()), [{"method_id": self.cash_a.id, "amount": 2000}])
            collected = session.confirm_layaway_pickup(folio.id, str(uuid4()), holder, detail["lines"])
            self.assertEqual(collected["picking_ids"], reservation.ids)
            self.assertEqual(collected["delivered"][0]["location"], destination.complete_name)
            self.assertEqual(collected["pickup_state"], "done")

    def test_sale_adjustment_requires_new_coverage_and_rolls_back_stock_failure(self):
        with patch.object(fields.Datetime, "now", return_value=datetime(2026, 11, 20, 20)):
            campaign, folio, product, _, opening = self._adjustment_fixture()
            b = self.session_b.with_user(self.cashier_b)
            state = self._checkout_state(folio)
            quote, shortage = self._checkout_args(b, campaign, product, 9, folio=folio)
            tenders = [{"method_id": self.cash_b.id, "amount": quote["required_deposit"]}]
            with self.assertRaisesRegex(UserError, "existencias libres"):
                b.confirm_layaway(*shortage, tenders)
            self.assertEqual(self._checkout_state(folio), state)
            self.assertFalse(folio._layaway_adjustment_moves())

            quote, addition = self._checkout_args(b, campaign, product, 3, folio=folio)
            self.assertEqual(quote["required_deposit"], 1000)
            with self.assertRaisesRegex(ValidationError, "insuficiente"):
                b.confirm_layaway(*addition, [])
            with patch("odoo.addons.pos_layaway.models.pos_layaway_payment.layaway_test_database",
                       return_value=False):
                with self.assertRaisesRegex(AccessError, "solo están disponibles para pruebas"):
                    b.confirm_layaway(*addition, tenders)
            self.assertEqual(self._checkout_state(folio), state)

            added = b.confirm_layaway(*addition, [{"method_id": self.cash_b.id, "amount": 1000}])
            self.assertEqual((added["amount_paid"], added["amount_due"]), (5000, 5000))
            self.assertEqual(added["sale_id"], opening["sale_id"])
            self.assertEqual(folio._layaway_adjustment_moves().amount_residual, 5000)
            self.assertEqual(self.session_b.cash_register_balance_end, 1000)
