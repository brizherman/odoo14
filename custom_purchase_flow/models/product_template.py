# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    x_cost_ins = fields.Float(
        string='Costo Ins',
        compute='_compute_costs_by_company',
        digits='Product Price',
    )
    x_cost_rio = fields.Float(
        string='Costo Rio',
        compute='_compute_costs_by_company',
        digits='Product Price',
    )
    x_cost_ens = fields.Float(
        string='Costo Ens',
        compute='_compute_costs_by_company',
        digits='Product Price',
    )

    @api.depends_context('company')
    def _compute_costs_by_company(self):
        company_ins = self.env['res.company'].browse(1)
        company_rio = self.env['res.company'].browse(2)
        company_ens = self.env['res.company'].browse(5)

        for product in self:
            product.x_cost_ins = product.with_company(company_ins).standard_price
            product.x_cost_rio = product.with_company(company_rio).standard_price
            product.x_cost_ens = product.with_company(company_ens).standard_price
