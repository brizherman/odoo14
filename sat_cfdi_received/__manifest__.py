# -*- coding: utf-8 -*-
{
    'name': 'Descarga de CFDIs recibidos del SAT',
    'version': '14.0.1.0.0',
    'summary': 'Descarga CFDIs recibidos del SAT usando FIEL (Descarga Masiva v1.5)',
    'author': 'Custom',
    'category': 'Accounting',
    'depends': [
        'base',
        'account',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/res_company_views.xml',
        'views/sat_download_request_views.xml',
        'views/sat_cfdi_received_views.xml',
        'wizard/sat_download_wizard_views.xml',
        'views/menu.xml',
    ],
    'external_dependencies': {
        'python': [
            'cfdiclient',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_hook',
}
