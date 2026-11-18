from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .pos_layaway_campaign import local_date
from .pos_layaway_payment import layaway_test_database


class PosLayawayPayment(models.Model):
    _inherit = "pos.layaway.payment"

    def _layaway_liability(self):
        self.ensure_one()
        return self.move_id.line_ids.filtered(lambda line: line.credit > 0).account_id

    def _layaway_unreversed_amount(self):
        self.ensure_one()
        return self.currency_id.round(self.amount + sum(
            item.amount for item in self.correction_ids if item.amount < 0
        ))

    def _reverse_layaway_tender(self, operation, session, amount):
        self.ensure_one()
        original_move = self.move_id
        date = local_date(operation.create_date, self.layaway_id.timezone)
        reference = "%s · %s · %s" % (self.layaway_id.folio, session.name, operation.reference)
        statement_line = self.env["account.bank.statement.line"]
        if self.tender_type == "cash":
            statement_line = self._record_layaway_cash(
                session, original_move.journal_id, self.currency_id, -amount,
                self._layaway_liability(), date, reference, original_move,
            )
            move = statement_line.move_id
        elif self.currency_id.compare_amounts(amount, self.amount) == 0:
            move = original_move._reverse_moves([{"ref": reference, "date": date}])
            move.action_post()
        else:
            move = self.env["account.move"].create({
                "move_type": "entry", "journal_id": original_move.journal_id.id,
                "ref": reference, "date": date, "reversed_entry_id": original_move.id,
                "line_ids": [(0, 0, {
                    "name": reference, "account_id": line.account_id.id,
                    "debit": amount if line.credit else 0,
                    "credit": amount if line.debit else 0,
                }) for line in original_move.line_ids],
            })
            move.action_post()
        return self.create({
            "operation_id": operation.id, "authorization_id": operation.id,
            "layaway_id": self.layaway_id.id, "kind": self.kind,
            "config_id": session.config_id.id, "company_id": self.company_id.id,
            "currency_id": self.currency_id.id, "method_id": self.method_id.id,
            "method_name": self.method_name, "tender_type": self.tender_type,
            "amount": -amount, "amount_tendered": 0, "amount_change": 0,
            "corrects_payment_id": self.id, "accounting_session_id": session.id,
            "move_id": move.id, "statement_line_id": statement_line.id,
        })


