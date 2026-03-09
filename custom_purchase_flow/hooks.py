# -*- coding: utf-8 -*-
"""
Translation hooks: overrides es_MX translations for purchase state labels
and the RFQ action/menu title so they match our custom flow naming.

apply_translations() is called:
  - on module INSTALL  via post_init_hook
  - on module UPGRADE  via a <function> record in data/translations.xml (noupdate="0")
"""
from odoo import SUPERUSER_ID, api


# Maps native English label (src) → our desired display name
_STATE_LABEL_OVERRIDES = {
    'RFQ': 'Borrador',
    'RFQ Sent': 'Enviada a Proveedor',
    'To Approve': 'Por Autorizar',
    'Purchase Order': 'PO Surtiendo',
    'Locked': 'Bloqueado',
    'Cancelled': 'Cancelado',
}

_LANGS = ['es_MX']

_RFQ_TITLE = 'Ordenes de Compra'


def apply_translations(env):
    """Write custom es_MX translations for state labels and RFQ title.
    Safe to call on both install and upgrade.
    """
    _apply_state_translations(env)
    _apply_rfq_action_menu_translations(env)


def post_init_hook(cr, registry):
    """Called on module install."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    apply_translations(env)


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
    """Set es_MX translation for RFQ action and menu to 'Ordenes de Compra'."""
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
            ])
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
