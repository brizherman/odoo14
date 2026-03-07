# -*- coding: utf-8 -*-
{
    'name': 'Company Archive',
    'version': '14.0.1.0.0',
    'summary': 'Add active field to companies so they can be archived',
    'author': 'Custom',
    'category': 'Base',
    'depends': ['base'],
    'data': [
        'views/res_company_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
