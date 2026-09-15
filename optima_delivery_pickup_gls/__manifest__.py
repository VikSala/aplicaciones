{
    "name": "Optima Delivery Pickup - GLS",
    "summary": "GLS ParcelShop + motor de tarifas XLSX para Optima Delivery Pickup",
    "version": "18.0.0.2.2",
    "category": "Website/eCommerce",
    "author": "Optima",
    "license": "AGPL-3",
    "depends": [
        "optima_delivery_pickup",
        "delivery_gls_asm",
    ],
    "external_dependencies": {"python": ["openpyxl"]},
    "data": [
        "security/ir.model.access.csv",
        "views/gls_tariff_views.xml",
        "views/gls_tariff_import_views.xml",
        "views/delivery_carrier_views.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "optima_delivery_pickup_gls/static/src/js/gls_provider.esm.js",
            "optima_delivery_pickup_gls/static/src/scss/gls_marker.scss",
        ],
    },
    "installable": True,
    "application": False,
}
