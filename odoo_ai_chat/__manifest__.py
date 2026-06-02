{
    "name": "Odoo AI Chat Local",
    "version": "18.0.2.10.37",
    "category": "Website",
    "summary": "Chat IA con n8n, carrito real, alta portal, usuario actual y administración desde IA para admin, cuentas de cliente e imagen condicional de producto y creación guiada con coste, categoría interna y categorías de ventas multiselección con búsqueda inferior, máximo 6 mostradas, rastreo de inventario, historial de pedidos de cliente, selector admin de historial por cliente, historial admin de compras por proveedor y comentarios técnicos en funciones",
    "depends": ["website", "website_sale", "sale", "purchase", "stock", "portal"],
    "data": [
        "views/res_config_settings_views.xml",
        "views/website_layout_inherit.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "odoo_ai_chat/static/src/js/ai_chat.js",
        ],
        "web.assets_backend": [
            "odoo_ai_chat/static/src/js/backend_history_filter.js",
        ],
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
