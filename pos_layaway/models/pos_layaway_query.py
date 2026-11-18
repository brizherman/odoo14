import json
import re

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

    def _layaway_receipt(self, folio_id, reference, original=False):
        operation = self._layaway_receipt_operations([
            ("layaway_id", "=", folio_id), ("reference", "=", reference),
        ])
        result = json.loads(operation.result) if operation else {}
        if not result.get("receipt"):
            raise AccessError(_("El comprobante original no está disponible."))
        return result, not (original and operation.session_id.id == self.id)

    def get_layaway_detail(self, record_id):
        folio = self._find_layaway(record_id)
        receipts = []
        for operation in self._layaway_receipt_operations([("layaway_id", "=", folio.id)]):
            result = json.loads(operation.result)
            receipt = result.get("receipt")
            if not receipt and (
                operation.kind == "authorize_transfer"
                or (operation.kind == "installment" and not result.get("amount_applied"))
            ):
                continue
            receipts.append({
                "reference": operation.reference,
                "kind": receipt["kind"] if receipt else operation.kind,
                "available": bool(receipt),
            })
        installment_methods = self.env["pos.payment.method"]
        if (
            layaway_test_database(self.env) and not self.rescue and not folio.sale_id
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
            **folio._pos_layaway_values(detail=True),
            "receipts": receipts,
            "installment_methods": [{
                "id": method.id, "name": method.name, "cash": method.is_cash_count,
            } for method in installment_methods],
            "campaign_id": folio.campaign_id.id,
            "sale_url": "/web#model=pos.order&id=%s&view_type=form" % sale.id if can_open_sale else False,
            "can_add_products": (
                layaway_test_database(self.env) and not folio.sale_id
                and folio.pickup_state != "done"
                and local_date(fields.Datetime.now(), folio.timezone) <= folio.addition_end
            ),
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
        return {
            "rows": [folio._pos_layaway_values() for folio in page[:page_size]],
            "has_more": len(page) > page_size,
            "can_open_layaway": layaway_test_database(self.env),
            **scope_filters,
        }


class PosLayaway(models.Model):
    _inherit = "pos.layaway"

    def _pos_layaway_filter_options(self, scope):
        campaigns = self.read_group(scope, ["campaign_id"], ["campaign_id"])
        shops = self.env["pos.layaway.line"].read_group(
            [("released_by_id", "=", False)] + [
                ("layaway_id." + field, operator, value) for field, operator, value in scope
            ],
            ["warehouse_id"], ["warehouse_id"],
        )
        return {
            "campaigns": [{"id": row["campaign_id"][0], "name": row["campaign_id"][1]}
                          for row in campaigns],
            "stores": [{"id": row["warehouse_id"][0], "name": row["warehouse_id"][1]}
                       for row in shops],
        }

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
            lines = self.env["pos.layaway.line"].search([
                ("warehouse_id", "=", record_id(filters["store"])),
                ("released_by_id", "=", False),
            ])
            domain.append(("line_ids", "in", lines.ids))
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
        if expiry in ("expired", "current"):
            timezones = self.read_group(scope, ["timezone"], ["timezone"])
            now = fields.Datetime.now()
            overdue = expression.AND([
                [("pickup_state", "!=", "done")],
                expression.OR([
                    [("timezone", "=", row["timezone"]),
                     ("pickup_end", "<", local_date(now, row["timezone"]))]
                    for row in timezones
                ]),
            ])
            if expiry == "current":
                overdue = expression.distribute_not(["!"] + expression.normalize_domain(overdue))
            domain += overdue
        return domain

    def _pos_layaway_values(self, detail=False):
        self.ensure_one()
        values = {
            "id": self.id, "folio": self.folio, "campaign": self.campaign_name,
            "customer": self.contact_name, "phone": self.phone,
            "opened_on": fields.Date.to_string(self.opened_on),
            "pickup_end": fields.Date.to_string(self.pickup_end),
            "payment_state": self.payment_state, "pickup_state": self.pickup_state,
            "expired": self.pickup_state != "done" and (
                self.pickup_end < local_date(fields.Datetime.now(), self.timezone)
            ),
            "amount_total": self.amount_total, "amount_due": self.amount_due,
        }
        if detail:
            values.update({
                "amount_deposit": self.amount_deposit, "amount_installments": self.amount_installments,
                "sale_name": self.sale_id.name,
                "lines": [{
                    "id": line.id, "name": line.product_name, "store": line.warehouse_id.display_name,
                    "location": line.location_id.complete_name, "qty": line.qty, "pending": line.qty_pending,
                } for line in self.line_ids],
            })
        return values
