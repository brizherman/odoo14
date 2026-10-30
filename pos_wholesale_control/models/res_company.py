# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods,protected-access
"""Company settings for wholesale POS pricing."""
from datetime import datetime, time

from dateutil.relativedelta import relativedelta
import pytz

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare

from .wholesale_pricelist_mapping import CUSTOMER_TYPE_SELECTION


class ResCompany(models.Model):
    """Thresholds and pricelists that decide retail versus wholesale."""

    _inherit = 'res.company'

    wholesale_control_active = fields.Boolean(
        string='Activar control de mayoreo',
        help='Al activarlo, el punto de venta elige la lista de menudeo o de '
             'mayoreo con estas reglas. Los pedidos ya cobrados conservan la '
             'decisión que ya tienen guardada.',
    )
    wholesale_previous_month_min = fields.Monetary(
        string='Mínimo del mes anterior',
        currency_field='currency_id',
        default=800.0,
        help='Compras netas requeridas durante el mes calendario anterior. '
             'El total incluye todas las sucursales.',
    )
    wholesale_current_order_min = fields.Monetary(
        string='Mínimo del pedido actual',
        currency_field='currency_id',
        default=1500.0,
        help='Total a precio de menudeo que califica el pedido actual para '
             'mayoreo cuando el mes anterior no alcanza su mínimo.',
    )
    wholesale_timezone = fields.Selection(
        selection='_wholesale_timezone_selection',
        string='Zona horaria del negocio',
        default='America/Tijuana',
        required=True,
        help='Los meses calendario de la elegibilidad usan esta zona horaria.',
    )
    wholesale_retail_pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Lista de precios de menudeo',
        help='Se usa cuando el cliente no está identificado o no califica. '
             'En Factor Fiesta es la Public Pricelist de la sucursal.',
    )
    wholesale_pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Lista de precios de mayoreo',
        help='Lista de mayoreo que debe estar disponible en todas las cajas '
             'de esta sucursal. En Factor Fiesta es Club Mayorista. '
             'Distribuidores puede usar otra lista en la asignación por tipo.',
    )
    wholesale_mapping_ids = fields.One2many(
        'pos.wholesale.pricelist.mapping',
        'company_id',
        string='Asignaciones por tipo de cliente',
    )
    wholesale_mapping_warning = fields.Text(
        string='Advertencia de configuración de mayoreo',
        compute='_compute_wholesale_mapping_warning',
    )

    @api.model
    def _wholesale_timezone_selection(self):
        return [(timezone, timezone) for timezone in pytz.common_timezones]

    def _wholesale_local_midnight_utc(self, day):
        """Naive UTC instant for midnight on ``day`` in the business timezone.

        A repeated midnight uses the earlier occurrence. A skipped midnight
        uses the first instant that exists after the gap. Month starts share
        this rule, so the three ranges stay contiguous.
        """
        self.ensure_one()
        timezone = pytz.timezone(self.wholesale_timezone)
        midnight = datetime.combine(day, time.min)
        try:
            local_midnight = timezone.localize(midnight, is_dst=None)
        except pytz.AmbiguousTimeError:
            local_midnight = timezone.localize(midnight, is_dst=True)
        except pytz.NonExistentTimeError:
            local_midnight = timezone.localize(midnight, is_dst=False)
        return local_midnight.astimezone(pytz.UTC).replace(tzinfo=None)

    def _wholesale_calendar_months(self, moment_utc=None):
        """Three local calendar months as half-open naive UTC ranges.

        Oldest month first. ``end_utc`` is the next local midnight, so a
        search uses ``date_order >= start_utc`` and ``date_order < end_utc``.
        ``moment_utc`` is a naive UTC instant; omitted means the current UTC time.
        """
        self.ensure_one()
        if moment_utc is None:
            moment_utc = datetime.utcnow().replace(microsecond=0)
        elif moment_utc.tzinfo is not None:
            moment_utc = moment_utc.astimezone(pytz.UTC).replace(tzinfo=None)
        timezone = pytz.timezone(self.wholesale_timezone)
        local_date = moment_utc.replace(tzinfo=pytz.UTC).astimezone(timezone).date()
        current_start = local_date.replace(day=1)
        month_starts = [
            current_start + relativedelta(months=offset)
            for offset in (-2, -1, 0, 1)
        ]
        months = []
        for index, start_day in enumerate(month_starts[:-1]):
            months.append({
                'year': start_day.year,
                'month': start_day.month,
                'is_current': index == 2,
                'start_utc': self._wholesale_local_midnight_utc(start_day),
                'end_utc': self._wholesale_local_midnight_utc(month_starts[index + 1]),
            })
        return months

    @api.depends(
        'wholesale_control_active',
        'wholesale_retail_pricelist_id',
        'wholesale_pricelist_id',
        'wholesale_mapping_ids.customer_type',
        'wholesale_mapping_ids.pricelist_id',
        'wholesale_mapping_ids.active',
    )
    def _compute_wholesale_mapping_warning(self):
        for company in self:
            company.wholesale_mapping_warning = company._wholesale_configuration_warning()

    def _pos_configs(self):
        self.ensure_one()
        return self.env['pos.config'].search([('company_id', '=', self.id)])

    def _pos_pricelists(self, config):
        if config.use_pricelist:
            return config.available_pricelist_ids
        return config.pricelist_id

    def _pricelist_available_on(self, config, pricelist):
        return bool(pricelist) and pricelist in self._pos_pricelists(config)

    def _wholesale_configuration_warning(self):
        """Return administrator warnings. These do not block saving."""
        self.ensure_one()
        messages = []
        retail = self.wholesale_retail_pricelist_id
        wholesale = self.wholesale_pricelist_id
        if retail and retail == wholesale:
            messages.append(_('La lista de menudeo y la lista de mayoreo son la misma.'))
        labels = dict(CUSTOMER_TYPE_SELECTION)
        active_mappings = self.wholesale_mapping_ids.filtered('active')
        mapped_types = set(active_mappings.mapped('customer_type'))
        missing = [
            labels.get(key, key)
            for key, _label in CUSTOMER_TYPE_SELECTION
            if key not in mapped_types
        ]
        if missing:
            messages.append(_(
                'Estos tipos de cliente no tienen una asignación de lista de '
                'precios activa: %(types)s.',
                types=', '.join(missing),
            ))
        configs = self._pos_configs()
        for mapping in active_mappings:
            missing_configs = configs.filtered(
                lambda config, pricelist=mapping.pricelist_id: not self._pricelist_available_on(
                    config, pricelist,
                )
            )
            if missing_configs:
                messages.append(_(
                    '%(pricelist)s (%(customer_type)s) no está disponible en %(configs)s.',
                    pricelist=mapping.pricelist_id.display_name,
                    customer_type=labels.get(mapping.customer_type, mapping.customer_type),
                    configs=', '.join(missing_configs.mapped('name')),
                ))
        return '\n'.join(messages) or False

    @api.constrains('wholesale_timezone')
    def _check_wholesale_timezone(self):
        for company in self:
            if company.wholesale_timezone not in pytz.all_timezones_set:
                raise ValidationError(_(
                    '%(timezone)s no es una zona horaria válida.',
                    timezone=company.wholesale_timezone,
                ))

    @api.constrains(
        'wholesale_control_active',
        'wholesale_previous_month_min',
        'wholesale_current_order_min',
        'wholesale_retail_pricelist_id',
        'wholesale_pricelist_id',
    )
    def _check_wholesale_control_activation(self):
        for company in self:
            company._validate_wholesale_thresholds()
            if company.wholesale_control_active:
                company._validate_wholesale_activation()

    def _threshold_amounts(self):
        self.ensure_one()
        return (
            (self.wholesale_previous_month_min, _('Mínimo del mes anterior')),
            (self.wholesale_current_order_min, _('Mínimo del pedido actual')),
        )

    def _named_pricelists(self):
        self.ensure_one()
        return (
            (self.wholesale_retail_pricelist_id, _('Lista de precios de menudeo')),
            (self.wholesale_pricelist_id, _('Lista de precios de mayoreo')),
        )

    def _validate_wholesale_thresholds(self):
        self.ensure_one()
        rounding = self.currency_id.rounding
        for amount, label in self._threshold_amounts():
            if float_compare(amount, 0.0, precision_rounding=rounding) < 0:
                raise ValidationError(_(
                    '%(label)s no puede ser negativo.',
                    label=label,
                ))

    def _validate_wholesale_activation(self):
        self.ensure_one()
        errors = []
        rounding = self.currency_id.rounding
        for amount, label in self._threshold_amounts():
            if float_compare(amount, 0.0, precision_rounding=rounding) <= 0:
                errors.append(_(
                    '%(label)s debe ser mayor que cero.',
                    label=label,
                ))
        named_lists = self._named_pricelists()
        for pricelist, label in named_lists:
            errors.extend(self._wholesale_pricelist_errors(pricelist, label))
        configs = self._pos_configs()
        if not configs:
            errors.append(_(
                'Esta sucursal no tiene punto de venta, así que el control de '
                'mayoreo no se puede activar.',
            ))
        else:
            for pricelist, label in named_lists:
                if not pricelist:
                    continue
                missing_configs = configs.filtered(
                    lambda config, current=pricelist: not self._pricelist_available_on(
                        config, current,
                    )
                )
                if missing_configs:
                    errors.append(_(
                        '%(label)s "%(pricelist)s" no está disponible en %(configs)s.',
                        label=label,
                        pricelist=pricelist.display_name,
                        configs=', '.join(missing_configs.mapped('name')),
                    ))
        if errors:
            raise ValidationError('\n'.join(errors))

    def _wholesale_pricelist_errors(self, pricelist, label):
        self.ensure_one()
        if not pricelist:
            return [_(
                '%(label)s es obligatorio antes de activar el control de mayoreo.',
                label=label,
            )]
        errors = []
        if pricelist.company_id and pricelist.company_id != self:
            errors.append(_(
                '%(label)s "%(pricelist)s" pertenece a otra sucursal.',
                label=label,
                pricelist=pricelist.display_name,
            ))
        if pricelist.currency_id != self.currency_id:
            errors.append(_(
                '%(label)s "%(pricelist)s" usa %(pricelist_currency)s. '
                'Esta sucursal usa %(company_currency)s.',
                label=label,
                pricelist=pricelist.display_name,
                pricelist_currency=pricelist.currency_id.name,
                company_currency=self.currency_id.name,
            ))
        if not pricelist.active:
            errors.append(_(
                '%(label)s "%(pricelist)s" está archivada.',
                label=label,
                pricelist=pricelist.display_name,
            ))
        return errors
