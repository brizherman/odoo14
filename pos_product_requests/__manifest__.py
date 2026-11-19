{
    "name": "POS Product Requests",
    "version": "14.0.1.1.0",
    "category": "Sales/Point of Sale",
    "summary": "Record and review unavailable product requests in the POS",
    "license": "AGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "security/pos_product_request_security.xml",
        "security/ir.model.access.csv",
        "views/assets.xml",
        "views/pos_product_request_views.xml",
    ],
    "qweb": ["static/src/xml/product_requests.xml"],
    "installable": True,
}
