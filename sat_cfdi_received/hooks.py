# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID


def post_init_hook(cr, registry):
    """Migrate legacy plaintext FIEL passwords after module install."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['res.company']._migrate_plaintext_fiel_passwords()
