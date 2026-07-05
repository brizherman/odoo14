# -*- coding: utf-8 -*-
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
    date_from = fields.Datetime(string='Date From', required=True)
    date_to = fields.Datetime(string='Date To', required=True)
    is_cash_count = fields.Boolean(
        string='Is Cash Count',
        default=True,
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

    def _check_date_range(self):
        self.ensure_one()
        if not self.date_from or not self.date_to:
            raise UserError(_('Please set both Date From and Date To.'))
        if self.date_from > self.date_to:
            raise UserError(_('Date From must be on or before Date To.'))

    def _get_orders_in_date_range(self):
        self.ensure_one()
        self._check_date_range()
        return self.env['pos.order'].search([
            ('company_id', '=', self.company_id.id),
            ('date_order', '>=', self.date_from),
            ('date_order', '<=', self.date_to),
            ('state', '=', 'paid'),
            ('partner_id', '=', False),
        ], order='date_order asc, id asc')

    def _get_eligible_orders(self):
        self.ensure_one()
        candidates = self._get_orders_in_date_range()
        return candidates.filtered(lambda order: order._is_eligible_for_reallocation())

    def _get_reallocation_skip_reason(self, order):
        self.ensure_one()
        if order.state != 'paid':
            return _('Order is not paid.')
        if order.partner_id:
            return _('Order has a customer assigned.')
        if order.session_id.state == 'closed':
            return _('POS session is closed.')
        if order._has_wallet_payment(self.company_id):
            return _('Order already has a Monedero payment.')
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

    def action_compute_totals(self):
        self.ensure_one()
        self._check_date_range()
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

        if self.amount_to_reallocate <= 0:
            raise UserError(_('Please enter an amount to reallocate greater than zero.'))

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

        eligible_orders = self._get_eligible_orders()
        shares = self._compute_proportional_shares(
            eligible_orders,
            self.amount_to_reallocate,
        )

        preview_commands = [(5, 0, 0)]
        for order in eligible_orders:
            wallet_amount = shares.get(order.id, 0.0)
            original_cash = order._get_net_cash_amount()
            preview_commands.append((0, 0, {
                'order_id': order.id,
                'original_cash': original_cash,
                'new_cash': original_cash - wallet_amount,
                'wallet_amount': wallet_amount,
            }))

        candidates = self._get_orders_in_date_range()
        skipped_orders = candidates.filtered(
            lambda order: not order._is_eligible_for_reallocation()
        )

        self.write({
            'preview_line_ids': preview_commands,
            'skipped_line_ids': self._build_skipped_lines(skipped_orders),
            'state': 'preview',
        })
        return True

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

    def action_confirm(self):
        self.ensure_one()
        if self.state != 'preview':
            raise UserError(_('Please preview the reallocation before confirming.'))
        if not self.preview_line_ids:
            raise UserError(_('There are no preview lines to confirm.'))

        PosOrder = self.env['pos.order']
        wallet_method = PosOrder._get_wallet_payment_method(self.company_id)
        if not wallet_method:
            wallet_method = PosOrder._setup_wallet_infrastructure_for_company(
                self.company_id
            )
        if not wallet_method:
            raise UserError(_(
                'Monedero Electrónico payment method is not configured for this company.'
            ))

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
            if not order._is_eligible_for_reallocation():
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
