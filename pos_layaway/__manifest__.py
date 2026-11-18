{
    "name": "Apartados en Punto de Venta",
    "summary": "Gestiona campañas, folios y reservas de apartados por tienda",
    "version": "14.0.1.6.0",
    "author": "Factor Fiesta",
    "license": "LGPL-3",
    "category": "Sales/Point of Sale",
    "depends": ["account", "point_of_sale", "pos_wholesale_control"],
    "data": [
        "security/pos_layaway_rules.xml",
        "security/ir.model.access.csv",
        "data/pos_layaway_sequence.xml",
        "views/pos_layaway_campaign_views.xml",
        "views/assets.xml",
        "report/layaway_label.xml",
        "report/layaway_receipt.xml",
    ],
    "qweb": ["static/src/xml/LayawayCampaignButton.xml", "static/src/xml/LayawayScreen.xml"],
}
