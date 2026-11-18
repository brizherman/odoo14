import json
from collections import defaultdict

from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

from .pos_layaway_campaign import local_date
from .pos_layaway_payment import layaway_test_database
from .stock_picking import _PICKUP_GUARD, LayawayStockError


class PosSession(models.Model):
    _inherit = "pos.session"

    def _check_layaway_pickup_test(self):
        if not layaway_test_database(self.env):
            raise AccessError(_("La entrega de apartados solo está disponible para pruebas."))

    def _layaway_pickup_block(self, folio):
        warehouse = self.config_id.picking_type_id.warehouse_id
        return folio.line_ids.filtered(lambda line: line.warehouse_id == warehouse and line.qty_pending)

    def _layaway_pickup_operations(self, folio, kind):
        return self.env["pos.layaway.operation"].sudo().search([
            ("layaway_id", "=", folio.id), ("kind", "=", kind), ("result", "!=", False),
        ])

    def register_layaway_pickup_authorization(self, folio_id, reference, partner_id):
        """Register an identified recipient in a separate operation before collection."""
        session = self.sudo(False)
        session._check_layaway_pickup_test()
        folio = session._find_layaway(folio_id, require_open=False)
        if not session.env.user.has_group("point_of_sale.group_pos_manager"):
            raise AccessError(_("El encargado debe registrar al autorizado para recoger."))
        partners = session.env["res.partner"]
        partner_id = partners._wholesale_record_id(partner_id)

        def apply(operation):
            session._lock_layaway_stock_session()
            if session.rescue or folio.pickup_state == "done":
                raise UserError(_("El apartado no admite autorizaciones de recogida."))
            partner = partners.with_context(active_test=True).search([
                ("id", "=", partner_id), ("active", "=", True), ("is_company", "=", False),
            ], limit=1)
            if not partner or partner.id == folio.partner_id.id or not (partner.name or "").strip():
                raise ValidationError(_("Selecciona una persona identificada distinta del titular."))
            return folio, {
                "reference": operation.reference,
                "partner_id": partner.id,
                "name": partner.name,
                "registered_by": operation.user_id.name,
                "registered_at": operation._receipt_identification(
                    folio, operation.create_date,
                )["confirmed_at"],
            }

        return session.env["pos.layaway.operation"].sudo()._confirm(
            session, reference, "authorize_pickup", {"partner_id": partner_id}, apply,
            layaway=folio, pass_operation=True,
        )

    def confirm_layaway_pickup(self, folio_id, reference, recipient, lines):
        """Confirm the complete local block and record the cashier's identity check."""
        session = self.sudo(False)
        session._check_layaway_pickup_test()
        folio = session._find_layaway(folio_id, require_open=False)
        if (
            not isinstance(recipient, dict) or recipient.get("identity_verified") is not True
            or recipient.get("kind") not in ("holder", "authorized")
        ):
            raise ValidationError(_("Identifica al receptor y confirma que verificaste su identidad."))
        kind = recipient["kind"]
        authorization = recipient.get("authorization_reference")
        if (
            (kind == "authorized" and (not isinstance(authorization, str) or len(authorization) != 36))
            or (kind == "holder" and authorization is not None and authorization is not False)
        ):
            raise ValidationError(_("Selecciona una autorización registrada para el receptor."))
        if not isinstance(lines, list) or not lines:
            raise ValidationError(_("Confirma las cantidades pendientes de la tienda."))
        quantities = {}
        for line in lines:
            if not isinstance(line, dict):
                raise ValidationError(_("Las cantidades de recogida no son válidas."))
            line_id, qty = line.get("id"), line.get("qty")
            if (
                type(line_id) is not int or line_id <= 0 or line_id in quantities
                or type(qty) not in (int, float) or not 0 < qty < 1e15
            ):
                raise ValidationError(_("Las cantidades de recogida no son válidas."))
            quantities[line_id] = float(qty)
        payload = {
            "recipient": kind, "authorization": authorization or False,
            "lines": sorted(quantities.items()),
        }
        return session.env["pos.layaway.operation"].sudo()._confirm(
            session, reference, "pickup", payload,
            lambda operation: session._apply_layaway_pickup(operation, folio, kind, authorization, quantities),
            layaway=folio, pass_operation=True,
        )

    def _apply_layaway_pickup(self, operation, folio, kind, authorization, quantities):
        self._lock_layaway_stock_session()
        if self.rescue:
            raise UserError(_("La recogida requiere una sesión ordinaria."))
        folio._check_pickup_payment()
        if local_date(operation.create_date, folio.timezone) > folio.pickup_end:
            raise UserError(_("Terminó el plazo de recogida del apartado."))
        recipient = {"partner_id": folio.partner_id.id, "name": folio.contact_name}
        if kind == "authorized":
            registration = self.env["pos.layaway.operation"].sudo().search([
                ("reference", "=", authorization), ("kind", "=", "authorize_pickup"),
                ("layaway_id", "=", folio.id), ("result", "!=", False),
            ], limit=1)
            if not registration:
                raise ValidationError(_("El receptor debe estar autorizado previamente en este apartado."))
            recipient = json.loads(registration.result)
        picking_type = self.config_id.picking_type_id
        source = picking_type.default_location_src_id
        lines = self._layaway_pickup_block(folio)
        if not lines or quantities != {line.id: line.qty_pending for line in lines}:
            raise ValidationError(_("Confirma exactamente el bloque pendiente de esta tienda."))
        if source.usage != "internal" or source.company_id != self.company_id or any(
            line.location_id != source for line in lines
        ):
            raise UserError(_("La mercancía no está reservada en la ubicación de esta caja."))

        stock_model = self.env["stock.move"].sudo().with_context(
            {}, allowed_company_ids=self.company_id.ids,
        )
        moves = stock_model._layaway_reserved_moves(folio, lines)
        pickings = moves.picking_id
        if pickings.owner_id or pickings.move_lines.filtered(lambda move: move.state != "cancel") != moves:
            raise LayawayStockError(_("La reserva contiene mercancía ajena al bloque de la tienda."))
        if any(float_compare(
            move.product_uom_qty, move.layaway_line_id.qty_pending,
            precision_rounding=move.product_uom.rounding,
        ) for move in moves):
            raise LayawayStockError(_("La demanda de inventario difiere del bloque pendiente."))
        self._check_layaway_pickup_quants(moves, source)
        delivered = [self._layaway_pickup_line(line) for line in lines]
        for move_line in moves.move_line_ids:
            move_line.qty_done = move_line.product_uom_qty
        pickings.with_context(layaway_pickup_guard=_PICKUP_GUARD)._action_done()
        if any(picking.state != "done" for picking in pickings):
            raise LayawayStockError(_("No se pudo validar la salida completa del apartado."))
        for line in lines:
            line.qty_picked_up = line.qty

        return folio, {
            "reference": operation.reference, "id": folio.id, "folio": folio.folio,
            "sale_id": folio.sale_id.id, "sale_name": folio.sale_id.name,
            "warehouse": operation.warehouse_id.display_name,
            **operation._receipt_identification(folio, operation.create_date),
            "recipient": dict(recipient, kind=kind, identity_verified=True),
            "picking_ids": pickings.ids, "delivered": delivered,
            "pickup_state": folio.pickup_state,
            "pending": [self._layaway_pickup_line(line) for line in folio.line_ids if line.qty_pending],
        }

    def _check_layaway_pickup_quants(self, moves, source):
        stock = moves.env["stock.quant"]
        locations = moves.env["stock.location"].search([
            ("id", "child_of", source.id), ("usage", "=", "internal"),
            ("company_id", "=", source.company_id.id),
        ])
        quantities = defaultdict(float)
        for line in moves.move_line_ids:
            move = line.move_id
            if (
                line.picking_id != move.picking_id or move.picking_id.location_id != source
                or line.location_id not in locations or line.location_dest_id != move.location_dest_id
                or move.location_dest_id != move.picking_id.location_dest_id
                or move.location_dest_id.usage != "customer"
                or line.product_id != move.product_id or line.company_id != source.company_id
                or line.product_id.tracking != "none" and not line.lot_id
                or line.product_qty <= 0
            ):
                raise LayawayStockError(_("La reserva contiene ubicaciones o cantidades no válidas."))
            key = (line.product_id, line.location_id, line.lot_id, line.package_id, line.owner_id)
            quantities[key] += line.product_qty
        for (product, location, lot, package, owner), qty in quantities.items():
            quants = stock._gather(product, location, lot_id=lot, package_id=package,
                                   owner_id=owner, strict=True).filtered(lambda quant: quant.lot_id == lot)
            if quants:
                stock.env.cr.execute(
                    "SELECT id FROM stock_quant WHERE id IN %s ORDER BY id FOR UPDATE", (tuple(quants.ids),),
                )
            if any(float_compare(
                sum(quants.mapped(field)), qty, precision_rounding=product.uom_id.rounding,
            ) < 0 for field in ("quantity", "reserved_quantity")):
                raise LayawayStockError(_("La reserva física de %s ya no está completa.") % product.display_name)

    def _layaway_pickup_line(self, line):
        return {
            "id": line.id, "name": line.product_name, "qty": line.qty_pending,
            "store": line.warehouse_id.display_name, "location": line.location_id.complete_name,
        }

    def _layaway_pickup_detail(self, folio):
        block = self._layaway_pickup_block(folio)
        return {
            "available": bool(
                layaway_test_database(self.env) and not self.rescue and block and folio.sale_id
                and folio.payment_state == "paid"
                and local_date(fields.Datetime.now(), folio.timezone) <= folio.pickup_end
            ),
            "lines": [self._layaway_pickup_line(line) for line in block],
            "authorizations": [
                json.loads(operation.result)
                for operation in self._layaway_pickup_operations(folio, "authorize_pickup")
            ],
            "history": [
                json.loads(operation.result)
                for operation in self._layaway_pickup_operations(folio, "pickup")
            ],
        }
