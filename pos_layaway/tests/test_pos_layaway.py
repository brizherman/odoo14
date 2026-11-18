from datetime import datetime
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
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
