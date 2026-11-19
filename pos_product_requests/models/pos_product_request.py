from uuid import UUID

from psycopg2.errors import UniqueViolation

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class PosProductRequest(models.Model):
    _name = "pos.product.request"
    _description = "POS Product Request"
    _rec_name = "product_text"
    _order = "create_date desc, id desc"
    _check_company_auto = True

    product_text = fields.Text(string="Requested Product", required=True, readonly=True)
    reason = fields.Selection(
        [
            ("out_of_stock", "Out of stock"),
            ("not_carried", "We don't carry it"),
            ("does_not_exist", "Does not exist"),
        ],
        required=True,
        readonly=True,
    )
    config_id = fields.Many2one(
        "pos.config", string="Point of Sale", required=True, readonly=True, index=True,
        ondelete="restrict", check_company=True,
    )
    company_id = fields.Many2one(
        "res.company", required=True, readonly=True, index=True, ondelete="restrict",
    )
    capture_key = fields.Char(required=True, readonly=True, copy=False)

    _sql_constraints = [
        (
            "capture_unique",
            "unique(config_id, capture_key)",
            "This capture already exists for this point of sale.",
        ),
    ]

    @api.constrains("product_text")
    def _check_product_text(self):
        for request in self:
            if not request.product_text or not request.product_text.strip():
                raise ValidationError(_("Enter the requested product."))

    @api.model
    def _pos_request_scope(self, session_id):
        if not self.env.user.has_group("point_of_sale.group_pos_user"):
            raise AccessError(_("Point of Sale access is required."))
        if type(session_id) is not int or session_id <= 0:
            raise AccessError(_("An active point of sale session is required."))
        session = self.env["pos.session"].search([
            ("id", "=", session_id),
            ("state", "=", "opened"),
            ("rescue", "=", False),
            ("config_id.company_id", "in", self.env.companies.ids),
        ], limit=1)
        if not session:
            raise AccessError(_("An active point of sale session is required."))
        # Shared open sessions follow the standard POS access rules.
        return [
            ("config_id", "=", session.config_id.id),
            ("company_id", "=", session.company_id.id),
        ], session

    @api.model
    def save_from_pos(self, session_id, product_text, reason, capture_key):
        domain, session = self._pos_request_scope(session_id)
        if not isinstance(product_text, str) or not product_text.strip():
            raise ValidationError(_("Enter the requested product."))
        if not isinstance(reason, str) or reason not in dict(self._fields["reason"].selection):
            raise ValidationError(_("Select a valid reason."))
        try:
            capture_key = str(UUID(capture_key))
        except (AttributeError, TypeError, ValueError):
            raise ValidationError(_("Invalid capture key.")) from None

        product_text = product_text.strip()
        domain.append(("capture_key", "=", capture_key))
        # Creation is restricted to the validated POS session.
        requests = self.with_context({}).sudo()
        request = requests.search(domain, limit=1)
        if not request:
            try:
                with self.env.cr.savepoint():
                    request = requests.create({
                        "product_text": product_text,
                        "reason": reason,
                        "config_id": session.config_id.id,
                        "company_id": session.company_id.id,
                        "capture_key": capture_key,
                    })
            except UniqueViolation as error:
                if error.diag.constraint_name != "pos_product_request_capture_unique":
                    raise
                # The winning transaction may be invisible to our repeatable-read snapshot.
                with self.env.registry.cursor() as cursor:
                    concurrent_requests = requests.with_env(requests.env(cr=cursor))
                    existing = concurrent_requests.search_read(
                        domain, ["product_text", "reason"], limit=1,
                    )
                if not existing:
                    raise
                return self._confirm_capture(existing[0], product_text, reason)

        return self._confirm_capture(
            request.read(["product_text", "reason"])[0], product_text, reason,
        )

    @api.model
    def _confirm_capture(self, request, product_text, reason):
        if request["product_text"] != product_text or request["reason"] != reason:
            raise ValidationError(_(
                "This capture was already saved with different details. "
                "Restore the original details or start a new capture."
            ))
        return request["id"]

    @api.model
    def history_from_pos(self, session_id):
        domain, _session = self._pos_request_scope(session_id)
        reasons = dict(self._fields["reason"]._description_selection(self.env))
        rows = self.sudo().search_read(domain, ["product_text", "reason", "create_date"])
        for row in rows:
            row["reason_label"] = reasons[row.pop("reason")]
            row["create_date"] = fields.Datetime.to_string(row["create_date"])
        return rows
