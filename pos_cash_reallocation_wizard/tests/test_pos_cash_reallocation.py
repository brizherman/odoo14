# -*- coding: utf-8 -*-
import uuid
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase

from odoo.addons.pos_cash_reallocation_wizard.models.pos_order import (
    CASH_PAYMENT_METHOD_NAME,
    WALLET_PAYMENT_METHOD_NAME,
)


class TestPosCashReallocation(TransactionCase):
    """Tests for POS Cash Reallocation Wizard module."""

    def setUp(self):
        super(TestPosCashReallocation, self).setUp()
        self.PosSession = self.env['pos.session']
        self.PosOrder = self.env['pos.order']
        self.PosPaymentMethod = self.env['pos.payment.method']
        self.Wizard = self.env['pos.cash.reallocation.wizard']
        self.Log = self.env['pos.cash.reallocation.log']
        self.product = self.env['product.product'].create({
            'name': 'Reallocation Test Product',
            'list_price': 100.0,
            'available_in_pos': True,
        })

        self.reallocation_group = self.env.ref(
            'pos_cash_reallocation_wizard.group_pos_cash_reallocation_manager'
        )
        self.env.user.write({'groups_id': [(4, self.reallocation_group.id)]})

        account_id = self.env.company.account_default_pos_receivable_account_id
        cash_journal = self.env['account.journal'].search([
            ('type', '=', 'cash'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)

        self.cash_payment_method = self.PosPaymentMethod.search([
            ('company_id', '=', self.env.company.id),
            ('name', '=', CASH_PAYMENT_METHOD_NAME),
            ('is_cash_count', '=', True),
        ], limit=1)
        if not self.cash_payment_method:
            self.cash_payment_method = self.PosPaymentMethod.create({
                'name': CASH_PAYMENT_METHOD_NAME,
                'is_cash_count': True,
                'receivable_account_id': account_id.id,
                'cash_journal_id': cash_journal.id,
                'company_id': self.env.company.id,
            })

        bank_name = 'Bank Test Realloc %s' % uuid.uuid4().hex[:8]
        self.bank_payment_method = self.PosPaymentMethod.create({
            'name': bank_name,
            'receivable_account_id': account_id.id,
            'company_id': self.env.company.id,
        })

        self.wallet_method = self.PosOrder._setup_wallet_infrastructure_for_company(
            self.env.company
        )

        sale_journal = self.env['account.journal'].search([
            ('type', '=', 'sale'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        pos_config_vals = {
            'journal_id': sale_journal.id,
        }
        self.pos_config_a = self.env['pos.config'].create(dict(
            pos_config_vals,
            name='Reallocation POS A %s' % uuid.uuid4().hex[:6],
        ))
        self.pos_config_b = self.env['pos.config'].create(dict(
            pos_config_vals,
            name='Reallocation POS B %s' % uuid.uuid4().hex[:6],
        ))
        for config in (self.pos_config_a, self.pos_config_b):
            config.payment_method_ids = [
                (6, 0, [self.cash_payment_method.id, self.bank_payment_method.id])
            ]

        self.assertNotIn(
            self.wallet_method,
            self.pos_config_a.payment_method_ids,
            'Wallet method must stay hidden from POS register config.',
        )

        self.basic_user = self.env['res.users'].create({
            'name': 'POS User No Realloc',
            'login': 'pos_no_realloc_%s' % uuid.uuid4().hex[:8],
            'email': 'pos_no_realloc_%s@test.com' % uuid.uuid4().hex[:8],
            'groups_id': [(6, 0, [
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
        })

    def _unique_date_range(self):
        """Narrow window far in the future to avoid production order collisions."""
        base = fields.Datetime.now() + timedelta(days=7300)
        offset = sum(ord(char) for char in self._testMethodName)
        date_from = base + timedelta(hours=offset)
        date_to = date_from + timedelta(hours=1)
        order_date = date_from + timedelta(minutes=15)
        return date_from, date_to, order_date

    def _open_session(self, pos_config):
        pos_config.open_session_cb()
        return pos_config.current_session_id

    def _force_close_session(self, session):
        session.sudo().write({'state': 'closed'})

    def _create_paid_order(
        self,
        session,
        amount,
        partner=False,
        payment_method=None,
        second_payment_method=None,
        second_amount=0.0,
        date_order=None,
    ):
        payment_method = payment_method or self.cash_payment_method
        total = amount + second_amount
        line_vals = {
            'name': 'OL/0001',
            'product_id': self.product.id,
            'qty': 1.0,
            'price_unit': total,
            'price_subtotal': total,
            'price_subtotal_incl': total,
        }
        order_vals = {
            'session_id': session.id,
            'amount_tax': 0,
            'amount_total': total,
            'amount_paid': total,
            'amount_return': 0,
            'lines': [(0, 0, line_vals)],
        }
        if partner:
            order_vals['partner_id'] = partner.id
        if date_order:
            order_vals['date_order'] = date_order

        order = self.PosOrder.create(order_vals)
        order.add_payment({
            'pos_order_id': order.id,
            'amount': amount,
            'payment_date': fields.Datetime.now(),
            'payment_method_id': payment_method.id,
        })
        if second_payment_method:
            order.add_payment({
                'pos_order_id': order.id,
                'amount': second_amount,
                'payment_date': fields.Datetime.now(),
                'payment_method_id': second_payment_method.id,
            })
        order.action_pos_order_paid()
        return order

    def _create_wizard(self, amount, date_from, date_to):
        return self.Wizard.create({
            'company_id': self.env.company.id,
            'date_from': date_from,
            'date_to': date_to,
            'amount_to_reallocate': amount,
        })

    def _run_reallocation(self, amount, date_from, date_to):
        wizard = self._create_wizard(amount, date_from, date_to)
        wizard.action_preview()
        return wizard, wizard.action_confirm()

    # ------------------------------------------------------------------
    # 7.3 Filter eligibility
    # ------------------------------------------------------------------
    def test_01_filter_eligible_orders(self):
        date_from, date_to, order_date = self._unique_date_range()
        session = self._open_session(self.pos_config_a)

        eligible = self._create_paid_order(
            session, 100.0, date_order=order_date,
        )
        with_customer = self._create_paid_order(
            session, 50.0,
            partner=self.env['res.partner'].create({'name': 'Customer'}),
            date_order=order_date,
        )
        mixed = self._create_paid_order(
            session, 60.0, second_payment_method=self.bank_payment_method,
            second_amount=40.0, date_order=order_date,
        )

        wizard = self._create_wizard(10.0, date_from, date_to)
        wizard.action_preview()

        preview_orders = wizard.preview_line_ids.mapped('order_id')
        skipped_orders = wizard.skipped_line_ids.mapped('order_id')

        self.assertTrue(eligible._is_eligible_for_reallocation())
        self.assertFalse(with_customer._is_eligible_for_reallocation())
        self.assertFalse(mixed._is_eligible_for_reallocation())
        self.assertIn(eligible, preview_orders)
        self.assertNotIn(with_customer, preview_orders)
        self.assertIn(mixed, skipped_orders)
        self.assertEqual(wizard.matched_order_count, 1)

    # ------------------------------------------------------------------
    # 7.4 Proportional split
    # ------------------------------------------------------------------
    def test_02_proportional_split(self):
        date_from, date_to, order_date = self._unique_date_range()
        session = self._open_session(self.pos_config_a)
        order_a = self._create_paid_order(session, 100.0, date_order=order_date)
        order_b = self._create_paid_order(session, 200.0, date_order=order_date)
        order_c = self._create_paid_order(session, 300.0, date_order=order_date)
        test_orders = order_a | order_b | order_c

        amount = 100.0
        wizard = self._create_wizard(amount, date_from, date_to)
        shares = wizard._compute_proportional_shares(test_orders, amount)
        self.assertAlmostEqual(sum(shares.values()), amount, places=2)
        self.assertAlmostEqual(
            shares[order_c.id],
            amount - shares[order_a.id] - shares[order_b.id],
            places=2,
        )

        totals_before = {order.id: order.amount_total for order in test_orders}
        wizard.action_preview()
        wizard.action_confirm()

        for order in test_orders:
            order.invalidate_cache()
            self.assertEqual(order.amount_total, totals_before[order.id])

    # ------------------------------------------------------------------
    # 7.5 Session closed before confirm
    # ------------------------------------------------------------------
    def test_03_session_closed_before_confirm(self):
        date_from, date_to, order_date = self._unique_date_range()
        session_a = self._open_session(self.pos_config_a)
        session_b = self._open_session(self.pos_config_b)

        order_closed = self._create_paid_order(
            session_a, 100.0, date_order=order_date,
        )
        order_open = self._create_paid_order(
            session_b, 100.0, date_order=order_date,
        )

        wizard = self._create_wizard(50.0, date_from, date_to)
        wizard.action_preview()
        self._force_close_session(session_a)

        result = wizard.action_confirm()
        order_open.invalidate_cache()
        order_closed.invalidate_cache()

        self.assertEqual(result.get('type'), 'ir.actions.client')
        self.assertTrue(order_open.has_wallet_payment)
        self.assertFalse(order_closed.has_wallet_payment)

        wallet_payments = order_open.payment_ids.filtered(
            lambda payment: payment.payment_method_id == self.wallet_method
        )
        self.assertAlmostEqual(sum(wallet_payments.mapped('amount')), 50.0, places=2)

    # ------------------------------------------------------------------
    # 7.6 Idempotency
    # ------------------------------------------------------------------
    def test_04_idempotency(self):
        date_from, date_to, order_date = self._unique_date_range()
        session = self._open_session(self.pos_config_a)
        order_a = self._create_paid_order(session, 100.0, date_order=order_date)
        order_b = self._create_paid_order(session, 100.0, date_order=order_date)

        self._run_reallocation(50.0, date_from, date_to)
        order_a.invalidate_cache()
        order_b.invalidate_cache()

        self.assertFalse(order_a._is_eligible_for_reallocation())
        self.assertFalse(order_b._is_eligible_for_reallocation())

        wizard = self._create_wizard(50.0, date_from, date_to)
        self.assertFalse(wizard._get_eligible_orders())

    # ------------------------------------------------------------------
    # 7.7 Undo
    # ------------------------------------------------------------------
    def test_05_undo_restores_payments(self):
        date_from, date_to, order_date = self._unique_date_range()
        session = self._open_session(self.pos_config_a)
        order = self._create_paid_order(session, 100.0, date_order=order_date)

        _wizard, _result = self._run_reallocation(25.0, date_from, date_to)
        log = self.Log.search([
            ('date_from', '=', date_from),
            ('date_to', '=', date_to),
        ], order='id desc', limit=1)

        cash_payment = order.payment_ids.filtered(
            lambda payment: payment.payment_method_id == self.cash_payment_method
            and payment.amount > 0
        )
        original_cash = 100.0
        self.assertAlmostEqual(cash_payment.amount, original_cash - 25.0, places=2)

        log.action_undo()
        order.invalidate_cache()

        cash_payment = order.payment_ids.filtered(
            lambda payment: payment.payment_method_id == self.cash_payment_method
            and payment.amount > 0
        )
        self.assertAlmostEqual(cash_payment.amount, original_cash, places=2)
        self.assertFalse(order.has_wallet_payment)
        self.assertEqual(log.state, 'reverted')

    def test_06_undo_blocked_when_session_closed(self):
        date_from, date_to, order_date = self._unique_date_range()
        session = self._open_session(self.pos_config_a)
        self._create_paid_order(session, 100.0, date_order=order_date)

        _wizard, _result = self._run_reallocation(25.0, date_from, date_to)
        log = self.Log.search([
            ('date_from', '=', date_from),
            ('date_to', '=', date_to),
        ], order='id desc', limit=1)

        self._force_close_session(session)

        with self.assertRaises(UserError):
            log.action_undo()

    # ------------------------------------------------------------------
    # 7.8 Access rights
    # ------------------------------------------------------------------
    def test_07_access_rights(self):
        date_from, date_to, _order_date = self._unique_date_range()
        with self.assertRaises(AccessError):
            self.Wizard.with_user(self.basic_user).create({
                'company_id': self.env.company.id,
                'date_from': date_from,
                'date_to': date_to,
                'amount_to_reallocate': 10.0,
            })

        with self.assertRaises(AccessError):
            self.Log.with_user(self.basic_user).search([])

    # ------------------------------------------------------------------
    # 7.9 Audit log
    # ------------------------------------------------------------------
    def test_08_audit_log_on_confirm_and_undo(self):
        date_from, date_to, order_date = self._unique_date_range()
        session = self._open_session(self.pos_config_a)
        self._create_paid_order(session, 100.0, date_order=order_date)
        self._create_paid_order(session, 100.0, date_order=order_date)

        _wizard, _result = self._run_reallocation(40.0, date_from, date_to)
        log = self.Log.search([
            ('user_id', '=', self.env.user.id),
            ('date_from', '=', date_from),
            ('date_to', '=', date_to),
        ], order='id desc', limit=1)

        self.assertTrue(log)
        self.assertEqual(log.state, 'done')
        self.assertEqual(log.order_count, 2)
        self.assertAlmostEqual(log.total_amount, 40.0, places=2)
        self.assertEqual(len(log.line_ids), 2)

        applied_lines = log.line_ids.filtered(lambda line: not line.skipped)
        self.assertEqual(len(applied_lines), 2)
        self.assertTrue(all(line.wallet_payment_id for line in applied_lines))

        log.action_undo()
        self.assertEqual(log.state, 'reverted')

    # ------------------------------------------------------------------
    # 7.11 Public API
    # ------------------------------------------------------------------
    def test_09_public_api_search_wallet_orders(self):
        date_from, date_to, order_date = self._unique_date_range()
        session = self._open_session(self.pos_config_a)
        order = self._create_paid_order(session, 100.0, date_order=order_date)

        self.assertFalse(
            self.PosOrder.search_wallet_reallocated_orders(
                self.env.company,
                [('id', '=', order.id)],
            )
        )

        _wizard, _result = self._run_reallocation(20.0, date_from, date_to)
        order.invalidate_cache()

        reallocated = self.PosOrder.search_wallet_reallocated_orders(
            self.env.company,
            [('id', '=', order.id)],
        )
        self.assertEqual(reallocated, order)
        self.assertTrue(order.has_wallet_payment)

        log = self.Log.search([
            ('date_from', '=', date_from),
            ('date_to', '=', date_to),
        ], order='id desc', limit=1)
        log.action_undo()
        order.invalidate_cache()

        self.assertFalse(
            self.PosOrder.search_wallet_reallocated_orders(
                self.env.company,
                [('id', '=', order.id)],
            )
        )
        self.assertFalse(order.has_wallet_payment)

    def test_10_wallet_payment_method_name(self):
        self.assertEqual(self.wallet_method.name, WALLET_PAYMENT_METHOD_NAME)
        self.assertFalse(self.wallet_method.is_cash_count)

    def test_13_legacy_wallet_name_migrated_to_lealtad(self):
        fresh_company = self.env['res.company'].create({
            'name': 'Legacy Wallet Test %s' % uuid.uuid4().hex[:6],
        })
        receivable_type = self.env.ref('account.data_account_type_receivable')
        receivable_account = self.env['account.account'].create({
            'name': 'Legacy Wallet Receivable',
            'code': '199901',
            'user_type_id': receivable_type.id,
            'reconcile': True,
            'company_id': fresh_company.id,
        })
        legacy = self.env['pos.payment.method'].sudo().create({
            'name': 'Monedero Electrónico',
            'is_cash_count': False,
            'receivable_account_id': receivable_account.id,
            'company_id': fresh_company.id,
        })
        resolved = self.PosOrder._get_wallet_payment_method(fresh_company)
        self.assertEqual(resolved, legacy)
        self.assertEqual(resolved.name, WALLET_PAYMENT_METHOD_NAME)

    def test_11_wizard_history_tab_shows_logs(self):
        date_from, date_to, order_date = self._unique_date_range()
        session = self._open_session(self.pos_config_a)
        self._create_paid_order(session, 100.0, date_order=order_date)

        wizard, _result = self._run_reallocation(20.0, date_from, date_to)
        log = self.Log.search([
            ('date_from', '=', date_from),
            ('date_to', '=', date_to),
        ], order='id desc', limit=1)

        self.assertIn(log, wizard.history_log_ids)

    def test_12_default_dates_and_preview_without_amount(self):
        self.env.user.write({'tz': 'America/Tijuana'})
        date_from, date_to, order_date = self._unique_date_range()
        session = self._open_session(self.pos_config_a)
        self._create_paid_order(session, 100.0, date_order=order_date)

        wizard = self.Wizard.create({'company_id': self.env.company.id})
        date_from_local = fields.Datetime.context_timestamp(
            self.env.user,
            wizard.date_from,
        )
        date_to_local = fields.Datetime.context_timestamp(
            self.env.user,
            wizard.date_to,
        )

        self.assertEqual(date_from_local.hour, 7)
        self.assertEqual(date_from_local.minute, 0)
        self.assertLessEqual(wizard.date_from, wizard.date_to)
        self.assertGreaterEqual(date_to_local, date_from_local)

        wizard.write({
            'date_from': date_from,
            'date_to': date_to,
        })
        wizard.action_preview()

        self.assertEqual(wizard.state, 'draft')
        self.assertTrue(wizard.has_run_search)
        self.assertEqual(wizard.matched_order_count, 1)
        self.assertAlmostEqual(wizard.total_net_cash, 100.0, places=2)
        self.assertFalse(wizard.preview_line_ids)

        wizard.write({'amount_to_reallocate': 20.0})
        wizard.action_preview()
        self.assertEqual(wizard.state, 'preview')
        self.assertTrue(wizard.preview_line_ids)
