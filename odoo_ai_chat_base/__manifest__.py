{
    "name": "Odoo AI Chat Base",
    "version": "18.0.1.0.0",
    "category": "Website",
    "summary": "Plantilla base de chatbot web conectada a n8n",
    "depends": ["website"],
    "data": [
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "odoo_ai_chat_base/static/src/css/ai_chat.css",
            "odoo_ai_chat_base/static/src/js/ai_chat.js",
        ],
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
