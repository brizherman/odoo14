# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods
"""Settings screen for wholesale POS pricing."""
from odoo import api, fields, models


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
            missing = [
                settings._fields[field_name].string
                for field_name in MAPPING_FIELD_BY_CUSTOMER_TYPE.values()
                if not settings[field_name]
            ]
            settings.wholesale_mapping_warning = (
                'Estos tipos de cliente no tienen una asignación de lista de '
                'precios activa: %s.' % ', '.join(missing)
                if missing else False
            )

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
            'wholesale_timezone': self.wholesale_timezone,
            'wholesale_retail_pricelist_id':
                self.wholesale_retail_pricelist_id.id,
            'wholesale_pricelist_id': self.wholesale_pricelist_id.id,
        })
