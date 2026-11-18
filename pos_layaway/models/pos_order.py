from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .stock_picking import LayawayStockError


class PosOrder(models.Model):
    _inherit = "pos.order"

    layaway_ids = fields.One2many("pos.layaway", "sale_id", string="Apartado", readonly=True)
    layaway_application_move_ids = fields.Many2many(
        "account.move", string="Aplicación de cobros de apartados", readonly=True, copy=False,
    )
    wholesale_reason_code = fields.Selection(
        selection_add=[("layaway_payment", "Cobro confirmado de apartado")],
        ondelete={"layaway_payment": "set null"},
    )

    def _process_payment_lines(self, pos_order, order, pos_session, draft):
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
        return super()._process_payment_lines(pos_order, order, pos_session, draft)

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
        protected = ("layaway_ids", "layaway_application_move_ids")
        if not self.env.su and (
            any(set(protected).intersection(vals) for vals in vals_list)
            or any(self.env.context.get("default_" + field) for field in protected)
        ):
            raise AccessError(_("El vínculo de venta de apartado lo asigna el servidor."))
        return super().create(vals_list)

    def write(self, vals):
        fields_protected = {"layaway_ids", "layaway_application_move_ids"}
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
        if self.sudo().layaway_ids:
            raise UserError(_("La venta final solo admite operaciones vinculadas al apartado."))
        return super().refund()

    def _generate_pos_order_invoice(self):
        if self.sudo().layaway_ids:
            raise UserError(_("La venta de apartado de prueba no admite facturación."))
        return super()._generate_pos_order_invoice()
