from copy import deepcopy

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .pos_layaway_campaign import local_date
from .pos_layaway_payment import layaway_test_database
from .stock_picking import LayawayStockError


class PosConfig(models.Model):
    _inherit = "pos.config"

    layaway_credit_test = fields.Boolean(compute="_compute_layaway_credit_test")

    @api.depends("layaway_application_method_id")
    def _compute_layaway_credit_test(self):
        for config in self:
            config.layaway_credit_test = bool(
                layaway_test_database(self.env) and config.sudo().layaway_application_method_id
            )


class PosLayawayCredit(models.Model):
    _name = "pos.layaway.credit"
    _description = "Saldo por vencimiento de apartado POS"
    _rec_name = "operation_id"

    layaway_id = fields.Many2one("pos.layaway", required=True, ondelete="restrict")
    operation_id = fields.Many2one("pos.layaway.operation", required=True, ondelete="restrict")
    partner_id = fields.Many2one(related="layaway_id.partner_id", store=True, index=True)
    campaign_id = fields.Many2one(related="layaway_id.campaign_id", store=True, index=True)
    currency_id = fields.Many2one(related="layaway_id.currency_id", store=True)
    reason = fields.Char(required=True)
    amount = fields.Monetary(required=True)
    expires_on = fields.Date(related="layaway_id.credit_end", store=True)
    order_id = fields.Many2one("pos.order", readonly=True, copy=False, ondelete="restrict")
    consumption_id = fields.Many2one(
        "pos.layaway.operation", readonly=True, copy=False, ondelete="restrict",
    )
    closure_id = fields.Many2one(
        "pos.layaway.operation", readonly=True, copy=False, ondelete="restrict",
    )
    state = fields.Selection(
        [("available", "Disponible"), ("consumed", "Consumido"), ("expired", "Caducado")],
        compute="_compute_state",
    )

    _sql_constraints = [
        ("layaway_unique", "UNIQUE(layaway_id)", "El apartado ya tiene un saldo por vencimiento."),
        ("operation_unique", "UNIQUE(operation_id)", "La operación ya tiene un saldo por vencimiento."),
        ("positive_amount", "CHECK(amount > 0)", "El saldo debe ser positivo."),
        ("order_unique", "UNIQUE(order_id)", "El pedido ya tiene un saldo aplicado."),
        ("one_resolution", "CHECK((order_id IS NULL) = (consumption_id IS NULL) "
         "AND (closure_id IS NULL OR order_id IS NULL))", "La resolución del saldo no es válida."),
    ]

    @api.depends("expires_on", "layaway_id.timezone", "order_id", "closure_id")
    def _compute_state(self):
        now = fields.Datetime.now()
        for credit in self:
            credit.state = credit._state_at(now)

    def _state_at(self, now):
        if self.order_id:
            return "consumed"
        if self.closure_id or local_date(now, self.layaway_id.timezone) > self.expires_on:
            return "expired"
        return "available"

    def _record_resolution(self, operation, order=None):
        self.ensure_one()
        if not self.env.su or not layaway_test_database(self.env):
            raise AccessError(_("La resolución del saldo solo está disponible para pruebas."))
        values = ({"order_id": order.id, "consumption_id": operation.id} if order
                  else {"closure_id": operation.id})
        return super().write(values)

    def write(self, vals):
        raise AccessError(_("El saldo conserva las condiciones de su emisión."))

    def unlink(self):
        raise AccessError(_("El saldo conserva el registro de su emisión."))

    def _pos_layaway_credit_values(self):
        self.ensure_one()
        return {
            "id": self.id, "reference": self.operation_id.reference,
            "partner_id": self.partner_id.id, "campaign_id": self.campaign_id.id,
            "amount": self.amount, "currency": self.currency_id.name,
            "expires_on": fields.Date.to_string(self.expires_on), "state": self.state,
        }


class PosLayaway(models.Model):
    _inherit = "pos.layaway"

    def _can_convert_layaway_to_credit(self):
        self.ensure_one()
        return (
            not self.sale_id and self.pickup_state == "pending" and bool(self.line_ids)
            and self.currency_id.compare_amounts(self.amount_due, 0) > 0
            and self.currency_id.compare_amounts(self.amount_paid, 0) > 0
        )


