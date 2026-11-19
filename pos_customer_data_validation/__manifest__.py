{
    "name": "POS Customer Data Validation",
    "version": "14.0.1.1.0",
    "summary": "Review customer data before POS payment",
    "author": "Custom",
    "license": "LGPL-3",
    "category": "Point of Sale",
    "depends": ["point_of_sale", "alta_mayoristas"],
    "data": ["views/pos_config_views.xml", "views/assets.xml"],
    "qweb": [
        "static/src/xml/CustomerDataPopup.xml",
        "static/src/xml/ClientDetailsEdit.xml",
        "static/src/xml/PaymentScreen.xml",
    ],
    "installable": True,
    "application": False,
}
