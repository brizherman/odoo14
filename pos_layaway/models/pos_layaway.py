from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


from .pos_layaway_campaign import local_date


TERMS = (
    "currency_id", "timezone", "opening_start", "opening_end", "addition_end",
    "pickup_end", "credit_end", "minimum_amount", "deposit_percentage",
)


class PosLayaway(models.Model):
    _name = "pos.layaway"
    _description = "Apartado POS"
    _order = "opened_at desc, id desc"
    _rec_name = "folio"

    folio = fields.Char(required=True, readonly=True, copy=False)
    campaign_id = fields.Many2one("pos.layaway.campaign", required=True, ondelete="restrict")
    campaign_name = fields.Char(required=True)
    campaign_code = fields.Char(required=True)
    participant_config_ids = fields.Many2many("pos.config")
    participant_company_ids = fields.Many2many("res.company")
    currency_id = fields.Many2one("res.currency", required=True)
    timezone = fields.Char(required=True)
    opening_start = fields.Date(required=True)
    opening_end = fields.Date(required=True)
    addition_end = fields.Date(required=True)
    pickup_end = fields.Date(required=True)
    credit_end = fields.Date(required=True)
    minimum_amount = fields.Monetary(required=True)
    deposit_percentage = fields.Float(required=True)
    partner_id = fields.Many2one("res.partner", required=True, ondelete="restrict")
    contact_name = fields.Char(required=True, index=True)
    phone = fields.Char(required=True)
    phone_digits = fields.Char(required=True, index=True)
    opened_at = fields.Datetime(required=True, index=True)
    opened_on = fields.Date(required=True, index=True)
    session_id = fields.Many2one("pos.session", required=True, ondelete="restrict")
    user_id = fields.Many2one("res.users", required=True, ondelete="restrict")
    warehouse_id = fields.Many2one("stock.warehouse", required=True, ondelete="restrict")
    line_ids = fields.One2many(
        "pos.layaway.line", "layaway_id", domain=[("released_by_id", "=", False)],
    )
    payment_ids = fields.One2many("pos.layaway.payment", "layaway_id")
    transfer_ids = fields.One2many("pos.layaway.transfer", "layaway_id")
    sale_id = fields.Many2one("pos.order", copy=False, ondelete="restrict", readonly=True)
    amount_total = fields.Monetary(compute="_compute_amounts", store=True)
    amount_deposit = fields.Monetary(compute="_compute_amounts", store=True)
    amount_installments = fields.Monetary(compute="_compute_amounts", store=True)
    amount_paid = fields.Monetary(compute="_compute_amounts", store=True)
    amount_due = fields.Monetary(compute="_compute_amounts", store=True)
    payment_state = fields.Selection(
        [("unpaid", "Sin pago"), ("partial", "Pago parcial"), ("paid", "Liquidado")],
        compute="_compute_amounts", store=True,
    )
    pickup_state = fields.Selection(
        [("pending", "Pendiente"), ("partial", "Parcial"), ("done", "Entregado")],
        compute="_compute_pickup_state", store=True,
    )

    _sql_constraints = [
        ("folio_unique", "UNIQUE(folio)", "El folio ya está en uso."),
        ("sale_unique", "UNIQUE(sale_id)", "La venta ya está vinculada a un apartado."),
    ]

    @api.depends(
        "line_ids.amount_total", "line_ids.released_by_id",
        "payment_ids.amount", "payment_ids.kind", "currency_id",
    )
    def _compute_amounts(self):
        for layaway in self:
            currency = layaway.currency_id
            payments = layaway.payment_ids
            layaway.amount_total = currency.round(sum(layaway.line_ids.mapped("amount_total")))
            layaway.amount_deposit = currency.round(sum(payments.filtered_domain([
                ("kind", "=", "deposit"),
            ]).mapped("amount")))
            layaway.amount_installments = currency.round(sum(payments.filtered_domain([
                ("kind", "=", "installment"),
            ]).mapped("amount")))
            layaway.amount_paid = currency.round(layaway.amount_deposit + layaway.amount_installments)
            layaway.amount_due = currency.round(layaway.amount_total - layaway.amount_paid)
            if layaway.amount_due <= 0:
                layaway.payment_state = "paid"
            else:
                layaway.payment_state = "partial" if layaway.amount_paid else "unpaid"

    @api.depends("line_ids.qty_picked_up", "line_ids.qty_pending", "line_ids.released_by_id")
    def _compute_pickup_state(self):
        for layaway in self:
            if not any(layaway.line_ids.mapped("qty_picked_up")):
                layaway.pickup_state = "pending"
            else:
                layaway.pickup_state = "partial" if any(
                    layaway.line_ids.mapped("qty_pending")
                ) else "done"

    def _check_reservation_coverage(self):
        self.ensure_one()
        required = self.currency_id.round(self.amount_total * self.deposit_percentage / 100)
        if self.currency_id.compare_amounts(self.amount_paid, required) < 0:
            raise ValidationError(_("El importe confirmado es insuficiente para reservar la mercancía."))

    def _check_pickup_payment(self):
        self.ensure_one()
        if self.currency_id.compare_amounts(self.amount_due, 0) > 0 or not self.sale_id:
            raise ValidationError(_("La mercancía solo se puede entregar después de liquidar el apartado."))

    @api.model
    def _create_folio(self, session, campaign, partner, name, phone, opened_at, lines):
        if not self.env.su:
            raise AccessError(_("La creación del folio requiere una operación del servidor."))
        if not lines:
            raise ValidationError(_("Agrega mercancía al apartado."))
        config = session.config_id
        return self.create({
            **{field: campaign[field].id if field == "currency_id" else campaign[field]
               for field in TERMS},
            "folio": self.env["ir.sequence"].next_by_code("pos.layaway"),
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "campaign_code": campaign.code,
            "participant_config_ids": [(6, 0, campaign.pos_config_ids.ids)],
            "participant_company_ids": [(6, 0, campaign.company_ids.ids)],
            "partner_id": partner.id,
            "contact_name": name,
            "phone": phone,
            "phone_digits": "".join(char for char in phone if char.isdecimal()),
            "opened_at": opened_at,
            "opened_on": local_date(opened_at, campaign.timezone),
            "session_id": session.id,
            "user_id": session.env.uid,
            "warehouse_id": config.picking_type_id.warehouse_id.id,
            "line_ids": [(0, 0, line) for line in lines],
        })

    def write(self, vals):
        self.check_access_rights("write")
        if "sale_id" in vals and (
            not self.env.su or not vals["sale_id"] or any(self.mapped("sale_id"))
        ):
            raise AccessError(_("La venta del apartado conserva el vínculo asignado por el servidor."))
        immutable = set(TERMS) | {
            "folio", "campaign_id", "campaign_name", "campaign_code", "participant_config_ids",
            "participant_company_ids", "partner_id", "contact_name", "phone", "phone_digits",
            "opened_at", "opened_on", "session_id", "user_id", "warehouse_id",
            "payment_ids", "amount_total", "amount_deposit", "amount_installments",
            "amount_paid", "amount_due", "payment_state",
        }
        if immutable.intersection(vals):
            raise ValidationError(_("El acuerdo original del apartado se conserva."))
        return super().write(vals)

    def unlink(self):
        raise ValidationError(_("El folio conserva el historial del apartado."))


