# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID


def post_init_hook(cr, registry):
    """Set all users to Sidebar Type = Invisible, Chatter Position = Normal (MuK theme)."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    users = env['res.users'].search([])
    if users:
        users.write({
            'sidebar_type': 'invisible',
            'chatter_position': 'normal',
        })
