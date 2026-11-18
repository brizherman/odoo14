from datetime import timezone

from odoo import _, fields, models
from odoo.addons.pos_wholesale_control.models.res_partner import WholesaleCurrencyError

from .pos_layaway_campaign import local_date
from .pos_layaway_payment import layaway_test_database


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _wholesale_monthly_totals(self, company, moment_utc=None):
        if not layaway_test_database(self.env) or not isinstance(self.id, int):
            return super()._wholesale_monthly_totals(company, moment_utc)
        moment = fields.Datetime.to_datetime(moment_utc or fields.Datetime.now())
        if moment.tzinfo is not None:
            moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
        rows = super()._wholesale_monthly_totals(company, moment)
        months = company._wholesale_calendar_months(moment)
        currency = company.currency_id
        payments = self._wholesale_layaway_tenders([
            ("recognition_at", ">=", months[0]["start_utc"]),
        ], moment)
        if any(payment.currency_id != currency for payment in payments):
            raise WholesaleCurrencyError()
        amounts = [0.0] * len(months)
        for payment in payments:
            index = self._wholesale_month_index(payment.recognition_at, months)
            amounts[index] += payment.amount
        for row, amount in zip(rows, amounts):
            row["ordinary_amount"] = row["amount"]
            row["amount"] = currency.round(row["amount"] + amount)
        return rows

    def _wholesale_layaway_tenders(self, domain, moment):
        payments = self.env["pos.layaway.payment"].sudo().search([
            ("layaway_id.partner_id", "=", self.id),
            ("paid_at", "<=", moment),
            # A confirmed cash line is already in the register's open statement.
            "|",
            ("move_id.state", "=", "posted"),
            "&", ("statement_line_id", "!=", False), ("move_id.state", "=", "draft"),
        ] + domain)
        # Authorized corrections carry their own signed amounts and confirmation dates.
        return payments.filtered(lambda payment: not any(
            move.state == "posted" and move.create_date <= moment
            for move in payment.move_id.reversal_move_id - payment.correction_ids.move_id
        ))

    def _wholesale_grouped_amount(self, model_name, domain):
        if model_name != "pos.order" or not layaway_test_database(self.env):
            return super()._wholesale_grouped_amount(model_name, domain)
        ordinary = super()._wholesale_grouped_amount(
            model_name, domain + [("layaway_ids", "=", False), ("layaway_credit_amount", "=", 0)],
        )
        credit_sales = self.env[model_name].sudo().read_group(
            domain + [("layaway_credit_amount", ">", 0)],
            ["amount_paid:sum", "layaway_credit_amount:sum"], ["partner_id"], lazy=False,
        )
        return ordinary + sum(row["amount_paid"] - row["layaway_credit_amount"] for row in credit_sales)

    def _wholesale_pos_refund_originals(self, refunds):
        originals = super()._wholesale_pos_refund_originals(refunds)
        if layaway_test_database(self.env):
            originals = {
                refund_id: order for refund_id, order in originals.items() if not order.layaway_ids
            }
        return originals

    def _wholesale_has_covered_layaway(self, config, currency, moment):
        if not config:
            return False
        folios = self.env["pos.layaway"].sudo().search([
            ("partner_id", "=", self.id),
            ("currency_id", "=", currency.id),
            ("participant_config_ids", "in", config.ids),
            ("opened_at", "<=", moment),
        ]).filtered(lambda folio: (
            folio.opening_start <= folio.opened_on <= folio.opening_end
            and local_date(moment, folio.timezone) <= folio.pickup_end
            and folio.pickup_state != "done"
            and currency.compare_amounts(folio.amount_total, folio.minimum_amount) > 0
        ))
        if not folios:
            return False
        amounts = dict.fromkeys(folios.ids, 0.0)
        for payment in self._wholesale_layaway_tenders([("layaway_id", "in", folios.ids)], moment):
            amounts[payment.layaway_id.id] += payment.amount
        return any(
            amounts[folio.id] > 0 and currency.compare_amounts(
                amounts[folio.id], currency.round(folio.amount_total * folio.deposit_percentage / 100),
            ) >= 0
            for folio in folios
        )

    def _wholesale_eligibility_response(self, facts):
        months = facts["months"]
        if not layaway_test_database(self.env) or not months:
            return super()._wholesale_eligibility_response(facts)
        company, config, partner = facts["company"], facts["config"], facts["partner"]
        ordinary = None
        fallback = False
        if facts["pricing_program"] == "distributor":
            ordinary = [dict(row, amount=row["ordinary_amount"]) for row in months]
            decision, reason, program = self._wholesale_distributor_decision(
                company, self._wholesale_previous_month_amount(ordinary),
                self._wholesale_current_month_amount(ordinary), facts["retail_amount"],
            )
            facts = dict(facts, decision=decision, reason_code=reason, pricing_program=program)
            # Only the ordinary purchases can qualify the distributor tier.
            currency = company.currency_id
            fallback = any(
                row["amount"] > row["ordinary_amount"]
                and currency.compare_amounts(row["amount"], minimum) >= 0
                for row, minimum in zip(months[-2:], (
                    company.wholesale_previous_month_min, company.wholesale_current_order_min,
                ))
            )
        fallback = fallback or partner._wholesale_has_covered_layaway(
            config, company.currency_id, fields.Datetime.now(),
        )
        response = super()._wholesale_eligibility_response(facts)
        pricelist = company.wholesale_pricelist_id
        if (
            fallback and company.wholesale_control_active
            and pricelist.currency_id == company.currency_id
            and self._wholesale_list_usable(company, config, pricelist)
        ):
            response["layaway_wholesale_pricelist_id"] = pricelist.id
            if response["reason_code"] == "below_threshold" and not response["error"]:
                response.update(
                    automatic_decision="wholesale",
                    pricing_program="wholesale",
                    reason_code="layaway_payment",
                    reason_text=self._wholesale_reason_text("layaway_payment"),
                    expected_pricelist=self._wholesale_pricelist_payload(pricelist),
                )
        if ordinary and response["pricing_program"] == "distributor":
            response["previous_month_amount"] = self._wholesale_previous_month_amount(ordinary)
        return response

    def _wholesale_reason_text(self, reason_code, program=False):
        if reason_code == "layaway_payment":
            return _("Los cobros confirmados del apartado habilitan mayoreo.")
        return super()._wholesale_reason_text(reason_code, program)
