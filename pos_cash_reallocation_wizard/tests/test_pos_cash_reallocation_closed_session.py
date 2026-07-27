# -*- coding: utf-8 -*-
import uuid
from datetime import timedelta
from unittest.mock import patch

from odoo import _, fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from odoo.addons.pos_cash_reallocation_wizard.models.pos_order import (
    CASH_PAYMENT_METHOD_NAME,
    WALLET_PAYMENT_METHOD_NAME,
)


class TestPosCashReallocationClosedSession(TransactionCase):
    """Unit tests for closed-session (posted) POS cash reallocation — Phase 2."""

    def setUp(self):
        super(TestPosCashReallocationClosedSession, self).setUp()
        self.PosSession = self.env['pos.session']
        self.PosOrder = self.env['pos.order']
        self.PosPaymentMethod = self.env['pos.payment.method']
        self.Wizard = self.env['pos.cash.reallocation.wizard']
        self.Log = self.env['pos.cash.reallocation.log']
        self.product = self.env['product.product'].create({
            'name': 'Closed Session Realloc Product',
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

        bank_name = 'Bank Closed Realloc %s' % uuid.uuid4().hex[:8]
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
        self.pos_config = self.env['pos.config'].create({
            'name': 'Closed Realloc POS %s' % uuid.uuid4().hex[:6],
            'journal_id': sale_journal.id,
        })
        self.pos_config.payment_method_ids = [
            (6, 0, [self.cash_payment_method.id, self.bank_payment_method.id])
        ]

        self.assertNotIn(
            self.wallet_method,
            self.pos_config.payment_method_ids,
            'Wallet method must stay hidden from POS register config.',
        )

    def _unique_date_range(self):
        """Narrow window far in the future to avoid production order collisions."""
        base = fields.Datetime.now() + timedelta(days=7400)
        offset = sum(ord(char) for char in self._testMethodName)
        date_from = base + timedelta(hours=offset)
        date_to = date_from + timedelta(hours=1)
        order_date = date_from + timedelta(minutes=15)
        return date_from, date_to, order_date

    def _open_session(self, pos_config=None):
        pos_config = pos_config or self.pos_config
        pos_config.open_session_cb()
        return pos_config.current_session_id

    def _create_posted_session_move(self, session, move_date=None):
        """Create a minimal posted journal entry linked as session.move_id."""
        move_date = move_date or fields.Date.today()
        receivable = self.env.company.account_default_pos_receivable_account_id
        journal = self.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': move_date,
            'ref': 'Test POS close %s' % session.name,
            'line_ids': [
                (0, 0, {
                    'name': 'Test debit',
                    'account_id': receivable.id,
                    'debit': 1.0,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': 'Test credit',
                    'account_id': receivable.id,
                    'debit': 0.0,
                    'credit': 1.0,
                }),
            ],
        })
        move.action_post()
        return move

    def _close_session_with_posted_move(self, session, orders=None, move_date=None):
        """Close session with posted move_id; set orders to done."""
        orders = orders or session.order_ids
        move = self._create_posted_session_move(session, move_date=move_date)
        session.sudo().write({
            'state': 'closed',
            'move_id': move.id,
            'stop_at': fields.Datetime.now(),
        })
        orders.sudo().write({'state': 'done'})
        return move

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

    def _create_wizard(self, amount, date_from, date_to, include_closed_sessions=False):
        return self.Wizard.create({
            'company_id': self.env.company.id,
            'date_from': date_from,
            'date_to': date_to,
            'amount_to_reallocate': amount,
            'include_closed_sessions': include_closed_sessions,
        })

    def _run_closed_reallocation(self, amount, date_from, date_to):
        wizard = self._create_wizard(
            amount, date_from, date_to, include_closed_sessions=True,
        )
        wizard.action_preview()
        return wizard, wizard.action_confirm()

    def _setup_closed_session_orders(self, date_order, amounts):
        """Open session, create orders, close session with posted move."""
        session = self._open_session()
        orders = self.PosOrder
        for amount in amounts:
            order = self._create_paid_order(
                session, amount, date_order=date_order,
            )
            orders |= order
        self._close_session_with_posted_move(session, orders)
        return session, orders

    # ------------------------------------------------------------------
    # 8.3 Eligibility: done + closed session
    # ------------------------------------------------------------------
    def test_01_eligibility_closed_vs_open_mode(self):
        date_from, date_to, order_date = self._unique_date_range()
        session, orders = self._setup_closed_session_orders(order_date, [100.0])
        order = orders[0]

        self.assertEqual(order.state, 'done')
        self.assertEqual(session.state, 'closed')
        self.assertTrue(session.move_id)
        self.assertEqual(session.move_id.state, 'posted')
        self.assertTrue(order._is_eligible_for_closed_session_reallocation())
        self.assertFalse(order._is_eligible_for_reallocation())
        self.assertEqual(
            self.PosOrder.get_reallocation_eligibility_mode(order),
            'closed',
        )

        closed_wizard = self._create_wizard(
            10.0, date_from, date_to, include_closed_sessions=True,
        )
        closed_wizard.action_preview()
        self.assertIn(order, closed_wizard.preview_line_ids.mapped('order_id'))
        self.assertEqual(closed_wizard.matched_order_count, 1)

        open_wizard = self._create_wizard(
            10.0, date_from, date_to, include_closed_sessions=False,
        )
        self.assertFalse(open_wizard._get_eligible_orders())
        self.assertNotIn(order, open_wizard._get_orders_in_date_range())

    # ------------------------------------------------------------------
    # 8.4 Hard blocks
    # ------------------------------------------------------------------
    def test_02_hard_blocks(self):
        date_from, date_to, order_date = self._unique_date_range()
        session = self._open_session()

        invoiced = self._create_paid_order(session, 100.0, date_order=order_date)
        mixed = self._create_paid_order(
            session, 60.0,
            second_payment_method=self.bank_payment_method,
            second_amount=40.0,
            date_order=order_date,
        )
        with_customer = self._create_paid_order(
            session, 50.0,
            partner=self.env['res.partner'].create({'name': 'Customer'}),
            date_order=order_date,
        )
        invoiced_move = self._create_posted_session_move(session)
        invoiced.sudo().write({
            'state': 'invoiced',
            'account_move': invoiced_move.id,
        })
        self._close_session_with_posted_move(
            session, invoiced | mixed | with_customer,
        )

        wizard = self._create_wizard(
            10.0, date_from, date_to, include_closed_sessions=True,
        )

        self.assertFalse(invoiced._is_eligible_for_closed_session_reallocation())
        self.assertEqual(
            wizard._get_reallocation_skip_reason(invoiced),
            _('Order is invoiced.'),
        )

        self.assertFalse(mixed._is_eligible_for_closed_session_reallocation())
        self.assertEqual(
            wizard._get_reallocation_skip_reason(mixed),
            _('Order has mixed payment methods.'),
        )

        self.assertFalse(with_customer._is_eligible_for_closed_session_reallocation())
        self.assertEqual(
            wizard._get_reallocation_skip_reason(with_customer),
            _('Order has a customer assigned.'),
        )

    def test_02d_hard_block_multiple_positive_cash_lines(self):
        date_from, date_to, order_date = self._unique_date_range()
        session = self._open_session()
        multi_cash = self._create_paid_order(
            session, 800.0,
            second_payment_method=self.cash_payment_method,
            second_amount=100.0,
            date_order=order_date,
        )
        self.env['pos.payment'].create({
            'pos_order_id': multi_cash.id,
            'amount': -45.68,
            'payment_date': fields.Datetime.now(),
            'payment_method_id': self.cash_payment_method.id,
        })
        multi_cash.amount_paid = sum(multi_cash.payment_ids.mapped('amount'))
        self._close_session_with_posted_move(session, multi_cash)

        wizard = self._create_wizard(
            10.0, date_from, date_to, include_closed_sessions=True,
        )

        self.assertFalse(multi_cash._is_eligible_for_closed_session_reallocation())
        self.assertEqual(
            wizard._get_reallocation_skip_reason(multi_cash),
            _('Order has multiple cash payment lines.'),
        )
        self.assertFalse(wizard._get_eligible_orders())

    def test_02b_hard_block_no_session_move(self):
        date_from, date_to, order_date = self._unique_date_range()
        session = self._open_session()
        order = self._create_paid_order(session, 80.0, date_order=order_date)
        session.sudo().write({
            'state': 'closed',
            'move_id': False,
            'stop_at': fields.Datetime.now(),
        })
        order.sudo().write({'state': 'done'})

        self.assertFalse(order._is_eligible_for_closed_session_reallocation())

        wizard = self._create_wizard(
            10.0, date_from, date_to, include_closed_sessions=True,
        )
        self.assertEqual(
            wizard._get_reallocation_skip_reason(order),
            _('POS session has no journal entry.'),
        )

    def test_02c_hard_block_already_reallocated(self):
        date_from, date_to, order_date = self._unique_date_range()
        _session, orders = self._setup_closed_session_orders(order_date, [100.0])
        order = orders[0]

        self._run_closed_reallocation(20.0, date_from, date_to)
        order.invalidate_cache()
        self.assertFalse(order._is_eligible_for_closed_session_reallocation())

        wizard = self._create_wizard(
            10.0, date_from, date_to, include_closed_sessions=True,
        )
        self.assertEqual(
            wizard._get_reallocation_skip_reason(order),
            _('Order already has a Lealtad payment.'),
        )

    # ------------------------------------------------------------------
    # 8.5 Proportional split on closed-session batch
    # ------------------------------------------------------------------
    def test_03_proportional_split_amount_total_unchanged(self):
        date_from, date_to, order_date = self._unique_date_range()
        session, orders = self._setup_closed_session_orders(
            order_date, [100.0, 200.0, 300.0],
        )
        order_a, order_b, order_c = orders[0], orders[1], orders[2]

        amount = 100.0
        wizard = self._create_wizard(
            amount, date_from, date_to, include_closed_sessions=True,
        )
        shares = wizard._compute_proportional_shares(orders, amount)
        self.assertAlmostEqual(sum(shares.values()), amount, places=2)
        self.assertAlmostEqual(
            shares[order_c.id],
            amount - shares[order_a.id] - shares[order_b.id],
            places=2,
        )

        totals_before = {order.id: order.amount_total for order in orders}
        wizard.action_preview()
        wizard.action_confirm()

        for order in orders:
            order.invalidate_cache()
            self.assertEqual(order.amount_total, totals_before[order.id])

    # ------------------------------------------------------------------
    # 8.6 Adjustment moves with correct accounts and amounts
    # ------------------------------------------------------------------
    def test_04_adjustment_moves_per_session(self):
        date_from, date_to, order_date = self._unique_date_range()
        session, orders = self._setup_closed_session_orders(
            order_date, [100.0, 100.0],
        )
        amount = 40.0
        self._run_closed_reallocation(amount, date_from, date_to)

        log = self.Log.search([
            ('date_from', '=', date_from),
            ('date_to', '=', date_to),
        ], order='id desc', limit=1)

        cash_account = session._get_cash_payment_method_receivable_account()
        wallet_account = session._get_wallet_receivable_account()

        self.assertEqual(len(log.adjustment_move_ids), 1)
        move = log.adjustment_move_ids
        self.assertEqual(move.state, 'posted')

        debit_line = move.line_ids.filtered(lambda line: line.debit > 0)
        credit_line = move.line_ids.filtered(lambda line: line.credit > 0)
        self.assertEqual(len(debit_line), 1)
        self.assertEqual(len(credit_line), 1)
        self.assertEqual(debit_line.account_id, wallet_account)
        self.assertEqual(credit_line.account_id, cash_account)
        self.assertAlmostEqual(debit_line.debit, amount, places=2)
        self.assertAlmostEqual(credit_line.credit, amount, places=2)

    # ------------------------------------------------------------------
    # 8.7 Payment lines after confirm
    # ------------------------------------------------------------------
    def test_05_payment_lines_after_confirm(self):
        date_from, date_to, order_date = self._unique_date_range()
        _session, orders = self._setup_closed_session_orders(order_date, [100.0])
        order = orders[0]

        self._run_closed_reallocation(25.0, date_from, date_to)
        order.invalidate_cache()

        self.assertTrue(order.has_wallet_payment)
        cash_payment = order.payment_ids.filtered(
            lambda payment: payment.payment_method_id == self.cash_payment_method
            and payment.amount > 0
        )
        wallet_payments = order.payment_ids.filtered(
            lambda payment: payment.payment_method_id == self.wallet_method
        )
        self.assertAlmostEqual(cash_payment.amount, 75.0, places=2)
        self.assertAlmostEqual(sum(wallet_payments.mapped('amount')), 25.0, places=2)

    # ------------------------------------------------------------------
    # 8.8 Log fields for closed-session run
    # ------------------------------------------------------------------
    def test_06_log_fields_closed_session(self):
        date_from, date_to, order_date = self._unique_date_range()
        session, _orders = self._setup_closed_session_orders(order_date, [100.0, 100.0])

        self._run_closed_reallocation(30.0, date_from, date_to)
        log = self.Log.search([
            ('date_from', '=', date_from),
            ('date_to', '=', date_to),
        ], order='id desc', limit=1)

        self.assertEqual(log.reallocation_mode, 'closed_session')
        self.assertIn(session, log.session_ids)
        self.assertTrue(log.adjustment_move_ids)
        self.assertEqual(log.adjustment_move_count, 1)
        self.assertEqual(log.state, 'done')
        self.assertEqual(log.order_count, 2)

    # ------------------------------------------------------------------
    # 8.9 Closed-session undo
    # ------------------------------------------------------------------
    def test_07_closed_session_undo(self):
        date_from, date_to, order_date = self._unique_date_range()
        _session, orders = self._setup_closed_session_orders(order_date, [100.0])
        order = orders[0]

        self._run_closed_reallocation(25.0, date_from, date_to)
        log = self.Log.search([
            ('date_from', '=', date_from),
            ('date_to', '=', date_to),
        ], order='id desc', limit=1)

        adjustment_move = log.adjustment_move_ids
        self.assertEqual(adjustment_move.state, 'posted')

        log.action_undo()
        order.invalidate_cache()

        self.assertEqual(log.state, 'reverted')
        self.assertFalse(order.has_wallet_payment)
        cash_payment = order.payment_ids.filtered(
            lambda payment: payment.payment_method_id == self.cash_payment_method
            and payment.amount > 0
        )
        self.assertAlmostEqual(cash_payment.amount, 100.0, places=2)
        self.assertTrue(
            adjustment_move.reversal_move_id.filtered(
                lambda reversal: reversal.state == 'posted'
            )
        )

    # ------------------------------------------------------------------
    # 8.10 Undo blocked when fiscal period locked
    # ------------------------------------------------------------------
    def test_08_undo_blocked_fiscal_period_locked(self):
        date_from, date_to, order_date = self._unique_date_range()
        _session, _orders = self._setup_closed_session_orders(order_date, [100.0])

        self._run_closed_reallocation(20.0, date_from, date_to)
        log = self.Log.search([
            ('date_from', '=', date_from),
            ('date_to', '=', date_to),
        ], order='id desc', limit=1)

        lock_patch = patch(
            'odoo.addons.account.models.company.ResCompany._get_user_fiscal_lock_date',
            return_value=fields.Date.today(),
        )
        with lock_patch:
            with self.assertRaises(UserError):
                log.action_undo()

    # ------------------------------------------------------------------
    # 8.11 Phase 1 regression: open-session unchanged
    # ------------------------------------------------------------------
    def test_09_open_session_regression_unchanged(self):
        date_from, date_to, order_date = self._unique_date_range()
        session = self._open_session()
        order = self._create_paid_order(session, 100.0, date_order=order_date)

        self.assertEqual(order.state, 'paid')
        self.assertTrue(order._is_eligible_for_reallocation())
        self.assertEqual(
            self.PosOrder.get_reallocation_eligibility_mode(order),
            'open',
        )

        wizard = self._create_wizard(
            25.0, date_from, date_to, include_closed_sessions=False,
        )
        wizard.action_preview()
        self.assertIn(order, wizard.preview_line_ids.mapped('order_id'))
        wizard.action_confirm()

        order.invalidate_cache()
        log = self.Log.search([
            ('date_from', '=', date_from),
            ('date_to', '=', date_to),
        ], order='id desc', limit=1)

        self.assertEqual(log.reallocation_mode, 'open_session')
        self.assertFalse(log.session_ids)
        self.assertFalse(log.adjustment_move_ids)
        self.assertTrue(order.has_wallet_payment)

    def test_10_wallet_payment_method_name(self):
        self.assertEqual(self.wallet_method.name, WALLET_PAYMENT_METHOD_NAME)

    def test_11_session_filter_limits_preview_totals(self):
        date_from, date_to, order_date = self._unique_date_range()
        session_a, orders_a = self._setup_closed_session_orders(order_date, [100.0, 200.0])
        session_b, orders_b = self._setup_closed_session_orders(order_date, [300.0])

        wizard = self._create_wizard(
            0.0, date_from, date_to, include_closed_sessions=True,
        )
        wizard.action_preview()

        self.assertIn(session_a, wizard.available_session_ids)
        self.assertIn(session_b, wizard.available_session_ids)
        self.assertAlmostEqual(wizard.total_net_cash, 600.0, places=2)
        self.assertEqual(wizard.matched_order_count, 3)

        wizard.write({'session_ids': [(6, 0, [session_a.id])]})
        wizard.action_preview()
        self.assertAlmostEqual(wizard.total_net_cash, 300.0, places=2)
        self.assertEqual(wizard.matched_order_count, 2)

        wizard.write({'amount_to_reallocate': 30.0})
        wizard.action_preview()
        preview_sessions = wizard.preview_line_ids.mapped('session_id')
        self.assertTrue(all(session == session_a for session in preview_sessions))
        wizard.action_confirm()

        log = self.Log.search([
            ('date_from', '=', date_from),
            ('date_to', '=', date_to),
        ], order='id desc', limit=1)
        self.assertEqual(log.session_ids, session_a)
        self.assertAlmostEqual(log.total_amount, 30.0, places=2)

    def test_12_include_orders_with_customers_closed_session(self):
        date_from, date_to, order_date = self._unique_date_range()
        session = self._open_session()
        with_customer = self._create_paid_order(
            session, 80.0,
            partner=self.env['res.partner'].create({'name': 'Customer'}),
            date_order=order_date,
        )
        self._close_session_with_posted_move(session, with_customer)
        with_customer.sudo().write({'state': 'done'})

        self.assertFalse(
            with_customer._is_eligible_for_closed_session_reallocation()
        )
        self.assertTrue(
            with_customer._is_eligible_for_closed_session_reallocation(
                include_customer=True,
            )
        )

        wizard = self._create_wizard(
            20.0, date_from, date_to, include_closed_sessions=True,
        )
        self.assertNotIn(
            with_customer,
            wizard._get_eligible_orders_without_session_filter(),
        )

        wizard.write({'include_orders_with_customers': True})
        wizard.action_preview()
        self.assertIn(with_customer, wizard.preview_line_ids.mapped('order_id'))

    def test_13_invoiced_blocked_even_with_customers_included(self):
        date_from, date_to, order_date = self._unique_date_range()
        session = self._open_session()
        invoiced = self._create_paid_order(
            session, 100.0,
            partner=self.env['res.partner'].create({'name': 'Invoiced Customer'}),
            date_order=order_date,
        )
        invoiced_move = self._create_posted_session_move(session)
        invoiced.sudo().write({
            'state': 'invoiced',
            'account_move': invoiced_move.id,
        })
        self._close_session_with_posted_move(session, invoiced)

        wizard = self._create_wizard(
            10.0, date_from, date_to, include_closed_sessions=True,
        )
        wizard.write({'include_orders_with_customers': True})
        self.assertFalse(
            invoiced._is_eligible_for_closed_session_reallocation(
                include_customer=True,
            )
        )
        self.assertNotIn(
            invoiced,
            wizard._get_eligible_orders_without_session_filter(),
        )
        self.assertEqual(
            wizard._get_reallocation_skip_reason(invoiced),
            _('Order is invoiced.'),
        )
