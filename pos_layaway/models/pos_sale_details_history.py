import json
from collections import defaultdict

from odoo import _, api, models

from .pos_layaway_campaign import local_date


class ReportSaleDetails(models.AbstractModel):
    _inherit = "report.point_of_sale.report_saledetails"

    @api.model
    def _layaway_report_closing(self, folio_ids, selected_configs, accessible_configs, stop):
        if not folio_ids:
            return {}

        # Only folios from the period's authorized movements reach this method.
        # Use all dated stock events for those folios: a change at one store may
        # release stock at another. Authorize the resulting rows by warehouse.
        operations = self.env["pos.layaway.operation"].sudo().search([
            ("layaway_id", "in", list(folio_ids)), ("create_date", "<=", stop),
            ("result", "!=", False),
            ("kind", "in", (
                "open", "add_products", "change_products", "relocate_block", "pickup",
                "settle_pickup", "convert_expiry_credit", "apply_expiry_credit", "close_expiry_credit",
            )),
        ])
        operations_by_folio = defaultdict(list)
        for operation in operations:
            operations_by_folio[operation.layaway_id.id].append(operation)

        sessions = self.env["pos.session"].search([("config_id", "in", accessible_configs.ids)])
        paid_by_folio = {
            row["layaway_id"][0]: row["amount"]
            for row in self.env["pos.layaway.payment"].sudo().read_group([
                ("layaway_id", "in", list(folio_ids)), ("paid_at", "<=", stop),
                ("session_id", "in", sessions.ids),
            ], ["amount:sum"], ["layaway_id"])
        }
        selected_warehouse_ids = set(selected_configs.picking_type_id.warehouse_id.ids)
        accessible_warehouse_ids = set(self.env["stock.warehouse"].with_context(active_test=False).search([
            ("company_id", "in", self.env.companies.ids),
        ]).ids)
        accessible_config_ids = set(accessible_configs.ids)
        folios = self.env["pos.layaway"].sudo().browse(sorted(folio_ids))
        snapshots_by_group = defaultdict(list)
        for folio in folios:
            rows, credit, has_opening = self._layaway_replay_goods(operations_by_folio[folio.id])
            currency = folio.currency_id
            complete_scope = has_opening and set(folio.participant_config_ids.ids) <= accessible_config_ids
            visible_rows = []
            for (warehouse, _product, name), row in rows.items():
                if warehouse.id not in accessible_warehouse_ids:
                    complete_scope = False
                    continue
                visible_rows.append({
                    **row, "name": name, "store": warehouse.display_name,
                    "context": warehouse.id not in selected_warehouse_ids,
                    "reserved_value": currency.round(row["reserved_value"]),
                })
            paid = currency.round(paid_by_folio.get(folio.id, 0))
            reserved = currency.round(sum(row["reserved_value"] for row in visible_rows))
            due = None
            if complete_scope:
                delivered = sum(row["delivered_value"] for row in visible_rows)
                due = 0 if credit else currency.round(reserved + delivered - paid)
                if credit:
                    if credit["state"] == "available" and local_date(stop, folio.timezone) > folio.credit_end:
                        credit["state"] = "expired"
                    credit["label"] = {
                        "available": _("Disponible"), "consumed": _("Consumido"), "expired": _("Caducado"),
                    }[credit["state"]]
            snapshots_by_group[(folio.campaign_id.id, currency.id)].append({
                "folio": folio.folio, "customer": folio.contact_name,
                "pickup_end": folio.pickup_end, "paid": paid, "reserved": reserved,
                "due": due, "credit": credit if complete_scope else None,
                "rows": sorted(visible_rows, key=lambda row: (row["context"], row["store"], row["name"])),
            })

        closing = {}
        precision = self.env["decimal.precision"].precision_get("Product Unit of Measure")
        for key, snapshots in snapshots_by_group.items():
            currency = self.env["res.currency"].browse(key[1])
            closing[key] = {
                "folios": snapshots,
                "quantity_precision": precision,
                "reserved": currency.round(sum(snapshot["reserved"] for snapshot in snapshots)),
                "paid": currency.round(sum(snapshot["paid"] for snapshot in snapshots)),
            }
        return closing

    @api.model
    def _layaway_replay_goods(self, operations):
        """Rebuild stock quantities and value from the confirmed operation payloads."""
        rows = defaultdict(lambda: dict.fromkeys((
            "initial", "added", "transferred_in", "transferred_out", "released",
            "delivered", "pending", "reserved_value", "delivered_value",
        ), 0))
        credit = None
        has_opening = False

        def record(warehouse, line, column, direction):
            row = rows[warehouse, line["product_id"], line["product_name"]]
            qty = line["qty"]
            amount = line["amount_total"]
            row[column] += qty
            row["pending"] += direction * qty
            row["reserved_value"] += direction * amount
            if column == "delivered":
                row["delivered_value"] += amount

        def from_line(line, quantity):
            # Only agreement terms are read from the line. Its present location
            # and picked quantity may reflect operations after the cutoff.
            return {
                "product_id": line.product_id.id, "product_name": line.product_name,
                "qty": quantity, "amount_total": line.amount_total * quantity / line.qty,
            }

        for operation in operations:
            payload = json.loads(operation.result)
            warehouse = operation.warehouse_id
            warehouses = operation.env["stock.warehouse"]
            lines = operation.env["pos.layaway.line"]
            if operation.kind in ("open", "add_products"):
                opening = operation.kind == "open"
                has_opening |= opening
                for line in payload["quote"]["lines"]:
                    record(warehouse, line, "initial" if opening else "added", 1)
            elif operation.kind == "change_products":
                removed = set(payload["removed_ids"])
                for line in payload["previous_lines"]:
                    if line["id"] in removed:
                        record(warehouses.browse(line["warehouse_id"]), line, "released", -1)
                for line in payload["lines"]:
                    record(warehouse, line, "added", 1)
            elif operation.kind == "relocate_block":
                destination = warehouses.browse(payload.get("destination_warehouse_id")) or (
                    operation.env["stock.picking"].browse(payload["reservation_id"]).picking_type_id.warehouse_id
                )
                for snapshot in payload["lines"]:
                    line = from_line(lines.browse(snapshot["id"]), snapshot["qty"])
                    record(warehouse, line, "transferred_out", -1)
                    record(destination, line, "transferred_in", 1)
            elif operation.kind in ("pickup", "settle_pickup"):
                for snapshot in payload.get("pickup", payload)["delivered"]:
                    record(warehouse, from_line(lines.browse(snapshot["id"]), snapshot["qty"]), "delivered", -1)
            elif operation.kind == "convert_expiry_credit":
                credit = payload["credit"]
                for snapshot in payload["released_lines"]:
                    line = lines.browse(snapshot["id"])
                    # Conversion releases these lines permanently, fixing their final warehouse.
                    record(line.warehouse_id, from_line(line, snapshot["qty"]), "released", -1)
            elif credit:
                credit["state"] = "consumed" if operation.kind == "apply_expiry_credit" else "expired"

        return rows, credit, has_opening
