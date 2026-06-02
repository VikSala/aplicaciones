{
    'name': 'Bloqueo de Proveedor por Ajustes',
    'version': '1.1',
    'depends': ['purchase', 'base_setup'],
    'data': [
        'security/security.xml', # Añadir esta línea
        'security/ir.model.access.csv',
        'views/vista.xml',
    ],
    'installable': True,
}