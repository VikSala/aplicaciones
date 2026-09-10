{
    "name": "Optima Delivery Pickup",
    "summary": "Núcleo multi-proveedor para puntos de recogida en ecommerce",
    "version": "18.0.0.8.6",
    "category": "Website/eCommerce",
    "author": "Optima",
    "license": "LGPL-3",
    "depends": ["website_sale", "stock_delivery"],
    "data": [
        "views/product_views.xml",
        "views/sale_order_views.xml",
        "views/stock_picking_views.xml",
        "views/website_delivery_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "optima_delivery_pickup/static/src/js/provider_registry.esm.js",
            "optima_delivery_pickup/static/src/js/checkout.esm.js",
            "optima_delivery_pickup/static/src/scss/checkout.scss",
        ],
    },
    "installable": True,
    "application": False,
}
