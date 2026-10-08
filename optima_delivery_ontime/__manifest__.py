{
    "name": "Optima Delivery OnTime",
    "summary": "OnTime home-delivery integration for Odoo",
    "version": "18.0.9.0.0",
    "category": "Inventory/Delivery",
    "author": "Optima",
    "license": "LGPL-3",
    "depends": ["delivery", "stock_delivery"],
    "data": [
        "security/ontime_security.xml",
        "security/ir.model.access.csv",
        "views/delivery_carrier_views.xml",
        "views/stock_picking_views.xml",
        "wizard/ontime_reconcile_wizard_views.xml",
    ],
    "external_dependencies": {
        "python": ["requests"],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
