{
    "name": "Optima Delivery Pickup - GLS",
    "summary": "Adaptador GLS ParcelShop para el mapa unificado de Optima Delivery Pickup",
    "version": "18.0.0.1.4",
    "category": "Website/eCommerce",
    "author": "Optima",
    "license": "AGPL-3",
    "depends": [
        "optima_delivery_pickup",
        "delivery_gls_asm",
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
