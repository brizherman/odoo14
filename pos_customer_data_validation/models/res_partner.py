import hashlib
import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


TRACKED_FIELDS = ("name", "mobile", "customer_type")
DATE_FIELDS = {name: "pos_%s_updated_at" % name for name in TRACKED_FIELDS}
PRICELIST_FIELD = "property_product_pricelist"
EVIDENCE_FIELD = "pos_pricelist_evidence"
PROTECTED_FIELDS = set(DATE_FIELDS.values()) | {EVIDENCE_FIELD}
EDITABLE_FIELDS = set(TRACKED_FIELDS) | {PRICELIST_FIELD}


class ResPartner(models.Model):
    _inherit = "res.partner"

    pos_name_updated_at = fields.Datetime(readonly=True, copy=False)
    pos_mobile_updated_at = fields.Datetime(readonly=True, copy=False)
    pos_customer_type_updated_at = fields.Datetime(readonly=True, copy=False)
    pos_pricelist_evidence = fields.Text(readonly=True, copy=False)

    @api.model
    def _pos_check_protected_values(self, values):
        if PROTECTED_FIELDS.intersection(values) or any(
            "default_%s" % name in self.env.context for name in PROTECTED_FIELDS
        ):
            raise AccessError(_("Las fechas del cliente son de solo lectura."))

    def _pos_pricelist_signature(self):
        """Conservative evidence of the effective value's resolution inputs.

        Elevated reads concern only technical evidence. Business permissions are
        checked separately; no elevated write or customer read is performed.
        Unrelated pricing edits may intentionally make a date unknown.
        """
        self.ensure_one()
        properties = self.env["ir.property"].sudo().search([
            ("name", "=", PRICELIST_FIELD),
            ("company_id", "in", [False, self.env.company.id]),
            ("res_id", "in", [False, "res.partner,%s" % self.id]),
        ], order="id")
        source = {
            "company": self.env.company.id,
            "context_revision": self.env.company.pos_customer_pricing_revision,
            "country": self.country_id.id,
            "commercial_partner": self.commercial_partner_id.id,
            "properties": properties.read([
                "value_reference", "pos_customer_data_revision",
            ]),
        }
        encoded = json.dumps(source, sort_keys=True, default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _pos_pricelist_date(self):
        self.ensure_one()
        evidence = json.loads(self.pos_pricelist_evidence or "{}").get(
            str(self.env.company.id), {},
        )
        if (evidence.get("value") == self.property_product_pricelist.id
                and evidence.get("signature") == self._pos_pricelist_signature()):
            return evidence.get("date") or False
        return False

    def _pos_store_evidence(self, dates, pricelist_date=None):
        """Private entry point: callers cannot set evidence through RPC/context."""
        self.ensure_one()
        values = dict(dates)
        if pricelist_date is not None:
            evidence = json.loads(self.pos_pricelist_evidence or "{}")
            evidence[str(self.env.company.id)] = {
                "value": self.property_product_pricelist.id,
                "date": fields.Datetime.to_string(
                    fields.Datetime.to_datetime(pricelist_date),
                ),
                "signature": self._pos_pricelist_signature(),
            }
            values[EVIDENCE_FIELD] = json.dumps(evidence, sort_keys=True)
        if values:
            super(ResPartner, self).write(values)

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            self._pos_check_protected_values(values)
        partners = super().create(vals_list)
        now = fields.Datetime.now()
        for partner in partners:
            dates = {
                date_field: now for name, date_field in DATE_FIELDS.items()
                if partner[name]
            }
            partner._pos_store_evidence(
                dates, now if partner.property_product_pricelist else False,
            )
        return partners

    def write(self, vals):
        self._pos_check_protected_values(vals)
        tracked = EDITABLE_FIELDS.intersection(vals)
        pricing = bool({PRICELIST_FIELD, "country_id", "parent_id", "is_company"}
                       .intersection(vals))
        if not tracked and not pricing:
            return super().write(vals)
        before = {
            p.id: {name: p[name] for name in TRACKED_FIELDS if name in tracked}
            for p in self
        }
        prices = {
            p.id: (p.property_product_pricelist.id, p._pos_pricelist_date())
            for p in self
        } if pricing else {}
        sources = {
            p.id: (p.country_id.id, p.commercial_partner_id.id) for p in self
        } if pricing else {}
        result = super().write(vals)
        now = fields.Datetime.now()
        for partner in self:
            dates = {
                DATE_FIELDS[name]: now for name, value in before[partner.id].items()
                if partner[name] != value
            }
            price_date = None
            if pricing:
                previous_value, previous_date = prices[partner.id]
                changed = (
                    previous_value != partner.property_product_pricelist.id
                )
                price_date = now if changed else previous_date
                source = (
                    partner.country_id.id, partner.commercial_partner_id.id,
                )
                if sources[partner.id] != source:
                    # A country/parent round trip must not revive another
                    # company's evidence for an intervening effective value.
                    super(ResPartner, partner).write({EVIDENCE_FIELD: False})
            partner._pos_store_evidence(dates, price_date)
        return result

    @api.model
    def _pos_customer_context(self, partner_id, config_id, write=False):
        if not self.env.user.has_group("point_of_sale.group_pos_user"):
            raise AccessError(_("Se requiere acceso a Punto de Venta."))
        if type(partner_id) is not int or type(config_id) is not int:
            raise ValidationError(_("Cliente o configuración inválidos."))
        config = self.env["pos.config"].browse(config_id).exists()
        config.check_access_rights("read")
        config.check_access_rule("read")
        if not config or config.company_id not in self.env.user.company_ids:
            raise AccessError(_("No tiene acceso a esta compañía o configuración."))
        partner = self.with_company(config.company_id).browse(partner_id).exists()
        partner.check_access_rights("write" if write else "read")
        partner.check_access_rule("write" if write else "read")
        if not partner or (
            partner.company_id and partner.company_id != config.company_id
        ):
            raise AccessError(_("No tiene acceso a este cliente en esta compañía."))
        return partner, config.with_company(config.company_id)

    def _pos_customer_payload(self, config):
        self.ensure_one()
        available = (config.available_pricelist_ids | config.pricelist_id).filtered(
            lambda price: price.active and (
                not price.company_id or price.company_id == config.company_id
            )
        )
        available.check_access_rights("read")
        available.check_access_rule("read")
        self.property_product_pricelist.check_access_rights("read")
        self.property_product_pricelist.check_access_rule("read")
        data = self.read(list(EDITABLE_FIELDS) + list(DATE_FIELDS.values()))[0]
        data["pos_pricelist_updated_at"] = self._pos_pricelist_date()
        types = self._fields["customer_type"]._description_selection(self.env)
        return {
            "partner": data,
            "customer_types": types,
            "pricelists": available.read(["name"]),
            "type_pricelist_ids": {
                key: available.filtered(
                    lambda price: self._pricelist_matches_customer_type(price, key)
                ).ids for key, label in types
            },
        }

    @api.model
    def pos_customer_data_read(self, partner_id, config_id):
        partner, config = self._pos_customer_context(partner_id, config_id)
        return partner._pos_customer_payload(config)

    @api.model
    def _pos_validate_customer_values(self, values, payload):
        missing = []
        for name, label in (("name", _("Nombre")), ("mobile", _("WhatsApp"))):
            if not isinstance(values[name], str) or not values[name].strip():
                missing.append(label)
        customer_type = values["customer_type"]
        types = dict(payload["customer_types"])
        if not isinstance(customer_type, str) or customer_type not in types:
            missing.append(_("Tipo de Cliente"))
        price_id = values[PRICELIST_FIELD]
        if type(price_id) is not int or not price_id:
            missing.append(_("Tarifa"))
        if missing:
            raise ValidationError(
                _("Complete los campos: %s.") % ", ".join(missing),
            )
        if price_id not in [p["id"] for p in payload["pricelists"]]:
            raise ValidationError(
                _("La tarifa no está disponible en este POS."),
            )
        if price_id not in payload["type_pricelist_ids"][customer_type]:
            raise ValidationError(
                _("La tarifa no corresponde al tipo de cliente."),
            )

    @api.model
    def pos_customer_data_save(self, partner_id, config_id, changes):
        if not isinstance(changes, dict) or set(changes) - EDITABLE_FIELDS:
            raise ValidationError(_("Solo se permiten los cuatro datos del cliente."))
        partner, config = self._pos_customer_context(
            partner_id, config_id, write=True,
        )
        # Serialize review writes; merge only edited fields over current data.
        with self.env.cr.savepoint():
            self.env.cr.execute(
                "SELECT id FROM res_partner WHERE id = %s FOR UPDATE",
                [partner.id],
            )
            partner.invalidate_cache()
            values = {name: partner[name] or False for name in TRACKED_FIELDS}
            values[PRICELIST_FIELD] = partner.property_product_pricelist.id
            values.update(changes)
            payload = partner._pos_customer_payload(config)
            partner._pos_validate_customer_values(values, payload)
            updates = {
                key: value for key, value in changes.items()
                if value != (
                    partner[key].id if key == PRICELIST_FIELD else partner[key]
                )
            }
            if updates:
                # Preserve alta_mayoristas' and core's UI-save rules.
                partner.create_from_ui(dict(
                    updates, id=partner.id, mobile=values["mobile"],
                ))
            result = partner._pos_customer_payload(config)
            effective = dict(result["partner"])
            effective_price = effective[PRICELIST_FIELD]
            effective[PRICELIST_FIELD] = (
                effective_price[0] if effective_price else False
            )
            partner._pos_validate_customer_values(effective, result)
            return result