class PosSession(models.Model):
    _inherit = "pos.session"

    def preview_layaway_credit(self, folio_number, partner_id):
        self._check_layaway_payment_test()
        scope = self._layaway_query_domain()
        if not isinstance(folio_number, str) or not folio_number.strip():
            raise ValidationError(_("Indica el folio del apartado."))
        folio = self.env["pos.layaway"].sudo().search(
            scope + [("folio", "=", folio_number.strip().upper())],
            limit=1,
        )
        credit = self._check_credit_purchase(folio, partner_id, fields.Datetime.now())
        return dict(credit._pos_layaway_credit_values(), folio=folio.folio, folio_id=folio.id)

    def _check_credit_purchase(self, folio, partner_id, moment):
        credit = folio.expiry_credit_id
        if not credit or type(partner_id) is not int or partner_id != credit.partner_id.id:
            raise UserError(_("No hay un saldo de este folio para el titular seleccionado."))
        if self.rescue or not self.currency_id == credit.currency_id == self.company_id.currency_id:
            raise UserError(_("El saldo requiere una sesión ordinaria en la moneda del apartado."))
        if credit._state_at(moment) != "available":
            raise UserError(_("El saldo está consumido o caducado."))
        return credit

    def confirm_layaway_credit_order(self, folio_id, reference, ui_order):
        self._check_layaway_payment_test()
        folio = self._find_layaway(folio_id, require_open=False)
        if not isinstance(ui_order, dict) or ui_order.get("pos_session_id") != self.id:
            raise ValidationError(_("El pedido no corresponde a esta caja."))
        if ui_order.get("to_invoice"):
            raise UserError(_("La compra con saldo de prueba se confirma sin facturación."))

        def apply(operation):
            self._lock_layaway_stock_session()
            confirmed_at = fields.Datetime.now()
            credit = self._check_credit_purchase(folio, ui_order.get("partner_id"), confirmed_at)
            session = self.sudo().with_context({}, allowed_company_ids=self.company_id.ids)
            method = session._layaway_application_method()
            orders = self.env["pos.order"].with_company(self.company_id)
            payload = deepcopy(ui_order)
            payload.update(creation_date=fields.Datetime.to_string(confirmed_at), user_id=self.env.uid)
            order = orders._confirm_credit_purchase(payload, credit, method)
            moves = session._apply_layaway_liabilities(
                folio.with_env(session.env), folio.payment_ids.with_env(session.env),
                method.receivable_account_id, local_date(confirmed_at, folio.timezone),
                "%s · %s" % (folio.folio, operation.reference),
            )
            credit._record_resolution(operation, order)
            order.sudo().layaway_application_move_ids = moves
            return folio, {
                "id": order.id, "pos_reference": order.pos_reference, "order_name": order.name,
                "reference": operation.reference, "credit_id": credit.id, "credit_amount": credit.amount,
                "amount_new": order.currency_id.round(order.amount_paid - credit.amount),
                "move_ids": moves.ids,
            }

        return self.env["pos.layaway.operation"].sudo()._confirm(
            self, reference, "apply_expiry_credit", ui_order, apply, folio, pass_operation=True,
        )

    def close_expired_layaway_credit(self, folio_id, reference, notes):
        self._check_layaway_payment_test()
        folio = self._find_layaway(folio_id, require_open=False)
        if self.rescue or not self.env.user.has_group("point_of_sale.group_pos_manager"):
            raise AccessError(_("El cierre del saldo requiere un encargado en una sesión ordinaria."))
        if not isinstance(notes, str) or not notes.strip() or len(notes.strip()) > 1000:
            raise ValidationError(_("Indica las observaciones del cierre (hasta 1000 caracteres)."))
        notes = notes.strip()

        def apply(operation):
            credit = folio.expiry_credit_id
            if not credit or credit._state_at(fields.Datetime.now()) != "expired":
                raise UserError(_("Solo se puede cerrar un saldo caducado sin consumo."))
            if credit.closure_id:
                raise UserError(_("El saldo ya tiene un cierre administrativo."))
            credit._record_resolution(operation)
            return folio, {
                "id": folio.id, "folio": folio.folio, "reference": operation.reference,
                "notes": notes, "reviewer": operation.user_id.name,
                "closed_at": operation._receipt_identification(folio, operation.create_date)["confirmed_at"],
            }

        return self.env["pos.layaway.operation"].sudo()._confirm(
            self, reference, "close_expiry_credit", {"notes": notes}, apply, folio, pass_operation=True,
        )

    def _convert_layaway_to_credit(self, folio, operation, reason):
        if not folio._can_convert_layaway_to_credit():
            raise UserError(_("El saldo requiere deuda, pagos confirmados y un apartado sin venta ni entregas."))

        pickings = self.env["stock.picking"].sudo().search([("layaway_id", "=", folio.id)])
        if pickings.move_lines.filtered_domain([("state", "=", "done"), ("location_dest_id.usage", "=", "customer")]):
            raise UserError(_("No se puede convertir un apartado con mercancía entregada."))
        pending = pickings.filtered(lambda picking: picking.state not in ("done", "cancel"))
        moves = pending.move_lines.filtered(lambda move: move.state != "cancel")
        lines = folio.line_ids
        if any(not move.layaway_line_id or move.layaway_line_id not in lines for move in moves) or any(
            moves.move_line_ids.mapped("qty_done")
        ):
            raise LayawayStockError(_("Revisa los movimientos de la reserva antes de liberar la mercancía."))

        released = [
            dict(self._layaway_pickup_line(line), amount_total=line.amount_total) for line in lines
        ]
        amount_due = folio.amount_due
        credit = self.env["pos.layaway.credit"].sudo().create({
            "layaway_id": folio.id, "operation_id": operation.id,
            "reason": reason, "amount": folio.amount_paid,
        })
        for company in pending.company_id.sorted("id"):
            company_pickings = pending.filtered(lambda picking: picking.company_id == company)
            company_pickings.with_context({}, allowed_company_ids=company.ids).action_cancel()
        lines.write({"released_by_id": operation.id})
        folio.invalidate_cache(["line_ids"])
        folio.expiry_credit_id = credit
        return {
            "credit": credit._pos_layaway_credit_values(),
            "debt_released": amount_due,
            "released_lines": released,
            "picking_ids": pending.ids,
            "payment_ids": folio.payment_ids.ids,
        }
