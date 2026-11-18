import hashlib
import json
import math
import re
import unicodedata

from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_round

from .pos_layaway_campaign import local_date
from .pos_layaway_payment import layaway_test_database


class PosSession(models.Model):
    _inherit = "pos.session"

    def quote_layaway(self, lines, campaign_id, partner_id=False, phone=False, layaway_id=False):
        self._check_layaway_session()
        session = self.with_company(self.company_id)
        quote = session._quote_layaway(
            lines, campaign_id, partner_id, phone, layaway_id, fields.Datetime.now(),
        )
        if layaway_test_database(self.env):
            methods = session._layaway_checkout_methods()
            quote.update({
                "confirmation": session._layaway_quote_digest(quote),
                "methods": [{
                    "id": method.id, "name": method.name, "cash": method.is_cash_count,
                } for method in methods],
            })
        return quote

    def _layaway_quote_digest(self, quote):
        snapshot = json.dumps([self.config_id.id, quote], sort_keys=True, allow_nan=False)
        return hashlib.sha256(snapshot.encode()).hexdigest()

    def _layaway_checkout_methods(self):
        session = self.sudo()
        return session.env["pos.layaway.payment"]._available_methods(session).filtered(
            lambda method: not method.layaway_transfer
        )

    def confirm_layaway(self, reference, proposal, confirmation, tenders):
        """Confirm the quoted agreement and its new money and stock together."""
        self._check_layaway_payment_test()
        session = self.sudo(False)._check_layaway_session(require_open=False)
        if not isinstance(proposal, dict) or set(proposal) != {
            "lines", "campaign_id", "partner_id", "phone", "layaway_id",
        }:
            raise ValidationError(_("Los datos de la propuesta de apartado no son válidos."))
        if not isinstance(confirmation, str) or not re.fullmatch(r"[a-f0-9]{64}", confirmation):
            raise ValidationError(_("Cotiza el apartado antes de confirmarlo."))
        session = session.with_company(session.company_id)
        folio = session._find_layaway(proposal["layaway_id"], require_open=False) if (
            proposal["layaway_id"]
        ) else self.env["pos.layaway"]
        operation_model = session.env["pos.layaway.operation"].sudo()
        tenders = operation_model.env["pos.layaway.payment"]._normalize_tenders(
            tenders, session.currency_id,
        ) if tenders != [] else []
        kind = "add_products" if folio else "open"

        return operation_model._confirm(
            session, reference, kind, [proposal, confirmation, tenders],
            lambda operation: session._apply_layaway_quote(
                operation, proposal, confirmation, tenders, folio,
            ),
            folio, pass_operation=True,
        )

    def _apply_layaway_quote(self, operation, proposal, confirmation, tenders, folio):
        self._lock_layaway_stock_session()
        quote = self._quote_layaway(**proposal, now=operation.create_date)
        if self._layaway_quote_digest(quote) != confirmation:
            raise ValidationError(_("Cambió la cotización. Vuelve a cotizar antes de confirmar."))
        if folio and folio.sale_id:
            raise UserError(_("Los ajustes de folios liquidados aún no están habilitados."))
        currency = self.currency_id
        amount = currency.round(sum(tender["amount"] for tender in tenders))
        if currency.compare_amounts(amount, quote["required_deposit"]) < 0 or not (amount or folio):
            raise ValidationError(_("El importe confirmado es insuficiente para reservar la mercancía."))
        allowed_methods = self._layaway_checkout_methods().ids
        if any(tender["method_id"] not in allowed_methods for tender in tenders):
            raise ValidationError(_("Usa un método de cobro inmediato habilitado en esta caja."))

        accounting = self.sudo().with_context({}, allowed_company_ids=self.company_id.ids)
        env = accounting.env
        if folio:
            kind = "installment"
            lines = env["pos.layaway.line"].create([
                dict(line, layaway_id=folio.id) for line in quote["lines"]
            ])
        else:
            kind = "deposit"
            folio = env["pos.layaway"]._create_folio(
                self, env["pos.layaway.campaign"].browse(quote["campaign_id"]),
                env["res.partner"].browse(quote["partner_id"]), quote["contact_name"],
                quote["phone"], operation.create_date, quote["lines"],
            )
            lines = folio.line_ids
        self._check_layaway_payment_amount(folio, amount, operation.create_date)
        payments = env["pos.layaway.payment"].browse()
        for tender in tenders:
            payments |= env["pos.layaway.payment"]._record_tender(
                operation, accounting, folio, kind, tender,
            )
        picking = env["stock.picking"]._reserve_layaway_lines(folio, self, lines)
        return folio, {
            "id": folio.id, "folio": folio.folio, "reference": operation.reference,
            "picking_id": picking.id, "quote": quote, "amount_applied": amount,
            "amount_paid": folio.amount_paid, "amount_due": folio.amount_due,
            "payments": payments.read([
                "method_id", "method_name", "amount", "amount_tendered", "amount_change",
            ], load="_classic_write"),
            "receipt": operation._receipt_snapshot(folio),
            **self._settle_layaway_if_paid(folio, operation, payments),
        }

    def _quote_layaway(self, lines, campaign_id, partner_id, phone, layaway_id, now):
        config = self.config_id
        campaign_model = self.env["pos.layaway.campaign"]
        partners = self.env["res.partner"]
        campaign_id = partners._wholesale_record_id(campaign_id)
        if layaway_id:
            agreement = self._find_layaway(layaway_id)
            if agreement.campaign_id.id != campaign_id:
                raise AccessError(_("El folio y la campaña no corresponden a esta caja."))
            if local_date(now, agreement.timezone) > agreement.addition_end:
                raise ValidationError(_("Terminó el plazo para agregar productos."))
            if agreement.pickup_state == "done":
                raise ValidationError(_("El folio ya no tiene mercancía pendiente."))
            if partner_id and partner_id != agreement.partner_id.id:
                raise ValidationError(_("El beneficiario del folio se conserva."))
            partner = agreement.partner_id
            name, phone = agreement.contact_name, agreement.phone
            previous_total, paid = agreement.amount_total, agreement.amount_paid
        else:
            agreement = campaign_model._available_for_opening(config, now).filtered(
                lambda campaign: campaign.id == campaign_id
            )
            if not agreement:
                raise ValidationError(_("La campaña no está abierta en esta caja."))
            partner = partners._wholesale_eligibility_partner(partner_id)
            name, phone = self._layaway_contact(partner, phone)
            previous_total = paid = 0.0

        currency = agreement.currency_id
        if currency != config.currency_id:
            raise ValidationError(_("La caja debe usar la moneda del apartado."))
        quoted = self._price_layaway_lines(lines, partner, currency, local_date(now, agreement.timezone))
        addition = currency.round(sum(line["amount_total"] for line in quoted))
        total = currency.round(previous_total + addition)
        if currency.compare_amounts(total, agreement.minimum_amount) <= 0:
            raise ValidationError(_("El total con impuestos debe superar el mínimo de la campaña."))
        target = currency.round(total * agreement.deposit_percentage / 100)
        return {
            "campaign_id": campaign_id, "layaway_id": layaway_id or False,
            "campaign_name": agreement.campaign_name if layaway_id else agreement.name,
            "partner_id": partner.id, "contact_name": name, "phone": phone,
            "currency_id": currency.id, "lines": quoted, "amount_new": addition,
            "amount_previous": previous_total, "amount_total": total,
            "amount_paid": paid, "required_deposit": max(0.0, currency.round(target - paid)),
            "wholesale_conditional": not layaway_id,
            "warehouse": config.picking_type_id.warehouse_id.display_name,
            "minimum_amount": agreement.minimum_amount,
            "deposit_percentage": agreement.deposit_percentage,
            "opening_start": fields.Date.to_string(agreement.opening_start),
            "opening_end": fields.Date.to_string(agreement.opening_end),
            "addition_end": fields.Date.to_string(agreement.addition_end),
            "pickup_end": fields.Date.to_string(agreement.pickup_end),
            "credit_end": fields.Date.to_string(agreement.credit_end),
        }

    def _layaway_contact(self, partner, phone):
        name = (partner.name or "").strip()
        normalized = unicodedata.normalize("NFKD", name.casefold())
        normalized = re.sub(r"[^a-z ]", "", "".join(
            char for char in normalized if not unicodedata.combining(char)
        ))
        generic_names = {"publico general", "publico en general", "cliente generico",
                         "consumidor final", "mostrador"}
        if not name or " ".join(normalized.split()) in generic_names:
            raise ValidationError(_("Identifica al beneficiario del apartado."))
        contact = phone or partner.mobile or partner.phone or ""
        if not isinstance(contact, str) or not re.fullmatch(r"[+\d ().\-]{7,32}", contact.strip()):
            raise ValidationError(_("Indica un teléfono de contacto válido."))
        count = sum(char.isdecimal() for char in contact)
        if not 7 <= count <= 15:
            raise ValidationError(_("Indica un teléfono de contacto válido."))
        return name, contact.strip()

    def _layaway_pricelist(self, partner, currency):
        config, company = self.config_id, self.company_id
        partners = self.env["res.partner"]
        pricelist = company.wholesale_pricelist_id
        if partners._wholesale_pricing_program(partner) == "distributor":
            eligibility = partners.get_wholesale_eligibility(partner.id, company.id, 0, config.id)
            if (
                eligibility["pricing_program"] == "distributor"
                and eligibility["automatic_decision"] == "wholesale" and not eligibility["error"]
            ):
                pricelist = self.env["product.pricelist"].browse(
                    eligibility["expected_pricelist"]["id"]
                )
        if not pricelist or pricelist.currency_id != currency or not partners._wholesale_list_usable(
            company, config, pricelist,
        ):
            raise ValidationError(_("Configura una lista de mayoreo válida para esta caja."))
        return pricelist

    def _price_layaway_lines(self, lines, partner, currency, date):
        if not isinstance(lines, list) or not lines:
            raise ValidationError(_("Agrega mercancía al apartado."))
        pricelist = self._layaway_pricelist(partner, currency)
        company = self.company_id
        position_model = self.env["account.fiscal.position"].sudo()
        position = position_model.get_fiscal_position(partner.id)
        # Read price/tax rules after resolving the product, session and contact with user access.
        taxes_model = self.env["account.tax"].sudo()
        picking_type = self.config_id.picking_type_id
        products = self.env["product.product"]
        quantities = {}
        for line in lines:
            if not isinstance(line, dict) or set(line) != {"product_id", "qty"}:
                raise ValidationError(_("Los datos de la mercancía no son válidos."))
            product_id = self.env["res.partner"]._wholesale_record_id(line["product_id"])
            quantity = line["qty"]
            if type(quantity) not in (int, float) or not 0 < quantity <= 1e9:
                raise ValidationError(_("La cantidad debe ser positiva y válida."))
            product = products.browse(product_id).exists()
            if product:
                product.check_access_rights("read")
                product.check_access_rule("read")
            if (
                not product or not product.active or not product.available_in_pos
                or not product.sale_ok or product.type != "product"
                or product.company_id and product.company_id != company
            ):
                raise ValidationError(_("El producto no puede apartarse en esta caja."))
            rounded = float_round(quantity, precision_rounding=product.uom_id.rounding)
            if not math.isclose(quantity, rounded, rel_tol=0, abs_tol=1e-9):
                raise ValidationError(_("La cantidad no respeta la unidad del producto."))
            quantities[product] = quantities.get(product, 0) + rounded

        result = []
        for product, quantity in quantities.items():
            price = pricelist.sudo().get_product_price(product, quantity, partner, date=date)
            product_taxes = product.sudo().taxes_id
            taxes = product_taxes.filtered(lambda tax: tax.company_id == company)
            if position:
                taxes = position.map_tax(taxes, product, partner)
            price = taxes_model._fix_tax_included_price_company(price, product_taxes, taxes, company)
            if not math.isfinite(price) or price < 0:
                raise ValidationError(_("El precio de mayoreo no es válido."))
            totals = taxes.compute_all(price, currency, quantity, product=product, partner=partner)
            result.append({
                "product_id": product.id, "product_name": product.display_name, "qty": quantity,
                "warehouse_id": picking_type.warehouse_id.id,
                "location_id": picking_type.default_location_src_id.id,
                "pricelist_id": pricelist.id, "price_unit": price,
                "amount_tax": currency.round(totals["total_included"] - totals["total_excluded"]),
                "amount_total": currency.round(totals["total_included"]),
                "tax_details": json.dumps(totals["taxes"]),
            })
        return result
