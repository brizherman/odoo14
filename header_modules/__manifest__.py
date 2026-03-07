# -*- coding: utf-8 -*-
{
    'name': 'Header Modules Menu',
    'version': '14.0.2.0.0',
    'summary': 'Dynamic secondary navbar below the main top bar with dropdowns for POS, Compras, Inventario, Facturación and Ventas',
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
    ],
    'qweb': [
        'static/src/xml/secondary_navbar.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
