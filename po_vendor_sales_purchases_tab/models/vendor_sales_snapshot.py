# -*- coding: utf-8 -*-
from odoo import fields, models


class VendorSalesSnapshot(models.Model):
    _name = 'vendor.sales.snapshot'
    _description = 'Vendor Sales Snapshot by Month and Department'
    _order = 'month desc, classification_department_id, id desc'

    partner_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        ondelete='cascade',
        index=True,
    )
    classification_department_id = fields.Many2one(
        'product.classification.department',
        string='Department',
        required=True,
        ondelete='restrict',
        index=True,
    )
    month = fields.Date(
        string='Month',
        required=True,
        help='First day of the calendar month',
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )
    amount_total = fields.Monetary(
        string='Amount Total',
        currency_field='currency_id',
        help='Tax-inclusive sales total',
    )

    _sql_constraints = [
        (
            'partner_company_dept_month_uniq',
            'unique(partner_id, company_id, classification_department_id, month)',
            'A sales snapshot already exists for this vendor, company, department, and month.',
        ),
    ]
