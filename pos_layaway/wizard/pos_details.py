from odoo import fields, models


class PosDetails(models.TransientModel):
    _inherit = "pos.details.wizard"

    layaway_campaign_id = fields.Many2one("pos.layaway.campaign", string="Campaña de apartados")

    def generate_report(self):
        self.ensure_one()
        action = super().generate_report()
        action["data"]["layaway_campaign_id"] = self.layaway_campaign_id.id or False
        return action
