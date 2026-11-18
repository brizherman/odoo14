from odoo import _, fields, models
from odoo.exceptions import AccessError


class PosSession(models.Model):
    _inherit = "pos.session"

    def get_layaway_campaigns(self):
        self.ensure_one()
        self.check_access_rights("read")
        self.check_access_rule("read")
        if not self.env.user.has_group("point_of_sale.group_pos_user"):
            raise AccessError(_("Se requiere acceso al punto de venta."))
        if self.state != "opened" or not self.config_id.active:
            return []
        campaigns = self.env["pos.layaway.campaign"]._available_for_opening(
            self.config_id, fields.Datetime.now()
        )
        return campaigns.read(["name", "code"])
