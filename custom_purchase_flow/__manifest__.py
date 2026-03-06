# -*- coding: utf-8 -*-
{
    'name': 'Custom Purchase Flow',
    'version': '14.0.1.0.0',
    'summary': 'Custom multi-state purchase approval and fulfillment flow',
    'author': 'Custom',
    'category': 'Purchase',
    'depends': ['web', 'purchase', 'stock', 'mail', 'purchase_stock'],
    'data': [
        'views/assets.xml',
        'security/security.xml',
        'security/ir.model.access.csv',
        'wizard/purchase_order_reject_views.xml',
        'wizard/purchase_order_receipt_date_views.xml',
        'wizard/purchase_order_tracking_views.xml',
        'views/purchase_order_views.xml',
        'views/purchase_menu_labels.xml',
    ],
    'qweb': [
        'static/src/xml/purchase_rfq_dashboard.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_hook',
}
