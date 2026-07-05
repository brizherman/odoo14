# -*- coding: utf-8 -*-
{
    'name': 'POS Cash Reallocation Wizard',
    'version': '14.0.1.0.0',
    'summary': 'Proportional cash reallocation from POS orders into Monedero Electrónico',
    'description': """
        Two-step wizard to reallocate cash from paid, cash-only, customer-less
        POS orders into a hidden Monedero Electrónico payment method.
    """,
    'author': 'Custom',
    'category': 'Point Of Sale',
    'depends': ['point_of_sale', 'account', 'mail'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/pos_cash_reallocation_sequence.xml',
        'views/pos_cash_reallocation_wizard_views.xml',
        'views/pos_cash_reallocation_log_views.xml',
        'views/pos_cash_reallocation_menu.xml',
        'views/pos_order_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
