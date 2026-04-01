{
    "name": "Óptima Connector Client",
    "summary": "Envía pedidos de compra a Óptima vía XML-RPC automáticamente",
    "version": "18.0.1.0.0",
    "author": "Óptima Iluminación Profesional",
    "website": "https://optimaluz.com",
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "data": [
        "security/ir.model.access.csv",
        "views/sale_request_wizard_views.xml",
    ],
    "depends": [
        "base",
        "purchase",
        "sale",
    ],
}
