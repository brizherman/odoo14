# -*- coding: utf-8 -*-
# pylint: disable=import-error,protected-access
"""Point the sales recompute cron at the next 12:00 AM America/Tijuana."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Set nextcall on the existing noupdate cron without running the job."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref(
        'alta_mayoristas.ir_cron_recompute_sales_last_6_months',
        raise_if_not_found=False,
    )
    if not cron:
        return
    cron.write({
        'nextcall': env['res.partner']._next_tijuana_midnight_utc(),
        'active': True,
    })
