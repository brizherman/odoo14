from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError


class PosSession(models.Model):
    _inherit = "pos.session"

    def _check_layaway_session(self, require_open=True):
        self.ensure_one()
        self.check_access_rights("read")
        self.check_access_rule("read")
        if not self.exists() or not self.env.user.has_group("point_of_sale.group_pos_user"):
            raise AccessError(_("Se requiere acceso al punto de venta."))
        if self.company_id not in self.env.companies:
            raise AccessError(_("La caja no pertenece a una compañía habilitada."))
        if require_open and (self.state != "opened" or not self.config_id.active):
            raise UserError(_("La sesión de esta caja no está abierta."))
        return self

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

    def _lock_layaway_stock_session(self):
        self.ensure_one()
        self.check_access_rights("write")
        self.check_access_rule("write")
        # An UPDATE forces concurrent payments or closing to retry on a fresh snapshot.
        self.env.cr.execute(
            "UPDATE pos_session SET write_date = %s WHERE id = %s",
            (fields.Datetime.now(), self.id),
        )
        self.invalidate_cache(["write_date"])

    def _validate_session(self):
        if self.env["stock.picking"]._layaway_stock_location(self.config_id.picking_type_id):
            self._lock_layaway_stock_session()
        return super()._validate_session()

    def _get_split_receivable_vals(self, payment, amount, amount_converted):
        vals = super()._get_split_receivable_vals(payment, amount, amount_converted)
        if payment.payment_method_id.sudo().layaway_application:
            order = payment.pos_order_id
            vals["name"] = "%s · %s" % (order.pos_reference, order.name)
        return vals

    def _reconcile_account_move_lines(self, data):
        data = super()._reconcile_account_move_lines(data)
        # Native POS creates one receivable line per split payment.
        for order in self.order_ids.filtered("layaway_application_move_ids"):
            payment = order.payment_ids.filtered(lambda line: line.payment_method_id.layaway_application)
            bridge = payment.payment_method_id.receivable_account_id
            entry = order.layaway_application_move_ids.line_ids.filtered_domain([
                ("account_id", "=", bridge.id), ("reconciled", "=", False),
            ])
            counterpart = self.move_id.line_ids.filtered_domain([
                ("account_id", "=", bridge.id), ("reconciled", "=", False),
                ("name", "=", "%s · %s" % (order.pos_reference, order.name)),
            ])
            if len(payment) != 1 or len(entry) != 1 or len(counterpart) != 1 or self.currency_id.compare_amounts(
                entry.credit, counterpart.debit,
            ):
                raise UserError(_("No cuadra la aplicación de cobros de %s.") % order.pos_reference)
            (entry | counterpart).reconcile()
        return data

    def _create_picking_at_end_of_session(self):
        self.ensure_one()
        holds = self.env["stock.picking"].sudo().with_company(self.company_id).search([
            ("layaway_hold_order_id.session_id", "=", self.id),
            ("state", "not in", ("done", "cancel")),
        ])
        holds._complete_pos_sale_hold()
        holds.write({"pos_session_id": self.id, "origin": self.name})
        return super()._create_picking_at_end_of_session()
