# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods
"""Map existing customer types to wholesale pricelists."""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

CUSTOMER_TYPE_SELECTION = [
    ('mayorista', 'Mayorista'),
    ('publico_general', 'Público General'),
    ('distribuidores', 'Distribuidores'),
    ('mayorista_dormido', 'Mayorista dormido'),
]


class WholesalePricelistMapping(models.Model):
    """Wholesale pricelist used when one customer type qualifies."""

    _name = 'pos.wholesale.pricelist.mapping'
    _description = 'Asignación de lista de precios de mayoreo'
    _order = 'company_id, customer_type'
    _rec_name = 'customer_type'

    company_id = fields.Many2one(
        'res.company',
        string='Sucursal',
        required=True,
        index=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
    )
    customer_type = fields.Selection(
        selection=CUSTOMER_TYPE_SELECTION,
        string='Tipo de cliente',
        required=True,
        help='Tipo de cliente definido por Alta Mayoristas. '
             'Esta asignación no cambia esa clasificación.',
    )
    pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Lista de precios de mayoreo',
        required=True,
        check_company=True,
        help='Lista que se aplica cuando este tipo de cliente califica para '
             'mayoreo. Público General y Mayorista dormido la usan solo cuando '
             'el pedido actual, a precio de menudeo, alcanza el mínimo. Si no, '
             'el pedido permanece en la lista de menudeo.',
    )
    active = fields.Boolean(string='Activo', default=True)

    _sql_constraints = [
        (
            'company_customer_type_uniq',
            'unique(company_id, customer_type)',
            'Cada tipo de cliente solo puede tener una asignación '
            'de lista de precios por sucursal.',
        ),
    ]

    @api.constrains('company_id', 'pricelist_id')
    def _check_pricelist_company_and_currency(self):
        for mapping in self:
            pricelist = mapping.pricelist_id
            company = mapping.company_id
            if pricelist.company_id and pricelist.company_id != company:
                raise ValidationError(_(
                    'La lista "%(pricelist)s" pertenece a %(owner)s '
                    'y no se puede usar para %(company)s.',
                    pricelist=pricelist.display_name,
                    owner=pricelist.company_id.display_name,
                    company=company.display_name,
                ))
            if pricelist.currency_id != company.currency_id:
                raise ValidationError(_(
                    'La lista "%(pricelist)s" usa %(pricelist_currency)s. '
                    '%(company)s requiere %(company_currency)s.',
                    pricelist=pricelist.display_name,
                    pricelist_currency=pricelist.currency_id.name,
                    company=company.display_name,
                    company_currency=company.currency_id.name,
                ))
            if not pricelist.active:
                raise ValidationError(_(
                    'La lista "%(pricelist)s" está archivada. Elija una lista activa.',
                    pricelist=pricelist.display_name,
                ))

    def name_get(self):
        """Show the customer type and wholesale pricelist."""
        labels = dict(CUSTOMER_TYPE_SELECTION)
        result = []
        for mapping in self:
            type_label = labels.get(mapping.customer_type) or mapping.customer_type
            pricelist_name = mapping.pricelist_id.display_name or ''
            result.append((mapping.id, f'{type_label} / {pricelist_name}'))
        return result
