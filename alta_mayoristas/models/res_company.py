# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods
"""Company settings for Expo Factor Fiesta WhatsApp."""
from odoo import fields, models


class ResCompany(models.Model):
    """Store the WhatsApp number used in Expo invitation messages."""

    _inherit = 'res.company'

    expo_whatsapp_number = fields.Char(
        string='Expo WhatsApp Number',
        help='Local MX number is fine (e.g. 6641231234). '
             'WhatsApp links add +52 automatically; if it already starts '
             'with 52, only + is added in the message text.',
    )
