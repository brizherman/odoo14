# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_date


class PosCashReallocationLog(models.Model):
    _name = 'pos.cash.reallocation.log'
    _description = 'POS Cash Reallocation Log'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default='/',
        index=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='User',
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        readonly=True,
        index=True,
    )
    date_from = fields.Datetime(string='Date From', required=True, readonly=True)
    date_to = fields.Datetime(string='Date To', required=True, readonly=True)
    total_amount = fields.Float(
        string='Total Reallocated',
        digits='Product Price',
        readonly=True,
    )
    order_count = fields.Integer(string='Order Count', readonly=True)
    reallocation_mode = fields.Selection(
        selection=[
            ('open_session', 'Open Session'),
            ('closed_session', 'Closed Session'),
        ],
        string='Reallocation Mode',
        default='open_session',
        required=True,
        readonly=True,
        index=True,
    )
    session_ids = fields.Many2many(
        'pos.session',
        'pos_cash_realloc_log_session_rel',
        'log_id',
        'session_id',
        string='POS Sessions',
        readonly=True,
    )
    adjustment_move_ids = fields.Many2many(
        'account.move',
        'pos_cash_realloc_log_move_rel',
        'log_id',
        'move_id',
        string='Adjustment Entries',
        readonly=True,
    )
    adjustment_move_count = fields.Integer(
        string='Journal Entry Count',
        compute='_compute_adjustment_move_count',
    )
    state = fields.Selection(
        selection=[
            ('done', 'Done'),
            ('reverted', 'Reverted'),
        ],
        string='Status',
        default='done',
        required=True,
        readonly=True,
        tracking=True,
    )
    line_ids = fields.One2many(
        'pos.cash.reallocation.log.line',
        'log_id',
        string='Lines',
        readonly=True,
    )

    @api.depends('adjustment_move_ids')
    def _compute_adjustment_move_count(self):
        for log in self:
            log.adjustment_move_count = len(log.adjustment_move_ids)

    @api.model
    def create(self, vals):
        if vals.get('name', '/') == '/':
            vals['name'] = self.env['ir.sequence'].next_by_code(
                'pos.cash.reallocation.log'
            ) or '/'
        log = super(PosCashReallocationLog, self).create(vals)
        if log.reallocation_mode == 'closed_session':
            log._check_closed_session_log_complete()
        return log

    def _check_closed_session_log_complete(self):
        self.ensure_one()
        if not self.session_ids:
            raise UserError(_(
                'Closed-session reallocation logs must list affected POS sessions.'
            ))
        if not self.adjustment_move_ids:
            raise UserError(_(
                'Closed-session reallocation logs must link at least one '
                'adjustment journal entry.'
            ))

    @api.model
    def create_closed_session_log(self, vals, session_ids, adjustment_move_ids):
        """Create audit log for a closed-session reallocation run."""
        vals = dict(vals)
        vals.update({
            'reallocation_mode': 'closed_session',
            'session_ids': [(6, 0, list(session_ids))],
            'adjustment_move_ids': [(6, 0, list(adjustment_move_ids))],
        })
        return self.create(vals)

    def action_view_adjustment_moves(self):
        self.ensure_one()
        action = self.env.ref('account.action_move_journal_line').read()[0]
        moves = self.adjustment_move_ids
        if len(moves) == 1:
            action.update({
                'view_mode': 'form',
                'res_id': moves.id,
                'views': [(False, 'form')],
            })
        else:
            action['domain'] = [('id', 'in', moves.ids)]
        return action

    def _get_lines_to_undo(self):
        self.ensure_one()
        return self.line_ids.filtered(
            lambda line: not line.skipped and line.wallet_payment_id
        )

    def _restore_payment_lines(self, lines_to_undo):
        for line in lines_to_undo:
            if line.cash_payment_id:
                line.cash_payment_id.write({'amount': line.original_cash_amount})
            line.wallet_payment_id.unlink()

    def action_undo(self):
        self.ensure_one()
        if self.state == 'reverted':
            raise UserError(_('This reallocation run has already been reverted.'))

        lines_to_undo = self._get_lines_to_undo()
        if not lines_to_undo:
            raise UserError(_('There are no applied reallocation lines to undo.'))

        if self.reallocation_mode == 'closed_session':
            return self._action_undo_closed_session(lines_to_undo)
        return self._action_undo_open_session(lines_to_undo)

    def _action_undo_open_session(self, lines_to_undo):
        self.ensure_one()
        orders = lines_to_undo.mapped('order_id')
        closed_orders = orders.filtered(lambda order: order.session_id.state == 'closed')
        if closed_orders:
            raise UserError(_(
                'Cannot undo this reallocation because the POS session is closed '
                'for the following order(s): %s',
                ', '.join(closed_orders.mapped('name')),
            ))

        self._restore_payment_lines(lines_to_undo)
        self.write({'state': 'reverted'})
        self.message_post(body=_(
            'Reallocation reverted by %s. Original cash amounts restored and '
            'wallet payment lines removed.',
            self.env.user.name,
        ))
        return True

    def _check_closed_session_undo_fiscal_period(self):
        self.ensure_one()
        reversal_date = fields.Date.context_today(self)
        lock_date = self.company_id._get_user_fiscal_lock_date()
        if reversal_date <= lock_date:
            raise UserError(_(
                'Cannot undo closed-session reallocation because the fiscal period '
                'is locked through %(lock_date)s.',
                lock_date=format_date(self.env, lock_date),
            ))

    def _check_adjustment_moves_reversible(self):
        self.ensure_one()
        for move in self.adjustment_move_ids:
            if move.state != 'posted':
                raise UserError(_(
                    'Adjustment entry %(move)s is not posted and cannot be reversed.',
                    move=move.display_name,
                ))
            if move.reversal_move_id.filtered(lambda reversal: reversal.state == 'posted'):
                raise UserError(_(
                    'Adjustment entry %(move)s has already been reversed.',
                    move=move.display_name,
                ))
            reconciled_lines = move.line_ids.filtered('reconciled')
            if reconciled_lines:
                raise UserError(_(
                    'Adjustment entry %(move)s has reconciled lines and cannot be '
                    'reversed automatically.',
                    move=move.display_name,
                ))

    def _reverse_adjustment_moves(self):
        """Reverse linked adjustment entries; return posted reversal moves."""
        self.ensure_one()
        moves = self.adjustment_move_ids.filtered(lambda move: move.state == 'posted')
        if not moves:
            return self.env['account.move']

        reversal_date = fields.Date.context_today(self)
        default_values_list = []
        for move in moves:
            default_values_list.append({
                'ref': _('Reversal of cash reallocation: %(reference)s', reference=move.ref or move.name),
                'date': reversal_date,
            })

        reversal_moves = moves._reverse_moves(default_values_list, cancel=True)
        return reversal_moves

    def _action_undo_closed_session(self, lines_to_undo):
        self.ensure_one()
        self._check_closed_session_undo_fiscal_period()
        self._check_adjustment_moves_reversible()

        with self.env.cr.savepoint():
            reversal_moves = self._reverse_adjustment_moves()
            self._restore_payment_lines(lines_to_undo)
            self.write({'state': 'reverted'})

        reversed_names = ', '.join(reversal_moves.mapped('name'))
        self.message_post(body=_(
            'Closed-session reallocation reverted by %(user)s at %(timestamp)s. '
            'Reversal journal entries: %(moves)s. Original cash amounts restored '
            'and wallet payment lines removed.',
            user=self.env.user.name,
            timestamp=fields.Datetime.to_string(fields.Datetime.now()),
            moves=reversed_names,
        ))
        return True
