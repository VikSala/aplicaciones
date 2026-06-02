{
    'name': 'Atajos Menú Principal',
    'version': '1.2',
    'category': 'Hidden',
    'summary': 'Atajos de apps por puesto de trabajo, globales o solo para administradores',
    'depends': ['base', 'web', 'hr'],
    'data': [
        'security/ir.model.access.csv',
        'security/ir_rules.xml',
        'views/shortcut_views.xml',
    ],
    'installable': True,
    'application': True,
}
