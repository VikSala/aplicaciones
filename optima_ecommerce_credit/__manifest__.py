{
    "name": "Optima Ecommerce Credit",
    "summary": "Riesgo financiero Ecommerce y pago a crédito controlado por crédito disponible",
    "version": "18.0.2.1.0",
    "category": "E-Commerce",
    "author": "Optima",
    "license": "AGPL-3",
    "depends": [
        "account",
        "sale",
        "website_sale",
    ],
    "data": [
        "views/res_partner_views.xml",
        "views/sale_order_views.xml",
        "views/account_move_views.xml",
        "templates/payment_templates.xml",
        "data/payment_method_data.xml",
        "data/payment_provider_data.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "optima_ecommerce_credit/static/src/js/post_processing.esm.js",
        ],
    },
    "installable": True,
    "application": False,
}
