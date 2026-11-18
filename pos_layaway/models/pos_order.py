from odoo import _, models

from .stock_picking import LayawayStockError


class PosOrder(models.Model):
    _inherit = "pos.order"

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
