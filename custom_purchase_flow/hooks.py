# -*- coding: utf-8 -*-
"""
Post-install hook: overrides the es_MX/es translations for:
- purchase.order state selection labels (custom UX names)
- RFQ action and menu names so they show "Ordenes de Compra" for Spanish users
  instead of "Solicitudes de presupuesto".
"""
from odoo import SUPERUSER_ID, api


# Maps native English label (src) → our desired display name
_STATE_LABEL_OVERRIDES = {
    'RFQ': 'Borrador',
    'RFQ Sent': 'Enviada a Proveedor',
    'To Approve': 'Por Aprobar',
    'Purchase Order': 'PO Surtiendo',
    'Locked': 'Bloqueado',
    'Cancelled': 'Cancelado',
}

_LANGS = ['es_MX', 'es']

_RFQ_TITLE = 'Ordenes de Compra'


def post_init_hook(cr, registry):
    """Overwrite ir.translation for state labels and RFQ action/menu names."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    _apply_state_translations(env)
    _apply_rfq_action_menu_translations(env)


def uninstall_hook(cr, registry):
    """Restore original es_MX translations when module is uninstalled."""
    pass  # Translations will be restored on next language reload if needed


def _apply_state_translations(env):
    Translation = env['ir.translation']
    for lang in _LANGS:
        for src, new_value in _STATE_LABEL_OVERRIDES.items():
            translations = Translation.search([
                ('lang', '=', lang),
                ('name', '=', 'ir.model.fields.selection,name'),
                ('src', '=', src),
            ])
            if translations:
                translations.write({'value': new_value})


def _apply_rfq_action_menu_translations(env):
    """Set Spanish translations for RFQ action and menu to 'Ordenes de Compra'
    so Spanish-language users (e.g. coordinador) see the same title as others."""
    Translation = env['ir.translation']
    try:
        action = env.ref('purchase.purchase_rfq')
        menu = env.ref('purchase.menu_purchase_rfq')
    except Exception:
        return
    for lang in _LANGS:
        for name, res_id in [
            ('ir.actions.act_window,name', action.id),
            ('ir.ui.menu,name', menu.id),
        ]:
            trans = Translation.search([
                ('lang', '=', lang),
                ('name', '=', name),
                ('res_id', '=', res_id),
            ], limit=1)
            if trans:
                trans.write({'value': _RFQ_TITLE})
            else:
                Translation.create({
                    'type': 'model',
                    'name': name,
                    'res_id': res_id,
                    'lang': lang,
                    'value': _RFQ_TITLE,
                    'state': 'translated',
                })
