import math

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


def local_date(now, timezone):
    utc_now = pytz.utc.localize(fields.Datetime.to_datetime(now))
    return utc_now.astimezone(pytz.timezone(timezone)).date()


class PosLayawayCampaign(models.Model):
    _name = "pos.layaway.campaign"
    _description = "Campaña de apartados POS"
    _order = "opening_start, id"

    name = fields.Char(string="Nombre", required=True)
    code = fields.Char(string="Identificador", required=True, copy=False)
    state = fields.Selection(
        [("draft", "Borrador"), ("active", "Activa"), ("archived", "Archivada")],
        string="Estado",
        required=True,
        default="draft",
        copy=False,
    )
    pos_config_ids = fields.Many2many("pos.config", string="Cajas participantes", required=True)
    warehouse_ids = fields.Many2many(
        "stock.warehouse", string="Tiendas", compute="_compute_participants", compute_sudo=True
    )
    company_ids = fields.Many2many(
        "res.company", string="Compañías", compute="_compute_participants", store=True
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    timezone = fields.Selection(
        [(name, name) for name in pytz.all_timezones],
        string="Zona horaria",
        required=True,
        default=lambda self: self.env.user.tz or "UTC",
    )
    opening_start = fields.Date(string="Inicio de apertura", required=True)
    opening_end = fields.Date(string="Fin de apertura", required=True)
    addition_end = fields.Date(string="Límite de adiciones", required=True)
    pickup_end = fields.Date(string="Límite de recogida", required=True)
    credit_end = fields.Date(string="Límite de uso del saldo", required=True)
    minimum_amount = fields.Monetary(
        string="Importe mínimo",
        required=True,
        default=0,
        help="El total con impuestos debe superar este importe.",
    )
    deposit_percentage = fields.Float(
        string="Anticipo (%)", required=True, default=0, help="Cobertura mínima del total vigente."
    )

    _sql_constraints = [
        ("code_unique", "UNIQUE(code)", "El identificador de campaña ya está en uso."),
    ]

    @api.depends("pos_config_ids.company_id", "pos_config_ids.picking_type_id.warehouse_id")
    def _compute_participants(self):
        for campaign in self:
            configs = campaign.pos_config_ids
            campaign.company_ids = configs.company_id
            campaign.warehouse_ids = configs.picking_type_id.warehouse_id

    @api.constrains("opening_start", "opening_end", "addition_end", "pickup_end", "credit_end")
    def _check_dates(self):
        for campaign in self:
            dates = (
                campaign.opening_start, campaign.opening_end, campaign.addition_end,
                campaign.pickup_end, campaign.credit_end,
            )
            if not all(dates) or list(dates) != sorted(dates):
                raise ValidationError(_("Revisa el orden de las fechas de la campaña."))

    @api.constrains("minimum_amount", "deposit_percentage")
    def _check_amounts(self):
        for campaign in self:
            if not math.isfinite(campaign.minimum_amount) or campaign.minimum_amount < 0:
                raise ValidationError(
                    _("El importe mínimo debe ser un importe válido mayor o igual a cero.")
                )
            if not 0 < campaign.deposit_percentage <= 100:
                raise ValidationError(
                    _("El porcentaje de anticipo debe ser mayor que 0 y no superior a 100.")
                )

    @api.constrains("pos_config_ids", "currency_id", "state")
    def _check_configurations(self):
        for campaign in self:
            configs = campaign.sudo().pos_config_ids
            if not configs:
                raise ValidationError(_("Selecciona al menos una caja participante."))
            if any(config.currency_id != campaign.currency_id for config in configs):
                raise ValidationError(
                    _("Las cajas participantes deben usar la moneda de la campaña.")
                )
            if any(
                not config.picking_type_id.warehouse_id
                or config.picking_type_id.warehouse_id.company_id != config.company_id
                for config in configs
            ):
                raise ValidationError(
                    _("Cada caja participante debe tener un almacén de su compañía.")
                )
            if campaign.state == "active" and any(not config.active for config in configs):
                raise ValidationError(_("Una campaña activa debe usar cajas activas."))

    def _check_company_access_for_management(self):
        if not self.env.su and (
            self.sudo().pos_config_ids.company_id - self.env.companies
        ):
            raise AccessError(
                _("Para administrar la campaña, habilita todas las compañías participantes.")
            )

    @api.model_create_multi
    def create(self, vals_list):
        self.check_access_rights("create")
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            if vals.get("state", self.env.context.get("default_state", "draft")) != "draft":
                raise ValidationError(_("Las campañas se deben crear en borrador."))
            vals["state"] = "draft"
            if not vals.get("code"):
                vals["code"] = self.env["ir.sequence"].next_by_code("pos.layaway.campaign")
        campaigns = super().create(vals_list)
        campaigns._check_company_access_for_management()
        campaigns._check_configurations()
        campaigns._check_amounts()
        return campaigns

    def write(self, vals):
        self.check_access_rights("write")
        self.check_access_rule("write")
        self._check_company_access_for_management()
        if "state" in vals:
            transitions = {
                "draft": ("active", "archived"),
                "active": ("archived",),
                "archived": (),
            }
            for campaign in self:
                if vals["state"] not in (campaign.state, *transitions[campaign.state]):
                    raise ValidationError(_("La transición de estado de la campaña no es válida."))
        result = super().write(vals)
        if "pos_config_ids" in vals:
            self._check_company_access_for_management()
        return result

    def copy(self, default=None):
        self.ensure_one()
        self.check_access_rights("create")
        self.check_access_rule("read")
        self._check_company_access_for_management()
        defaults = dict(default or {}, state="draft")
        defaults.setdefault("name", _("%s (copia)") % self.name)
        return super().copy(defaults)

    def action_activate(self):
        return self.write({"state": "active"})

    def action_archive(self):
        return self.write({"state": "archived"})

    @api.model
    def _available_for_opening(self, config, now):
        campaigns = self.search([
            ("state", "=", "active"),
            ("pos_config_ids", "in", config.ids),
            ("currency_id", "=", config.currency_id.id),
        ])
        return campaigns.filtered(
            lambda campaign: campaign.opening_start
            <= local_date(now, campaign.timezone)
            <= campaign.opening_end
        )
