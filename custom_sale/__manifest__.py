{
    'name': 'My First Module',
    'version': '19.0.1.0.0',
    'summary': 'This is a simple Odoo module',
    'description': 'Detailed description of my module',
    'author': 'Ayushi',
    'website': 'https://www.example.com',
    'category': 'Custom',
    'depends': ['base', 'sale'],
    'data': [
        'views/test_sale.xml',
        'views/delivery.xml',
        'views/invoice.xml',

    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': True,
    'auto_install': False,
}
