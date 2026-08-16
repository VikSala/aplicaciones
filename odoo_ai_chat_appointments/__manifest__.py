{
    "name": "Odoo AI Chat Citas",
    "version": "18.0.8.0.0",
    "category": "Website",
    "summary": "Chatbot web para gestión de citas con empleados y WhatsApp",
    "depends": [
        "website",
        "hr",
        "hr_attendance",
        "open_whatsapp_connector",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/ir_cron_data.xml",
        "views/appointment_service_views.xml",
        "views/appointment_availability_views.xml",
        "views/appointment_conversation_views.xml",
        "views/appointment_session_views.xml",
        "views/hr_attendance_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "odoo_ai_chat_appointments/static/src/css/ai_chat.css",
            "odoo_ai_chat_appointments/static/src/js/ai_chat.js",
        ],
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
