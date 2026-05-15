{
    'name': 'Custom Report Modifier',
    'version': '18.0.1.0.0',
    'summary': 'Motor de herencias dinámicas sobre ir.ui.view sin despliegue de módulos',
    'description': """
        Permite crear, activar y desactivar herencias XPath sobre vistas Qweb
        directamente desde la interfaz, sin necesidad de crear módulos adicionales.
    """,
    'author': 'Custom',
    'category': 'Technical',
    'depends': ['base', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/custom_report_modifier_views.xml',
        'views/custom_report_modifier_menu.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
