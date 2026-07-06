# -*- coding: utf-8 -*-
from odoo import fields, models


class PosCashReallocationWizardPreviewLine(models.TransientModel):
    _name = 'pos.cash.reallocation.wizard.preview.line'
    _description = 'POS Cash Reallocation Wizard Preview Line'
    _order = 'id asc'

    wizard_id = fields.Many2one(
        'pos.cash.reallocation.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    order_id = fields.Many2one(
        'pos.order',
        string='POS Order',
        required=True,
        readonly=True,
    )
    original_cash = fields.Float(
        string='Original Cash',
        digits='Product Price',
        readonly=True,
    )
    new_cash = fields.Float(
        string='New Cash',
        digits='Product Price',
        readonly=True,
    )
    wallet_amount = fields.Float(
        string='Lealtad Amount',
        digits='Product Price',
        readonly=True,
    )


class PosCashReallocationWizardSkipLine(models.TransientModel):
    _name = 'pos.cash.reallocation.wizard.skip.line'
    _description = 'POS Cash Reallocation Wizard Skip Line'
    _order = 'id asc'

    wizard_id = fields.Many2one(
        'pos.cash.reallocation.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    order_id = fields.Many2one(
        'pos.order',
        string='POS Order',
        required=True,
        readonly=True,
    )
    skip_reason = fields.Char(
        string='Skip Reason',
        readonly=True,
    )
