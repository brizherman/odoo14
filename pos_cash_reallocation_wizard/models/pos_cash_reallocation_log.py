# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


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

    @api.model
    def create(self, vals):
        if vals.get('name', '/') == '/':
            vals['name'] = self.env['ir.sequence'].next_by_code(
                'pos.cash.reallocation.log'
            ) or '/'
        return super(PosCashReallocationLog, self).create(vals)

    def action_undo(self):
        self.ensure_one()
        if self.state == 'reverted':
            raise UserError(_('This reallocation run has already been reverted.'))

        lines_to_undo = self.line_ids.filtered(
            lambda line: not line.skipped and line.wallet_payment_id
        )
        if not lines_to_undo:
            raise UserError(_('There are no applied reallocation lines to undo.'))

        orders = lines_to_undo.mapped('order_id')
        closed_orders = orders.filtered(lambda order: order.session_id.state == 'closed')
        if closed_orders:
            raise UserError(_(
                'Cannot undo this reallocation because the POS session is closed '
                'for the following order(s): %s',
                ', '.join(closed_orders.mapped('name')),
            ))

        for line in lines_to_undo:
            if line.cash_payment_id:
                line.cash_payment_id.write({'amount': line.original_cash_amount})
            line.wallet_payment_id.unlink()

        self.write({'state': 'reverted'})
        self.message_post(body=_(
            'Reallocation reverted by %s. Original cash amounts restored and '
            'wallet payment lines removed.',
            self.env.user.name,
        ))
        return True