class PosSession(models.Model):
    _inherit = "pos.session"

    def correct_layaway_payment(self, folio_id, payment_id, reference, correction):
        """Authorize a synthetic refund or method correction in the receiving company."""
        self._check_layaway_payment_test()
        session = self.sudo(False)
        if not session.env.user.has_group("point_of_sale.group_pos_manager"):
            raise AccessError(_("Solo el encargado puede autorizar correcciones de cobro."))
        folio = session._find_layaway(folio_id, require_open=False)
        payment_id = session.env["res.partner"]._wholesale_record_id(payment_id)
        payment = folio.payment_ids.filtered_domain([
            ("id", "=", payment_id), ("amount", ">", 0), ("company_id", "=", session.company_id.id),
        ])
        if not payment:
            raise AccessError(_("El cobro no pertenece al apartado y a la compañía de esta caja."))
        values = session._normalize_layaway_correction(correction, folio.currency_id)
        return session.env["pos.layaway.operation"].sudo()._confirm(
            session, reference, values["kind"], [payment.id, values],
            lambda operation: session._apply_layaway_correction(operation, folio, payment, values),
            folio, pass_operation=True,
        )

    def _normalize_layaway_correction(self, correction, currency):
        if not isinstance(correction, dict):
            raise ValidationError(_("Indica el tipo de corrección de cobro."))
        kind = correction.get("kind")
        common = {"kind", "reason", "evidence"}
        if kind == "refund_payment" and set(correction) == common | {"amount"}:
            details = {"amount": self.env["pos.layaway.payment"]._round_tender(correction["amount"], currency)}
        elif kind == "reclassify_payment" and not set(correction) - (common | {"method_id", "bank_reference"}):
            method_id = self.env["res.partner"]._wholesale_record_id(correction.get("method_id"))
            if not method_id:
                raise ValidationError(_("Indica el método correcto del cobro."))
            details = {"method_id": method_id}
            if correction.get("bank_reference"):
                details.update(self.env["pos.layaway.transfer"]._layaway_transfer_verification(
                    correction["bank_reference"], correction.get("reason"), correction.get("evidence"),
                ))
        else:
            raise ValidationError(_("Indica el tipo de corrección de cobro."))
        for key, limit in (("reason", 500), ("evidence", 2000)):
            value = correction.get(key)
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
                raise ValidationError(_("Indica el motivo y la evidencia de la corrección."))
            details[key] = value.strip()
        return dict(details, kind=kind)

    def _apply_layaway_correction(self, operation, folio, payment, values):
        self._lock_layaway_stock_session()
        currency = folio.currency_id
        if self.rescue or currency != self.currency_id or currency != self.company_id.currency_id:
            raise UserError(_("La corrección requiere una sesión ordinaria en la moneda del apartado."))
        if payment.move_id.state != "posted" and not (
            payment.statement_line_id and payment.move_id.state == "draft"
        ):
            raise ValidationError(_("El cobro original no está confirmado."))
        external_reversals = payment.move_id.reversal_move_id - payment.correction_ids.move_id
        if any(move.state != "cancel" for move in external_reversals):
            raise ValidationError(_("El cobro ya tiene una reversión contable fuera del apartado."))
        remaining = payment._layaway_unreversed_amount()
        refund = values["kind"] == "refund_payment"
        amount = values["amount"] if refund else remaining
        if not amount or currency.compare_amounts(amount, remaining) > 0:
            raise ValidationError(_("La corrección excede el importe vigente del cobro."))
        context = {"allowed_company_ids": self.company_id.ids}
        receiving = self.sudo().with_context(context)
        payment = payment.with_env(receiving.env)
        method = receiving.env["pos.payment.method"]
        transfer_model = receiving.env["pos.layaway.transfer"]
        bank_reference = values.get("bank_reference")
        if not refund:
            receiving = payment.session_id
            method = payment._available_methods(receiving).filtered_domain([
                ("id", "=", values["method_id"]),
            ])
            if not method or method == payment.method_id:
                raise ValidationError(_("Elige un método distinto disponible en la caja original."))
            if method.layaway_transfer != bool(bank_reference):
                raise ValidationError(_("Para reclasificar a transferencia, verifica la referencia bancaria."))
            if bank_reference:
                transfer_model._check_layaway_bank_reference(self.company_id, bank_reference)
        if folio.sale_id and (refund or payment.tender_type == "cash" or method.is_cash_count):
            raise UserError(_("Esta corrección de una venta liquidada requiere validación contable y fiscal."))
        if payment.tender_type == "cash" or method.is_cash_count:
            receiving._lock_layaway_stock_session()
        if refund and payment.tender_type == "cash" and payment.move_id.journal_id not in (
            payment._available_methods(receiving).cash_journal_id
        ):
            raise ValidationError(_("La sesión que devuelve el efectivo debe usar el mismo diario de caja."))

        previous = folio.amount_paid
        reversal = payment._reverse_layaway_tender(operation, receiving, amount)
        replacement = payment.browse()
        if not refund:
            tender = {"method_id": method.id, "amount": amount, "amount_tendered": amount, "amount_change": 0}
            replacement = payment._record_tender(
                operation, receiving, folio, payment.kind, tender,
                operation if bank_reference else None, original=payment,
            )
            if bank_reference:
                transfer_model.create({
                    "operation_id": operation.id, "authorization_id": operation.id,
                    "layaway_id": folio.id, "kind": payment.kind, "company_id": receiving.company_id.id,
                    "currency_id": currency.id, "method_id": method.id, "amount": amount,
                    "payment_id": replacement.id, "bank_reference": bank_reference,
                    "reason": values["reason"], "evidence": values["evidence"],
                })
        return folio, {
            "id": folio.id, "reference": operation.reference, "kind": values["kind"],
            "authorization_id": operation.id, "approved_by": operation.user_id.id,
            "reason": values["reason"], "evidence": values["evidence"],
            "original_payment_id": payment.id, "original_reference": payment.reference,
            "reversal_payment_id": reversal.id, "replacement_payment_id": replacement.id,
            "session_id": receiving.id, "sale_id": folio.sale_id.id,
            "original_amount": payment.amount,
            "corrected_amount": currency.round(remaining - amount) if refund else amount,
            "money_returned": amount if refund else 0,
            "amount_paid_before": previous, "amount_paid": folio.amount_paid, "amount_due": folio.amount_due,
        }

    def _layaway_correction_detail(self, folio):
        if (
            not layaway_test_database(self.env)
            or not self.env.user.has_group("point_of_sale.group_pos_manager")
        ):
            return []
        payments = folio.payment_ids.filtered_domain([("company_id", "=", self.company_id.id)])
        return [{
            "id": payment.id, "reference": payment.reference, "method": payment.method_name,
            "amount": payment.amount, "session": payment.session_id.name,
            "corrects": payment.corrects_payment_id.reference,
            "remaining": payment._layaway_unreversed_amount() if payment.amount > 0 else 0,
            "can_refund": not folio.sale_id,
            "methods": [{
                "id": method.id, "name": method.name, "transfer": method.layaway_transfer,
            } for method in payment._available_methods(payment.session_id) if (
                method != payment.method_id
                and (payment.session_id.state == "opened" or not method.is_cash_count)
                and (not folio.sale_id or not method.is_cash_count)
                and (payment.tender_type != "cash" or payment.session_id.state == "opened" and not folio.sale_id)
            )] if payment.amount > 0 else [],
        } for payment in payments]