class PosLayawayLine(models.Model):
    _name = "pos.layaway.line"
    _description = "Mercancía de apartado POS"

    layaway_id = fields.Many2one("pos.layaway", required=True, ondelete="restrict", index=True)
    product_id = fields.Many2one("product.product", required=True, ondelete="restrict")
    product_name = fields.Char(required=True)
    warehouse_id = fields.Many2one("stock.warehouse", required=True, ondelete="restrict")
    location_id = fields.Many2one("stock.location", required=True, ondelete="restrict")
    qty = fields.Float(required=True, digits="Product Unit of Measure")
    qty_picked_up = fields.Float(digits="Product Unit of Measure")
    qty_pending = fields.Float(compute="_compute_pending", digits="Product Unit of Measure")
    currency_id = fields.Many2one(related="layaway_id.currency_id")
    pricelist_id = fields.Many2one("product.pricelist", ondelete="restrict")
    price_unit = fields.Float(required=True, digits="Product Price")
    amount_tax = fields.Monetary(required=True)
    amount_total = fields.Monetary(required=True)
    tax_details = fields.Text()
    released_by_id = fields.Many2one(
        "pos.layaway.operation", ondelete="restrict", copy=False, readonly=True, index=True,
    )

    _sql_constraints = [
        ("positive_qty", "CHECK(qty > 0)", "La cantidad debe ser positiva."),
        ("pickup_qty", "CHECK(qty_picked_up >= 0 AND qty_picked_up <= qty)",
         "La cantidad entregada no puede superar la cantidad acordada."),
    ]

    @api.depends("qty", "qty_picked_up")
    def _compute_pending(self):
        for line in self:
            line.qty_pending = line.qty - line.qty_picked_up
