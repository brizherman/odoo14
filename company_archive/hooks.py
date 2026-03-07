# -*- coding: utf-8 -*-


def post_init_hook(cr, registry):
    """Create Archive and Unarchive server actions for res.company."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    model = env.ref('base.model_res_company')
    actions = env['ir.actions.server'].search([
        ('binding_model_id', '=', model.id),
        ('name', 'in', ('Archive', 'Unarchive')),
    ])
    if actions:
        return
    env['ir.actions.server'].create([
        {
            'name': 'Archive',
            'type': 'ir.actions.server',
            'model_id': model.id,
            'binding_model_id': model.id,
            'binding_view_types': 'form',
            'state': 'code',
            'code': 'records.action_archive()',
        },
        {
            'name': 'Unarchive',
            'type': 'ir.actions.server',
            'model_id': model.id,
            'binding_model_id': model.id,
            'binding_view_types': 'form',
            'state': 'code',
            'code': 'records.action_unarchive()',
        },
    ])
