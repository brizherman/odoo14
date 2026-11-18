import math

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .stock_picking import LayawayStockError


_CREDIT_PURCHASE = object()


class PosOrder(models.Model):
    _inherit = "pos.order"

    layaway_ids = fields.One2many("pos.layaway", "sale_id", string="Apartado", readonly=True)
    layaway_credit_ids = fields.One2many(
        "pos.layaway.credit", "order_id", string="Saldo de apartado aplicado", readonly=True,
    )
    layaway_credit_amount = fields.Monetary(
        compute="_compute_layaway_credit_amount", store=True, readonly=True,
    )
    layaway_application_move_ids = fields.Many2many(
        "account.move", string="Aplicación de cobros de apartados", readonly=True, copy=False,
    )
    wholesale_reason_code = fields.Selection(
        selection_add=[("layaway_payment", "Cobro confirmado de apartado")],
        ondelete={"layaway_payment": "set null"},
    )

    @api.depends("layaway_credit_ids.amount")
    def _compute_layaway_credit_amount(self):
        for order in self:
            order.layaway_credit_amount = sum(order.layaway_credit_ids.mapped("amount"))

    def _purchase_credit(self):
        if self.env.context.get("layaway_credit_token") is _CREDIT_PURCHASE:
            return self.env["pos.layaway.credit"].sudo().browse(self.env.context["layaway_credit_id"])
        return self.env["pos.layaway.credit"]

    @api.model
    def _confirm_credit_purchase(self, payload, credit, method):
        session = self.env["pos.session"].browse(payload["pos_session_id"])
        self._wholesale_fiscal_position(payload, session.company_id)
        name = self._wholesale_pos_uid(payload)
        if name != payload["name"]:
            raise ValidationError(_("El folio de la compra no es válido."))
        existing = self.search([("session_id", "=", session.id), ("pos_reference", "=", name)])
        if existing and (
            len(existing) != 1 or existing.state != "draft" or existing.id != payload.get("server_id")
        ):
            raise UserError(_("El ticket ya está registrado en esta caja."))
        if payload.get("server_id") and not existing:
            raise UserError(_("El borrador de compra no está disponible en esta caja."))

        # Only the server injects the accounting tender. The register submits real payments.
        if any(line[2]["payment_method_id"] == method.id for line in payload["statement_ids"]):
            raise ValidationError(_("El saldo lo agrega el servidor al confirmar la compra."))
        orders = self.with_context(layaway_credit_token=_CREDIT_PURCHASE, layaway_credit_id=credit.id)
        order = self.browse(orders._process_order({"data": payload}, False, existing.with_env(orders.env)))
        if order.state != "paid" or order.session_id != session:
            raise UserError(_("La compra con saldo no se confirmó en esta caja."))
        return order

    @api.model
    def _wholesale_retail_amount(self, company, partner, fiscal_position, lines):
        amount = super()._wholesale_retail_amount(company, partner, fiscal_position, lines)
        credit = self._purchase_credit()
        return max(0, amount - credit.amount) if credit else amount

    @api.model
    def _order_fields(self, ui_order):
        vals = super()._order_fields(ui_order)
        if self._purchase_credit():
            for command in vals["lines"] or []:
                if command[0] != 0:
                    raise ValidationError(_("La compra con saldo requiere líneas de venta nuevas."))
                line = command[2]
                product = self.env["product.product"].browse(line["product_id"])
                taxes = product.taxes_id.filtered(lambda tax: tax.company_id.id == vals["company_id"])
                line["tax_ids"] = [(6, 0, taxes.ids)]
        return vals

    def _check_credit_order_amounts(self, payload, order, session, credit):
        currency = credit.currency_id
        if order.currency_id != currency or order.partner_id != credit.partner_id or not order.lines:
            raise ValidationError(_("La compra debe corresponder al titular y a la moneda del saldo."))
        if any(
            line.qty <= 0 or not all(map(math.isfinite, (line.qty, line.price_unit, line.discount)))
            or line.price_unit < 0 or not 0 <= line.discount <= 100
            or line.product_id.company_id and line.product_id.company_id != order.company_id
            for line in order.lines
        ):
            raise ValidationError(_("El saldo requiere una compra con cantidades e importes válidos."))
        total = subtotal = 0.0
        for line in order.lines:
            values = line._compute_amount_line_all()
            total += values["price_subtotal_incl"]
            subtotal += values["price_subtotal"]
            line.write(values)
        total = currency.round(total)
        tax = currency.round(total - subtotal)
        payable = order._get_rounded_amount(total)
        if currency.compare_amounts(min(total, payable), credit.amount) < 0:
            raise ValidationError(_("El total de la compra debe cubrir todo el saldo."))
        if currency.compare_amounts(total, order.amount_total) or currency.compare_amounts(tax, order.amount_tax):
            raise ValidationError(_("El total o los impuestos cambiaron. Revisa la compra."))

        amount = cash = 0.0
        for command in payload["statement_ids"]:
            values = command[2]
            method = session.payment_method_ids.sudo().filtered(lambda row: row.id == values["payment_method_id"])
            tender = values["amount"]
            if (
                not method or not method.active or method.use_payment_terminal or method.layaway_application
                or not math.isfinite(tender) or currency.compare_amounts(tender, 0) <= 0
            ):
                raise ValidationError(_("El cobro de la diferencia requiere un método de prueba disponible."))
            amount += tender
            if method.is_cash_count:
                cash += tender
        change = payload["amount_return"]
        if (
            not math.isfinite(change) or change < 0 or currency.compare_amounts(cash, change) < 0
            or currency.compare_amounts(amount - change, payable - credit.amount)
        ):
            raise ValidationError(_("El cobro neto debe coincidir con la diferencia de la compra."))

    def _process_payment_lines(self, pos_order, order, pos_session, draft):
        credit = self._purchase_credit()
        if credit:
            self._check_credit_order_amounts(pos_order, order, pos_session, credit)
        picking_type = order.config_id.picking_type_id
        pickings = self.env["stock.picking"]
        positive = pickings._layaway_positive_lines(order.lines)
        if not draft and positive and pickings._layaway_stock_location(picking_type):
            order.session_id._lock_layaway_stock_session()
            partner = order.partner_id
            destination = (
                partner.property_stock_customer or picking_type.default_location_dest_id
                or self.env["stock.warehouse"]._get_partner_locations()[0]
            )
            pickings._reserve_pos_sale(positive, picking_type, destination.id, partner, order)
        result = super()._process_payment_lines(pos_order, order, pos_session, draft)
        if credit:
            method = pos_session.config_id.sudo().layaway_application_method_id
            order.sudo().with_context(
                layaway_credit_token=_CREDIT_PURCHASE, layaway_credit_id=credit.id,
            ).add_payment({
                "pos_order_id": order.id, "amount": credit.amount,
                "payment_method_id": method.id, "payment_date": order.date_order,
            })
        return result

    def _create_order_picking(self):
        self.ensure_one()
        if self.sudo().layaway_ids:
            return
        holds = self.env["stock.picking"].sudo().search([
            ("layaway_hold_order_id", "=", self.id), ("state", "not in", ("done", "cancel")),
        ])
        if holds:
            if self.state == "draft":
                raise LayawayStockError(_("La venta no quedó pagada y no se confirmó la salida."))
            if not self.session_id.update_stock_at_closing or (
                self.company_id.anglo_saxon_accounting and self.to_invoice
            ):
                holds._complete_pos_sale_hold()
                holds.write({"pos_session_id": self.session_id.id, "pos_order_id": self.id})
        return super()._create_order_picking()

    @api.model_create_multi
    def create(self, vals_list):
        protected = ("layaway_ids", "layaway_application_move_ids", "layaway_credit_ids", "layaway_credit_amount")
        if not self.env.su and (
            any(set(protected).intersection(vals) for vals in vals_list)
            or any(self.env.context.get("default_" + field) for field in protected)
        ):
            raise AccessError(_("El vínculo de venta de apartado lo asigna el servidor."))
        return super().create(vals_list)

    def write(self, vals):
        fields_protected = {"layaway_ids", "layaway_application_move_ids", "layaway_credit_ids", "layaway_credit_amount"}
        if not self.env.su and fields_protected.intersection(vals):
            raise AccessError(_("El vínculo de venta de apartado lo asigna el servidor."))
        if self.sudo().layaway_application_move_ids and (
            {"lines", "payment_ids", "partner_id", "session_id", "company_id", "account_move",
             "fiscal_position_id", "pricelist_id", "amount_total", "amount_paid", "amount_tax",
             "amount_return", "date_order", "pos_reference", "name", "to_invoice",
             "picking_ids"}.intersection(vals)
            or "state" in vals and vals["state"] != "done"
        ):
            raise UserError(_("La venta final solo admite operaciones vinculadas al apartado."))
        return super().write(vals)

    def refund(self):
        if self.sudo().layaway_ids or self.sudo().layaway_credit_ids:
            raise UserError(_("La venta final solo admite operaciones vinculadas al apartado."))
        return super().refund()

    def _generate_pos_order_invoice(self):
        if self.sudo().layaway_ids or self.sudo().layaway_credit_ids:
            raise UserError(_("La venta de apartado de prueba no admite facturación."))
        return super()._generate_pos_order_invoice()


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    def _check_layaway_credit_lines(self, orders):
        if orders.sudo().layaway_credit_ids:
            raise UserError(_("La compra con saldo conserva sus líneas confirmadas."))

    @api.model_create_multi
    def create(self, vals_list):
        default_order = self.env.context.get("default_order_id")
        order_ids = [vals.get("order_id", default_order) for vals in vals_list]
        self._check_layaway_credit_lines(self.env["pos.order"].browse([order for order in order_ids if order]))
        return super().create(vals_list)

    def write(self, vals):
        orders = self.order_id | self.env["pos.order"].browse(vals.get("order_id"))
        self._check_layaway_credit_lines(orders)
        return super().write(vals)

    def unlink(self):
        self._check_layaway_credit_lines(self.order_id)
        return super().unlink()
