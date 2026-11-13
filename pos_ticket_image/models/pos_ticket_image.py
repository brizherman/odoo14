# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods
"""One campaign image for every POS receipt in an inclusive date range."""
import base64
import binascii

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
JPEG_SIGNATURE = b'\xff\xd8\xff'


def _image_is_png_or_jpg(value):
    """True when the stored bytes are a PNG or a JPEG.

    The Image field keeps the original format when it does not resize.
    A GIF or any other type must not be saved.
    """
    if not value:
        return False
    payload = value
    if isinstance(payload, str):
        payload = payload.encode('ascii', errors='ignore')
    if payload.startswith(PNG_SIGNATURE) or payload.startswith(JPEG_SIGNATURE):
        return True
    try:
        decoded = base64.b64decode(payload)
    except (binascii.Error, ValueError, TypeError):
        return False
    return (
        decoded.startswith(PNG_SIGNATURE)
        or decoded.startswith(JPEG_SIGNATURE)
    )


class PosTicketImage(models.Model):
    """Campaign printed on the receipt. The date range is the only switch."""

    _name = 'pos.ticket.image'
    _description = 'POS Ticket Campaign Image'
    _order = 'date_start, id'

    name = fields.Char(required=True)
    image = fields.Image(
        required=True,
        max_width=1920,
        max_height=1920,
    )
    image_512 = fields.Image(
        string='Image 512',
        related='image',
        max_width=512,
        max_height=512,
        store=True,
    )
    date_start = fields.Date(required=True, string='Start Date')
    date_end = fields.Date(required=True, string='End Date')
    position = fields.Selection(
        selection=[
            ('top', 'Top'),
            ('bottom', 'Bottom'),
        ],
        required=True,
        default='bottom',
    )

    @api.constrains('image')
    def _check_image_format(self):
        """Block a save when the image is not a PNG or a JPG."""
        for campaign in self:
            if campaign.image and not _image_is_png_or_jpg(campaign.image):
                raise ValidationError(_(
                    'The campaign image must be a PNG or JPG file.'
                ))

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        """Block a backwards range and any inclusive overlap.

        Two ranges overlap when each starts on or before the other ends.
        The message names the campaign that is already saved.
        """
        for campaign in self:
            if not campaign.date_start or not campaign.date_end:
                continue
            if campaign.date_end < campaign.date_start:
                raise ValidationError(_(
                    'The end date must be on or after the start date.'
                ))
            overlap = self.search([
                ('id', '!=', campaign.id),
                ('date_start', '<=', campaign.date_end),
                ('date_end', '>=', campaign.date_start),
            ], limit=1)
            if overlap:
                raise ValidationError(_(
                    'This date range overlaps "%(name)s".',
                    name=overlap.name,
                ))
