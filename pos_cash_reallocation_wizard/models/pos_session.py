# -*- coding: utf-8 -*-
from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def get_lealtad_amount(self):
        """Return total Lealtad payments for this session."""
        self.ensure_one()
        wallet_method = self.env['pos.order']._get_wallet_payment_method(
            self.company_id
        )
        if not wallet_method:
            return 0.0
        payments = self.env['pos.payment'].search([
            ('session_id', '=', self.id),
            ('payment_method_id', '=', wallet_method.id),
        ])
        return sum(payments.mapped('amount'))
