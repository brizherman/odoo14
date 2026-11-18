import json

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

    @http.route("/pos/layaway/receipt/<int:session_id>/<int:folio_id>/<string:reference>",
                auth="user", type="http", methods=["GET"])
    def receipt(self, session_id, folio_id, reference, original=None):
        session = request.env["pos.session"].browse(session_id)
        result, reprint = session._layaway_receipt(folio_id, reference, original == "1")
        lines = result.get("quote", {}).get("lines", [])
        digits = result["receipt"]["decimal_places"]
        return request.render("pos_layaway.layaway_receipt", {
            "document": result,
            "reprint": reprint,
            "tax_total": sum(line["amount_tax"] for line in lines),
            "tax_names": {
                line["product_id"]: ", ".join(dict.fromkeys(
                    tax["name"] for tax in json.loads(line["tax_details"])
                )) for line in lines
            },
            "money": lambda amount: "{:,.{}f}".format(amount, digits),
        }, headers=[("Cache-Control", "no-store")])
