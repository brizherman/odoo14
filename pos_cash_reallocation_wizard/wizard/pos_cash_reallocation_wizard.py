# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round

from ..models.pos_order import CASH_PAYMENT_METHOD_NAME


class PosCashReallocationWizard(models.TransientModel):
    _name = 'pos.cash.reallocation.wizard'
    _description = 'POS Cash Reallocation Wizard'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    date_from = fields.Datetime(
        string='Date From',
        required=True,
        default=lambda self: self._default_date_from(),
    )
    date_to = fields.Datetime(
        string='Date To',
        required=True,
        default=lambda self: self._default_date_to(),
    )
    is_cash_count = fields.Boolean(
        string='Is Cash Count',
        default=True,
        readonly=True,
    )
    include_closed_sessions = fields.Boolean(
        string='Include Closed Sessions',
        default=False,
        help=(
            'Reallocate cash from posted (done) orders on closed POS sessions. '
            'Posts compensating journal entries. Does not modify bank statements.'
        ),
    )
    include_orders_with_customers = fields.Boolean(
        string='Include Orders With Customers',
        default=False,
        help=(
            'Include paid or posted orders that have a customer assigned. '
            'Invoiced orders remain excluded.'
        ),
    )
    has_locked_fiscal_period = fields.Boolean(
        string='Locked Fiscal Period Detected',
        readonly=True,
    )
    locked_session_warning = fields.Text(
        string='Fiscal Period Warning',
        readonly=True,
    )
    amount_to_reallocate = fields.Float(
        string='Amount to Reallocate',
        digits='Product Price',
    )
    matched_order_count = fields.Integer(
        string='Matched Orders',
        readonly=True,
    )
    total_net_cash = fields.Float(
        string='Total Net Cash',
        digits='Product Price',
        readonly=True,
    )
    available_session_ids = fields.Many2many(
        'pos.session',
        compute='_compute_available_session_ids',
        string='Sessions in Date Range',
    )
    session_ids = fields.Many2many(
        'pos.session',
        'pos_cash_realloc_wizard_session_rel',
        'wizard_id',
        'session_id',
        string='POS Sessions to Include',
        help=(
            'Optional. Leave empty to include all eligible sessions in the date '
            'range. Click Preview again after changing this selection.'
        ),
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('preview', 'Preview'),
            ('done', 'Done'),
        ],
        string='Status',
        default='draft',
        required=True,
    )
    has_run_search = fields.Boolean(
        string='Search Completed',
        default=False,
        readonly=True,
    )
    preview_line_ids = fields.One2many(
        'pos.cash.reallocation.wizard.preview.line',
        'wizard_id',
        string='Preview Lines',
        readonly=True,
    )
    skipped_line_ids = fields.One2many(
        'pos.cash.reallocation.wizard.skip.line',
        'wizard_id',
        string='Skipped Orders',
        readonly=True,
    )
    history_log_ids = fields.Many2many(
        'pos.cash.reallocation.log',
        string='Reallocation History',
        compute='_compute_history_log_ids',
        readonly=True,
    )

    HISTORY_LOG_LIMIT = 100

    @api.model
    def _default_date_from(self):
        tz_name = self.env.user.tz or self._context.get('tz') or 'UTC'
        tz = pytz.timezone(tz_name)
        now_local = datetime.now(tz)
        start_local = now_local.replace(hour=7, minute=0, second=0, microsecond=0)
        if now_local < start_local:
            start_local -= timedelta(days=1)
        return start_local.astimezone(pytz.UTC).replace(tzinfo=None)

    @api.model
    def _default_date_to(self):
        return fields.Datetime.now()

    @api.depends('company_id', 'state')
    def _compute_history_log_ids(self):
        Log = self.env['pos.cash.reallocation.log']
        for wizard in self:
            if wizard.company_id:
                wizard.history_log_ids = Log.search([
                    ('company_id', '=', wizard.company_id.id),
                ], order='create_date desc, id desc', limit=self.HISTORY_LOG_LIMIT)
            else:
                wizard.history_log_ids = Log.browse()

    @api.depends('date_from', 'date_to', 'company_id', 'include_closed_sessions',
                 'include_orders_with_customers')
    def _compute_available_session_ids(self):
        for wizard in self:
            sessions = self.env['pos.session']
            if wizard.date_from and wizard.date_to and wizard.date_from <= wizard.date_to:
                eligible = wizard._get_eligible_orders_without_session_filter()
                sessions = eligible.mapped('session_id')
            wizard.available_session_ids = sessions

    @api.onchange('date_from', 'date_to', 'include_closed_sessions',
                  'include_orders_with_customers', 'company_id')
    def _onchange_search_criteria(self):
        self.session_ids = [(5, 0, 0)]
        self._reset_preview_for_filter_change(clear_search=True)

    @api.onchange('session_ids')
    def _onchange_session_ids(self):
        if self.has_run_search:
            self._reset_preview_for_filter_change(clear_search=False)

    def _reset_preview_for_filter_change(self, clear_search=False):
        self.state = 'draft'
        self.preview_line_ids = [(5, 0, 0)]
        if clear_search:
            self.has_run_search = False
            self.matched_order_count = 0
            self.total_net_cash = 0.0
            self.skipped_line_ids = [(5, 0, 0)]
            self.has_locked_fiscal_period = False
            self.locked_session_warning = False

    def _check_session_filter(self):
        self.ensure_one()
        if not self.session_ids:
            return
        invalid = self.session_ids - self.available_session_ids
        if invalid:
            raise UserError(_(
                'The following POS session(s) are not eligible in the selected '
                'date range: %s',
                ', '.join(invalid.mapped('name')),
            ))

    def _check_date_range(self):
        self.ensure_one()
        if not self.date_from or not self.date_to:
            raise UserError(_('Please set both Date From and Date To.'))
        if self.date_from > self.date_to:
            raise UserError(_('Date From must be on or before Date To.'))

    def _base_order_search_domain(self):
        self.ensure_one()
        order_state = 'done' if self.include_closed_sessions else 'paid'
        domain = [
            ('company_id', '=', self.company_id.id),
            ('date_order', '>=', self.date_from),
            ('date_order', '<=', self.date_to),
            ('state', '=', order_state),
        ]
        if not self.include_orders_with_customers:
            domain.append(('partner_id', '=', False))
        return domain

    def _get_orders_in_date_range(self):
        self.ensure_one()
        self._check_date_range()
        domain = self._base_order_search_domain()
        if self.session_ids:
            domain.append(('session_id', 'in', self.session_ids.ids))
        return self.env['pos.order'].search(domain, order='date_order asc, id asc')

    def _get_eligible_orders_without_session_filter(self):
        """Eligible orders in the date range, ignoring session_ids filter."""
        self.ensure_one()
        candidates = self.env['pos.order'].search(
            self._base_order_search_domain(),
            order='date_order asc, id asc',
        )
        return candidates.filtered(lambda order: self._order_is_eligible(order))

    def _order_is_eligible(self, order):
        self.ensure_one()
        include_customer = self.include_orders_with_customers
        if self.include_closed_sessions:
            return order._is_eligible_for_closed_session_reallocation(
                include_customer=include_customer,
            )
        return order._is_eligible_for_reallocation(
            include_customer=include_customer,
        )

    def _get_eligible_orders(self):
        self.ensure_one()
        candidates = self._get_orders_in_date_range()
        return candidates.filtered(lambda order: self._order_is_eligible(order))

    def _get_open_session_skip_reason(self, order):
        if order.state != 'paid':
            return _('Order is not paid.')
        if not self.include_orders_with_customers and order.partner_id:
            return _('Order has a customer assigned.')
        if order.session_id.state == 'closed':
            return _('POS session is closed.')
        if order._has_wallet_payment(self.company_id):
            return _('Order already has a Lealtad payment.')
        net_cash = order._get_net_cash_amount()
        if net_cash <= 0:
            return _('Net cash is zero or negative.')
        payment_methods = order.payment_ids.mapped('payment_method_id')
        if len(payment_methods) != 1:
            return _('Order has mixed payment methods.')
        payment_method = payment_methods[0]
        if payment_method.name != CASH_PAYMENT_METHOD_NAME:
            return _('Payment method is not Efectivo.')
        if not payment_method.is_cash_count:
            return _('Payment method is not counted as cash.')
        return False

    def _get_closed_session_skip_reason(self, order):
        if order.state == 'invoiced' or order.account_move:
            return _('Order is invoiced.')
        if order.state != 'done':
            return _('Order is not posted (done).')
        if order.partner_id and not self.include_orders_with_customers:
            return _('Order has a customer assigned.')
        if order.session_id.state != 'closed':
            return _('POS session is not closed.')
        session_move = order.session_id.move_id
        if not session_move:
            return _('POS session has no journal entry.')
        if session_move.state != 'posted':
            return _('POS session journal entry is not posted.')
        if order._is_fiscal_period_locked(order._get_closed_session_reallocation_date()):
            return _('Fiscal period is locked for this session.')
        if order._has_wallet_payment(self.company_id):
            return _('Order already has a Lealtad payment.')
        net_cash = order._get_net_cash_amount()
        if net_cash <= 0:
            return _('Net cash is zero or negative.')
        payment_methods = order.payment_ids.mapped('payment_method_id')
        if len(payment_methods) != 1:
            return _('Order has mixed payment methods.')
        payment_method = payment_methods[0]
        if payment_method.name != CASH_PAYMENT_METHOD_NAME:
            return _('Payment method is not Efectivo.')
        if not payment_method.is_cash_count:
            return _('Payment method is not counted as cash.')
        return False

    def _get_reallocation_skip_reason(self, order):
        self.ensure_one()
        if self.include_closed_sessions:
            return self._get_closed_session_skip_reason(order)
        return self._get_open_session_skip_reason(order)

    def _get_locked_sessions_for_preview(self, orders):
        self.ensure_one()
        if not self.include_closed_sessions:
            return self.env['pos.session']

        PosSession = self.env['pos.session']
        locked_sessions = PosSession
        seen_session_ids = set()
        for order in orders:
            session = order.session_id
            if session.id in seen_session_ids:
                continue
            seen_session_ids.add(session.id)
            if order._is_fiscal_period_locked(order._get_closed_session_reallocation_date()):
                locked_sessions |= session
        return locked_sessions

    @api.model
    def _compute_proportional_shares(self, orders, amount):
        """Return {order_id: share} with rounding remainder on the last order."""
        if not orders or amount <= 0:
            return {}

        total_net_cash = sum(orders.mapped(lambda order: order._get_net_cash_amount()))
        if total_net_cash <= 0:
            return {}

        precision = self.env['decimal.precision'].precision_get('Product Price')
        order_list = list(orders)
        shares = {}
        running_total = 0.0

        for index, order in enumerate(order_list):
            net_cash = order._get_net_cash_amount()
            if index == len(order_list) - 1:
                share = amount - running_total
            else:
                share = float_round(
                    (net_cash / total_net_cash) * amount,
                    precision_digits=precision,
                )
            shares[order.id] = share
            running_total += share

        return shares

    def _build_skipped_lines(self, orders):
        self.ensure_one()
        commands = [(5, 0, 0)]
        for order in orders:
            reason = self._get_reallocation_skip_reason(order)
            if reason:
                commands.append((0, 0, {
                    'order_id': order.id,
                    'skip_reason': reason,
                }))
        return commands

    def _group_preview_lines_by_session(self):
        """Return {session_id: total wallet_amount} for adjustment posting."""
        self.ensure_one()
        totals = {}
        for line in self.preview_line_ids:
            if line.wallet_amount <= 0:
                continue
            session_id = line.session_id.id or line.order_id.session_id.id
            totals[session_id] = totals.get(session_id, 0.0) + line.wallet_amount
        return totals

    def action_compute_totals(self):
        self.ensure_one()
        self._check_date_range()
        self._check_session_filter()
        eligible_orders = self._get_eligible_orders()
        if not eligible_orders:
            raise UserError(_(
                'No eligible orders found for the selected company and date range.'
            ))

        total_net_cash = sum(
            eligible_orders.mapped(lambda order: order._get_net_cash_amount())
        )
        self.write({
            'matched_order_count': len(eligible_orders),
            'total_net_cash': total_net_cash,
        })
        return True

    def action_preview(self):
        self.ensure_one()
        self.action_compute_totals()

        candidates = self._get_orders_in_date_range()
        skipped_orders = candidates.filtered(
            lambda order: not self._order_is_eligible(order)
        )
        eligible_orders = self._get_eligible_orders()
        locked_sessions = self._get_locked_sessions_for_preview(eligible_orders)
        locked_warning = False
        if locked_sessions:
            locked_warning = _(
                'Confirm is blocked: fiscal period is locked for session(s): %s',
                ', '.join(locked_sessions.mapped('name')),
            )

        base_write = {
            'has_run_search': True,
            'skipped_line_ids': self._build_skipped_lines(skipped_orders),
            'has_locked_fiscal_period': bool(locked_sessions),
            'locked_session_warning': locked_warning or False,
        }

        if self.amount_to_reallocate <= 0:
            self.write(dict(base_write, preview_line_ids=[(5, 0, 0)]))
            return self._preview_notification(locked_warning)

        precision = self.env['decimal.precision'].precision_get('Product Price')
        if float_compare(
            self.amount_to_reallocate,
            self.total_net_cash,
            precision_digits=precision,
        ) > 0:
            raise UserError(_(
                'Amount to reallocate (%(amount).2f) cannot exceed total net cash '
                '(%(total).2f) of the matched orders.',
                amount=self.amount_to_reallocate,
                total=self.total_net_cash,
            ))

        shares = self._compute_proportional_shares(
            eligible_orders,
            self.amount_to_reallocate,
        )

        preview_commands = [(5, 0, 0)]
        for order in eligible_orders:
            wallet_amount = shares.get(order.id, 0.0)
            original_cash = order._get_net_cash_amount()
            preview_vals = {
                'order_id': order.id,
                'original_cash': original_cash,
                'new_cash': original_cash - wallet_amount,
                'wallet_amount': wallet_amount,
            }
            if self.include_closed_sessions:
                preview_vals['session_id'] = order.session_id.id
            preview_commands.append((0, 0, preview_vals))

        self.write(dict(base_write, preview_line_ids=preview_commands, state='preview'))
        return self._preview_notification(locked_warning)

    def _preview_notification(self, locked_warning):
        if not locked_warning:
            return True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Warning'),
                'message': locked_warning,
                'type': 'warning',
                'sticky': True,
            },
        }

    def _get_primary_cash_payment(self, order):
        cash_payment = order.payment_ids.filtered(
            lambda payment: (
                payment.payment_method_id.is_cash_count
                and payment.amount > 0
                and not payment.is_change
            )
        )[:1]
        if not cash_payment:
            cash_payment = order.payment_ids.filtered(
                lambda payment: (
                    payment.payment_method_id.is_cash_count and payment.amount > 0
                )
            )[:1]
        return cash_payment

    def _get_wallet_method(self):
        self.ensure_one()
        PosOrder = self.env['pos.order']
        wallet_method = PosOrder._get_wallet_payment_method(self.company_id)
        if not wallet_method:
            wallet_method = PosOrder._setup_wallet_infrastructure_for_company(
                self.company_id
            )
        if not wallet_method:
            raise UserError(_(
                'Lealtad payment method is not configured for this company.'
            ))
        return wallet_method

    def action_confirm(self):
        self.ensure_one()
        if self.state != 'preview':
            raise UserError(_('Please preview the reallocation before confirming.'))
        self._check_session_filter()
        if self.amount_to_reallocate <= 0:
            raise UserError(_('Please enter an amount to reallocate greater than zero.'))
        if not self.preview_line_ids:
            raise UserError(_('There are no preview lines to confirm.'))
        if self.include_closed_sessions:
            if self.has_locked_fiscal_period:
                raise UserError(_(
                    'Cannot confirm: one or more matched POS sessions fall in a '
                    'locked fiscal period.'
                ))
            return self._action_confirm_closed_session()
        return self._action_confirm_open_session()

    def _action_confirm_open_session(self):
        self.ensure_one()
        PosOrder = self.env['pos.order']
        wallet_method = self._get_wallet_method()

        pending = []
        skipped_at_confirm = []

        for line in self.preview_line_ids:
            order = line.order_id
            if order.session_id.state == 'closed':
                skipped_at_confirm.append({
                    'order': order,
                    'wallet_amount': line.wallet_amount,
                    'original_cash': line.original_cash,
                    'skip_reason': _('POS session closed before confirm.'),
                })
                continue
            if not order._is_eligible_for_reallocation(
                    include_customer=self.include_orders_with_customers):
                skip_reason = self._get_reallocation_skip_reason(order)
                skipped_at_confirm.append({
                    'order': order,
                    'wallet_amount': line.wallet_amount,
                    'original_cash': line.original_cash,
                    'skip_reason': skip_reason or _('Order no longer eligible.'),
                })
                continue
            pending.append({
                'order': order,
                'wallet_amount': line.wallet_amount,
                'original_cash': line.original_cash,
            })

        pool_amount = sum(item['wallet_amount'] for item in skipped_at_confirm)
        if pool_amount > 0 and pending:
            remaining_orders = PosOrder.browse([item['order'].id for item in pending])
            redistributed = self._compute_proportional_shares(remaining_orders, pool_amount)
            for item in pending:
                extra = redistributed.get(item['order'].id, 0.0)
                item['wallet_amount'] += extra

        log_line_vals = []
        total_applied = 0.0
        applied_count = 0

        for item in pending:
            order = item['order']
            wallet_amount = item['wallet_amount']
            if wallet_amount <= 0:
                continue

            cash_payment = self._get_primary_cash_payment(order)
            original_cash = cash_payment.amount if cash_payment else item['original_cash']
            wallet_payment = order._apply_cash_reallocation(wallet_amount, wallet_method)

            log_line_vals.append({
                'order_id': order.id,
                'session_id': order.session_id.id,
                'original_cash_amount': original_cash,
                'new_cash_amount': original_cash - wallet_amount,
                'wallet_amount': wallet_amount,
                'cash_payment_id': cash_payment.id if cash_payment else False,
                'wallet_payment_id': wallet_payment.id,
                'skipped': False,
            })
            total_applied += wallet_amount
            applied_count += 1

        for item in skipped_at_confirm:
            log_line_vals.append({
                'order_id': item['order'].id,
                'session_id': item['order'].session_id.id,
                'original_cash_amount': item['original_cash'],
                'new_cash_amount': item['original_cash'],
                'wallet_amount': 0.0,
                'skipped': True,
                'skip_reason': item['skip_reason'],
            })

        self.env['pos.cash.reallocation.log'].create({
            'company_id': self.company_id.id,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'total_amount': total_applied,
            'order_count': applied_count,
            'reallocation_mode': 'open_session',
            'line_ids': [(0, 0, vals) for vals in log_line_vals],
        })

        if skipped_at_confirm:
            self.write({
                'skipped_line_ids': [(0, 0, {
                    'order_id': item['order'].id,
                    'skip_reason': item['skip_reason'],
                }) for item in skipped_at_confirm],
            })

        self.write({'state': 'done'})

        if skipped_at_confirm:
            skipped_names = ', '.join(
                item['order'].name for item in skipped_at_confirm
            )
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Warning'),
                    'message': _(
                        'Reallocation completed with warnings. The following order(s) '
                        'were skipped and their share was redistributed: %s',
                        skipped_names,
                    ),
                    'type': 'warning',
                    'sticky': True,
                },
            }
        return True

    def _action_confirm_closed_session(self):
        self.ensure_one()
        Log = self.env['pos.cash.reallocation.log']
        wallet_method = self._get_wallet_method()
        session_totals = self._group_preview_lines_by_session()
        if not session_totals:
            raise UserError(_('No reallocation amounts to apply.'))

        for line in self.preview_line_ids:
            if line.wallet_amount <= 0:
                continue
            order = line.order_id
            if not order._is_eligible_for_closed_session_reallocation(
                    include_customer=self.include_orders_with_customers):
                reason = self._get_closed_session_skip_reason(order)
                raise UserError(_(
                    'Order %(order)s is no longer eligible: %(reason)s',
                    order=order.name,
                    reason=reason or _('Unknown reason.'),
                ))
            order._check_closed_session_reallocation_allowed()

        log_name = self.env['ir.sequence'].next_by_code(
            'pos.cash.reallocation.log'
        ) or '/'

        with self.env.cr.savepoint():
            log_line_vals = []
            total_applied = 0.0
            applied_count = 0

            for line in self.preview_line_ids:
                wallet_amount = line.wallet_amount
                if wallet_amount <= 0:
                    continue

                order = line.order_id
                cash_payment = self._get_primary_cash_payment(order)
                original_cash = cash_payment.amount if cash_payment else line.original_cash
                wallet_payment = order._apply_cash_reallocation(
                    wallet_amount,
                    wallet_method,
                    closed_session=True,
                )
                log_line_vals.append({
                    'order_id': order.id,
                    'session_id': order.session_id.id,
                    'original_cash_amount': original_cash,
                    'new_cash_amount': original_cash - wallet_amount,
                    'wallet_amount': wallet_amount,
                    'cash_payment_id': cash_payment.id if cash_payment else False,
                    'wallet_payment_id': wallet_payment.id,
                    'skipped': False,
                })
                total_applied += wallet_amount
                applied_count += 1

            adjustment_moves = self.env['account.move']
            sessions = self.env['pos.session']
            PosSession = self.env['pos.session']
            for session_id, session_total in session_totals.items():
                session = PosSession.browse(session_id)
                move = session._create_reallocation_adjustment_move(
                    session_total,
                    log_name,
                )
                adjustment_moves |= move
                sessions |= session

            Log.create_closed_session_log({
                'name': log_name,
                'company_id': self.company_id.id,
                'date_from': self.date_from,
                'date_to': self.date_to,
                'total_amount': total_applied,
                'order_count': applied_count,
                'line_ids': [(0, 0, vals) for vals in log_line_vals],
            }, sessions.ids, adjustment_moves.ids)

        self.write({'state': 'done'})
        return self._notify_closed_session_success(sessions, adjustment_moves)

    def _notify_closed_session_success(self, sessions, adjustment_moves):
        self.ensure_one()
        session_names = ', '.join(sessions.mapped('name'))
        move_names = ', '.join(adjustment_moves.mapped('name'))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _(
                    'Closed-session reallocation completed. Sessions adjusted: '
                    '%(sessions)s. Journal entries: %(moves)s.',
                    sessions=session_names,
                    moves=move_names,
                ),
                'type': 'success',
                'sticky': False,
            },
        }
