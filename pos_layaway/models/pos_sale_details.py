from datetime import timedelta

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

        configs = report.env["pos.config"].with_context(active_test=False)
        config_ids = data["config_ids"]
        if config_ids:
            configs = configs.search([("id", "in", config_ids)])
        else:
            configs = configs.search([])
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
            ("result", "!=", False), ("payment_ids", "=", False),
        ])

        events = [
            (payment.paid_at, payment.session_id, payment.operation_id, payment)
            for payment in payments
        ] + [
            (operation.create_date, operation.session_id, operation, None)
            for operation in operations
        ]
        groups = {}
        for moment, session, operation, payment in sorted(events, key=lambda event: event[0]):
            folio = operation.layaway_id
            group = groups.setdefault(folio.campaign_id.id, {
                "name": folio.campaign_name, "code": folio.campaign_code, "movements": [],
            })
            group["movements"].append({
                "date": moment,
                "config": session.config_id.name,
                "session": session.name,
                "folio": folio.folio,
                "reference": operation.reference,
                "kind": operation.kind,
                "method": payment.method_name if payment else False,
                "amount": payment.amount if payment else None,
                "currency": folio.currency_id.name,
                "precision": folio.currency_id.decimal_places,
            })
        return sorted(groups.values(), key=lambda group: (group["name"], group["code"]))
