from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class PosConfig(models.Model):
    _inherit = "pos.config"

    customer_data_review_enabled = fields.Boolean(
        string="Revisar datos del cliente al cobrar",
        default=False,
        copy=False,
        help="Muestra la revisión antes de validar ventas con cliente seleccionado. "
             "Recarga el punto de venta después de cambiar esta opción.",
    )

    @api.model
    def _check_customer_review_configuration_access(self):
        if not self.env.su and not self.env.user.has_group("base.group_system"):
            raise AccessError(_("Solo un administrador puede cambiar la revisión de clientes."))

    @api.model
    def create(self, values):
        values = dict(values)
        field = "customer_data_review_enabled"
        if field not in values:
            values[field] = self.default_get([field]).get(field, False)
        if values[field]:
            self._check_customer_review_configuration_access()
        return super().create(values)

    def write(self, values):
        if "customer_data_review_enabled" in values:
            self._check_customer_review_configuration_access()
        return super().write(values)
