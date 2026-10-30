# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods,protected-access
"""Trusted wholesale eligibility for POS pricing."""
import logging
import math
from datetime import datetime

import pytz
from babel.core import UnknownLocaleError
from babel.dates import format_date

from odoo import _, api, fields, models
from odoo.exceptions import AccessError
from odoo.tools.float_utils import float_compare

_logger = logging.getLogger(__name__)

# Same qualifying states as Alta Mayoristas. Draft, cancelled, and unpaid
# orders are excluded because they are not in these lists.
POS_ORDER_STATES = ('paid', 'done', 'invoiced')
SALE_ORDER_STATES = ('sale', 'done')
# Odoo names a POS refund "{original} REFUND". The Spanish translation of
# that suffix is "REEMBOLSO", without the leading space.
POS_REFUND_SUFFIXES = (' REFUND', ' REEMBOLSO', 'REEMBOLSO')


class ResPartner(models.Model):
    """Calendar-month purchase totals used to decide wholesale pricing."""

    _inherit = 'res.partner'

    @api.model
    def get_wholesale_eligibility(self, partner_id=False, company_id=False,
                                  retail_order_amount=0.0, config_id=False):
        """Return the trusted retail or wholesale decision for one POS order.

        ``automatic_decision`` is ``wholesale`` only when ``error`` is false.
        A configuration block can leave ``reason_code`` on the rule that
        matched and still force retail. ``retail_order_amount`` is the live
        retail-priced total from the cashier. Payment must recalculate it.
        """
        company = self._wholesale_eligibility_company(company_id)
        config = self._wholesale_eligibility_config(company, config_id)
        retail_amount = self._wholesale_rounded(company.currency_id, retail_order_amount)
        partner = self._wholesale_eligibility_partner(partner_id)
        facts = {
            'company': company,
            'partner': partner,
            'config': config,
            'months': [],
            'retail_amount': retail_amount,
            'decision': 'retail',
            'reason_code': 'no_identified_customer',
        }
        if not partner:
            return self._wholesale_eligibility_response(facts)
        try:
            facts['months'] = partner._wholesale_monthly_totals(company)
        except Exception:  # pylint: disable=broad-except
            # Any history failure stays on retail. The cashier may continue
            # only with an audited manager override, which is checked later.
            _logger.exception(
                'Wholesale history failed for partner %s on company %s',
                partner.id, company.id,
            )
            facts['reason_code'] = 'history_unavailable'
            return self._wholesale_eligibility_response(facts)
        facts['decision'], facts['reason_code'] = self._wholesale_price_decision(
            company,
            self._wholesale_previous_month_amount(facts['months']),
            retail_amount,
        )
        return self._wholesale_eligibility_response(facts)

    def _wholesale_monthly_totals(self, company, moment_utc=None):
        """Three local calendar months of net sales, oldest first.

        Every company is included on purpose: the store where the customer
        buys now does not limit the total. sudo() is required so company
        record rules on pos.order and sale.order do not hide other
        sucursales. The result is month amounts, not orders.

        Each row has label, year, month, amount, and is_current. The current
        row is month-to-date because its range ends at the next local midnight
        and later dates have no orders yet.
        """
        self.ensure_one()
        company.ensure_one()
        months = company._wholesale_calendar_months(moment_utc)
        amounts = dict((index, 0.0) for index in range(len(months)))
        if isinstance(self.id, int) and months:
            window_start = months[0]['start_utc']
            window_end = months[-1]['end_utc']
            self._wholesale_add_order_totals(
                amounts, months, 'pos.order', POS_ORDER_STATES,
            )
            self._wholesale_add_order_totals(
                amounts, months, 'sale.order', SALE_ORDER_STATES,
            )
            self._wholesale_add_pos_refunds(amounts, months, window_start, window_end)
            self._wholesale_add_sale_credit_notes(
                amounts, months, window_start, window_end,
            )
        return self._wholesale_month_rows(company, amounts, months)

    def _wholesale_month_rows(self, company, amounts, months):
        currency = company.currency_id
        rows = []
        for index, month in enumerate(months):
            amount = amounts[index]
            if currency:
                amount = currency.round(amount)
            rows.append({
                'label': self._wholesale_month_label(month['year'], month['month']),
                'year': month['year'],
                'month': month['month'],
                'amount': amount,
                'is_current': month['is_current'],
            })
        return rows

    def _wholesale_month_label(self, year, month):
        lang = self.env.context.get('lang') or self.env.user.lang or 'es_MX'
        month_start = datetime(year, month, 1)
        try:
            return format_date(month_start, 'MMMM yyyy', locale=lang)
        except (UnknownLocaleError, ValueError):
            return format_date(month_start, 'MMMM yyyy', locale='es_MX')

    def _wholesale_add_order_totals(self, amounts, months, model_name, states):
        """Add read_group sums for one model. No company filter.

        POS refunds stay out of this sum and are applied later to the
        original sale month. Sales orders have no matching name suffix.
        """
        if model_name not in self.env:
            return
        for index, month in enumerate(months):
            domain = [
                ('partner_id', '=', self.id),
                ('state', 'in', list(states)),
                ('date_order', '>=', month['start_utc']),
                ('date_order', '<', month['end_utc']),
            ]
            if model_name == 'pos.order':
                domain.extend(self._wholesale_exclude_refund_domain())
            amounts[index] += self._wholesale_grouped_amount(model_name, domain)

    def _wholesale_grouped_amount(self, model_name, domain):
        groups = self.env[model_name].sudo().read_group(
            domain,
            ['amount_total:sum'],
            ['partner_id'],
            lazy=False,
        )
        total = 0.0
        for group in groups:
            total += group.get('amount_total') or 0.0
        return total

    def _wholesale_pos_refund_suffixes(self):
        suffixes = list(POS_REFUND_SUFFIXES)
        translated = _(' REFUND')
        if translated and translated not in suffixes:
            suffixes.append(translated)
        return suffixes

    def _wholesale_exclude_refund_domain(self):
        return [
            ('name', 'not ilike', suffix)
            for suffix in self._wholesale_pos_refund_suffixes()
        ]

    def _wholesale_refund_match_domain(self):
        leaves = [
            ('name', 'ilike', suffix)
            for suffix in self._wholesale_pos_refund_suffixes()
        ]
        if len(leaves) <= 1:
            return leaves
        return (['|'] * (len(leaves) - 1)) + leaves

    def _wholesale_strip_refund_suffix(self, name):
        if not name:
            return False
        suffixes = sorted(self._wholesale_pos_refund_suffixes(), key=len, reverse=True)
        for suffix in suffixes:
            if name.endswith(suffix):
                original = name[:-len(suffix)].rstrip()
                return original or False
        return False

    def _wholesale_add_pos_refunds(self, amounts, months, window_start, window_end):
        """Move a POS refund onto the original sale month.

        Odoo 14 dates the refund now and stores no link to the original.
        The negative amount_total is applied to the original date_order.
        Only refund orders are read; the qualifying sales stay in read_group.
        """
        if 'pos.order' not in self.env or not window_start or not window_end:
            return
        refunds = self.env['pos.order'].sudo().search(
            [
                ('partner_id', '=', self.id),
                ('state', 'in', list(POS_ORDER_STATES)),
                ('amount_total', '<', 0),
            ] + self._wholesale_refund_match_domain()
        )
        originals = self._wholesale_pos_refund_originals(refunds)
        for refund in refunds:
            original = originals.get(refund.id)
            if not original:
                continue
            index = self._wholesale_month_index(original.date_order, months)
            if index is None:
                continue
            amounts[index] += refund.amount_total

    def _wholesale_pos_refund_originals(self, refunds):
        """Map refund id to the original paid order, when one is found."""
        originals = {}
        if not refunds:
            return originals
        pos_order = self.env['pos.order'].sudo()
        names = []
        original_name_by_refund = {}
        for refund in refunds:
            original_name = self._wholesale_strip_refund_suffix(refund.name)
            if not original_name:
                continue
            names.append(original_name)
            original_name_by_refund[refund.id] = original_name
        by_name = {}
        if names:
            for order in pos_order.search([
                ('partner_id', '=', self.id),
                ('state', 'in', list(POS_ORDER_STATES)),
                ('name', 'in', names),
            ]):
                by_name.setdefault(order.name, pos_order.browse())
                by_name[order.name] |= order
        unmatched = self.env['pos.order']
        for refund in refunds:
            candidates = by_name.get(original_name_by_refund.get(refund.id), pos_order.browse())
            picked = self._wholesale_pick_refund_original(refund, candidates)
            if picked:
                originals[refund.id] = picked
            else:
                unmatched |= refund
        originals.update(self._wholesale_refund_originals_by_receipt(unmatched, refunds))
        return originals

    def _wholesale_pick_refund_original(self, refund, candidates):
        if refund.pos_reference and len(candidates) > 1:
            same_receipt = candidates.filtered(
                lambda order, receipt=refund.pos_reference: order.pos_reference == receipt
            )
            if same_receipt:
                candidates = same_receipt
        if not candidates:
            return self.env['pos.order']
        return candidates.sorted(key=lambda order: (order.date_order, order.id))[:1]

    def _wholesale_refund_originals_by_receipt(self, unmatched, refunds):
        originals = {}
        references = [reference for reference in unmatched.mapped('pos_reference') if reference]
        if not references:
            return originals
        by_receipt = self.env['pos.order'].sudo().search([
            ('partner_id', '=', self.id),
            ('state', 'in', list(POS_ORDER_STATES)),
            ('pos_reference', 'in', references),
            ('id', 'not in', refunds.ids),
        ] + self._wholesale_exclude_refund_domain())
        for refund in unmatched:
            if not refund.pos_reference:
                continue
            candidates = by_receipt.filtered(
                lambda order, receipt=refund.pos_reference: order.pos_reference == receipt
            )
            picked = self._wholesale_pick_refund_original(refund, candidates)
            if picked:
                originals[refund.id] = picked
        return originals

    def _wholesale_add_sale_credit_notes(self, amounts, months, window_start, window_end):
        """Subtract posted sales credit notes from the original sale month.

        sale.order.amount_total stays unchanged when a credit note is posted.
        POS credit notes are not subtracted here: the negative POS refund
        already represents that return.
        """
        move_line = self.env['account.move.line']
        if 'sale_line_ids' not in move_line._fields or not window_start or not window_end:
            return
        lines = move_line.sudo().search([
            ('move_id.move_type', '=', 'out_refund'),
            ('move_id.state', '=', 'posted'),
            ('exclude_from_invoice_tab', '=', False),
            ('display_type', '=', False),
            ('sale_line_ids.order_id.partner_id', '=', self.id),
            ('sale_line_ids.order_id.state', 'in', list(SALE_ORDER_STATES)),
            ('sale_line_ids.order_id.date_order', '>=', window_start),
            ('sale_line_ids.order_id.date_order', '<', window_end),
        ])
        for line in lines:
            index = self._wholesale_credit_note_month_index(line, months)
            if index is None:
                continue
            amounts[index] -= abs(line.price_total or 0.0)

    def _wholesale_credit_note_month_index(self, line, months):
        dated = []
        orders = line.sale_line_ids.order_id.filtered(
            lambda order: order.partner_id.id == self.id and order.state in SALE_ORDER_STATES
        )
        for order in orders:
            index = self._wholesale_month_index(order.date_order, months)
            if index is not None:
                dated.append((order.date_order, order.id, index))
        if not dated:
            return None
        dated.sort()
        return dated[0][2]

    def _wholesale_month_index(self, value, months):
        moment = value if isinstance(value, datetime) else fields.Datetime.to_datetime(value)
        if not moment:
            return None
        if moment.tzinfo is not None:
            moment = moment.astimezone(pytz.UTC).replace(tzinfo=None)
        for index, month in enumerate(months):
            if month['start_utc'] <= moment < month['end_utc']:
                return index
        return None

    def _wholesale_record_id(self, value):
        """Return a database id. Virtual, empty, and boolean values do not count."""
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return False
        return value

    def _wholesale_eligibility_company(self, company_id):
        """The register company, limited to companies this POS user may use."""
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_(
                'Solo usuarios de Punto de Venta pueden consultar '
                'la elegibilidad de mayoreo.'
            ))
        record_id = self._wholesale_record_id(company_id)
        company = self.env['res.company']
        if record_id:
            company = company.browse(record_id).exists()
        if not company or company not in self.env.companies:
            raise AccessError(_('No puede consultar la elegibilidad de esta sucursal.'))
        return company

    def _wholesale_eligibility_config(self, company, config_id):
        """The current register, when the POS sends one."""
        if not config_id:
            return self.env['pos.config']
        record_id = self._wholesale_record_id(config_id)
        if not record_id:
            raise AccessError(_('La caja del punto de venta no es válida.'))
        config = self.env['pos.config'].browse(record_id)
        config.check_access_rights('read')
        config.check_access_rule('read')
        config = config.exists()
        if not config or config.company_id != company:
            raise AccessError(_('La caja no pertenece a esta sucursal.'))
        return config

    def _wholesale_eligibility_partner(self, partner_id):
        """The selected customer, or an empty record when nobody is identified.

        A deleted id is unidentified. A customer hidden by record rules raises,
        so a missing customer is not used to hide a forbidden one.
        """
        self.check_access_rights('read')
        record_id = self._wholesale_record_id(partner_id)
        if not record_id:
            return self.browse()
        partner = self.browse(record_id).exists()
        if not partner:
            return self.browse()
        partner.check_access_rule('read')
        return partner

    def _wholesale_coerce_amount(self, amount):
        try:
            value = float(amount or 0.0)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(value):
            return 0.0
        return value

    def _wholesale_rounded(self, currency, amount):
        amount = self._wholesale_coerce_amount(amount)
        if currency:
            return currency.round(amount)
        return amount

    def _wholesale_previous_month_amount(self, months):
        """Amount for the month immediately before the current month-to-date row."""
        for index, month in enumerate(months):
            if month.get('is_current') and index:
                return months[index - 1].get('amount') or 0.0
        return 0.0

    def _wholesale_price_decision(self, company, previous_amount, retail_amount):
        """Previous month wins. The current order is checked only when it does not."""
        currency = company.currency_id
        rounding = currency.rounding or 0.01
        previous_amount = self._wholesale_rounded(currency, previous_amount)
        retail_amount = self._wholesale_rounded(currency, retail_amount)
        previous_min = self._wholesale_rounded(currency, company.wholesale_previous_month_min)
        current_min = self._wholesale_rounded(currency, company.wholesale_current_order_min)
        if float_compare(previous_amount, previous_min, precision_rounding=rounding) >= 0:
            return 'wholesale', 'previous_month'
        if float_compare(retail_amount, current_min, precision_rounding=rounding) >= 0:
            return 'wholesale', 'current_order'
        return 'retail', 'below_threshold'

    def _wholesale_list_for_decision(self, company, partner, decision):
        """Retail list, or the customer-type wholesale list when the order qualifies."""
        if decision != 'wholesale':
            return company.wholesale_retail_pricelist_id
        customer_type = partner.customer_type if partner else False
        mapping = self._wholesale_type_mapping(company, customer_type)
        if mapping:
            return mapping.pricelist_id
        return company.wholesale_pricelist_id

    def _wholesale_type_mapping(self, company, customer_type):
        if not customer_type:
            return self.env['pos.wholesale.pricelist.mapping']
        return company.wholesale_mapping_ids.filtered(
            lambda mapping: mapping.customer_type == customer_type and mapping.active
        )[:1]

    def _wholesale_list_usable(self, company, config, pricelist):
        """A list can be applied when it is active and, if a register is known, on that register."""
        if not pricelist or not pricelist.active:
            return False
        if not config:
            return True
        return company._pricelist_available_on(config, pricelist)

    def _wholesale_unusable_list_message(self, pricelist, wholesale):
        if not pricelist:
            if wholesale:
                return _(
                    'No hay lista de mayoreo para este cliente. El pedido queda en menudeo.'
                )
            return _('No hay lista de menudeo configurada para esta sucursal.')
        if not pricelist.active:
            return _(
                'La lista "%(pricelist)s" está archivada. El pedido queda en menudeo.',
                pricelist=pricelist.display_name,
            )
        return _(
            'La lista "%(pricelist)s" no está disponible en esta caja. '
            'El pedido queda en menudeo.',
            pricelist=pricelist.display_name,
        )

    def _wholesale_guard_decision(self, facts):
        """Keep wholesale only when that list can actually be applied."""
        company = facts['company']
        config = facts['config']
        decision = facts['decision']
        reason_code = facts['reason_code']
        retail_list = company.wholesale_retail_pricelist_id
        expected = self._wholesale_list_for_decision(company, facts['partner'], decision)
        retail_ok = self._wholesale_list_usable(company, config, retail_list)
        fallback = retail_list if retail_ok else self.env['product.pricelist']
        closed = reason_code in ('no_identified_customer', 'history_unavailable')
        if closed or decision != 'wholesale':
            message = False
            if not retail_ok:
                message = self._wholesale_unusable_list_message(retail_list, False)
            return 'retail', fallback, message
        if not self._wholesale_list_usable(company, config, expected):
            if retail_ok:
                message = self._wholesale_unusable_list_message(expected, True)
            else:
                message = self._wholesale_unusable_list_message(retail_list, False)
            return 'retail', fallback, message
        if not company.wholesale_control_active:
            message = _('El control de mayoreo no está activo en esta sucursal.')
            if not retail_ok:
                message = self._wholesale_unusable_list_message(retail_list, False)
            return 'retail', fallback, message
        return 'wholesale', expected, False

    def _wholesale_reason_text(self, reason_code):
        texts = {
            'previous_month': _('El mes anterior alcanza el mínimo de mayoreo.'),
            'current_order': _(
                'El pedido actual, a precio de menudeo, alcanza el mínimo de mayoreo.'
            ),
            'below_threshold': _(
                'Ni el mes anterior ni este pedido alcanzan el mínimo de mayoreo.'
            ),
            'no_identified_customer': _(
                'Seleccione un cliente para evaluar el precio de mayoreo.'
            ),
            'history_unavailable': _(
                'No se pudo consultar el historial de compras. El pedido queda en menudeo.'
            ),
        }
        return texts.get(reason_code, '')

    def _wholesale_response_error(self, reason_code, guard_error):
        if reason_code == 'history_unavailable':
            return self._wholesale_reason_text(reason_code)
        return guard_error or False

    def _wholesale_response_reason_text(self, reason_code, error):
        """Show the block when configuration, not the customer rule, forced retail."""
        if error and reason_code not in ('no_identified_customer', 'history_unavailable'):
            return error
        return self._wholesale_reason_text(reason_code)

    def _wholesale_pricelist_payload(self, pricelist):
        if not pricelist:
            return False
        return {'id': pricelist.id, 'name': pricelist.display_name}

    def _wholesale_currency_payload(self, currency):
        if not currency:
            return False
        return {
            'id': currency.id,
            'name': currency.name,
            'symbol': currency.symbol,
            'rounding': currency.rounding,
        }

    def _wholesale_eligibility_response(self, facts):
        """Build the eligibility contract returned to the POS."""
        company = facts['company']
        partner = facts['partner']
        months = facts['months']
        reason_code = facts['reason_code']
        decision, expected, guard_error = self._wholesale_guard_decision(facts)
        error = self._wholesale_response_error(reason_code, guard_error)
        currency = company.currency_id
        return {
            'customer_id': partner.id if partner else False,
            'customer_type': partner.customer_type if partner else False,
            'months': months,
            'previous_month_amount': self._wholesale_rounded(
                currency, self._wholesale_previous_month_amount(months),
            ),
            'previous_month_min': self._wholesale_rounded(
                currency, company.wholesale_previous_month_min,
            ),
            'current_order_min': self._wholesale_rounded(
                currency, company.wholesale_current_order_min,
            ),
            'retail_order_amount': self._wholesale_rounded(currency, facts['retail_amount']),
            'automatic_decision': decision,
            'reason_code': reason_code,
            'reason_text': self._wholesale_response_reason_text(reason_code, error),
            'retail_pricelist': self._wholesale_pricelist_payload(
                company.wholesale_retail_pricelist_id,
            ),
            'expected_pricelist': self._wholesale_pricelist_payload(expected),
            'timezone': company.wholesale_timezone,
            'currency': self._wholesale_currency_payload(currency),
            'error': error or False,
        }
