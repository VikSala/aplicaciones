{
    "name": "Menú de Usuario Personalizado",
    "version": "18.0.4.0.4",
    "category": "Website",
    "summary": "Portal B2B moderno con navegación lateral y panel de pedidos avanzado",
    "depends": [
        "portal",
        "sale",
        "sale_stock",
        "account",
        "stock",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/portal_layout.xml",
        "views/portal_home.xml",
        "views/portal_orders.xml",
        "views/portal_returns.xml",
        "views/portal_pages.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "mi_cuenta_extendida_usuario/static/src/scss/portal.scss",
            "mi_cuenta_extendida_usuario/static/src/js/portal_account.js",
        ],
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
