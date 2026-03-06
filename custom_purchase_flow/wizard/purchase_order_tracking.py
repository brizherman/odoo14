# -*- coding: utf-8 -*-
from odoo import models, fields, _


class PurchaseOrderTrackingWizard(models.TransientModel):
    _name = 'purchase.order.tracking.wizard'
    _description = 'Purchase Order Tracking Wizard'

    purchase_order_id = fields.Many2one(
        'purchase.order',
        string='Purchase Order',
        required=True,
        readonly=True,
    )
    tracking_number = fields.Char(string='Tracking Number')
    no_tracking_reason = fields.Text(string='No Tracking Reason')

    def action_apply(self):
        self.ensure_one()
        po = self.purchase_order_id
        vals = {
            'tracking_number': self.tracking_number,
            'no_tracking_reason': self.no_tracking_reason,
        }
        po.write(vals)
        return {'type': 'ir.actions.act_window_close'}
