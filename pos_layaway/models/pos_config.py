from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class PosConfig(models.Model):
    _inherit = "pos.config"

    layaway_enabled = fields.Boolean(
        string="Habilitar apartados", default=False, copy=False,
        help="Permite abrir apartados nuevos en esta caja. Al apagarlo, los folios "
             "existentes siguen disponibles. Recarga el POS para actualizar sus botones.",
    )
    layaway_menu_available = fields.Boolean(compute="_compute_layaway_menu_available")

    @api.depends("layaway_enabled")
    def _compute_layaway_menu_available(self):
        folios = self.env["pos.layaway"].sudo()
        for config in self:
            config.layaway_menu_available = config.layaway_enabled or bool(
                config.id and folios.search([
                    ("participant_config_ids", "in", config.ids),
                ], limit=1)
            )

    @api.model
    def _check_layaway_toggle_access(self):
        if not self.env.su and not self.env.user.has_group("base.group_system"):
            raise AccessError(_("Solo un administrador puede cambiar el interruptor de apartados."))

    @api.model
    def create(self, values):
        values = dict(values)
        if "layaway_enabled" not in values:
            values["layaway_enabled"] = self.default_get(["layaway_enabled"]).get("layaway_enabled", False)
        if values["layaway_enabled"]:
            self._check_layaway_toggle_access()
        return super().create(values)

    def write(self, vals):
        if "layaway_enabled" in vals:
            self._check_layaway_toggle_access()
        return super().write(vals)

    def _lock_layaway_opening(self):
        self.ensure_one()
        # Serialize the final opening check with changes to this register's switch.
        self.env.cr.execute("SELECT id FROM pos_config WHERE id = %s FOR SHARE", (self.id,))
        self.invalidate_cache(["layaway_enabled"])
