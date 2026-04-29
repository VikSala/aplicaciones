{
    'name': 'Gestión de Gastos e Inventario',
    'version': '18.0.1.0.0',
    'category': 'Operations',
    'depends': ['stock', 'project', 'account','mail', 'analytic'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/inv_gasto_views.xml',
        'views/project_project_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}