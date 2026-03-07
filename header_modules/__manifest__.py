# -*- coding: utf-8 -*-
{
    'name': 'Header Modules Menu',
    'version': '14.0.1.0.8',
    'summary': 'Top-level "Modules" menu with POS, Purchase, Inventory, Invoicing, Sales (full submenus on hover)',
    'author': 'Custom',
    'category': 'Productivity',
    'depends': [
        'base',
        'point_of_sale',
        'purchase',
        'stock',
        'account',
        'sale_management',
        'muk_web_theme',
    ],
    'data': [
        'views/assets.xml',
        'data/menu.xml',
        'data/menu_icon_update.xml',
        'data/menu_restore.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
