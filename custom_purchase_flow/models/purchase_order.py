# -*- coding: utf-8 -*-
from lxml import etree
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # --- State field extension ---
    # Inserts custom states in the correct positions within the native selection.
    # Native order: draft, sent, to approve, purchase, done, cancel
    # Custom additions:
    #   'approved'        after 'to approve'
    #   'pending_payment' after 'sent'
    #   'in_transit'      after 'purchase'
    #   'arrived'         after 'in_transit'
    #   'done'            final Done step
    # Native state order: draft → sent → to approve → purchase → done → cancel
    # We override labels for native states and insert custom states in the correct positions.
    # selection_add reorders by placing each tuple relative to the next:
    #   ('draft', 'Borrador')            — override label
    #   ('to approve', 'Por Aprobar')    — override label
    #   ('approved', ...)                — new, inserted after 'to approve'
    #   ('sent', 'Enviada a Proveedor')  — override label, inserted after 'approved'
    #   ('pending_payment', ...)         — new, inserted after 'sent'
    #   ('purchase', 'PO Surtiendo')     — override label, inserted after 'pending_payment'
    #   ('in_transit', ...)              — new, inserted after 'purchase'
    #   ('arrived', ...)                 — new, inserted after 'in_transit'
    #   ('hecho', 'Hecho')               — new custom final state (not native done/Bloqueado)
    state = fields.Selection(
        selection_add=[
            ('draft', 'Borrador'),
            ('to approve', 'Por Aprobar'),
            ('approved', 'Aprobada'),
            ('sent', 'Enviada a Proveedor'),
            ('pending_payment', 'Pendiente de Pago'),
            ('purchase', 'PO Surtiendo'),
            ('in_transit', 'PO En Tránsito'),
            ('arrived', 'PO Llegó'),
            ('hecho', 'Hecho'),
            ('done', 'Done'),
        ],
        ondelete={
            'approved': 'set default',
            'pending_payment': 'set default',
            'in_transit': 'set default',
            'arrived': 'set default',
            'hecho': 'set default',
        },
    )

    # --- Custom fields ---
    rejection_reason = fields.Text(
        string="Motivo de rechazo",
        readonly=True,
        copy=False,
    )
    tracking_number = fields.Char(
        string="Número de guía",
        copy=False,
    )
    no_tracking_reason = fields.Text(
        string="Motivo sin guía",
        copy=False,
    )
    date_sent = fields.Datetime(
        string="Fecha de envío al proveedor",
        readonly=True,
        copy=False,
    )
    receipt_deadline = fields.Datetime(
        string="Límite Recepción",
        related='date_planned',
        store=False,
    )
    order_limit_display = fields.Char(
        string="Límite Pedir",
        compute='_compute_order_limit_display',
        store=False,
    )
    order_limit_delta = fields.Integer(
        string="Límite Pedir (días)",
        compute='_compute_order_limit_display',
        store=False,
    )
    sent_days_display = fields.Char(
        string="Limite Enviado",
        compute='_compute_sent_days_display',
        store=False,
    )
    sent_days_delta = fields.Integer(
        string="Limite Enviado (días)",
        compute='_compute_sent_days_display',
        store=False,
    )
    receipt_status = fields.Selection(
        selection=[
            ('draft', 'Borrador'),
            ('waiting', 'Esperando otra operación'),
            ('confirmed', 'En espera'),
            ('assigned', 'Listo'),
            ('done', 'Hecho'),
            ('cancel', 'Cancelado'),
        ],
        string="Estado de recepción",
        compute='_compute_receipt_status',
        store=False,
    )

    # --- Computed fields ---
    @api.depends('order_line.date_planned')
    def _compute_date_planned(self):
        """Override native behavior to keep Fecha Recepción empty
        unless the user sets it manually.

        We deliberately do NOT derive date_planned from order lines,
        and we never overwrite a manually entered value.
        """
        for order in self:
            if order.date_planned:
                # Keep whatever the user has set.
                continue
            # Leave it empty (False) until the user fills it explicitly.
            order.date_planned = False

    @api.depends('state', 'date_order')
    def _compute_order_limit_display(self):
        today = fields.Date.context_today(self)
        for order in self:
            order.order_limit_delta = False
            if order.state not in ('draft', 'to approve') or not order.date_order:
                order.order_limit_display = ''
                continue
            order_date = fields.Date.to_date(order.date_order)
            if not order_date:
                order.order_limit_display = ''
                continue
            days = (today - order_date).days
            order.order_limit_delta = days
            order.order_limit_display = _("%s days") % days

    @api.depends('state', 'date_sent')
    def _compute_sent_days_display(self):
        today = fields.Date.context_today(self)
        for order in self:
            order.sent_days_delta = False
            if order.state in ('pending_payment', 'purchase', 'in_transit', 'arrived'):
                order.sent_days_display = ''
                continue
            if not order.date_sent:
                order.sent_days_display = _("N/D")
                continue
            sent_date = fields.Date.to_date(order.date_sent)
            if not sent_date:
                order.sent_days_display = _("N/D")
                continue
            days = (today - sent_date).days
            order.sent_days_delta = days
            order.sent_days_display = _("%s days") % days

    @api.depends('picking_ids', 'picking_ids.state')
    def _compute_receipt_status(self):
        for order in self:
            pickings = order.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel')
            )
            if pickings:
                order.receipt_status = pickings[0].state
            elif order.picking_ids:
                done = order.picking_ids.filtered(lambda p: p.state == 'done')
                order.receipt_status = done[-1].state if done else 'cancel'
            else:
                order.receipt_status = False

    @api.model
    def get_rfq_dashboard_counts(self):
        """Return per-state counts for the custom RFQ/PO flow.

        This is used by the RFQ list dashboard to show how many purchase
        orders are currently in each custom state, covering the full
        end-to-end flow (draft → arrived).
        """
        po = self.env['purchase.order']
        states = [
            'draft',
            'to approve',
            'approved',
            'sent',
            'pending_payment',
            'purchase',
            'in_transit',
            'arrived',
            'hecho',
        ]
        counts = dict((state, 0) for state in states)
        for state in states:
            counts[state] = po.search_count([('state', '=', state)])
        return counts

    @api.model
    def retrieve_dashboard(self):
        """Extend the standard purchase dashboard with RFQ state counts."""
        values = super(PurchaseOrder, self).retrieve_dashboard()
        values['rfq_state_counts'] = self.get_rfq_dashboard_counts()
        return values

    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        """Hide Edit button when PO is not editable.
        Only draft purchase orders are editable; all other states are read-only.
        """
        res = super().fields_view_get(
            view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu
        )
        if view_type != 'form':
            return res
        # Right after "Solicitar aprobación" the client sends this flag; hide Edit without needing active_id.
        if self.env.context.get('from_request_approval'):
            doc = etree.fromstring(res['arch'])
            for form in doc.xpath('//form'):
                form.set('edit', 'false')
                break
            res['arch'] = etree.tostring(doc, encoding='unicode')
            return res
        order = self
        if not order or len(order) != 1:
            active_id = self.env.context.get('active_id')
            if self.env.context.get('active_model') == 'purchase.order' and active_id:
                order = self.browse(active_id)
        if not order or len(order) != 1:
            return res
        # Clear transient flag if present; edition is allowed only in draft anyway.
        Flag = self.env['purchase.order.hide.edit.flag']
        Flag.search([('order_id', '=', order.id)]).unlink()
        can_edit = order.state == 'draft'
        if not can_edit:
            doc = etree.fromstring(res['arch'])
            for form in doc.xpath('//form'):
                form.set('edit', 'false')
                break
            res['arch'] = etree.tostring(doc, encoding='unicode')
        return res

    # =========================================================================
    # State transition methods — Task 4.0
    # =========================================================================

    def action_request_approval(self):
        """Coordinator submits draft PO for approval → state becomes 'to approve'.
        Returns a reload action so the form updates immediately (Edit button disappears
        without refresh); coordinators will still see Edit in 'to approve'.
        """
        updated = self.browse()
        for order in self:
            if order.state != 'draft':
                continue
            order._add_supplier_to_product()
            order.write({'state': 'to approve'})
            if order.partner_id not in order.message_partner_ids:
                order.message_subscribe([order.partner_id.id])
            updated |= order
        if len(updated) == 1:
            self.env['purchase.order.hide.edit.flag'].create({'order_id': updated.id})
            ctx = dict(self.env.context, from_request_approval=True)
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'purchase.order',
                'res_id': updated.id,
                'view_mode': 'form',
                'target': 'current',
                'context': ctx,
            }
        return True

    def button_approve(self, force=False):
        """Direction approves PO → state becomes 'approved' (not 'purchase').

        We replicate the native _approval_allowed filter but write 'approved'
        instead of 'purchase' to stay in the custom flow.
        """
        orders = self.filtered(lambda o: o._approval_allowed())
        orders.write({'state': 'approved', 'date_approve': fields.Datetime.now()})
        return {}

    def action_open_reject_wizard(self):
        """Opens the rejection wizard for the Direction role."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject Purchase Order'),
            'res_model': 'purchase.order.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_purchase_order_id': self.id},
        }

    def action_set_to_draft(self):
        """Purchase Dept reverts PO to draft (Cambiar a Borrador).
        Allowed from to_approve only.
        """
        allowed = ('to approve',)
        for order in self:
            if order.state not in allowed:
                raise UserError(
                    _("Solo puedes cambiar a Borrador desde Por Aprobar.")
                )
            order.write({'state': 'draft', 'rejection_reason': False})
        return True

    def action_send_to_vendor(self):
        """Purchase Dept sends approved PO to vendor → state becomes 'sent'."""
        self.ensure_one()
        self.write({
            'state': 'sent',
            'date_sent': fields.Datetime.now(),
        })

    def action_set_to_approved(self):
        """Purchase Dept reverts PO from Enviada a Proveedor back to Aprobada."""
        for order in self:
            if order.state != 'sent':
                raise UserError(
                    _("Solo puedes cambiar a Aprobada desde el estado Enviada a Proveedor.")
                )
            order.write({'state': 'approved'})
        return True

    def action_set_fulfilling(self):
        """Purchase Dept marks PO as being fulfilled.

        Writes state to 'purchase' first so that purchase_stock._create_picking()
        proceeds (it filters on state='purchase'/'done'), then creates the receipt.
        Only allowed from 'sent' or 'pending_payment'.
        """
        for order in self:
            if order.state not in ('sent', 'pending_payment'):
                raise UserError(
                    _("Solo puedes marcar como Surtiendo desde los estados 'Enviada a Proveedor' o 'PO Pendiente de Pago'.")
                )
            if not order.date_planned:
                raise UserError(
                    _("Por favor captura la Fecha de Recepción antes de marcar la orden como Surtiendo.")
                )
            order._add_supplier_to_product()
            if order.partner_id not in order.message_partner_ids:
                order.message_subscribe([order.partner_id.id])
            # Write purchase state first so _create_picking filter passes
            order.write({'state': 'purchase', 'date_approve': fields.Datetime.now()})
            order._create_picking()

    def action_set_pending_payment(self):
        """Purchase Dept marks PO as pending payment → state becomes 'pending_payment'."""
        self.write({'state': 'pending_payment'})

    def action_set_to_sent(self):
        """Purchase Dept reverts PO from Pendiente de Pago back to Enviada a Proveedor."""
        for order in self:
            if order.state != 'pending_payment':
                raise UserError(
                    _("Solo puedes cambiar a Enviada a Proveedor desde el estado Pendiente de Pago.")
                )
            order.write({'state': 'sent'})
        return True

    def action_set_in_transit(self):
        """Purchase Dept marks PO as in transit → state becomes 'in_transit'.

        Must be called from PO Surtiendo and requires tracking info first.
        """
        for order in self:
            if order.state != 'purchase':
                raise UserError(
                    _(
                        "Solo puedes marcar como En Tránsito "
                        "desde el estado 'PO Surtiendo'."
                    )
                )
            if not order.tracking_number and not order.no_tracking_reason:
                raise UserError(
                    _(
                        "Por favor llena el Número de Guía o indica el motivo por "
                        "el que no hay guía antes de marcar la orden como En Tránsito."
                    )
                )
            order.write({'state': 'in_transit'})

    def action_revert_to_purchase(self):
        """Cashier or Purchase Dept reverts PO from En Tránsito back to PO Surtiendo."""
        for order in self:
            if order.state != 'in_transit':
                raise UserError(
                    _("Solo puedes regresar a PO Surtiendo desde el estado PO En Tránsito.")
                )
            order.write({'state': 'purchase'})
        return True

    def action_set_arrived(self):
        """Cashier confirms physical arrival → state becomes 'arrived'."""
        for order in self:
            if order.state != 'in_transit':
                raise UserError(
                    _(
                        "Solo puedes marcar como Llegó desde el estado "
                        "PO En Tránsito."
                    )
                )
            order.write({'state': 'arrived'})

    def action_set_hecho(self):
        """Set PO to custom final state Hecho (from PO Llegó only). Not related to native done/Bloqueado."""
        for order in self:
            if order.state != 'arrived':
                raise UserError(
                    _("Solo puedes marcar como Hecho desde el estado PO Llegó.")
                )
            order.write({'state': 'hecho'})

    def action_open_tracking_wizard(self):
        """Open wizard to edit tracking info while form stays readonly."""
        self.ensure_one()
        if self.state not in ('purchase', 'in_transit', 'arrived'):
            raise UserError(
                _(
                    "Solo puedes editar el rastreo cuando la orden está en "
                    "PO Surtiendo, En Tránsito o Llegó."
                )
            )
        ctx = dict(self.env.context or {})
        ctx.update({
            'default_purchase_order_id': self.id,
            'default_tracking_number': self.tracking_number,
            'default_no_tracking_reason': self.no_tracking_reason,
        })
        return {
            'name': _('Editar rastreo'),
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order.tracking.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': ctx,
        }

    def action_open_receipt_date_wizard(self):
        """Open wizard to edit Fecha de recepción while form stays readonly.

        Allowed only in Enviada a Proveedor (sent) and Pendiente de Pago.
        """
        self.ensure_one()
        if self.state not in ('sent', 'pending_payment'):
            raise UserError(
                _(
                    "Solo puedes editar la Fecha de Recepción cuando la orden está en "
                    "Enviada a Proveedor o Pendiente de Pago."
                )
            )
        ctx = dict(self.env.context or {})
        ctx.update({
            'default_purchase_order_id': self.id,
            'default_date_planned': self.date_planned,
        })
        return {
            'name': _('Editar fecha de recepción'),
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order.receipt.date.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': ctx,
        }

    def action_revert_to_in_transit(self):
        """Cashier reverts an arrived PO back to in_transit to correct a mistake."""
        self.write({'state': 'in_transit'})

    # =========================================================================
    # Deletion policy
    # =========================================================================

    def unlink(self):
        """Completely block deletion of purchase orders in all states."""
        raise UserError(_("Deleting purchase orders is not allowed. Cancel them instead."))
