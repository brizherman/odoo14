# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods,protected-access
"""Trusted pricing snapshot stored when a POS order is paid."""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .pos_wholesale_override import DECISION_SELECTION, REASON_SELECTION

WHOLESALE_SNAPSHOT_FIELDS = frozenset([
    'wholesale_automatic_decision',
    'wholesale_final_decision',
    'wholesale_reason_code',
    'wholesale_reason_text',
    'wholesale_retail_amount',
    'wholesale_previous_month_amount',
    'wholesale_previous_month_min',
    'wholesale_current_order_min',
    'wholesale_timezone',
    'wholesale_applied_pricelist_id',
    'wholesale_override_id',
    'wholesale_has_override',
])


class PosOrder(models.Model):
    """Reject a paid order whose pricelist is not the trusted decision."""

    _inherit = 'pos.order'

    wholesale_automatic_decision = fields.Selection(
        selection=DECISION_SELECTION,
        string='Decisión automática',
        readonly=True,
        copy=False,
    )
    wholesale_final_decision = fields.Selection(
        selection=DECISION_SELECTION,
        string='Decisión final',
        readonly=True,
        copy=False,
    )
    wholesale_reason_code = fields.Selection(
        selection=REASON_SELECTION,
        string='Código del motivo',
        readonly=True,
        copy=False,
    )
    wholesale_reason_text = fields.Text(
        string='Motivo',
        readonly=True,
        copy=False,
    )
    wholesale_retail_amount = fields.Monetary(
        string='Total a precio de menudeo',
        currency_field='currency_id',
        readonly=True,
        copy=False,
    )
    wholesale_previous_month_amount = fields.Monetary(
        string='Compras del mes anterior',
        currency_field='currency_id',
        readonly=True,
        copy=False,
    )
    wholesale_previous_month_min = fields.Monetary(
        string='Mínimo del mes anterior',
        currency_field='currency_id',
        readonly=True,
        copy=False,
    )
    wholesale_current_order_min = fields.Monetary(
        string='Mínimo del pedido actual',
        currency_field='currency_id',
        readonly=True,
        copy=False,
    )
    wholesale_timezone = fields.Char(
        string='Zona horaria',
        readonly=True,
        copy=False,
    )
    wholesale_applied_pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Lista aplicada',
        readonly=True,
        copy=False,
    )
    wholesale_override_id = fields.Many2one(
        'pos.wholesale.override',
        string='Excepción de gerente',
        readonly=True,
        copy=False,
    )
    wholesale_has_override = fields.Boolean(
        string='Excepción de gerente',
        readonly=True,
        copy=False,
        help='Indica que un gerente autorizó la lista de este ticket. '
             'No cambia el tipo de cliente ni las compras de los meses siguientes.',
    )

    @api.model
    def _order_fields(self, ui_order):
        """Keep only the snapshot this server just calculated.

        Values under the same names in the cashier payload are ignored.
        ``_wholesale_trusted`` is set by the payment check, not by the client.
        """
        vals = super()._order_fields(ui_order)
        trusted = ui_order.get('_wholesale_trusted')
        if trusted:
            vals.update(trusted)
        return vals

    @api.model
    def _process_order(self, order, draft, existing_order):
        data = order.get('data') or {}
        prepared = None
        if draft:
            if isinstance(data, dict):
                data.pop('_wholesale_trusted', None)
        else:
            prepared = self._wholesale_prepare_payment(data, existing_order)
        checker = self.with_context(wholesale_snapshot_write=bool(prepared))
        return checker._wholesale_finish_order(
            order, draft, existing_order, prepared,
        )

    def _wholesale_finish_order(self, order, draft, existing_order, prepared):
        """Save the order with the payment snapshot, then link its exception.

        The draft being updated is a different recordset from self. The
        snapshot write has to travel with that record, not only with self.
        """
        if existing_order and prepared:
            existing_order = existing_order.with_context(wholesale_snapshot_write=True)
        paid = super()._process_order(order, draft, existing_order)
        if prepared and prepared.get('override'):
            self.browse(paid)._wholesale_link_override(prepared['override'])
        return paid

    def _export_for_ui(self, order):
        result = super()._export_for_ui(order)
        result.update({
            'wholesale_automatic_decision': order.wholesale_automatic_decision,
            'wholesale_final_decision': order.wholesale_final_decision,
            'wholesale_reason_code': order.wholesale_reason_code,
            'wholesale_reason_text': order.wholesale_reason_text,
            'wholesale_retail_amount': order.wholesale_retail_amount,
            'wholesale_previous_month_amount': order.wholesale_previous_month_amount,
            'wholesale_previous_month_min': order.wholesale_previous_month_min,
            'wholesale_current_order_min': order.wholesale_current_order_min,
            'wholesale_timezone': order.wholesale_timezone,
            'wholesale_applied_pricelist_id': order.wholesale_applied_pricelist_id.id,
            'wholesale_override_id': order.wholesale_override_id.id,
            'wholesale_has_override': order.wholesale_has_override,
        })
        return result

    @api.model_create_multi
    def create(self, vals_list):
        """Reject a snapshot that did not come from the payment check."""
        if not isinstance(vals_list, list):
            vals_list = [vals_list]
        if any(self._wholesale_snapshot_keys(vals) for vals in vals_list):
            self._wholesale_check_snapshot_write(self.browse())
        return super().create(vals_list)

    def write(self, vals):
        """Reject a snapshot change that did not come from the payment check."""
        if self._wholesale_snapshot_keys(vals):
            self._wholesale_check_snapshot_write(self)
        return super().write(vals)

    def unlink(self):
        """Keep a paid order once it stores a wholesale decision."""
        locked = self.filtered(
            lambda order: order.wholesale_final_decision and order.state != 'draft'
        )
        if locked:
            raise UserError(_(
                'No se puede borrar un pedido cobrado que ya tiene decisión de mayoreo.'
            ))
        return super().unlink()

    @api.model
    def _wholesale_prepare_payment(self, ui_order, existing_order):
        """Recalculate the decision and reject a pricelist that does not match.

        Returns None when this company has not activated the control, so the
        register keeps its current behavior. Client snapshot keys are removed
        in every case.
        """
        if not isinstance(ui_order, dict):
            raise UserError(_('El pedido enviado por la caja no es válido.'))
        ui_order.pop('_wholesale_trusted', None)
        facts = self._wholesale_payment_facts(ui_order)
        if not facts:
            return None
        decision = self._wholesale_payment_decision(facts, ui_order, existing_order)
        ui_order['_wholesale_trusted'] = self._wholesale_trusted_vals(facts, decision)
        return {'override': decision['override']}

    @api.model
    def _wholesale_payment_facts(self, ui_order):
        """Session, customer, retail total, and eligibility for one payload."""
        session = self._wholesale_session(ui_order)
        company = session.company_id
        if not company.wholesale_control_active:
            return None
        partner = self.env['res.partner']._wholesale_eligibility_partner(
            ui_order.get('partner_id'),
        )
        fiscal_position = self._wholesale_fiscal_position(ui_order, company)
        retail_amount = self._wholesale_retail_amount(
            company, partner, fiscal_position, ui_order.get('lines'),
        )
        return {
            'company': company,
            'partner': partner,
            'pos_uid': self._wholesale_pos_uid(ui_order),
            'eligibility': self.env['res.partner'].get_wholesale_eligibility(
                partner.id if partner else False,
                company.id,
                retail_amount,
                session.config_id.id,
            ),
        }

    @api.model
    def _wholesale_payment_decision(self, facts, ui_order, existing_order):
        """Expected list, or the list stored on this ticket's exception."""
        submitted_id = self.env['res.partner']._wholesale_record_id(
            ui_order.get('pricelist_id'),
        )
        override = self._wholesale_find_override(facts['pos_uid'], facts['company'])
        eligibility = facts['eligibility']
        if override:
            self._wholesale_check_override(
                override, facts['partner'], submitted_id, existing_order,
            )
            return {
                'override': override,
                'final_decision': override.final_decision,
                'applied_id': override.applied_pricelist_id.id,
            }
        expected = eligibility.get('expected_pricelist') or {}
        applied_id = expected.get('id')
        if not applied_id or submitted_id != applied_id:
            self._wholesale_raise_mismatch(eligibility)
        return {
            'override': override,
            'final_decision': eligibility['automatic_decision'],
            'applied_id': applied_id,
        }

    @api.model
    def _wholesale_trusted_vals(self, facts, decision):
        """Snapshot written on the order. Client copies of these keys are ignored."""
        eligibility = facts['eligibility']
        override = decision['override']
        return {
            'wholesale_automatic_decision': eligibility['automatic_decision'],
            'wholesale_final_decision': decision['final_decision'],
            'wholesale_reason_code': eligibility['reason_code'],
            'wholesale_reason_text': eligibility['reason_text'],
            'wholesale_retail_amount': eligibility['retail_order_amount'],
            'wholesale_previous_month_amount': eligibility['previous_month_amount'],
            'wholesale_previous_month_min': eligibility['previous_month_min'],
            'wholesale_current_order_min': eligibility['current_order_min'],
            'wholesale_timezone': eligibility['timezone'],
            'wholesale_applied_pricelist_id': decision['applied_id'],
            'wholesale_override_id': override.id if override else False,
            'wholesale_has_override': bool(override),
        }

    def _wholesale_link_override(self, override):
        self.ensure_one()
        override._wholesale_link(self)

    @api.model
    def _wholesale_session(self, ui_order):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_(
                'Solo usuarios de Punto de Venta pueden registrar un pedido.'
            ))
        session_id = self.env['res.partner']._wholesale_record_id(
            ui_order.get('pos_session_id'),
        )
        if not session_id:
            raise UserError(_('La sesión de punto de venta no es válida.'))
        session = self.env['pos.session'].browse(session_id)
        session.check_access_rights('read')
        session.check_access_rule('read')
        session = session.exists()
        if not session:
            raise UserError(_('La sesión de punto de venta no es válida.'))
        return session

    @api.model
    def _wholesale_pos_uid(self, ui_order):
        name = ui_order.get('name')
        pos_uid = name.strip() if isinstance(name, str) else ''
        if not pos_uid:
            raise UserError(_('El ticket no tiene folio.'))
        return pos_uid

    @api.model
    def _wholesale_fiscal_position(self, ui_order, company):
        position_id = self.env['res.partner']._wholesale_record_id(
            ui_order.get('fiscal_position_id'),
        )
        if not position_id:
            return self.env['account.fiscal.position']
        position = self.env['account.fiscal.position'].browse(position_id)
        position.check_access_rights('read')
        position.check_access_rule('read')
        position = position.exists()
        if not position or (position.company_id and position.company_id != company):
            raise UserError(_('La posición fiscal no pertenece a esta sucursal.'))
        return position

    @api.model
    def _wholesale_retail_amount(self, company, partner, fiscal_position, lines):
        """Retail total from the retail list, keeping discount and tax.

        The unit price in the payload is not used. A negative discount is
        treated as zero so a modified client cannot inflate this total.
        """
        pricelist = company.wholesale_retail_pricelist_id
        currency = company.currency_id
        if not pricelist:
            return 0.0
        if pricelist.currency_id != currency:
            raise UserError(_(
                'La lista de menudeo "%(pricelist)s" no usa la moneda de la sucursal.',
                pricelist=pricelist.display_name,
            ))
        pricing = {
            'company': company,
            'partner': partner,
            'fiscal_position': fiscal_position,
            'pricelist': pricelist,
            'currency': currency,
        }
        total = 0.0
        for line in self._wholesale_iter_lines(lines):
            total += self._wholesale_line_retail_total(pricing, line)
        if currency:
            return currency.round(total)
        return total

    @api.model
    def _wholesale_line_retail_total(self, pricing, line):
        """Tax-included retail amount for one payload line."""
        company = pricing['company']
        partner = pricing['partner']
        product_id = self.env['res.partner']._wholesale_record_id(line.get('product_id'))
        if not product_id:
            return 0.0
        product = self.env['product.product'].browse(product_id).exists()
        if not product:
            return 0.0
        quantity = self.env['res.partner']._wholesale_coerce_amount(line.get('qty'))
        if not quantity:
            return 0.0
        discount = self._wholesale_discount(line.get('discount'))
        price = pricing['pricelist'].get_product_price(
            product, abs(quantity), partner or False,
        )
        taxes = product.taxes_id.filtered(
            lambda tax, current=company: tax.company_id == current
        )
        fiscal_position = pricing['fiscal_position']
        if fiscal_position:
            taxes = fiscal_position.map_tax(taxes, product, partner or False)
        price = self.env['account.tax']._fix_tax_included_price_company(
            price, product.taxes_id, taxes, company,
        )
        discounted = price * (1.0 - discount / 100.0)
        totals = taxes.compute_all(
            discounted,
            pricing['currency'],
            quantity,
            product=product,
            partner=partner or False,
        )
        return totals['total_included']

    @api.model
    def _wholesale_discount(self, value):
        discount = self.env['res.partner']._wholesale_coerce_amount(value)
        if discount < 0.0:
            return 0.0
        if discount > 100.0:
            return 100.0
        return discount

    @api.model
    def _wholesale_iter_lines(self, lines):
        if not lines:
            return
        for line in lines:
            data = line
            if isinstance(line, (list, tuple)):
                if len(line) < 3 or line[0] not in (0, 1) or not isinstance(line[2], dict):
                    continue
                data = line[2]
            if isinstance(data, dict):
                yield data

    @api.model
    def _wholesale_find_override(self, pos_uid, company):
        """Find the ticket exception, including one stored for another company.

        sudo() is required so a record rule cannot hide an existing folio.
        A hidden row would let the same folio be authorized twice.
        """
        override = self.env['pos.wholesale.override'].sudo().search([
            ('pos_uid', '=', pos_uid),
        ], limit=1)
        if override and override.company_id != company:
            raise UserError(_(
                'El folio de este ticket ya tiene una excepción en otra sucursal.'
            ))
        return override

    @api.model
    def _wholesale_check_override(self, override, partner, submitted_id, existing_order):
        if override.partner_id != partner:
            raise UserError(_(
                'La excepción de mayoreo es para otro cliente. '
                'Seleccione de nuevo al cliente o abra un ticket nuevo.'
            ))
        manager_user = override.manager_user_id
        manager_active = override.manager_employee_id.active
        if not manager_active or not manager_user or not manager_user.active:
            raise UserError(_('El gerente que autorizó esta excepción ya no puede usarse.'))
        if not manager_user.has_group('point_of_sale.group_pos_manager'):
            raise UserError(_(
                'El gerente que autorizó esta excepción ya no tiene ese permiso.'
            ))
        pricelist = override.applied_pricelist_id
        if not pricelist or not pricelist.active or pricelist.id != submitted_id:
            raise UserError(_(
                'Este ticket tiene una excepción para la lista "%(pricelist)s". '
                'Use esa lista o abra un ticket nuevo.',
                pricelist=pricelist.display_name if pricelist else _('sin lista'),
            ))
        linked = override.pos_order_id
        if linked and (not existing_order or linked != existing_order):
            raise UserError(_(
                'Esta excepción ya se usó en el pedido %(order)s.',
                order=linked.display_name,
            ))

    @api.model
    def _wholesale_raise_mismatch(self, eligibility):
        expected = eligibility.get('expected_pricelist') or {}
        if not expected.get('id'):
            raise UserError(
                eligibility.get('error')
                or eligibility.get('reason_text')
                or _('No hay una lista de precios válida para cobrar este pedido.')
            )
        reason = eligibility.get('reason_text') or eligibility.get('error') or ''
        if eligibility.get('reason_code') == 'history_unavailable':
            reason = _(
                '%(reason)s Para cobrar en mayoreo se necesita una excepción de gerente.',
                reason=reason,
            )
        raise UserError(_(
            'No se puede cobrar con la lista seleccionada. '
            'La lista que corresponde es "%(pricelist)s". %(reason)s',
            pricelist=expected.get('name'),
            reason=reason,
        ))

    @api.model
    def _wholesale_snapshot_keys(self, vals):
        if not isinstance(vals, dict):
            return frozenset()
        return WHOLESALE_SNAPSHOT_FIELDS.intersection(vals)

    def _wholesale_check_snapshot_write(self, orders):
        if not self.env.context.get('wholesale_snapshot_write'):
            raise UserError(_(
                'La decisión de mayoreo solo la registra el punto de venta al cobrar.'
            ))
        locked = orders.filtered(
            lambda order: order.state != 'draft' and order.wholesale_final_decision
        )
        if locked:
            raise UserError(_(
                'La decisión de mayoreo de un pedido cobrado no se puede modificar.'
            ))
