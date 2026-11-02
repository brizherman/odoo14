# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods
"""Settings screen for wholesale POS pricing."""
from odoo import _, api, fields, models


MAPPING_FIELD_BY_CUSTOMER_TYPE = {
    'mayorista': 'wholesale_mayorista_pricelist_id',
    'publico_general': 'wholesale_publico_general_pricelist_id',
    'distribuidores': 'wholesale_distribuidores_pricelist_id',
    'mayorista_dormido': 'wholesale_mayorista_dormido_pricelist_id',
}


class ResConfigSettings(models.TransientModel):
    """Expose company wholesale rules on the Point of Sale settings."""

    _inherit = 'res.config.settings'

    wholesale_control_active = fields.Boolean(string='Activar control de mayoreo')
    wholesale_previous_month_min = fields.Monetary(
        string='Mínimo del mes anterior',
        currency_field='wholesale_currency_id',
    )
    wholesale_current_order_min = fields.Monetary(
        string='Mínimo del pedido actual',
        currency_field='wholesale_currency_id',
    )
    wholesale_distributor_min = fields.Monetary(
        string='Mínimo de distribuidor del mes anterior',
        currency_field='wholesale_currency_id',
        help='Compras netas del mes anterior, o acumulado del mes en curso '
             'más el ticket abierto, que un cliente Distribuidores necesita '
             'para Super Precios. El monto usa la moneda de la sucursal.',
    )
    wholesale_timezone = fields.Selection(
        selection=lambda self: self.env[
            'res.company'
        ]._wholesale_timezone_selection(),
        string='Zona horaria del negocio',
    )
    wholesale_retail_pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Lista de precios de menudeo',
    )
    wholesale_pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Lista de precios de mayoreo',
    )
    wholesale_mayorista_pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Mayorista',
    )
    wholesale_publico_general_pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Público General',
    )
    wholesale_distribuidores_pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Distribuidores',
    )
    wholesale_mayorista_dormido_pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Mayorista dormido',
    )
    wholesale_mapping_warning = fields.Text(
        string='Advertencia de configuración de mayoreo',
        compute='_compute_wholesale_mapping_warning',
    )
    wholesale_currency_id = fields.Many2one(
        related='company_id.currency_id',
    )

    @api.depends(
        'company_id',
        'wholesale_mayorista_pricelist_id',
        'wholesale_publico_general_pricelist_id',
        'wholesale_distribuidores_pricelist_id',
        'wholesale_mayorista_dormido_pricelist_id',
    )
    def _compute_wholesale_mapping_warning(self):
        for settings in self:
            messages = []
            missing = [
                settings._fields[field_name].string
                for field_name in MAPPING_FIELD_BY_CUSTOMER_TYPE.values()
                if not settings[field_name]
            ]
            if missing:
                messages.append(_(
                    'Estos tipos de cliente no tienen una asignación de lista de '
                    'precios activa: %(types)s.',
                    types=', '.join(missing),
                ))
            messages.extend(settings._wholesale_distributor_setting_messages())
            settings.wholesale_mapping_warning = '\n'.join(messages) or False

    def _wholesale_distributor_setting_messages(self):
        """Unsaved distributor-list problems shown before the company is written."""
        self.ensure_one()
        pricelist = self.wholesale_distribuidores_pricelist_id
        if not pricelist:
            return [_(
                'Distribuidores no tiene una asignación de lista de precios. '
                'No se usa la lista general de mayoreo.'
            )]
        if not pricelist.active:
            return [_(
                'La lista de Distribuidores "%(pricelist)s" está archivada. '
                'No se usa la lista general de mayoreo.',
                pricelist=pricelist.display_name,
            )]
        currency = self.wholesale_currency_id
        if currency and pricelist.currency_id != currency:
            return [_(
                'La lista de Distribuidores "%(pricelist)s" usa '
                '%(pricelist_currency)s. Esta sucursal usa %(company_currency)s.',
                pricelist=pricelist.display_name,
                pricelist_currency=pricelist.currency_id.name,
                company_currency=currency.name,
            )]
        company = self.company_id
        if not company:
            return []
        configs = company._pos_configs()
        missing_configs = configs.filtered(
            lambda config, current=pricelist: not company._pricelist_available_on(
                config, current,
            )
        )
        if missing_configs:
            return [_(
                'La lista de Distribuidores "%(pricelist)s" no está disponible '
                'en %(configs)s.',
                pricelist=pricelist.display_name,
                configs=', '.join(missing_configs.mapped('name')),
            )]
        return []

    @api.model
    def get_values(self):
        values = super().get_values()
        company = self.env.company
        values.update({
            'wholesale_control_active': company.wholesale_control_active,
            'wholesale_previous_month_min':
                company.wholesale_previous_month_min,
            'wholesale_current_order_min':
                company.wholesale_current_order_min,
            'wholesale_distributor_min':
                company.wholesale_distributor_min,
            'wholesale_timezone': company.wholesale_timezone,
            'wholesale_retail_pricelist_id':
                company.wholesale_retail_pricelist_id.id,
            'wholesale_pricelist_id': company.wholesale_pricelist_id.id,
        })
        mappings = {
            mapping.customer_type: mapping
            for mapping in company.wholesale_mapping_ids
            if mapping.active
        }
        empty_mapping = self.env['pos.wholesale.pricelist.mapping']
        for customer_type, field_name in (
                MAPPING_FIELD_BY_CUSTOMER_TYPE.items()):
            values[field_name] = mappings.get(
                customer_type,
                empty_mapping,
            ).pricelist_id.id
        return values

    def set_values(self):
        super().set_values()
        self.ensure_one()
        company = self.company_id
        mappings = {
            mapping.customer_type: mapping
            for mapping in company.wholesale_mapping_ids
        }
        Mapping = self.env['pos.wholesale.pricelist.mapping']
        for customer_type, field_name in (
                MAPPING_FIELD_BY_CUSTOMER_TYPE.items()):
            mapping = mappings.get(customer_type)
            pricelist = self[field_name]
            if mapping and pricelist:
                mapping.write({
                    'pricelist_id': pricelist.id,
                    'active': True,
                })
            elif pricelist:
                Mapping.create({
                    'company_id': company.id,
                    'customer_type': customer_type,
                    'pricelist_id': pricelist.id,
                    'active': True,
                })
            elif mapping:
                mapping.unlink()

        company.write({
            'wholesale_control_active': self.wholesale_control_active,
            'wholesale_previous_month_min':
                self.wholesale_previous_month_min,
            'wholesale_current_order_min': self.wholesale_current_order_min,
            'wholesale_distributor_min': self.wholesale_distributor_min,
            'wholesale_timezone': self.wholesale_timezone,
            'wholesale_retail_pricelist_id':
                self.wholesale_retail_pricelist_id.id,
            'wholesale_pricelist_id': self.wholesale_pricelist_id.id,
        })
