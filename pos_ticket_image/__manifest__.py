# -*- coding: utf-8 -*-
# pylint: disable=missing-module-docstring,manifest-required-author,missing-readme,manifest-deprecated-key
{
    'name': 'POS Ticket Campaign Image',
    'version': '14.0.1.0.0',
    'summary': 'Print a campaign image on the POS receipt for a date range',
    'description': """
Prints one campaign image on the POS receipt when the sale date falls
inside an inclusive date range. Every company and every point of sale
uses the same list.
""",
    'author': 'Custom',
    'category': 'Point of Sale',
    'depends': [
        'point_of_sale',
        'custom_invoice',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/pos_ticket_image_views.xml',
        'views/assets.xml',
    ],
    'qweb': [
        'static/src/xml/OrderReceipt.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
