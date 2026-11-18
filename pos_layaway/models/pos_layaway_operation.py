import hashlib
import json
import uuid

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class PosLayawayOperation(models.Model):
    _name = "pos.layaway.operation"
    _description = "Operación confirmada de apartado POS"
    _order = "create_date, id"
    _rec_name = "reference"

    _receipt_kinds = (
        "open", "add_products", "installment", "settle", "authorize_transfer", "change_products",
        "pickup", "settle_pickup",
    )

    reference = fields.Char(required=True)
    kind = fields.Char(required=True)
    fingerprint = fields.Char(required=True)
    layaway_id = fields.Many2one("pos.layaway", ondelete="restrict", index=True)
    session_id = fields.Many2one("pos.session", required=True, ondelete="restrict")
    warehouse_id = fields.Many2one("stock.warehouse", required=True, ondelete="restrict")
    user_id = fields.Many2one("res.users", required=True, ondelete="restrict")
    result = fields.Text()

    _sql_constraints = [
        ("reference_unique", "UNIQUE(reference)", "La referencia de operación ya existe."),
    ]

    @api.model
    def _confirm(self, session, reference, kind, payload, apply, layaway=None, pass_operation=False):
        """Run a server-owned callback and persist its JSON result in the same transaction.

        The callback returns (folio, result). The caller validates access and supplies
        normalized business inputs; the originating session is recorded on first use.
        Set pass_operation when the callback must link records to the claimed operation.
        """
        if not self.env.su:
            raise AccessError(_("La confirmación requiere una operación del servidor."))
        try:
            reference = str(uuid.UUID(reference))
        except (AttributeError, TypeError, ValueError):
            raise ValidationError(_("La referencia de operación no es válida."))
        origin = session._check_layaway_session(require_open=False)
        if layaway and origin.config_id not in layaway.participant_config_ids:
            raise AccessError(_("El apartado no pertenece a esta caja."))
        fingerprint = hashlib.sha256(json.dumps(
            [kind, layaway.id if layaway else None, payload],
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode()).hexdigest()

        with self.env.cr.savepoint():
            operation = self.search([("reference", "=", reference)], limit=1)
            if not operation:
                origin._check_layaway_session()
                now = fields.Datetime.now()
                # Under REPEATABLE READ PostgreSQL raises 40001 on a concurrent
                # invisible conflict. Odoo retries the entire RPC in a fresh snapshot.
                self.env.cr.execute("""
                    INSERT INTO pos_layaway_operation (
                        reference, kind, fingerprint, session_id, warehouse_id,
                        user_id, create_uid, create_date, write_uid, write_date, layaway_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (reference) DO NOTHING
                    RETURNING id
                """, (
                    reference, kind, fingerprint, origin.id,
                    origin.config_id.picking_type_id.warehouse_id.id,
                    session.env.uid, session.env.uid, now, session.env.uid, now,
                    layaway.id if layaway else None,
                ))
                claimed = self.env.cr.fetchone()
                if claimed:
                    operation = self.browse(claimed[0])
                    if layaway:
                        # Serialize different operations on the same folio as well.
                        self.env.cr.execute(
                            "UPDATE pos_layaway SET write_date = %s WHERE id = %s",
                            (now, layaway.id),
                        )
                        layaway.invalidate_cache(["write_date"])
                    folio, result = apply(operation) if pass_operation else apply()
                    if not folio or origin.config_id not in folio.participant_config_ids:
                        raise AccessError(_("El resultado no corresponde a esta caja."))
                    stored = json.dumps(result, allow_nan=False)
                    super(PosLayawayOperation, operation).write({
                        "layaway_id": folio.id, "result": stored,
                    })
                    return json.loads(stored)
                operation = self.search([("reference", "=", reference)], limit=1)
            if (
                not operation.layaway_id
                or origin.config_id not in operation.layaway_id.participant_config_ids
                or operation.fingerprint != fingerprint
            ):
                raise ValidationError(_("La referencia corresponde a otra operación."))
            return json.loads(operation.result)

    def _receipt_identification(self, folio, confirmed_at):
        self.ensure_one()
        confirmed_at = pytz.UTC.localize(confirmed_at).astimezone(pytz.timezone(folio.timezone))
        return {
            "cashier": self.user_id.name,
            "register": self.session_id.config_id.name,
            "session": self.session_id.name,
            "confirmed_at": confirmed_at.isoformat(sep=" ", timespec="seconds"),
            "timezone": folio.timezone,
            "currency": folio.currency_id.name,
            "decimal_places": folio.currency_id.decimal_places,
        }

    def _installment_receipt(self, folio, authorization=None):
        return {
            **self._receipt_identification(folio, (authorization or self).create_date),
            "kind": "installment",
            "campaign_name": folio.campaign_name,
            "contact_name": folio.contact_name,
            "phone": folio.phone,
            "warehouse": self.warehouse_id.display_name,
            "amount_total": folio.amount_total,
        }

    def _sale_ticket_snapshot(self, folio, payments, receipt=None):
        receiving = payments.session_id or self.session_id
        return {
            **(receipt or self._receipt_identification(folio, self.create_date)),
            "campaign_name": folio.campaign_name,
            "contact_name": folio.contact_name,
            "phone": folio.phone,
            "warehouse": receiving.config_id.picking_type_id.warehouse_id.display_name,
            "receiving_register": receiving.config_id.name,
            "receiving_session": receiving.name,
            "payments": payments.read(
                ["method_name", "amount", "amount_tendered", "amount_change"], load="_classic_write",
            ),
            "amount_new": folio.currency_id.round(sum(payments.mapped("amount"))),
        }

    def _sale_ticket_values(self, result):
        settlement = result["settlement"]
        ticket = settlement.get("ticket")
        if ticket is None:
            # Earlier settlements saved the original lines, state and immutable payment IDs.
            payments = self.env["pos.layaway.payment"].browse(settlement["new_payment_ids"])
            ticket = self._sale_ticket_snapshot(self.layaway_id, payments, result.get("receipt"))
        return {
            **ticket,
            "amount_total": settlement["amount_total"],
            "amount_tax": settlement["amount_tax"],
            "amount_previous": settlement["amount_previous"],
            "previous_deposit": settlement["previous_deposit"],
            "previous_installments": round(
                settlement["amount_previous"] - settlement["previous_deposit"], ticket["decimal_places"],
            ),
            "pickup_state": settlement["pickup_state"],
            "lines": settlement["lines"],
        }

    def _receipt_snapshot(self, folio):
        return {
            **self._receipt_identification(folio, self.create_date),
            "kind": self.kind,
            "conditions": [
                _("Los plazos son inclusivos en la zona horaria indicada."),
                _("La mercancía queda reservada en la tienda indicada. "
                  "La recogida requiere liquidar todo el apartado."),
                _("Las adiciones respetan el plazo original "
                  "y la cobertura pactada sobre el total vigente."),
                _("La cancelación voluntaria no está permitida. "
                  "Los cambios de mercancía requieren autorización."),
                _("La recogida fuera de plazo requiere autorización y reserva disponible."),
            ],
        }

    def write(self, vals):
        raise ValidationError(_("La operación confirmada conserva su resultado original."))

    def unlink(self):
        raise ValidationError(_("La operación confirmada conserva su resultado original."))
