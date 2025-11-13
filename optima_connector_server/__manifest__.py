{
    "name": "Óptima Connector Server",
    "summary": "Integra pedidos de clientes externos vía XML-RPC y automatiza el envío de correos al confirmar ventas. Ajustes/Tecnic>
    "version": "18.0.1.1.0",
    "author": "Óptima Iluminación Profesional",
    "website": "https://optimaluz.com",
    "license": "LGPL-3",
    "depends": [
        "sale_management",
        "mail",  # Asegura que mail.template esté disponible
    ],
    "data": [],
    "installable": True,
    "application": False,
}
