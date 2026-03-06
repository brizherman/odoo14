# -*- coding: utf-8 -*-
"""Transient model to mark a PO as 'just submitted' so Edit is hidden on next form load."""
from odoo import models, fields


class PurchaseOrderHideEditFlag(models.TransientModel):
    _name = 'purchase.order.hide.edit.flag'
    _description = 'Flag to hide Edit button once after request approval'

    order_id = fields.Many2one(
        'purchase.order',
        string='Purchase Order',
        required=True,
        ondelete='cascade',
    )
