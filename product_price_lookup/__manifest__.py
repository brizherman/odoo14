# -*- coding: utf-8 -*-
# pylint: disable=missing-module-docstring,manifest-required-author,missing-readme,manifest-deprecated-key
{
    'name': 'Consulta de precios',
    'version': '14.0.1.1.0',
    'summary': 'Consulta el precio con impuesto de un producto en tres listas',
    'description': """
Muestra el precio unitario con impuesto de un producto para Público General,
Mayorista y Distribuidores. La misma consulta está en el backend y en el
punto de venta. No elige un cliente y no modifica el ticket abierto.
""",
    'author': 'Custom',
    'category': 'Sales',
    'depends': [
        'point_of_sale',
        'alta_mayoristas',
    ],
    'data': [
        'views/res_config_settings_views.xml',
        'views/product_price_lookup_views.xml',
        'views/assets.xml',
    ],
    'qweb': [
        'static/src/xml/price_lookup_backend.xml',
        'static/src/xml/PriceLookupButton.xml',
        'static/src/xml/PriceLookupPopup.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
