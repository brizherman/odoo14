from odoo import http
from odoo.http import request


class LayawayLabel(http.Controller):
    @http.route("/pos/layaway/label/<int:session_id>/<int:folio_id>", auth="user", type="http")
    def label(self, session_id, folio_id):
        session = request.env["pos.session"].browse(session_id)
        folio = session._find_layaway(folio_id)
        return request.render(
            "pos_layaway.layaway_label", {"docs": folio},
            headers=[("Cache-Control", "no-store")],
        )
