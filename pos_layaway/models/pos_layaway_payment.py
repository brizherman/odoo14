import math
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .pos_layaway_campaign import local_date


class PosConfig(models.Model):
    _inherit = "pos.config"

    layaway_liability_account_id = fields.Many2one(
        "account.account", check_company=True, ondelete="restrict",
        groups="account.group_account_manager", string="Pasivo de cobros de apartados",
    )
    layaway_card_journal_id = fields.Many2one(
        "account.journal", check_company=True, ondelete="restrict",
        groups="account.group_account_manager", string="Diario de cobros con tarjeta de apartados",
    )


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    layaway_card_clearing_account_id = fields.Many2one(
        "account.account", check_company=True, ondelete="restrict",
        groups="account.group_account_manager", string="Cuenta puente de tarjeta de apartados",
    )


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    def write(self, vals):
        protected = {
            "amount", "amount_currency", "foreign_currency_id", "statement_id", "journal_id",
            "date", "payment_ref", "partner_id", "line_ids", "move_id",
        }
        if protected.intersection(vals) and self.env["pos.layaway.payment"].sudo().search_count([
            ("statement_line_id", "in", self.ids),
        ]):
            raise AccessError(_("El movimiento de efectivo conserva el cobro confirmado."))
        return super().write(vals)


