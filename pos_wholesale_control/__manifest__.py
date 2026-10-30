# -*- coding: utf-8 -*-
# pylint: disable=missing-module-docstring,manifest-required-author,missing-readme
{
    'name': 'Control de precios mayoristas en POS',
    'version': '14.0.1.1.0',
    'summary': (
        'Aplica precios de menudeo o mayoreo en el punto de venta '
        'según el historial de compra'
    ),
    'description': """
El punto de venta elige la lista de menudeo o de mayoreo. No modifica
alta_mayoristas ni los pedidos ya cobrados.

Antes de activarlo en una sucursal, en Punto de venta → Configuración:

- Lista de menudeo: Public Pricelist, en MXN y disponible en cada caja.
- Lista de mayoreo: Club Mayorista, también disponible en cada caja.
- Asignaciones: mayorista, público general y mayorista dormido usan
  Club Mayorista. Distribuidores usa Super Precios a Distribuidores.
- Mínimos: MXN $800 del mes anterior y MXN $1,500 del pedido actual.
- Zona horaria: America/Tijuana.
- La caja debe usar empleados de pos_hr. El gerente necesita el grupo
  Punto de venta / Responsable y un NIP.

La activación queda apagada después de instalar o actualizar. Los totales
mensuales suman todas las sucursales. Una excepción de gerente vale solo
para el ticket en curso.
""",
    'author': 'Custom',
    'category': 'Point of Sale',
    'depends': [
        'point_of_sale',
        'pos_hr',
        'alta_mayoristas',
    ],
    'data': [
        'security/wholesale_security.xml',
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/pos_order_views.xml',
        'views/pos_wholesale_override_views.xml',
        'views/assets.xml',
    ],
    'qweb': [
        'static/src/xml/wholesale_status_panel.xml',
        'static/src/xml/manager_override_popup.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
