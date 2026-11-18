from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare

from .pos_layaway_payment import layaway_test_database


_PICKUP_GUARD = object()
_RELOCATION_GUARD = object()


class LayawayStockError(UserError):
    """A POS sale could not obtain or complete its stock reservation."""


class StockPicking(models.Model):
    _inherit = "stock.picking"

    layaway_id = fields.Many2one(
        "pos.layaway", index=True, ondelete="restrict", copy=False, readonly=True,
    )
    layaway_hold_order_id = fields.Many2one(
        "pos.order", index=True, ondelete="restrict", copy=False, readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        protected = {"layaway_id", "layaway_hold_order_id"}
        if not self.env.su and (
            any(protected.intersection(vals) for vals in vals_list)
            or any(self.env.context.get("default_" + field) for field in protected)
        ):
            raise AccessError(_("La referencia de la reserva la asigna el servidor."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and {"layaway_id", "layaway_hold_order_id"}.intersection(vals):
            raise AccessError(_("La referencia de la reserva la asigna el servidor."))
        return super().write(vals)

    def button_validate(self):
        if self.sudo().layaway_id:
            raise AccessError(_("Registra la recogida desde el apartado."))
        return super().button_validate()

    def _send_confirmation_email(self):
        ordinary = self.filtered(lambda picking: not picking.layaway_id)
        return super(StockPicking, ordinary)._send_confirmation_email()

    @api.model
    def _layaway_stock_location(self, picking_type):
        source = picking_type.default_location_src_id
        if source.usage != "internal":
            return False
        locations = self.env["stock.location"].sudo()
        overlapping = locations.search([
            "|", ("id", "child_of", source.id), ("id", "parent_of", source.id),
        ])
        if self.sudo().search_count([
            ("layaway_id", "!=", False), ("state", "not in", ("done", "cancel")),
            ("location_id", "in", overlapping.ids),
        ]):
            return True
        if self.env["pos.layaway"].sudo().search_count([
            ("pickup_state", "!=", "done"),
            ("participant_config_ids.picking_type_id.default_location_src_id", "in", overlapping.ids),
        ]):
            return True
        configs = self.env["pos.layaway.campaign"].sudo().search([
            ("state", "=", "active"),
        ]).pos_config_ids
        return any(
            config.picking_type_id.default_location_src_id in overlapping for config in configs
        )

    def _require_stock_reserved(self):
        for move in self.move_lines.filtered(lambda record: record.product_id.type == "product"):
            if float_compare(
                move.reserved_availability, move.product_uom_qty,
                precision_rounding=move.product_uom.rounding,
            ) != 0:
                raise LayawayStockError(
                    _("No hay existencias libres suficientes para %s.") % move.product_id.display_name
                )

    @api.model
    def _reserve_layaway_lines(self, layaway, session, lines):
        """Assign stock in the current shop and leave all done quantities at zero."""
        if not self.env.su:
            raise AccessError(_("La reserva requiere una operación del servidor."))
        session._check_layaway_session()
        if session.config_id not in layaway.participant_config_ids:
            raise AccessError(_("El apartado no pertenece a esta caja."))
        picking_type = session.config_id.picking_type_id
        source = picking_type.default_location_src_id
        if source.usage != "internal" or source.company_id != session.company_id:
            raise UserError(_("La caja debe tener una ubicación interna de su compañía."))
        if not lines or any(
            line.layaway_id != layaway
            or line.warehouse_id != picking_type.warehouse_id
            or line.location_id != source
            or line.product_id.type != "product"
            or line.product_id.company_id and line.product_id.company_id != session.company_id
            for line in lines
        ):
            raise UserError(_("La mercancía no corresponde a la tienda del apartado."))
        # A second call for the same lines must run through the operation ledger.
        with self.env.cr.savepoint():
            self.env.cr.execute("SELECT id FROM pos_layaway WHERE id = %s FOR UPDATE", (layaway.id,))
            layaway._check_reservation_coverage()
            self.env.cr.execute(
                "UPDATE pos_layaway_line SET write_date = %s WHERE id IN %s",
                (fields.Datetime.now(), tuple(lines.ids)),
            )
            if self.env["stock.move"].search_count([
                ("layaway_line_id", "in", lines.ids), ("state", "not in", ("done", "cancel")),
            ]):
                raise UserError(_("La mercancía del apartado ya tiene una reserva."))
            picking = self._create_layaway_picking(layaway, lines, picking_type, source)
            picking.action_confirm()
            picking.action_assign()
            picking._require_stock_reserved()
            return picking

    @api.model
    def _create_layaway_picking(self, folio, lines, picking_type, source, destination=None, origins=None):
        picking_model = self.with_company(picking_type.company_id)
        destination = destination or (
            picking_type.default_location_dest_id or self.env["stock.warehouse"]._get_partner_locations()[0]
        )
        picking = picking_model.create({
            **picking_model._prepare_picking_vals(folio.partner_id, picking_type, source.id, destination.id),
            "layaway_id": folio.id,
            "origin": folio.folio,
        })
        picking.env["stock.move"].create([{
            "name": line.product_name,
            "product_id": line.product_id.id,
            "product_uom": line.product_id.uom_id.id,
            "product_uom_qty": line.qty_pending,
            "location_id": source.id,
            "location_dest_id": destination.id,
            "company_id": picking_type.company_id.id,
            "picking_id": picking.id,
            "picking_type_id": picking_type.id,
            "layaway_line_id": line.id,
            "move_orig_ids": [(4, origins[line.id])] if origins else [],
        } for line in lines])
        return picking

    @api.model
    def _layaway_positive_lines(self, lines):
        return lines.filtered(lambda line: line.qty > 0 and line.product_id.type in ("product", "consu"))

    @api.model
    def _reserve_pos_sale(self, lines, picking_type, destination_id, partner, order=False):
        """Use the native POS move preparation, including the lots selected at the till."""
        source = picking_type.default_location_src_id
        model = self.sudo().with_company(picking_type.company_id).with_context(
            bypass_reservation_update=False
        )
        picking = model.create({
            **model._prepare_picking_vals(partner, picking_type, source.id, destination_id),
            "layaway_hold_order_id": order.id if order else False,
            "origin": order.name if order else False,
        })
        picking._create_move_from_pos_order_lines(lines)
        for move_line in picking.move_line_ids.filtered(
            lambda line: line.product_id.tracking != "none" and line.qty_done and not line.product_qty
        ):
            picking._reserve_pos_lot(move_line, source)
        picking.move_lines._recompute_state()
        picking._require_stock_reserved()
        picking.move_line_ids.write({"qty_done": 0})
        return picking

    def _reserve_pos_lot(self, move_line, source):
        if not move_line.lot_id:
            raise LayawayStockError(_("Indica un lote o número de serie existente para %s.")
                            % move_line.product_id.display_name)
        product = move_line.product_id
        quantity = move_line.product_uom_id._compute_quantity(move_line.qty_done, product.uom_id)
        lot = move_line.lot_id
        move = move_line.move_id
        move_line.unlink()
        quants = self.env["stock.quant"]._gather(product, source, lot_id=lot)
        for quant in quants.filtered(lambda item: item.lot_id == lot):
            available = quant.quantity - quant.reserved_quantity
            if available > 0 and quantity > 0:
                quantity -= move._update_reserved_quantity(
                    quantity, available, quant.location_id, lot_id=quant.lot_id,
                    package_id=quant.package_id, owner_id=quant.owner_id, strict=True,
                )
        if float_compare(quantity, 0, precision_rounding=product.uom_id.rounding) > 0:
            raise LayawayStockError(_("No hay existencias libres del lote %s.") % lot.name)

    def _complete_pos_sale_hold(self):
        for picking in self:
            picking._require_stock_reserved()
            for line in picking.move_line_ids:
                line.qty_done = line.product_uom_qty
            picking._action_done()
            if picking.state != "done":
                raise LayawayStockError(_("No se pudo validar la salida de la venta POS."))

    @api.model
    def _create_picking_from_pos_order_lines(self, location_dest_id, lines, picking_type, partner=False):
        lines = lines.filtered(lambda line: not line.order_id.sudo().layaway_ids)
        if not lines:
            return self.browse()
        order_ids = lines.order_id.ids
        holds = self.sudo().search([
            ("layaway_hold_order_id", "in", order_ids), ("state", "=", "done"),
        ]) if order_ids else self.browse()
        already_done = set(holds.layaway_hold_order_id.ids)
        positive = self._layaway_positive_lines(lines)
        covered = positive.filtered(lambda line: line.order_id.id in already_done)
        result = self.browse()
        if positive - covered and self._layaway_stock_location(picking_type):
            # Handles deferred orders created before the module was installed.
            picking = self._reserve_pos_sale(positive - covered, picking_type, location_dest_id, partner)
            picking._complete_pos_sale_hold()
            result |= self.browse(picking.id)
            covered = positive
        return result | super()._create_picking_from_pos_order_lines(
            location_dest_id, lines - covered, picking_type, partner,
        )


class StockMove(models.Model):
    _inherit = "stock.move"

    layaway_line_id = fields.Many2one(
        "pos.layaway.line", ondelete="restrict", copy=False, readonly=True, index=True,
    )

    def _prepare_merge_moves_distinct_fields(self):
        return super()._prepare_merge_moves_distinct_fields() + ["layaway_line_id"]

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and (
            any("layaway_line_id" in vals for vals in vals_list)
            or self.env.context.get("default_layaway_line_id")
        ):
            raise AccessError(_("La referencia de la reserva la asigna el servidor."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and (
            "layaway_line_id" in vals or (
                ("picking_id" in vals or vals.get("state") == "done")
                and self.sudo().layaway_line_id
            )
        ):
            raise AccessError(_("La referencia de la reserva la asigna el servidor."))
        return super().write(vals)

    @api.model
    def _layaway_reserved_moves(self, folio, lines):
        moves = self.search([
            ("layaway_line_id", "in", lines.ids), ("state", "not in", ("done", "cancel")),
        ])
        # Inventory can also change reservations outside the POS.
        for table, ids in (
            ("stock_picking", moves.picking_id.ids), ("stock_move", moves.ids),
            ("stock_move_line", moves.move_line_ids.ids),
        ):
            if ids:
                self.env.cr.execute(
                    "SELECT id FROM %s WHERE id IN %%s ORDER BY id FOR UPDATE" % table, (tuple(ids),),
                )
        by_line = defaultdict(lambda: self.browse())
        for move in moves:
            by_line[move.layaway_line_id.id] |= move
        for line in lines:
            move = by_line[line.id]
            if (
                len(move) != 1 or move.picking_id.layaway_id != folio
                or move.state != "assigned" or move.picking_id.state != "assigned"
                or move.product_id != line.product_id or move.location_id != line.location_id
                or move.company_id != line.warehouse_id.company_id
                or move.product_uom != line.product_id.uom_id
                or float_compare(move.reserved_availability, line.qty_pending,
                                 precision_rounding=line.product_id.uom_id.rounding)
                or any(move.move_line_ids.mapped("qty_done"))
            ):
                raise LayawayStockError(_("La reserva de %s en %s debe estar completa.")
                                        % (line.product_name, line.warehouse_id.display_name))
        return moves

    def _action_done(self, cancel_backorder=False):
        moves = self.sudo()
        folios = moves.picking_id.layaway_id | moves.layaway_line_id.layaway_id
        if folios:
            if not layaway_test_database(self.env):
                raise AccessError(_("La entrega de apartados solo está disponible para pruebas."))
            guard = self.env.context.get("layaway_pickup_guard")
            relocation = guard is _RELOCATION_GUARD and all(
                move.picking_type_id.code == "internal" and move.location_dest_id.usage == "internal"
                for move in moves
            )
            if not relocation:
                for folio in folios:
                    folio._check_pickup_payment()
            if not self.env.su or not (guard is _PICKUP_GUARD or relocation):
                raise AccessError(_("Registra la recogida desde el apartado."))
        return super()._action_done(cancel_backorder=cancel_backorder)


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    @api.model_create_multi
    def create(self, vals_list):
        picking_model = self.env["stock.picking"].sudo()
        move_model = self.env["stock.move"].sudo()
        for vals in vals_list:
            picking = picking_model.browse(vals.get("picking_id", self.env.context.get("default_picking_id")))
            move = move_model.browse(vals.get("move_id", self.env.context.get("default_move_id")))
            if (picking.layaway_id and picking.state == "done") or (
                move.layaway_line_id and move.state == "done"
            ):
                raise AccessError(_("La salida confirmada conserva sus movimientos de inventario."))
        return super().create(vals_list)

    def write(self, vals):
        if {
            "qty_done", "state", "move_id", "picking_id", "product_id", "product_uom_id",
            "location_id", "location_dest_id", "lot_id", "package_id", "result_package_id", "owner_id",
        }.intersection(vals) and any(
            line.state == "done" and (line.move_id.layaway_line_id or line.picking_id.layaway_id)
            for line in self.sudo()
        ):
            raise AccessError(_("La salida confirmada conserva sus movimientos de inventario."))
        return super().write(vals)

    def _free_reservation(self, product_id, location_id, quantity, lot_id=None,
                          package_id=None, owner_id=None, ml_to_ignore=None):
        quant = self.env["stock.quant"].sudo()
        available = quant._get_available_quantity(
            product_id, location_id, lot_id=lot_id, package_id=package_id,
            owner_id=owner_id, strict=True,
        )
        if float_compare(quantity, available, precision_rounding=product_id.uom_id.rounding) > 0:
            protected = self.sudo().search_count([
                ("product_id", "=", product_id.id), ("location_id", "=", location_id.id),
                ("lot_id", "=", lot_id.id if lot_id else False),
                ("package_id", "=", package_id.id if package_id else False),
                ("owner_id", "=", owner_id.id if owner_id else False),
                ("product_qty", ">", 0), ("state", "not in", ["done", "cancel"]),
                ("id", "not in", self.ids + (ml_to_ignore.ids if ml_to_ignore is not None else [])),
                "|", ("picking_id.layaway_id", "!=", False),
                ("picking_id.layaway_hold_order_id", "!=", False),
            ])
            if protected:
                raise UserError(_("La salida usaría existencias reservadas para un apartado o venta POS."))
        return super()._free_reservation(
            product_id, location_id, quantity, lot_id=lot_id, package_id=package_id,
            owner_id=owner_id, ml_to_ignore=ml_to_ignore,
        )
