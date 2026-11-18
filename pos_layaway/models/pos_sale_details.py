import json
from collections import defaultdict
from datetime import timedelta
from itertools import groupby

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class ReportSaleDetails(models.AbstractModel):
    _inherit = "report.point_of_sale.report_saledetails"

    @api.model
    def _get_report_values(self, docids, data=None):
        values = super()._get_report_values(docids, data=data)
        values["layaway_campaigns"] = self._get_layaway_campaigns(values)
        return values

    @api.model
    def _get_layaway_campaigns(self, data):
        report = self.sudo(False)
        if not report.env.user.has_group("point_of_sale.group_pos_manager"):
            return []

        start = fields.Datetime.to_datetime(data["date_start"])
        stop = fields.Datetime.to_datetime(data["date_stop"])
        if not start or not stop:
            return []
        if stop < start:
            stop = start + timedelta(days=1, seconds=-1)

        campaign_domain = []
        campaign_id = data.get("layaway_campaign_id")
        if campaign_id:
            campaigns = report.env["pos.layaway.campaign"]
            if type(campaign_id) is not int or not campaigns.search([("id", "=", campaign_id)]):
                raise AccessError(_("La campaña de apartados no está disponible."))
            campaign_domain = [("layaway_id.campaign_id", "=", campaign_id)]

        accessible_configs = report.env["pos.config"].with_context(active_test=False).search([])
        config_ids = data["config_ids"]
        configs = accessible_configs & accessible_configs.browse(config_ids) if config_ids else accessible_configs
        sessions = report.env["pos.session"].search([
            ("config_id", "in", configs.ids),
            ("company_id", "in", report.env.companies.ids),
        ])
        if not sessions:
            return []

        # Historical models are private to the addon. Resolve the report's POS scope
        # under the caller's record rules before reading its selected history.
        scope = [
            ("session_id", "in", sessions.ids),
            ("layaway_id", "!=", False),
        ] + campaign_domain
        payments = report.env["pos.layaway.payment"].sudo().search(scope + [
            ("paid_at", ">=", start), ("paid_at", "<=", stop),
        ])
        operations = report.env["pos.layaway.operation"].sudo().search(scope + [
            ("create_date", ">=", start), ("create_date", "<=", stop),
            ("result", "!=", False),
        ])

        events = defaultdict(list)
        for payment in payments:
            operation = payment.operation_id
            if payment.authorization_id.kind == "authorize_transfer":
                operation = payment.authorization_id
            events[operation, payment.session_id, payment.paid_at].append(payment)

        # Preserve non-cash events, including the original request for a
        # transfer that may only be confirmed in a later period or session.
        for operation in operations:
            if operation.kind in ("refund_payment", "reclassify_payment"):
                continue
            key = (operation, operation.session_id, operation.create_date)
            if (operation.kind != "authorize_transfer" or key in events
                    or json.loads(operation.result).get("settlement")):
                events.setdefault(key, [])

        groups = {}
        folio_ids = set()
        for operation, session, moment in sorted(
            events, key=lambda key: (key[2], key[0].id, key[1].id),
        ):
            folio = operation.layaway_id
            group_key = (folio.campaign_id.id, folio.currency_id.id)
            folio_ids.add(folio.id)
            group = groups.setdefault(group_key, {
                "name": folio.campaign_name, "code": folio.campaign_code, "movements": [],
                "currency": folio.currency_id.name, "precision": folio.currency_id.decimal_places,
            })
            group["movements"].append(report._layaway_report_movement(
                operation, session, moment, events[operation, session, moment],
            ))
        closing = report._layaway_report_closing(folio_ids, configs, accessible_configs, stop)
        for key, group in groups.items():
            currency = report.env["res.currency"].browse(key[1])
            report._summarize_layaway_movements(group, currency)
            group["closing"] = closing[key]
        return sorted(groups.values(), key=lambda group: (group["name"], group["code"]))

    @api.model
    def _layaway_report_movement(self, operation, session, moment, payments):
        folio = operation.layaway_id
        currency = folio.currency_id
        result = json.loads(operation.result)
        kind = operation.kind
        origin = payments[0].operation_id if payments else operation
        # Settlement and sale values belong to the session that created them,
        # even when a transfer was received in a different session.
        local_operation = session == operation.session_id
        settlement = result.get("settlement") if local_operation else None
        credit_applied = 0
        linked_sale = None
        breakdown = []
        for payment in payments:
            breakdown.append({
                "method": payment.method_name, "amount": payment.amount,
                "effect": ("reversal" if payment.amount < 0 else
                           "replacement" if payment.corrects_payment_id else "collected"),
            })

        if kind == "apply_expiry_credit":
            order = operation.env["pos.order"].browse(result["id"])
            credit_applied = result["credit_amount"]
            linked_sale = order.amount_total
            methods = defaultdict(float)
            for payment in order.payment_ids.filtered(
                lambda line: not line.payment_method_id.layaway_application,
            ):
                methods[payment.payment_method_id.name] += payment.amount
            # Standard POS stores change as a negative payment. Net it within
            # its method before treating the tender as money received.
            breakdown = [
                {"method": method, "amount": currency.round(amount), "effect": "collected"}
                for method, amount in sorted(methods.items()) if not currency.is_zero(amount)
            ]
        elif settlement:
            linked_sale = settlement["amount_total"]

        return {
            "date": moment,
            "config": session.config_id.name,
            "session": session.name,
            "session_id": session.id,
            "store": (payments[0].warehouse_id if payments else operation.warehouse_id).display_name,
            "folio": folio.folio,
            "customer": folio.contact_name,
            "cashier": origin.user_id.name,
            "authorizer": operation.user_id.name if origin != operation else False,
            "reference": operation.reference,
            "original_reference": (result.get("original_reference") or
                                   (origin.reference if origin != operation else False)),
            "kind": kind,
            "label": self._layaway_movement_label(kind, result, settlement, payments),
            "amount": currency.round(sum(line["amount"] for line in breakdown)),
            "breakdown": breakdown,
            "previous": settlement["amount_previous"] if settlement else 0,
            "credit_applied": credit_applied,
            "credit_issued": (result.get("credit") or {}).get("amount", 0),
            "linked_sale": linked_sale,
            "sale_name": result.get("sale_name") or result.get("order_name"),
            "adjustment": result.get("sale_adjustment"),
        }

    @api.model
    def _layaway_movement_label(self, kind, result, settlement, payments):
        labels = {
            "open": _("Anticipo"),
            "add_products": _("Adición de mercancía"),
            "deposit": _("Anticipo"),
            "installment": _("Abono"),
            "settle": _("Liquidación"),
            "settle_pickup": _("Liquidación y recogida"),
            "authorize_transfer": _("Confirmación de transferencia"),
            "change_products": _("Ajuste de mercancía"),
            "refund_payment": _("Reversión de cobro"),
            "reclassify_payment": _("Reclasificación de cobro"),
            "pickup": _("Recogida"),
            "authorize_pickup": _("Autorización de recogida"),
            "relocate_block": _("Traslado de reserva"),
            "review_expiry": _("Revisión de vencimiento"),
            "convert_expiry_credit": _("Conversión a saldo por vencimiento"),
            "apply_expiry_credit": _("Aplicación de saldo"),
            "close_expiry_credit": _("Cierre de saldo caducado"),
        }
        label = labels.get(kind, kind)
        if kind == "authorize_transfer" and payments:
            payment_label = labels[payments[0].kind]
            label = "%s · %s" % (payment_label, label)
        if kind == "add_products":
            if result.get("sale_adjustment"):
                label = "%s · %s" % (label, labels["change_products"])
            if payments and not settlement:
                label = "%s · %s" % (label, labels["installment"])
        if settlement and kind not in ("settle", "settle_pickup"):
            label = "%s · %s" % (label, labels["settle"])
        if result.get("pending_transfers"):
            label = "%s · %s" % (label, _("Solicitud de transferencia"))
        return label

    @api.model
    def _summarize_layaway_movements(self, group, currency):
        totals = defaultdict(lambda: defaultdict(float))
        cash_rows = []
        campaign_total = defaultdict(float)
        for movement in group["movements"]:
            for line in movement["breakdown"]:
                key = (movement["store"], movement["config"], movement["session"],
                       movement["session_id"], line["method"], movement["label"])
                for total in (totals[key], campaign_total):
                    total[line["effect"]] += line["amount"]
                    total["net"] += line["amount"]

        for session_key, session_items in groupby(sorted(totals), key=lambda key: key[:4]):
            store, config, session, _session_id = session_key
            session_keys = list(session_items)
            for method, method_items in groupby(session_keys, key=lambda key: key[4]):
                method_keys = list(method_items)
                for key in method_keys:
                    cash_rows.append(self._layaway_cash_row(
                        key[5], totals[key], currency, method=method,
                    ))
                if len(method_keys) > 1:
                    cash_rows.append(self._layaway_cash_row(
                        _("Subtotal por método"), self._layaway_cash_sum(totals, method_keys),
                        currency, method=method, subtotal=True,
                    ))
            cash_rows.append(self._layaway_cash_row(
                _("Total de sesión"), self._layaway_cash_sum(totals, session_keys),
                currency, session="%s · %s · %s" % (store, config, session), subtotal=True,
            ))
        group["cash_by_session"] = cash_rows
        group["cash_total"] = self._layaway_cash_row(
            _("Total de caja de la campaña"), campaign_total, currency, subtotal=True,
        )
        group["other_totals"] = {
            field: currency.round(sum(row[field] or 0 for row in group["movements"]))
            for field in ("previous", "credit_applied", "credit_issued", "linked_sale")
        }

    @api.model
    def _layaway_cash_sum(self, totals, keys):
        return {
            column: sum(totals[key][column] for key in keys)
            for column in ("collected", "reversal", "replacement", "net")
        }

    @api.model
    def _layaway_cash_row(self, label, total, currency, method=False, session=False, subtotal=False):
        return {
            "label": label, "method": method, "session": session, "subtotal": subtotal,
            **{
                column: currency.round(total[column])
                for column in ("collected", "reversal", "replacement", "net")
            },
        }
