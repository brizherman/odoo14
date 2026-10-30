# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods
"""Settings screen for wholesale POS pricing."""
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Expose company wholesale rules on the Point of Sale settings."""

    _inherit = 'res.config.settings'

    wholesale_control_active = fields.Boolean(
        related='company_id.wholesale_control_active',
        readonly=False,
    )
    wholesale_previous_month_min = fields.Monetary(
        related='company_id.wholesale_previous_month_min',
        readonly=False,
        currency_field='wholesale_currency_id',
    )
    wholesale_current_order_min = fields.Monetary(
        related='company_id.wholesale_current_order_min',
        readonly=False,
        currency_field='wholesale_currency_id',
    )
    wholesale_timezone = fields.Selection(
        related='company_id.wholesale_timezone',
        readonly=False,
    )
    wholesale_retail_pricelist_id = fields.Many2one(
        related='company_id.wholesale_retail_pricelist_id',
        readonly=False,
    )
    wholesale_pricelist_id = fields.Many2one(
        related='company_id.wholesale_pricelist_id',
        readonly=False,
    )
    wholesale_mapping_ids = fields.One2many(
        related='company_id.wholesale_mapping_ids',
        readonly=False,
    )
    wholesale_mapping_warning = fields.Text(
        related='company_id.wholesale_mapping_warning',
    )
    wholesale_currency_id = fields.Many2one(
        related='company_id.currency_id',
    )
