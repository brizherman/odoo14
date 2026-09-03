# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods
"""Company settings for Expo Factor Fiesta WhatsApp."""
from odoo import fields, models


class ResCompany(models.Model):
    """Store the WhatsApp number used in Expo invitation messages."""

    _inherit = 'res.company'

    expo_whatsapp_number = fields.Char(
        string='Expo WhatsApp Number',
        help='WhatsApp number for this company used in Expo Factor Fiesta '
             'invitation messages (placeholder {company_whatsapp}).',
    )
