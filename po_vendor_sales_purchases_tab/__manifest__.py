# -*- coding: utf-8 -*-
{
    'name': 'PO Vendor Purchases & Sales Tab',
    'version': '14.0.1.0.5',
    'summary': 'PO tab comparing vendor purchases (Google Sheets) vs sales by department',
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
