# -*- coding: utf-8 -*-
"""Validation helpers for SAT download date ranges."""
from odoo import _, fields
from odoo.exceptions import ValidationError


def validate_download_date_range(recordset, date_from, date_to):
    """Ensure a SAT download range is valid and within one calendar month."""
    if not date_from or not date_to:
        return

    if date_from >= date_to:
        raise ValidationError(_('La fecha inicial debe ser anterior a la fecha final.'))

    delta = date_to - date_from
    if delta.total_seconds() < 2:
        raise ValidationError(_('El SAT requiere un rango de fechas de al menos 2 segundos.'))

    from_local = fields.Datetime.context_timestamp(recordset, date_from)
    to_local = fields.Datetime.context_timestamp(recordset, date_to)
    if from_local.year != to_local.year or from_local.month != to_local.month:
        raise ValidationError(_(
            'El rango de fechas debe estar dentro del mismo mes calendario.'
        ))
