import json
import re
from collections import defaultdict

from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.osv import expression

from .pos_layaway_campaign import local_date
from .pos_layaway_payment import layaway_test_database


class PosSession(models.Model):
    _inherit = "pos.session"

    def _layaway_query_domain(self, require_open=True):
        self._check_layaway_session(require_open=require_open)
        return [("participant_config_ids", "in", self.config_id.ids)]

    def _find_layaway(self, record_id, require_open=True):
        domain = self._layaway_query_domain(require_open=require_open)
        folio = self.env["pos.layaway"].sudo().search(
            domain + [("id", "=", self.env["res.partner"]._wholesale_record_id(record_id))],
            limit=1,
        )
        if not folio:
            raise AccessError(_("El apartado no está disponible en esta caja."))
        return folio

    def _layaway_receipt_operations(self, domain):
        self._check_layaway_session()
        operations = self.env["pos.layaway.operation"].sudo()
        return operations.search(domain + [
            ("layaway_id.participant_config_ids", "in", self.config_id.ids),
            ("kind", "in", operations._receipt_kinds),
            ("result", "!=", False),
        ])

    def _layaway_receipt(self, folio_id, reference, original=False, final_sale=False, pickup=False):
        operation = self._layaway_receipt_operations([
            ("layaway_id", "=", folio_id), ("reference", "=", reference),
        ])
        result = json.loads(operation.result) if operation else {}
        if final_sale and result.get("settlement"):
            result["ticket"] = operation._sale_ticket_values(result)
        elif not final_sale and (operation.kind == "pickup" or pickup and result.get("pickup")):
            result = result.get("pickup", result)
            # Older pickup operations already saved the physical handover and receipt metadata.
            result.setdefault("campaign_name", operation.layaway_id.campaign_name)
            result.setdefault("contact_name", operation.layaway_id.contact_name)
            result.setdefault("phone", operation.layaway_id.phone)
            result["pickup_receipt"] = True
        elif final_sale or pickup or not result.get("receipt"):
            raise AccessError(_("El comprobante original no está disponible."))
        return result, not (original and operation.session_id.id == self.id)

    def get_layaway_detail(self, record_id):
        folio = self._find_layaway(record_id)
        now = fields.Datetime.now()
        credit = folio.expiry_credit_id
        credit_status = False
        if credit:
            credit_status = credit._pos_layaway_credit_values()
            if credit.closure_id:
                credit_status["closure"] = json.loads(credit.closure_id.result)
            elif credit.consumption_id:
                credit_status["consumption"] = json.loads(credit.consumption_id.result)
            elif (
                layaway_test_database(self.env) and not self.rescue and credit._state_at(now) == "expired"
                and self.env.user.has_group("point_of_sale.group_pos_manager")
            ):
                credit_status["can_close"] = True
        can_review_expired = bool(
            layaway_test_database(self.env) and not self.rescue
            and self.env.user.has_group("point_of_sale.group_pos_manager") and folio._layaway_pickup_overdue(now)
        )
        receipts = []
        for operation in self._layaway_receipt_operations([("layaway_id", "=", folio.id)]):
            result = json.loads(operation.result)
            receipt = result.get("receipt")
            if result.get("settlement"):
                receipts.append({
                    "reference": operation.reference, "kind": "final_sale", "available": True,
                })
            if operation.kind == "pickup" or result.get("pickup"):
                receipts.append({
                    "reference": operation.reference, "kind": "pickup", "available": True,
                })
                if operation.kind == "pickup":
                    continue
            # Legacy settlements can have a sale or pickup snapshot without a
            # separate payment receipt.
            if not receipt and not (
                operation.kind in ("open", "add_products")
                or (operation.kind == "installment" and result.get("amount_applied"))
            ):
                continue
            receipts.append({
                "reference": operation.reference,
                "kind": receipt["kind"] if receipt else operation.kind,
                "available": bool(receipt),
            })
        installment_methods = self.env["pos.payment.method"]
        if (
            layaway_test_database(self.env) and not self.rescue
            and (not folio.sale_id or folio._layaway_adjustable_sale())
            and self.currency_id == folio.currency_id == self.company_id.currency_id
            and not folio.currency_id.is_zero(folio.amount_due)
            and local_date(fields.Datetime.now(), folio.timezone) <= folio.pickup_end
        ):
            installment_methods = self._layaway_checkout_methods()
        sale = folio.sale_id.with_env(self.env)
        can_open_sale = (
            sale and sale.check_access_rights("read", raise_exception=False)
            and sale._filter_access_rules("read")
        )
        return {
            **folio._pos_layaway_values(folio._layaway_reserved_quantities(), detail=True),
            "receipts": receipts,
            "installment_methods": [{
                "id": method.id, "name": method.name, "cash": method.is_cash_count,
            } for method in installment_methods],
            "campaign_id": folio.campaign_id.id,
            "sale_url": "/web#model=pos.order&id=%s&view_type=form" % sale.id if can_open_sale else False,
            "can_add_products": (
                layaway_test_database(self.env)
                and folio._layaway_can_modify_products(fields.Datetime.now())
            ),
            "sale_adjustments": folio._layaway_adjustment_history(),
            "merchandise_history": folio._layaway_merchandise_history(),
            "pickup": self._layaway_pickup_detail(folio),
            "expiry_review": {
                "can_review": can_review_expired,
                "can_convert": can_review_expired and folio._can_convert_layaway_to_credit(),
                "credit_end": fields.Date.to_string(folio.credit_end),
                "history": [
                    json.loads(review.result)
                    for review in self._layaway_pickup_operations(folio, ("review_expiry", "convert_expiry_credit"))
                ],
            },
            "expiry_credit": credit_status,
            "transfer_review": self._layaway_transfer_detail(folio),
            "payment_corrections": self._layaway_correction_detail(folio),
            "changeable_lines": (
                self._layaway_changeable_lines(folio).ids
                if self._can_change_layaway(folio, fields.Datetime.now()) else []
            ),
        }

    def get_layaways(self, filters=None, offset=0):
        scope = self._layaway_query_domain()
        folios = self.env["pos.layaway"].sudo()
        filters = filters or {}
        if not isinstance(filters, dict) or type(offset) is not int or offset < 0:
            raise ValidationError(_("Los filtros de apartados no son válidos."))

        scope_filters = folios._pos_layaway_filter_options(scope)
        domain = scope + folios._pos_layaway_filter_domain(filters, scope)
        page_size = 30
        page = folios.search(domain, offset=offset, limit=page_size + 1)
        visible = page[:page_size]
        reserved = visible._layaway_reserved_quantities()
        return {
            "rows": [folio._pos_layaway_values(reserved) for folio in visible],
            "has_more": len(page) > page_size,
            "can_open_layaway": self.config_id.layaway_enabled and layaway_test_database(self.env),
            "can_review_expired": self.env.user.has_group("point_of_sale.group_pos_manager"),
            **scope_filters,
        }