class PosLayawayPayment(models.Model):
    _name = "pos.layaway.payment"
    _description = "Cobro confirmado de apartado POS"
    _order = "paid_at, id"
    _rec_name = "reference"
    _check_company_auto = True

    operation_id = fields.Many2one("pos.layaway.operation", required=True, ondelete="restrict")
    reference = fields.Char(related="operation_id.reference", store=True, index=True)
    layaway_id = fields.Many2one("pos.layaway", required=True, ondelete="restrict", index=True)
    campaign_id = fields.Many2one(related="layaway_id.campaign_id", store=True, index=True)
    kind = fields.Selection(
        [("deposit", "Anticipo"), ("installment", "Abono")], required=True,
    )
    session_id = fields.Many2one(related="operation_id.session_id", store=True, index=True)
    warehouse_id = fields.Many2one(related="operation_id.warehouse_id", store=True)
    user_id = fields.Many2one(related="operation_id.user_id", store=True)
    paid_at = fields.Datetime(
        related="operation_id.create_date", string="Fecha y hora del cobro", store=True, index=True,
    )
    config_id = fields.Many2one("pos.config", required=True, ondelete="restrict")
    company_id = fields.Many2one("res.company", required=True, ondelete="restrict", index=True)
    currency_id = fields.Many2one("res.currency", required=True, ondelete="restrict")
    method_id = fields.Many2one(
        "pos.payment.method", required=True, ondelete="restrict", check_company=True,
    )
    method_name = fields.Char(required=True)
    tender_type = fields.Selection([("cash", "Efectivo"), ("card", "Tarjeta")], required=True)
    amount = fields.Monetary(required=True)
    amount_tendered = fields.Monetary(required=True)
    amount_change = fields.Monetary(required=True)
    move_id = fields.Many2one("account.move", required=True, ondelete="restrict", check_company=True)
    statement_line_id = fields.Many2one(
        "account.bank.statement.line", ondelete="restrict", index=True,
    )

    _sql_constraints = [
        ("operation_method_unique", "UNIQUE(operation_id, method_id)",
         "El método de cobro ya está registrado en esta operación."),
        ("valid_tender", "CHECK(amount > 0 AND amount_change >= 0 "
         "AND amount_tendered = amount + amount_change "
         "AND (tender_type = 'cash' OR amount_change = 0))", "Los importes del cobro no son válidos."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_("El cobro requiere una operación del servidor."))
        return super().create(vals_list)

    def write(self, vals):
        raise ValidationError(_("El cobro confirmado conserva sus importes originales."))

    def unlink(self):
        raise ValidationError(_("El cobro confirmado conserva sus importes originales."))

    @api.model
    def _normalize_tenders(self, tenders, currency):
        if not isinstance(tenders, list) or not tenders:
            raise ValidationError(_("Indica al menos un método de cobro."))
        normalized = {}
        for tender in tenders:
            if not isinstance(tender, dict) or set(tender) - {"method_id", "amount", "amount_tendered"}:
                raise ValidationError(_("El desglose de cobro no es válido."))
            method_id = tender.get("method_id")
            if type(method_id) is not int or method_id <= 0 or method_id in normalized:
                raise ValidationError(_("Indica una sola línea por método de cobro."))
            amount = self._round_tender(tender.get("amount"), currency)
            tendered = self._round_tender(tender.get("amount_tendered", amount), currency)
            if tendered < amount:
                raise ValidationError(_("El importe recibido debe cubrir el importe aplicado."))
            normalized[method_id] = {
                "method_id": method_id, "amount": amount, "amount_tendered": tendered,
                "amount_change": currency.round(tendered - amount),
            }
        return [normalized[method_id] for method_id in sorted(normalized)]

    @api.model
    def _round_tender(self, amount, currency):
        if type(amount) in (int, float):
            try:
                if math.isfinite(amount) and amount > 0:
                    rounded = currency.round(amount)
                    if rounded > 0 and math.isfinite(rounded):
                        return rounded
            except OverflowError:
                pass
        raise ValidationError(_("El importe del cobro debe ser positivo y válido para la moneda."))

    @api.model
    def _record_tender(self, operation, session, folio, kind, tender):
        config = session.config_id
        company = session.company_id
        method = session.payment_method_ids.filtered_domain([
            ("id", "=", tender["method_id"]), ("active", "=", True),
            ("company_id", "=", company.id), ("use_payment_terminal", "=", False),
        ])
        if not method:
            raise ValidationError(_("El método de cobro no está disponible en esta caja."))
        liability = config.layaway_liability_account_id
        if (
            liability.company_id != company or liability.deprecated or
            liability.internal_group != "liability" or liability.internal_type != "other" or
            (liability.currency_id and liability.currency_id != folio.currency_id)
        ):
            raise UserError(_("Configura una cuenta de pasivo para los cobros de apartados."))

        ref = "%s · %s · %s · %s" % (folio.folio, session.name, operation.reference, method.id)
        date = local_date(operation.create_date, folio.timezone)
        amount = tender["amount"]
        statement_line = self.env["account.bank.statement.line"]
        if method.is_cash_count:
            statement = session.cash_register_id
            if (
                statement.state != "open" or statement.journal_id != method.cash_journal_id or
                statement.currency_id != folio.currency_id
            ):
                raise UserError(_("El método de efectivo requiere el extracto abierto de esta sesión."))
            statement_line = statement_line.create({
                "statement_id": statement.id, "date": date, "payment_ref": ref,
                "amount": amount, "counterpart_account_id": liability.id,
            })
            move = statement_line.move_id
        else:
            if tender["amount_change"]:
                raise ValidationError(_("Solo el efectivo puede generar cambio."))
            journal = config.layaway_card_journal_id
            clearing = method.layaway_card_clearing_account_id
            if (
                journal.company_id != company or journal.type != "general" or
                (journal.currency_id and journal.currency_id != folio.currency_id) or
                clearing.company_id != company or clearing.deprecated or
                clearing.internal_group != "asset" or clearing.internal_type != "other" or
                (clearing.currency_id and clearing.currency_id != folio.currency_id)
            ):
                raise UserError(_("El método requiere una configuración de tarjeta para apartados."))
            move = self.env["account.move"].create({
                "journal_id": journal.id, "move_type": "entry", "ref": ref, "date": date,
                "line_ids": [
                    (0, 0, {"name": ref, "account_id": clearing.id, "debit": amount}),
                    (0, 0, {"name": ref, "account_id": liability.id, "credit": amount}),
                ],
            })
            move.action_post()

        return self.create({
            **tender, "operation_id": operation.id, "layaway_id": folio.id, "kind": kind,
            "config_id": config.id, "company_id": company.id, "currency_id": folio.currency_id.id,
            "method_name": method.name, "tender_type": "cash" if method.is_cash_count else "card",
            "move_id": move.id, "statement_line_id": statement_line.id,
        })


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.depends("cash_register_id.total_entry_encoding")
    def _compute_cash_balance(self):
        super()._compute_cash_balance()

    def _register_layaway_payment(self, folio_id, reference, kind, tenders):
        """Post a synthetic deposit or partial installment through the server history."""
        if not re.fullmatch(r"odoo_test(?:_[a-z0-9_]+)?", self.env.cr.dbname):
            raise AccessError(_("Los cobros de apartados solo están disponibles para pruebas."))
        session = self.sudo(False)._check_layaway_session(require_open=False)
        folio = self.env["pos.layaway"].sudo().search([
            ("id", "=", self.env["res.partner"]._wholesale_record_id(folio_id)),
            ("participant_config_ids", "in", session.config_id.ids),
        ], limit=1)
        if not folio:
            raise AccessError(_("El apartado no está disponible en esta caja."))
        if kind not in ("deposit", "installment"):
            raise ValidationError(_("El tipo de cobro no es válido."))

        accounting_session = session.sudo().with_context({}, allowed_company_ids=session.company_id.ids)
        payment_model = accounting_session.env["pos.layaway.payment"]
        currency = folio.currency_id
        tenders = payment_model._normalize_tenders(tenders, currency)

        def apply(operation):
            session._lock_layaway_stock_session()
            if session.rescue or currency != session.currency_id or currency != session.company_id.currency_id:
                raise UserError(_("El cobro requiere una sesión ordinaria en la moneda del apartado."))
            if folio.sale_id or local_date(operation.create_date, folio.timezone) > folio.pickup_end:
                raise UserError(_("El apartado no admite abonos en su estado actual."))
            if kind == "deposit" and (folio.amount_paid or folio.session_id != session):
                raise ValidationError(_("El anticipo inicial corresponde a la sesión de apertura."))
            previous = folio.amount_paid
            applied = currency.round(sum(tender["amount"] for tender in tenders))
            comparison = currency.compare_amounts(applied, folio.amount_due)
            if comparison > 0:
                raise ValidationError(_("El importe aplicado no puede superar el restante."))
            if comparison == 0:
                raise UserError(_("La liquidación del apartado aún no está habilitada."))

            payments = payment_model.browse()
            for tender in tenders:
                payments |= payment_model._record_tender(
                    operation, accounting_session, folio, kind, tender,
                )
            return folio, {
                "reference": operation.reference, "folio": folio.folio,
                "amount_applied": applied, "amount_paid_before": previous,
                "amount_paid": folio.amount_paid, "amount_due": folio.amount_due,
                "payments": payments.read([
                    "method_id", "method_name", "amount", "amount_tendered", "amount_change",
                ], load="_classic_write"),
            }

        return self.env["pos.layaway.operation"].sudo()._confirm(
            session, reference, kind, tenders, apply, folio, pass_operation=True,
        )
