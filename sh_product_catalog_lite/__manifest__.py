{
    'name': 'Catálogo de Productos Pro',
    'version': '1.0',
    'summary': 'Generador de catálogos en PDF desde la lista de productos',
    'category': 'Sales',
    'author': 'Custom Dev',
    'depends': ['product', 'sale'],
    'data': [
            'security/ir.model.access.csv', # No olvides dar permisos al wizard
            'views/product_catalog_wizard_view.xml',
            'reports/report_catalog.xml',
            'reports/report_catalog_template.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}