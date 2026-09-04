{
    "name": "Optima Sendcloud Zonal Test",
    "summary": "Diagnostic comparison for Sendcloud zonal shipping methods",
    "version": "18.0.1.0.0",
    "category": "Operations/Inventory/Delivery",
    "author": "Optima",
    "license": "LGPL-3",
    "depends": ["delivery_sendcloud_oca"],
    "data": [
        "security/ir.model.access.csv",
        "views/sendcloud_zonal_test_wizard_view.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
