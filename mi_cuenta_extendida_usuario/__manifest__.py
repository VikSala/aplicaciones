{
    'name': 'Menú de Usuario Personalizado',
    'version': '1.0',
    'category': 'Website',
    'summary': 'Personalización del portal de cliente con botones específicos',
    'depends': ['portal', 'sale', 'account', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/vista.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}