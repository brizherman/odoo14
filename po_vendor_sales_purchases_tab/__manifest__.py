# -*- coding: utf-8 -*-
{
    'name': 'Pestaña Compras y Ventas del Proveedor en OC',
    'version': '14.0.1.0.9',
    'summary': 'Pestaña en OC que compara compras del proveedor (Google Sheets) vs ventas por departamento',
    'author': 'Custom',
    'category': 'Purchase',
    'depends': [
        'purchase',
        'custom_purchase_flow',
        'product_classifications',
        'sale',
        'point_of_sale',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/vendor_mapping_views.xml',
        'views/vendor_sheet_config_views.xml',
        'views/vendor_sheet_sync_log_views.xml',
        'views/purchase_order_views.xml',
        'data/menu.xml',
    ],
    'external_dependencies': {
        'python': [
            'google-api-python-client',
            'google-auth',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
