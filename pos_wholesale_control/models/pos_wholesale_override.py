# -*- coding: utf-8 -*-
# pylint: disable=import-error,too-few-public-methods,protected-access
"""Immutable manager overrides for one POS ticket."""
import hmac

from odoo import _, api, fields, models
from odoo.exceptions import UserError

DECISION_SELECTION = [
    ('retail', 'Menudeo'),
    ('wholesale', 'Mayoreo'),
]
REASON_SELECTION = [
    ('previous_month', 'Mes anterior'),
    ('current_month', 'Mes actual'),
    ('current_order', 'Pedido actual'),
    ('below_threshold', 'Debajo del mínimo'),
    ('no_identified_customer', 'Sin cliente'),
    ('history_unavailable', 'Historial no disponible'),
]


class WholesaleOverride(models.Model):
    """One audited pricing exception. It never changes the customer."""

    _name = 'pos.wholesale.override'
    _description = 'Excepción de mayoreo en POS'
    _order = 'override_datetime desc, id desc'
    _rec_name = 'pos_uid'

    pos_uid = fields.Char(
        string='Folio del ticket',
        required=True,
        index=True,
        help='Folio que la caja envía como nombre del pedido. '
             'Una repetición del mismo cobro usa este mismo folio.',
    )
    pos_order_id = fields.Many2one(
        'pos.order',
        string='Pedido',
        index=True,
        ondelete='restrict',
        help='Se llena al cobrar. Antes de eso la excepción pertenece solo al ticket.',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Sucursal de la caja',
        required=True,
        index=True,
        ondelete='restrict',
        help='Sucursal donde se autorizó la excepción.',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Cliente',
        required=True,
        index=True,
        ondelete='restrict',
    )
    manager_employee_id = fields.Many2one(
        'hr.employee',
        string='Gerente',
        required=True,
        ondelete='restrict',
    )
    manager_user_id = fields.Many2one(
        'res.users',
        string='Usuario gerente',
        required=True,
        ondelete='restrict',
    )
    cashier_employee_id = fields.Many2one(
        'hr.employee',
        string='Cajero',
        ondelete='restrict',
    )
    cashier_user_id = fields.Many2one(
        'res.users',
        string='Usuario cajero',
        ondelete='restrict',
    )
    override_datetime = fields.Datetime(
        string='Fecha de autorización',
        required=True,
        default=fields.Datetime.now,
    )
    reason = fields.Text(string='Motivo', required=True)
    automatic_decision = fields.Selection(
        selection=DECISION_SELECTION,
        string='Decisión automática',
        required=True,
    )
    final_decision = fields.Selection(
        selection=DECISION_SELECTION,
        string='Decisión autorizada',
        required=True,
    )
    reason_code = fields.Selection(
        selection=REASON_SELECTION,
        string='Motivo automático',
        required=True,
    )
    reason_text = fields.Text(string='Explicación automática')
    retail_order_amount = fields.Monetary(
        string='Total a precio de menudeo',
        currency_field='currency_id',
    )
    previous_month_amount = fields.Monetary(
        string='Compras del mes anterior',
        currency_field='currency_id',
    )
    previous_month_min = fields.Monetary(
        string='Mínimo del mes anterior',
        currency_field='currency_id',
    )
    current_order_min = fields.Monetary(
        string='Mínimo del pedido actual',
        currency_field='currency_id',
    )
    timezone = fields.Char(string='Zona horaria')
    applied_pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Lista autorizada',
        required=True,
        ondelete='restrict',
    )

    _sql_constraints = [
        (
            'pos_uid_uniq',
            'unique(pos_uid)',
            'Este ticket ya tiene una excepción de mayoreo.',
        ),
    ]

    @api.model
    def authorize_from_pos(self, manager_employee_id, pin, reason,
                           overridden_decision, ui_order):
        """Check the manager PIN and store one exception for this ticket.

        The customer type, the customer's pricelist, the mappings, and the
        thresholds are not written. The PIN is read with sudo() because
        hr.employee.pin is limited to HR users. pos_hr reads it the same way.
        The PIN is compared and then discarded.
        """
        # The five arguments are the RPC contract the cashier screen will call.
        # pylint: disable=too-many-arguments
        if not isinstance(ui_order, dict):
            raise UserError(_('El pedido enviado por la caja no es válido.'))
        register = self._wholesale_active_register(ui_order)
        approved = self._wholesale_approved_request(
            register, manager_employee_id, pin, reason, overridden_decision, ui_order,
        )
        if approved['existing']:
            return self._wholesale_same_override(approved['existing'], approved)
        # sudo() after the PIN and group checks: no access group may create
        # these rows directly. The context flag is the only create path.
        record = self.sudo().with_context(wholesale_authorize=True).create(
            self._wholesale_override_vals(approved),
        )
        return self.browse(record.id)._wholesale_pos_payload()

    @api.model
    def _wholesale_active_register(self, ui_order):
        """Company and register for a payload, when wholesale control is on."""
        orders = self.env['pos.order']
        session = orders._wholesale_session(ui_order)
        company = session.company_id
        if not company.wholesale_control_active:
            raise UserError(_('El control de mayoreo no está activo en esta sucursal.'))
        return {'orders': orders, 'company': company, 'config': session.config_id}

    @api.model
    def _wholesale_approved_request(self, register, manager_employee_id, pin,
                                    reason, decision, ui_order):
        """Manager, customer, eligibility, and list for one authorization."""
        # Same RPC facts as authorize_from_pos, grouped for the checks below.
        # pylint: disable=too-many-arguments
        company = register['company']
        config = register['config']
        orders = register['orders']
        manager = self._wholesale_check_manager(manager_employee_id, pin, company, config)
        target = self._wholesale_override_target(register, ui_order, decision)
        return {
            'company': company,
            'manager': manager,
            'cashier': self._wholesale_cashier(ui_order, company, config),
            'reason': self._wholesale_clean_reason(reason),
            'decision': decision,
            'partner': target['partner'],
            'pos_uid': target['pos_uid'],
            'eligibility': target['eligibility'],
            'applied': target['applied'],
            'existing': orders._wholesale_find_override(target['pos_uid'], company),
        }

    @api.model
    def _wholesale_override_target(self, register, ui_order, decision):
        """Customer, server eligibility, and the list the manager chose."""
        if decision not in ('retail', 'wholesale'):
            raise UserError(_('La decisión de la excepción no es válida.'))
        company = register['company']
        config = register['config']
        orders = register['orders']
        partner = self.env['res.partner']._wholesale_eligibility_partner(
            ui_order.get('partner_id'),
        )
        if not partner:
            raise UserError(_('Seleccione un cliente antes de autorizar una excepción.'))
        fiscal_position = orders._wholesale_fiscal_position(ui_order, company)
        retail_amount = orders._wholesale_retail_amount(
            company, partner, fiscal_position, ui_order.get('lines'),
        )
        partners = self.env['res.partner']
        applied = partners._wholesale_list_for_decision(company, partner, decision)
        if not partners._wholesale_list_usable(company, config, applied):
            raise UserError(partners._wholesale_unusable_list_message(
                applied, decision == 'wholesale',
            ))
        return {
            'partner': partner,
            'pos_uid': orders._wholesale_pos_uid(ui_order),
            'eligibility': partners.get_wholesale_eligibility(
                partner.id, company.id, retail_amount, config.id,
            ),
            'applied': applied,
        }

    @api.model
    def _wholesale_override_vals(self, approved):
        """Field values for a new exception. The PIN is not among them."""
        eligibility = approved['eligibility']
        cashier = approved['cashier']
        manager = approved['manager']
        return {
            'pos_uid': approved['pos_uid'],
            'company_id': approved['company'].id,
            'partner_id': approved['partner'].id,
            'manager_employee_id': manager.id,
            'manager_user_id': manager.user_id.id,
            'cashier_employee_id': cashier.id,
            'cashier_user_id': cashier.user_id.id,
            'reason': approved['reason'],
            'automatic_decision': eligibility['automatic_decision'],
            'final_decision': approved['decision'],
            'reason_code': eligibility['reason_code'],
            'reason_text': eligibility['reason_text'],
            'retail_order_amount': eligibility['retail_order_amount'],
            'previous_month_amount': eligibility['previous_month_amount'],
            'previous_month_min': eligibility['previous_month_min'],
            'current_order_min': eligibility['current_order_min'],
            'timezone': eligibility['timezone'],
            'applied_pricelist_id': approved['applied'].id,
        }

    def _wholesale_link(self, order):
        """Attach the paid order. This is the only later change allowed."""
        self.ensure_one()
        if self.pos_order_id == order:
            return
        if self.pos_order_id:
            raise UserError(_('Esta excepción ya está ligada a otro pedido.'))
        # sudo(): the cashier can read the row but cannot write audit data.
        # The payment check already matched the customer, list, and manager.
        self.sudo().with_context(wholesale_link_override=True).write({
            'pos_order_id': order.id,
        })

    def _wholesale_pos_payload(self):
        """Values the cashier needs to apply the authorized list."""
        self.ensure_one()
        pricelist = self.applied_pricelist_id
        return {
            'id': self.id,
            'pos_uid': self.pos_uid,
            'partner_id': self.partner_id.id,
            'automatic_decision': self.automatic_decision,
            'final_decision': self.final_decision,
            'reason': self.reason,
            'applied_pricelist': {
                'id': pricelist.id,
                'name': pricelist.display_name,
            },
        }

    @api.model
    def _wholesale_check_manager(self, manager_employee_id, pin, company, config):
        """Return the manager employee after PIN and group checks."""
        if not config.module_pos_hr:
            raise UserError(_(
                'Esta caja no pide NIP de empleado, así que no puede '
                'autorizar una excepción.'
            ))
        manager_id = self.env['res.partner']._wholesale_record_id(manager_employee_id)
        # sudo() reads pin, which HR users alone can see on the form.
        manager = self.env['hr.employee'].sudo().browse(manager_id).exists()
        if not manager or not manager.active or manager.company_id != company:
            raise UserError(_('El empleado no puede autorizar en esta sucursal.'))
        if config.employee_ids and manager not in config.employee_ids:
            raise UserError(_('Este empleado no tiene acceso a esta caja.'))
        user = manager.user_id
        if not user or not user.active or company not in user.company_ids:
            raise UserError(_(
                'Este empleado no tiene un usuario de gerente en esta sucursal.'
            ))
        if not user.has_group('point_of_sale.group_pos_manager'):
            raise UserError(_('Este empleado no es gerente de punto de venta.'))
        stored_pin = manager.pin or ''
        if not stored_pin:
            raise UserError(_('Este empleado no tiene NIP.'))
        supplied = self._wholesale_pin_text(pin)
        if not hmac.compare_digest(stored_pin, supplied):
            raise UserError(_('El NIP del gerente no es correcto.'))
        return manager

    @api.model
    def _wholesale_cashier(self, ui_order, company, config):
        """Cashier on the ticket, when that employee belongs to this register."""
        cashier_id = self.env['res.partner']._wholesale_record_id(
            ui_order.get('employee_id'),
        )
        if not cashier_id:
            return self.env['hr.employee']
        cashier = self.env['hr.employee'].sudo().browse(cashier_id).exists()
        if not cashier or not cashier.active or cashier.company_id != company:
            return self.env['hr.employee']
        if config.employee_ids and cashier not in config.employee_ids:
            return self.env['hr.employee']
        return cashier

    @api.model
    def _wholesale_pin_text(self, pin):
        """PIN as typed. A number is accepted; a boolean is not a PIN."""
        if isinstance(pin, str):
            return pin
        if isinstance(pin, int) and not isinstance(pin, bool):
            return str(pin)
        return ''

    @api.model
    def _wholesale_clean_reason(self, reason):
        """Return the reason text, which cannot be empty."""
        cleaned = reason.strip() if isinstance(reason, str) else ''
        if not cleaned:
            raise UserError(_('La excepción necesita un motivo.'))
        return cleaned

    @api.model
    def _wholesale_same_override(self, existing, approved):
        """Return the stored exception when a retry repeats the same request."""
        same = (
            existing.partner_id == approved['partner']
            and existing.manager_employee_id == approved['manager']
            and existing.reason == approved['reason']
            and existing.final_decision == approved['decision']
            and existing.applied_pricelist_id == approved['applied']
        )
        if not same:
            raise UserError(_(
                'Este ticket ya tiene una excepción distinta. Abra un ticket nuevo.'
            ))
        return self.browse(existing.id)._wholesale_pos_payload()

    @api.model_create_multi
    def create(self, vals_list):
        """Create an exception only from the authorized POS path."""
        if not self.env.context.get('wholesale_authorize'):
            raise UserError(_(
                'Las excepciones de mayoreo solo se registran desde el punto de venta.'
            ))
        return super().create(vals_list)

    def write(self, vals):
        """Allow only the first link from an exception to its paid order.

        Rights are checked first so a cashier is denied by the ACL. sudo()
        skips that check and still hits the immutability guard below.
        """
        self.check_access_rights('write')
        self.check_access_rule('write')
        linking = self.env.context.get('wholesale_link_override')
        if not linking or set(vals) - {'pos_order_id'}:
            raise UserError(_('El registro de excepción no se puede modificar.'))
        if any(record.pos_order_id for record in self):
            raise UserError(_('Esta excepción ya está ligada a un pedido.'))
        return super().write(vals)

    def unlink(self):
        """Keep the audit row. An empty recordset still follows normal deletion."""
        if self:
            raise UserError(_('El registro de excepción no se puede borrar.'))
        return super().unlink()

    def copy(self, default=None):
        """Keep one row per ticket. An empty recordset still follows normal copy."""
        if self:
            raise UserError(_('El registro de excepción no se puede duplicar.'))
        return super().copy(default)
