from uuid import NAMESPACE_URL, uuid5

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .pos_layaway_campaign import local_date
from .pos_layaway_payment import layaway_test_database


class PosLayawayTransfer(models.Model):
    _name = "pos.layaway.transfer"
    _description = "Transferencia manual de apartado POS"
    _order = "id desc"
    _rec_name = "reference"
    _check_company_auto = True

    operation_id = fields.Many2one("pos.layaway.operation", required=True, ondelete="restrict")
    reference = fields.Char(related="operation_id.reference")
    layaway_id = fields.Many2one("pos.layaway", required=True, ondelete="restrict", index=True)
    kind = fields.Selection(
        [("deposit", "Anticipo"), ("installment", "Abono")], required=True,
    )
    session_id = fields.Many2one(related="operation_id.session_id")
    company_id = fields.Many2one("res.company", required=True, ondelete="restrict", index=True)
    currency_id = fields.Many2one("res.currency", required=True, ondelete="restrict")
    method_id = fields.Many2one(
        "pos.payment.method", required=True, ondelete="restrict", check_company=True,
    )
    amount = fields.Monetary(required=True)
    authorization_id = fields.Many2one("pos.layaway.operation", ondelete="restrict", copy=False)
    payment_id = fields.Many2one(
        "pos.layaway.payment", ondelete="restrict", copy=False, check_company=True,
    )
    bank_reference = fields.Char(copy=False)
    reason = fields.Text(copy=False)
    evidence = fields.Text(copy=False)

    _sql_constraints = [
        ("operation_method_unique", "UNIQUE(operation_id, method_id)",
         "El método de transferencia ya está registrado en esta operación."),
        ("bank_reference_unique", "UNIQUE(company_id, bank_reference)",
         "La referencia bancaria ya se aplicó en esta compañía."),
        ("valid_amount", "CHECK(amount > 0)", "La transferencia debe tener un importe positivo."),
        ("verified_payment", """
            CHECK(
                (payment_id IS NULL AND authorization_id IS NULL AND bank_reference IS NULL
                    AND reason IS NULL AND evidence IS NULL)
                OR
                (payment_id IS NOT NULL AND authorization_id IS NOT NULL AND bank_reference IS NOT NULL
                    AND reason IS NOT NULL AND evidence IS NOT NULL)
            )
         """, "La transferencia confirmada debe conservar su autorización y evidencia."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su or not layaway_test_database(self.env):
            raise AccessError(_("La transferencia requiere una operación de prueba del servidor."))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_("La transferencia conserva su registro y autorización originales."))

    def unlink(self):
        raise AccessError(_("La transferencia conserva su registro y autorización originales."))

    def _approve(self, authorization, folio, verification):
        self.ensure_one()
        if authorization.session_id.company_id != self.company_id:
            raise AccessError(_("La transferencia debe verificarse en la compañía que la recibió."))
        if self.payment_id or self.search_count([
            ("company_id", "=", self.company_id.id),
            ("bank_reference", "=", verification["bank_reference"]),
        ]):
            raise ValidationError(_("La referencia bancaria ya se aplicó en esta compañía."))
        receiving = self.session_id.with_context({}, allowed_company_ids=self.company_id.ids)
        receiving._check_layaway_payment_amount(folio, self.amount, authorization.create_date)
        # The receiving session owns the payment. Authorization supplies the recognition date.
        payment_model = receiving.env["pos.layaway.payment"]
        paid_before = folio.amount_paid
        tender = {
            "method_id": self.method_id.id, "amount": self.amount,
            "amount_tendered": self.amount, "amount_change": 0,
        }
        payment = payment_model._record_tender(
            self.operation_id, receiving, folio, self.kind, tender, authorization,
        )
        super(PosLayawayTransfer, self).write({
            **verification, "authorization_id": authorization.id, "payment_id": payment.id,
        })
        result = {
            "id": folio.id, "folio": folio.folio,
            "reference": authorization.reference, "transfer_id": self.id,
            "session_id": receiving.id, "payment_id": payment.id, "amount_applied": self.amount,
            "amount_paid_before": paid_before, "amount_paid": folio.amount_paid,
            "amount_due": folio.amount_due,
        }
        if self.kind == "installment":
            result.update({
                "receipt": self.operation_id._installment_receipt(folio, authorization),
                "transfer_reference": self.reference,
                "payments": payment.read([
                    "method_id", "method_name", "amount", "amount_tendered", "amount_change",
                ], load="_classic_write"),
            })
        return folio, result


class PosSession(models.Model):
    _inherit = "pos.session"

    def register_layaway_transfer(self, folio_id, reference, kind, tenders):
        return self._register_layaway_payment(folio_id, reference, kind, tenders, require_transfer=True)

    def authorize_layaway_transfer(self, folio_id, transfer_id, bank_reference, reason, evidence):
        self._check_layaway_payment_test()
        session = self.sudo(False)
        if not session.env.user.has_group("point_of_sale.group_pos_manager"):
            raise AccessError(_("Solo el encargado puede autorizar transferencias."))
        folio = session._find_layaway(folio_id, require_open=False)
        transfer = folio.transfer_ids.filtered_domain([
            ("id", "=", session.env["res.partner"]._wholesale_record_id(transfer_id)),
        ])
        if not transfer:
            raise AccessError(_("La transferencia no corresponde a este apartado."))
        verification = {
            "bank_reference": bank_reference, "reason": reason, "evidence": evidence,
        }
        for name, limit in (("bank_reference", 120), ("reason", 500), ("evidence", 2000)):
            value = verification[name]
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
                raise ValidationError(
                    _("Indica la referencia bancaria, el motivo y la evidencia de recepción.")
                )
            verification[name] = value.strip()
        verification["bank_reference"] = verification["bank_reference"].upper()
        if not verification["bank_reference"].isprintable() or len(verification["bank_reference"]) > 120:
            raise ValidationError(_("Indica una referencia bancaria válida."))
        reference = str(uuid5(NAMESPACE_URL, "pos_layaway/transfer/%s/%s" % (
            transfer.reference, transfer.method_id.id,
        )))
        return session.env["pos.layaway.operation"].sudo()._confirm(
            session, reference, "authorize_transfer", [transfer.id, verification],
            lambda operation: transfer._approve(operation, folio, verification),
            folio, pass_operation=True,
        )

    def _layaway_transfer_detail(self, folio):
        if not layaway_test_database(self.env):
            return {}
        methods = self.env["pos.layaway.payment"].sudo()._available_methods(self.sudo())
        transfer_methods = methods.filtered(
            lambda method: method.layaway_transfer and not method.is_cash_count
        )
        can_approve = self.env.user.has_group("point_of_sale.group_pos_manager")
        can_register = (
            transfer_methods and not folio.sale_id and folio.amount_due > 0
            and local_date(fields.Datetime.now(), folio.timezone) <= folio.pickup_end
        )
        kind = "deposit" if (
            folio.session_id == self and not folio.amount_paid
            and not folio.transfer_ids.filtered(lambda transfer: transfer.kind == "deposit")
        ) else "installment"
        return {
            "kind": kind,
            "methods": [
                {"id": method.id, "name": method.name}
                for method in methods if not method.layaway_transfer or method in transfer_methods
            ] if can_register else [],
            "transfers": [{
                "id": transfer.id, "amount": transfer.amount,
                "method": transfer.method_id.name, "reference": transfer.reference,
                "confirmed": bool(transfer.payment_id),
                "can_approve": can_approve and transfer.company_id == self.company_id,
                "bank_reference": (
                    transfer.bank_reference
                    if can_approve and transfer.company_id == self.company_id else False
                ),
            } for transfer in folio.transfer_ids],
        }
