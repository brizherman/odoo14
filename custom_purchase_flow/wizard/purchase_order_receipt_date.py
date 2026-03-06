#! -*- coding: utf-8 -*-
from odoo import models, fields, _


class PurchaseOrderReceiptDateWizard(models.TransientModel):
    _name = 'purchase.order.receipt.date.wizard'
    _description = 'Purchase Order Receipt Date Wizard'

    purchase_order_id = fields.Many2one(
        'purchase.order',
        string='Purchase Order',
        required=True,
        readonly=True,
    )
    date_planned = fields.Datetime(
        string='Fecha de recepción',
        required=True,
    )

    def action_apply(self):
        self.ensure_one()
        po = self.purchase_order_id
        po.write({'date_planned': self.date_planned})
        return {'type': 'ir.actions.act_window_close'}