class PosLayaway(models.Model):
    _inherit = "pos.layaway"

    def _layaway_pickup_overdue(self, now):
        self.ensure_one()
        return self.pickup_state in ("pending", "partial") and self.pickup_end < local_date(now, self.timezone)

    def _pos_layaway_filter_options(self, scope):
        campaigns = self.read_group(scope, ["campaign_id"], ["campaign_id"])
        shops = self.env["pos.layaway.line"].read_group(
            self._layaway_store_line_domain(scope),
            ["warehouse_id"], ["warehouse_id"],
        )
        return {
            "campaigns": [{"id": row["campaign_id"][0], "name": row["campaign_id"][1]}
                          for row in campaigns],
            "stores": [{"id": row["warehouse_id"][0], "name": row["warehouse_id"][1]}
                       for row in shops],
        }

    def _layaway_store_line_domain(self, scope):
        return expression.AND([
            [("layaway_id." + field, operator, value) for field, operator, value in scope],
            ["|", ("released_by_id", "=", False),
             ("released_by_id.kind", "=", "convert_expiry_credit")],
        ])

    def _pos_layaway_filter_domain(self, filters, scope):
        domain = []
        query = filters.get("query")
        if isinstance(query, str) and query.strip():
            query = query.strip()[:100]
            token = re.sub(r"([%_\\])", r"\\\1", query)
            search = [[("folio", "ilike", token)], [("contact_name", "ilike", token)]]
            digits = "".join(char for char in query if char.isdecimal())
            if digits and all(char.isdecimal() or char in " +().-" for char in query):
                search.append([("phone_digits", "like", digits)])
            domain += expression.OR(search)
        record_id = self.env["res.partner"]._wholesale_record_id
        if filters.get("campaign"):
            domain.append(("campaign_id", "=", record_id(filters["campaign"])))
        if filters.get("store"):
            lines = self.env["pos.layaway.line"]._search(
                self._layaway_store_line_domain(scope)
                + [("warehouse_id", "=", record_id(filters["store"]))],
            )
            domain.append(("line_ids", "in", lines))
        for key, operator in (("from", ">="), ("to", "<=")):
            if filters.get(key):
                try:
                    date = fields.Date.to_date(filters[key])
                except (TypeError, ValueError):
                    raise ValidationError(_("La fecha del filtro no es válida."))
                domain.append(("opened_on", operator, date))
        for state in ("payment_state", "pickup_state"):
            if filters.get(state):
                domain.append((state, "=", filters[state]))
        expiry = filters.get("expiry")
        credit_state = filters.get("credit_state")
        if expiry in ("expired", "current", "expired_credit") or credit_state in ("available", "expired"):
            timezones = self.read_group(scope, ["timezone"], ["timezone"])
            now = fields.Datetime.now()

            def past_deadline(field):
                return expression.OR([
                    [("timezone", "=", row["timezone"]), (field, "<", local_date(now, row["timezone"]))]
                    for row in timezones
                ])

            if expiry in ("expired", "current"):
                overdue = expression.AND([
                    [("pickup_state", "in", ("pending", "partial"))], past_deadline("pickup_end"),
                ])
                domain += ["!"] + overdue if expiry == "current" else overdue
            if credit_state in ("available", "expired") or expiry == "expired_credit":
                expired_credit = expression.OR([
                    [("expiry_credit_id.closure_id", "!=", False)], past_deadline("credit_end"),
                ])
                domain += [("expiry_credit_id", "!=", False), ("expiry_credit_id.order_id", "=", False)]
                if credit_state:
                    domain += ["!"] + expired_credit if credit_state == "available" else expired_credit
                if expiry == "expired_credit":
                    domain += [("expiry_credit_id.closure_id", "=", False)] + expired_credit
        if credit_state == "consumed":
            domain.append(("expiry_credit_id.order_id", "!=", False))
        return domain

    def _layaway_reserved_quantities(self):
        quantities = defaultdict(float)
        moves = self.env["stock.move"].search([
            ("layaway_line_id", "in", self.line_ids.filtered("qty_pending").ids),
            ("state", "not in", ("done", "cancel", "draft")),
            ("location_dest_id.usage", "=", "customer"),
        ])
        for move in moves:
            quantities[move.layaway_line_id.id] += move.reserved_availability
        return quantities

    def _layaway_merchandise_history(self):
        self.ensure_one()
        operations = self.env["pos.layaway.operation"].search([
            ("layaway_id", "=", self.id), ("kind", "in", ("add_products", "change_products")),
            ("result", "!=", False),
        ])
        history = []
        for operation in operations:
            result = json.loads(operation.result)
            snapshot = result.get("quote", {}) if operation.kind == "add_products" else result
            removed_ids = set(snapshot.get("removed_ids", []))
            history.append({
                "reference": operation.reference,
                "kind": operation.kind,
                "store": operation.warehouse_id.display_name,
                "date": operation._receipt_identification(self, operation.create_date)["confirmed_at"],
                "reason": result.get("reason"),
                "supervisor": operation.user_id.name if operation.kind == "change_products" else False,
                "added": [{"name": line["product_name"], "qty": line["qty"]}
                          for line in snapshot.get("lines", [])],
                "removed": [{"name": line["product_name"], "qty": line["qty"]}
                            for line in snapshot.get("previous_lines", []) if line["id"] in removed_ids],
            })
        return history

    def _pos_layaway_values(self, reserved, detail=False):
        self.ensure_one()
        reserved_amounts = {
            line.id: self.currency_id.round(
                line.amount_total * min(line.qty_pending, reserved.get(line.id, 0)) / line.qty,
            ) for line in self.line_ids
        }
        values = {
            "id": self.id, "folio": self.folio, "campaign": self.campaign_name,
            "customer": self.contact_name, "phone": self.phone,
            "opened_on": fields.Date.to_string(self.opened_on),
            "pickup_end": fields.Date.to_string(self.pickup_end),
            "payment_state": self.payment_state, "pickup_state": self.pickup_state,
            "expired": self._layaway_pickup_overdue(fields.Datetime.now()),
            "amount_total": self.amount_total, "amount_due": self.amount_due,
            "amount_paid": self.amount_paid,
            "amount_reserved": self.currency_id.round(sum(reserved_amounts.values())),
            "currency": self.currency_id.name, "decimal_places": self.currency_id.decimal_places,
            "credit_state": self.expiry_credit_id.state,
        }
        if detail:
            values.update({
                "amount_deposit": self.amount_deposit, "amount_installments": self.amount_installments,
                "sale_name": self.sale_id.name,
                "addition_end": fields.Date.to_string(self.addition_end),
                "credit_end": fields.Date.to_string(self.credit_end),
                "timezone": self.timezone,
                "lines": [{
                    "id": line.id, "name": line.product_name, "store": line.warehouse_id.display_name,
                    "location": line.location_id.complete_name, "qty": line.qty, "pending": line.qty_pending,
                    "picked_up": line.qty_picked_up, "reserved_amount": reserved_amounts[line.id],
                } for line in self.line_ids],
            })
        return values
