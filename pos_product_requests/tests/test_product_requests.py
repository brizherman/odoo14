from uuid import uuid4

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import SavepointCase, tagged
from odoo.tests.common import new_test_user


@tagged("post_install", "-at_install")
class TestProductRequests(SavepointCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cashier = new_test_user(
            cls.env, login="requests_cashier",
            groups="base.group_user,point_of_sale.group_pos_user",
        )
        cls.other_user = new_test_user(cls.env, login="requests_non_pos")
        cls.system_user = new_test_user(
            cls.env, login="requests_system", groups="base.group_user,base.group_system",
        )
        cls.manager = new_test_user(
            cls.env, login="requests_manager",
            groups="base.group_user,point_of_sale.group_pos_manager",
        )
        cls.config = cls.env["pos.config"].create({"name": "Requests test POS"})
        cls.session = cls.env["pos.session"].create({
            "config_id": cls.config.id,
            "user_id": cls.cashier.id,
        })
        cls.other_config = cls.env["pos.config"].create({"name": "Other test POS"})
        cls.other_session = cls.env["pos.session"].create({
            "config_id": cls.other_config.id,
            "user_id": cls.cashier.id,
        })
        cls.requests = cls.env["pos.product.request"]
        cls.cashier_requests = cls.requests.with_user(cls.cashier)

    def save(self, text="Special screw", reason="out_of_stock", key=None, session=None):
        return self.cashier_requests.save_from_pos(
            (session or self.session).id, text, reason, key or str(uuid4()),
        )

    def test_rejects_blank_text_invalid_reason_and_invalid_key(self):
        for text, reason in [
            ("", "out_of_stock"), (" \r\n\t", "out_of_stock"),
            ("Screw", ""), ("Screw", "unknown"), ("Screw", ["out_of_stock"]),
        ]:
            with self.subTest(text=text, reason=reason), self.assertRaises(ValidationError):
                self.save(text, reason)
        with self.assertRaises(ValidationError):
            self.save(key="invalid")
        self.assertFalse(self.cashier_requests.history_from_pos(self.session.id))

    def test_save_is_independent_of_order_and_client(self):
        captured = self.requests.browse(self.save("  Special screw  ", "not_carried"))
        self.assertEqual(captured.product_text, "Special screw")
        self.assertEqual(captured.reason, "not_carried")
        self.assertEqual(captured.config_id, self.config)
        self.assertEqual(captured.company_id, self.config.company_id)
        self.assertLessEqual(captured.create_date, fields.Datetime.now())
        self.assertFalse(self.session.order_ids)

    def test_same_capture_is_idempotent_and_distinct_captures_are_independent(self):
        key = str(uuid4())
        first = self.save(key=key)
        self.assertEqual(self.save(key=key), first)
        self.assertEqual(self.save(key=key.replace("-", "").upper()), first)
        with self.assertRaises(ValidationError):
            self.save("Different product", key=key)
        second = self.save()
        self.assertNotEqual(first, second)
        rows = self.cashier_requests.history_from_pos(self.session.id)
        self.assertEqual([row["id"] for row in rows], [second, first])

    def test_history_across_sessions_is_sorted_and_scoped(self):
        old = self.save("Old")
        self.session.write({"state": "closed", "stop_at": fields.Datetime.now()})
        current_session = self.env["pos.session"].create({"config_id": self.config.id})
        first = self.save("First", "not_carried", session=current_session)
        second = self.save("Second", "does_not_exist", session=current_session)
        other = self.save("Other POS", session=self.other_session)
        dates = ("2026-01-01 12:00:00", "2026-01-02 12:00:00")
        self.env.cr.execute(
            "UPDATE pos_product_request SET create_date = %s WHERE id = %s",
            (dates[0], old),
        )
        self.env.cr.execute(
            "UPDATE pos_product_request SET create_date = %s WHERE id IN %s",
            (dates[1], (first, second)),
        )
        self.requests.invalidate_cache(["create_date"])
        rows = self.cashier_requests.history_from_pos(current_session.id)
        self.assertEqual([row["id"] for row in rows], [second, first, old])
        self.assertEqual(
            [(row["product_text"], row["reason_label"], row["create_date"]) for row in rows],
            [
                ("Second", "Does not exist", dates[1]),
                ("First", "We don't carry it", dates[1]),
                ("Old", "Out of stock", dates[0]),
            ],
        )
        self.assertEqual(
            [row["id"] for row in self.cashier_requests.history_from_pos(self.other_session.id)],
            [other],
        )

    def test_session_must_be_open_and_not_a_rescue(self):
        for values in [
            {"state": "opening_control"}, {"state": "closing_control"},
            {"state": "closed"}, {"state": "opened", "rescue": True},
        ]:
            self.session.write(values)
            with self.assertRaises(AccessError):
                self.save()
            with self.assertRaises(AccessError):
                self.cashier_requests.history_from_pos(self.session.id)
        for invalid_id in (False, "1", -1, 2147483647):
            with self.subTest(session_id=invalid_id), self.assertRaises(AccessError):
                self.cashier_requests.history_from_pos(invalid_id)

    def test_rpc_requires_pos_access_and_cashier_has_no_direct_crud(self):
        captured = self.cashier_requests.browse(self.save())
        users_requests = self.requests.with_user(self.other_user)
        with self.assertRaises(AccessError):
            users_requests.save_from_pos(self.session.id, "Screw", "out_of_stock", str(uuid4()))
        with self.assertRaises(AccessError):
            users_requests.history_from_pos(self.session.id)
        for operation in (
            lambda: self.cashier_requests.search([]),
            lambda: self.cashier_requests.create({"product_text": "Screw"}),
            lambda: captured.write({"product_text": "Changed"}),
            captured.unlink,
        ):
            with self.assertRaises(AccessError):
                operation()

    def test_company_isolation_in_rpc_and_record_rule(self):
        company = self.env["res.company"].create({"name": "Other requests company"})
        config = self.env["pos.config"].with_company(company).create({
            "name": "Other company POS",
            "company_id": company.id,
        })
        session = self.env["pos.session"].with_company(company).create({"config_id": config.id})
        external_cashier = new_test_user(
            self.env, login="requests_external_cashier",
            groups="base.group_user,point_of_sale.group_pos_user",
            company_id=company.id, company_ids=[(6, 0, company.ids)],
        )
        outside = self.requests.with_context(allowed_company_ids=company.ids).with_user(
            external_cashier,
        ).save_from_pos(session.id, "External", "out_of_stock", str(uuid4()))
        inside = self.save()
        with self.assertRaises(AccessError):
            self.cashier_requests.history_from_pos(session.id)
        with self.assertRaises(AccessError):
            self.save(session=session)
        with self.assertRaises(AccessError):
            self.cashier_requests.with_context(
                allowed_company_ids=company.ids,
            ).history_from_pos(session.id)
        for user in self.system_user | self.manager:
            visible = self.requests.with_user(user).search([]).ids
            self.assertIn(inside, visible)
            self.assertNotIn(outside, visible)

    def test_backend_menu_is_visible_to_pos_manager_with_read_only_access(self):
        menu = self.env.ref("pos_product_requests.pos_product_request_menu")
        self.assertEqual(menu.parent_id, self.env.ref("point_of_sale.menu_point_of_sale"))
        self.assertEqual(menu.action.res_model, self.requests._name)
        self.assertIn(menu.id, menu.with_user(self.manager)._visible_menu_ids())
        self.assertNotIn(menu.id, menu.with_user(self.cashier)._visible_menu_ids())

        manager_requests = self.requests.with_user(self.manager)
        captured = manager_requests.browse(self.save())
        self.assertEqual(captured.read(["product_text"])[0]["product_text"], "Special screw")
        for operation in (
            lambda: manager_requests.create({"product_text": "Direct request"}),
            lambda: captured.write({"product_text": "Changed"}),
            captured.unlink,
        ):
            with self.assertRaises(AccessError):
                operation()
