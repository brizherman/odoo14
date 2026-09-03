# -*- coding: utf-8 -*-
# pylint: disable=missing-module-docstring,manifest-required-author,missing-readme
{
    'name': 'Alta Mayoristas',
    'version': '14.0.1.8.2',
    'summary': 'Classify POS customers and assign matching pricelists',
    'author': 'Custom',
    'category': 'Point of Sale',
    'depends': ['point_of_sale', 'sale', 'contacts'],
    'data': [
        'security/classifier_security.xml',
        'data/ir_cron_sales_last_6_months.xml',
        'data/expo_whatsapp_template.xml',
        'views/res_company_views.xml',
        'views/res_partner_views.xml',
        'views/res_partner_classifier_views.xml',
        'views/assets.xml',
    ],
    'qweb': [
        'static/src/xml/ClientDetailsEdit.xml',
        'static/src/xml/customer_type_checkboxes_field.xml',
        'static/src/xml/partner_classifier_list.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
