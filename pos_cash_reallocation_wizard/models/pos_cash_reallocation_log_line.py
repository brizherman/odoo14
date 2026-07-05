# -*- coding: utf-8 -*-
from odoo import fields, models


class PosCashReallocationLogLine(models.Model):
    _name = 'pos.cash.reallocation.log.line'
    _description = 'POS Cash Reallocation Log Line'
    _order = 'id asc'

    log_id = fields.Many2one(
        'pos.cash.reallocation.log',
        string='Reallocation Log',
        required=True,
        ondelete='cascade',
        index=True,
    )
    order_id = fields.Many2one(
        'pos.order',
        string='POS Order',
        required=True,
        ondelete='restrict',
        index=True,
    )
    original_cash_amount = fields.Float(string='Original Cash', digits='Product Price')
    new_cash_amount = fields.Float(string='New Cash', digits='Product Price')
    wallet_amount = fields.Float(string='Wallet Amount', digits='Product Price')
    cash_payment_id = fields.Many2one(
        'pos.payment',
        string='Cash Payment',
        ondelete='set null',
    )
    wallet_payment_id = fields.Many2one(
        'pos.payment',
        string='Wallet Payment',
        ondelete='set null',
    )
    skipped = fields.Boolean(string='Skipped', default=False)
    skip_reason = fields.Char(string='Skip Reason')
