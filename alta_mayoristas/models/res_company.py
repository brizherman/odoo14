# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods
"""Company settings for Expo Factor Fiesta WhatsApp."""
from odoo import fields, models


class ResCompany(models.Model):
    """Store the WhatsApp number used in Expo invitation messages."""

    _inherit = 'res.company'

    expo_whatsapp_number = fields.Char(
        string='Número de WhatsApp Expo',
        help='Puede ser un número local MX (ej. 6641231234). '
             'Los enlaces de WhatsApp agregan +52 automáticamente; si ya '
             'empieza con 52, en el texto del mensaje solo se agrega el +.',
    )
