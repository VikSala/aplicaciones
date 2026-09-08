{
    "name": "Optima Delivery Pickup - Sendcloud",
    "summary": "Adaptador Sendcloud para Optima Delivery Pickup",
    "version": "18.0.0.3.1",
    "category": "Website/eCommerce",
    "author": "Optima",
    "license": "LGPL-3",
    "depends": [
        "optima_delivery_pickup",
        "delivery_sendcloud_oca",
    ],
    "data": ["views/sale_order_views.xml"],
    "assets": {
        "web.assets_frontend": [
            "optima_delivery_pickup_sendcloud/static/src/js/sendcloud_provider.esm.js",
        ],
    },
    "installable": True,
    "application": False,
}
