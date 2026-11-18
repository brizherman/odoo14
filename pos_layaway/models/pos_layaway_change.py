import re

from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

from .pos_layaway_campaign import local_date
from .pos_layaway_payment import layaway_test_database


class PosSession(models.Model):
    _inherit = "pos.session"

    def _can_change_layaway(self, folio, now):
        return (
            layaway_test_database(self.env)
            and self.env.user.has_group("point_of_sale.group_pos_manager")
            and folio._layaway_can_modify_products(now)
            and folio.currency_id == self.currency_id
        )

    def _check_layaway_change_access(self):
        if not layaway_test_database(self.env):
            raise AccessError(_("Los cambios de mercancía solo están disponibles para pruebas."))
        if not self.env.user.has_group("point_of_sale.group_pos_manager"):
            raise AccessError(_("El encargado debe autorizar el cambio de mercancía."))

    def _layaway_changeable_lines(self, folio):
        delivered = self.env["stock.move"].sudo().search([
            ("layaway_line_id", "in", folio.line_ids.ids), ("state", "=", "done"),
            ("location_dest_id.usage", "=", "customer"),
        ]).layaway_line_id
        return folio.line_ids.filtered(
            lambda line: not line.qty_picked_up and line.warehouse_id.company_id in self.env.companies
        ) - delivered

    def quote_layaway_change(self, folio_id, remove_ids, lines):
        self._check_layaway_change_access()
        folio = self._find_layaway(folio_id)
        session = self.with_company(self.company_id)
        quote = session._quote_layaway_change(folio, remove_ids, lines, fields.Datetime.now())
        return dict(quote, confirmation=session._layaway_quote_digest(quote))

    def confirm_layaway_change(self, reference, folio_id, remove_ids, lines, confirmation, reason):
        session = self.sudo(False)
        session._check_layaway_change_access()
        folio = session._find_layaway(folio_id, require_open=False)
        session = session.with_company(session.company_id)
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
            raise ValidationError(_("Indica el motivo del cambio de mercancía."))
        if not isinstance(confirmation, str) or not re.fullmatch(r"[a-f0-9]{64}", confirmation):
            raise ValidationError(_("Cotiza el cambio antes de confirmarlo."))
        reason = reason.strip()
        return session.env["pos.layaway.operation"].sudo()._confirm(
            session, reference, "change_products", [remove_ids, lines, confirmation, reason],
            lambda operation: session._apply_layaway_change(
                operation, folio, remove_ids, lines, confirmation, reason,
            ),
            folio, pass_operation=True,
        )

    def _quote_layaway_change(self, folio, remove_ids, lines, now):
        if not self._can_change_layaway(folio, now):
            raise UserError(_("El apartado no admite cambios de mercancía en su estado, plazo o moneda."))
        if (
            not isinstance(remove_ids, list) or not remove_ids
            or any(type(line_id) is not int or line_id <= 0 for line_id in remove_ids)
            or len(remove_ids) != len(set(remove_ids))
            or not isinstance(lines, list)
        ):
            raise ValidationError(_("Selecciona líneas válidas para retirar del apartado."))
        removed = self._layaway_changeable_lines(folio).filtered(lambda line: line.id in remove_ids)
        if len(removed) != len(remove_ids):
            raise ValidationError(_("Solo se puede retirar mercancía pendiente del folio en compañías habilitadas."))
        kept = folio.line_ids - removed
        if not kept and not lines:
            raise ValidationError(_("El apartado debe conservar mercancía."))
        currency = folio.currency_id
        new = self._price_layaway_lines(
            lines, folio.partner_id, currency, local_date(now, folio.timezone),
        ) if lines else []
        total = currency.round(sum(kept.mapped("amount_total")) + sum(
            line["amount_total"] for line in new
        ))
        if currency.compare_amounts(total, folio.minimum_amount) <= 0:
            raise ValidationError(_("El total con impuestos debe superar el mínimo de la campaña."))
        if currency.compare_amounts(total, folio.amount_paid) < 0:
            raise ValidationError(_("El total no puede ser inferior a lo pagado."))
        required = currency.round(total * folio.deposit_percentage / 100)
        if currency.compare_amounts(folio.amount_paid, required) < 0:
            raise ValidationError(_("El importe confirmado es insuficiente para reservar la mercancía."))
        return {
            "id": folio.id,
            "previous_lines": folio.line_ids._layaway_change_snapshot(),
            "removed_ids": removed.ids,
            "lines": new,
            "amount_previous": folio.amount_total,
            "amount_total": total,
            "amount_paid": folio.amount_paid,
            "amount_due": currency.round(total - folio.amount_paid),
        }

    def _apply_layaway_change(self, operation, folio, remove_ids, lines, confirmation, reason):
        self._lock_layaway_stock_session()
        quote = self._quote_layaway_change(folio, remove_ids, lines, operation.create_date)
        if self._layaway_quote_digest(quote) != confirmation:
            raise ValidationError(_("Cambió la cotización. Vuelve a cotizar antes de autorizar el cambio."))
        env = self.sudo().with_context(
            {}, allowed_company_ids=self.env.companies.ids,
        ).env
        removed = env["pos.layaway.line"].browse(quote["removed_ids"])
        moves = env["stock.move"].search([
            ("layaway_line_id", "in", removed.ids), ("state", "not in", ("done", "cancel")),
        ])
        if len(moves) != len(removed) or moves.layaway_line_id != removed:
            # Recordset equality ignores ordering.
            raise UserError(_("La mercancía seleccionada no tiene las reservas esperadas."))
        for move in moves:
            line = move.layaway_line_id
            if (
                move.picking_id.layaway_id != folio or move.state in ("draft", "done")
                or move.company_id != line.warehouse_id.company_id or move.quantity_done
                or move.location_id != line.location_id or move.product_id != line.product_id
                or float_compare(move.reserved_availability, line.qty,
                                 precision_rounding=move.product_uom.rounding) != 0
            ):
                raise UserError(_("La mercancía seleccionada no tiene las reservas esperadas."))
        released = [{
            "line_id": move.layaway_line_id.id, "move_id": move.id,
            "picking_id": move.picking_id.id, "qty": move.reserved_availability,
        } for move in moves]
        moves._action_cancel()
        removed.write({"released_by_id": operation.id})
        folio.invalidate_cache(["line_ids"])
        new = env["pos.layaway.line"].create([
            dict(line, layaway_id=folio.id) for line in quote["lines"]
        ])
        if new:
            picking = env["stock.picking"]._reserve_layaway_lines(folio, self, new)
            reserved = [{
                "line_id": move.layaway_line_id.id, "move_id": move.id,
                "picking_id": picking.id, "qty": move.reserved_availability,
            } for move in picking.move_lines]
        else:
            reserved = []
        adjustment = self._post_layaway_adjustment(folio, operation, new, removed)
        settlement = self._settle_layaway_if_paid(folio, operation, env["pos.layaway.payment"])
        return folio, {
            **quote,
            "folio": folio.folio,
            "reference": operation.reference,
            "reason": reason,
            "user_id": operation.user_id.id,
            "authorized_at": fields.Datetime.to_string(operation.create_date),
            "current_lines": folio.line_ids._layaway_change_snapshot(),
            "released": released,
            "reserved": reserved,
            **adjustment,
            **settlement,
        }


class PosLayawayLine(models.Model):
    _inherit = "pos.layaway.line"

    def _layaway_change_snapshot(self):
        return self.read([
            "product_id", "product_name", "warehouse_id", "location_id", "qty",
            "qty_picked_up", "pricelist_id", "price_unit", "amount_tax", "amount_total",
            "tax_details",
        ], load="_classic_write")
