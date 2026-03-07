# -*- coding: utf-8 -*-
from odoo import models, api


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def _default_sidebar_type(self):
        return 'invisible'

    @api.model
    def _default_chatter_position(self):
        return 'normal'
