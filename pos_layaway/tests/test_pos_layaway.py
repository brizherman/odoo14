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
        cls.company_a = cls.env.company
        cls.company_b = cls.env["res.company"].create({
            "name": "Layaway Company B", "currency_id": cls.company_a.currency_id.id,
        })
        cls.company_ids = (cls.company_a | cls.company_b).ids
        cls.pricelist = cls.env["product.pricelist"].create({
            "name": "Layaway Test Pricelist", "currency_id": cls.company_a.currency_id.id,
        })
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
            "available_pricelist_ids": [(6, 0, cls.pricelist.ids)],
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
