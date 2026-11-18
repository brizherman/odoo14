from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .pos_layaway_campaign import local_date
from .stock_picking import LayawayStockError


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
    state = fields.Selection(
        [("available", "Disponible"), ("expired", "Caducado")], compute="_compute_state",
    )

    _sql_constraints = [
        ("layaway_unique", "UNIQUE(layaway_id)", "El apartado ya tiene un saldo por vencimiento."),
        ("operation_unique", "UNIQUE(operation_id)", "La operación ya tiene un saldo por vencimiento."),
        ("positive_amount", "CHECK(amount > 0)", "El saldo debe ser positivo."),
    ]

    @api.depends("expires_on", "layaway_id.timezone")
    def _compute_state(self):
        now = fields.Datetime.now()
        for credit in self:
            expired = local_date(now, credit.layaway_id.timezone) > credit.expires_on
            credit.state = "expired" if expired else "available"

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
