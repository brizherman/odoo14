from odoo import _, models
from odoo.exceptions import AccessError, UserError

from .pos_layaway_campaign import local_date
from .stock_picking import _RELOCATION_GUARD, LayawayStockError


class PosSession(models.Model):
    _inherit = "pos.session"

    def _layaway_relocation_destinations(self, folio, block):
        config = self.config_id
        picking_type = config.picking_type_id
        source = picking_type.default_location_src_id
        if (
            not self.env.user.has_group("point_of_sale.group_pos_manager")
            or not picking_type.warehouse_id.int_type_id.active
        ):
            return folio.participant_config_ids.browse()

        def valid(target):
            target_type = target.picking_type_id
            destination = target_type.default_location_src_id
            if (
                not target.active or not target_type.active or target.company_id != config.company_id
                or target_type.default_location_dest_id and target_type.default_location_dest_id.usage != "customer"
                or destination.usage != "internal" or destination.company_id != config.company_id
                or not source.parent_path or not destination.parent_path
                or destination.parent_path.startswith(source.parent_path)
                or source.parent_path.startswith(destination.parent_path)
            ):
                return False
            return all(
                line.location_id == destination
                for line in folio.line_ids - block
                if line.warehouse_id == target_type.warehouse_id and line.qty_pending
            )

        return (folio.participant_config_ids - config).filtered(valid)

    def relocate_layaway_block(self, folio_id, reference, destination_id, lines):
        """Record the physical transfer and reserve the same units at its destination."""
        session = self.sudo(False)
        session._check_layaway_pickup_test()
        folio = session._find_layaway(folio_id, require_open=False)
        if not session.env.user.has_group("point_of_sale.group_pos_manager"):
            raise AccessError(_("El encargado debe confirmar el traslado de mercancía."))
        destination_id = session.env["res.partner"]._wholesale_record_id(destination_id)
        quantities = session._normalize_layaway_block(lines)

        def apply(operation):
            session._lock_layaway_stock_session()
            if session.rescue or local_date(operation.create_date, folio.timezone) > folio.pickup_end:
                raise UserError(_("El traslado requiere una sesión ordinaria dentro del plazo de recogida."))
            block = session._validate_layaway_local_block(folio, quantities)
            destination = session._layaway_relocation_destinations(folio, block).filtered(
                lambda config: config.id == destination_id,
            )
            if not destination:
                raise UserError(_("Elige otra ubicación participante de la misma compañía para el traslado."))
            return folio, session._transfer_layaway_reservation(folio, operation, block, destination)

        return session.env["pos.layaway.operation"].sudo()._confirm(
            session, reference, "relocate_block", {"destination": destination_id, "lines": quantities},
            apply, layaway=folio, pass_operation=True,
        )

    def _transfer_layaway_reservation(self, folio, operation, block, destination_config):
        source_type = self.config_id.picking_type_id
        source = source_type.default_location_src_id
        destination_type = destination_config.picking_type_id
        destination = destination_type.default_location_src_id
        moves = self._checked_layaway_block_moves(folio, block, source)
        old_pickings = moves.picking_id
        reservations = {
            move.layaway_line_id.id: [
                (line.product_qty, line.location_id, line.lot_id, line.package_id, line.owner_id)
                for line in move.move_line_ids
            ] for move in moves
        }
        moved_lines = [self._layaway_pickup_line(line) for line in block]
        old_pickings.action_cancel()
        picking_model = old_pickings.env["stock.picking"]
        transfer = picking_model._create_layaway_picking(
            folio, block, source_type.warehouse_id.int_type_id, source, destination,
        )
        transfer.action_confirm()
        for move in transfer.move_lines:
            for qty, location, lot, package, owner in reservations[move.layaway_line_id.id]:
                move._update_reserved_quantity(qty, qty, location, lot, package, owner)
            move._recompute_state()
        transfer._require_stock_reserved()
        for line in transfer.move_line_ids:
            line.qty_done = line.product_uom_qty
        transfer.with_context(layaway_pickup_guard=_RELOCATION_GUARD)._action_done()
        if transfer.state != "done":
            raise LayawayStockError(_("No se pudo completar el traslado del bloque."))

        block.write({"warehouse_id": destination_type.warehouse_id.id, "location_id": destination.id})
        reservation = picking_model._create_layaway_picking(
            folio, block, destination_type, destination,
            origins={move.layaway_line_id.id: move.id for move in transfer.move_lines},
        )
        reservation.action_confirm()
        reservation.action_assign()
        reservation._require_stock_reserved()
        return {
            **operation._receipt_identification(folio, operation.create_date),
            "id": folio.id, "folio": folio.folio, "reference": operation.reference,
            "source": source.complete_name, "destination": destination.complete_name,
            "lines": moved_lines, "transfer_id": transfer.id, "transfer_name": transfer.name,
            "previous_reservation_ids": old_pickings.ids, "reservation_id": reservation.id,
        }
