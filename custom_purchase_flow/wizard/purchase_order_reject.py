# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class PurchaseOrderRejectWizard(models.TransientModel):
    _name = 'purchase.order.reject.wizard'
    _description = 'Purchase Order Rejection Wizard'

    purchase_order_id = fields.Many2one(
        comodel_name='purchase.order',
        string="Purchase Order",
        required=True,
    )
    rejection_reason = fields.Text(
        string="Rejection Reason",
        required=True,
    )

    @api.constrains('rejection_reason')
    def _check_rejection_reason(self):
        for wizard in self:
            if not wizard.rejection_reason or not wizard.rejection_reason.strip():
                raise ValidationError(_("Rejection reason is required."))

    def action_reject_to_draft(self):
        """Reject the PO — return it to Draft state."""
        self.ensure_one()
        po = self.purchase_order_id
        po.write({
            'state': 'draft',
            'rejection_reason': self.rejection_reason,
        })
        po.sudo().message_post(
            body=_("Rejected — Returned to Draft<br/>Reason: %s") % self.rejection_reason,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
        return {'type': 'ir.actions.act_window_close'}

    def action_reject_to_cancel(self):
        """Reject the PO — cancel it entirely."""
        self.ensure_one()
        po = self.purchase_order_id
        po.write({
            'state': 'cancel',
            'rejection_reason': self.rejection_reason,
        })
        po.sudo().message_post(
            body=_("Rejected — Cancelled<br/>Reason: %s") % self.rejection_reason,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
        return {'type': 'ir.actions.act_window_close'}
