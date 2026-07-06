# -*- coding: utf-8 -*-


def post_init_hook(cr, registry):
    """Provision Lealtad infrastructure per company and flag legacy wallet orders."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    PosOrder = env['pos.order']
    wallet_method_ids = []
    for company in env['res.company'].search([]):
        method = PosOrder._setup_wallet_infrastructure_for_company(company)
        if method:
            wallet_method_ids.append(method.id)

    if not wallet_method_ids:
        return

    # Fast SQL backfill for orders that already have wallet payment lines.
    cr.execute(
        """
        UPDATE pos_order
        SET has_wallet_payment = TRUE
        WHERE id IN (
            SELECT DISTINCT pos_order_id
            FROM pos_payment
            WHERE payment_method_id IN %s
        )
        """,
        (tuple(wallet_method_ids),),
    )
