# -*- coding: utf-8 -*-


def post_init_hook(cr, registry):
    """Provision Lealtad account, journal, and payment method per company."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    PosOrder = env['pos.order']
    for company in env['res.company'].search([]):
        PosOrder._setup_wallet_infrastructure_for_company(company)
