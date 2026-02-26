{
    'name': "Product Image On Sale/Purchase Order Line",
    'version': '18.0.0.0.0',
    'summary': "Imágenes de producto en lineas: Ventas y Compras",
    'description': 
        """
        Display product image on sale order line(inherit_view_order_form) and purchase order line(inherit_purchase_order_form).
        """,
    'author': "Óptima Iluminación Profesional",
    'company': "Óptima Iluminación Profesional",
    'maintainer': 'Óptima Iluminación Profesional',
    'website': "https://optimaluz.com",
    'depends': ['base', 'sale'],
    'license': 'AGPL-3',
    'data': [
        'views/soluntec_inherit_view_order_form.xml',
        'views/soluntec_inherit_purchase_order_form.xml'],
    'demo': [],
    'installable': True,
    'auto_install': False,
}