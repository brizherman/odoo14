{
    "name": "Apartados en Punto de Venta",
    "summary": "Configura campañas de apartados por tienda y caja",
    "version": "14.0.1.0.0",
    "author": "Factor Fiesta",
    "license": "LGPL-3",
    "category": "Sales/Point of Sale",
    "depends": ["point_of_sale", "pos_wholesale_control"],
    "data": [
        "security/pos_layaway_rules.xml",
        "security/ir.model.access.csv",
        "data/pos_layaway_sequence.xml",
        "views/pos_layaway_campaign_views.xml",
        "views/assets.xml",
    ],
    "qweb": ["static/src/xml/LayawayCampaignButton.xml"],
}
