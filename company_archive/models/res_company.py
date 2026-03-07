# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError


class ResCompany(models.Model):
    _inherit = 'res.company'

    active = fields.Boolean(default=True, help='Uncheck to archive the company; it will be hidden from the company switcher.')

    def action_archive(self):
        """Archive the company; hide from company switcher."""
        for company in self:
            if company == self.env.company:
                raise UserError(_("You cannot archive the company you are currently using. Switch to another company first."))
        self.write({'active': False})

    def action_unarchive(self):
        """Restore the company; show again in company switcher."""
        self.write({'active': True})
