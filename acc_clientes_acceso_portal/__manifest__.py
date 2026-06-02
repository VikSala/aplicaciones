{
    'name': 'Acceso Clientes ',
    'version': '1.0',
    'author': 'Desarrollo Interno',
    'category': 'Tools',
    'summary': 'Campos de usuario y contraseña',
    'depends': ['base'], 
    'data': [
        'security/ir.model.access.csv',
        'views/partner_view.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}