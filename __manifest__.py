{
    'name': 'Clinic Management',
    'version': '19.0.1.0.0',
    'summary': 'Manages doctors and patient',
    'description': """
        Clinic Management System Module
        This module is used to create appoitments, register for patient and doctors ,
        also you can create consultation along with prescription within Odoo.
    """,
    'category': 'Academic',
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'license': 'LGPL-3',

    'depends': [
        'base',
        'mail',
        'product',
        'account',
    ],

    'data': [
        # Security
        'security/ir.model.access.csv',

        # Sequence
        'data/corn_scheduler.xml',
        'data/sequence.xml',
        'data/email_template.xml',

        'report/appointment_report.xml',

        #wizard
        'wizard/appointment_wizard.xml',
        
        # Views

        'views/patient_management.xml',
        'views/doctor_managment.xml',
        'views/appointment_management.xml',
        'views/speciality.xml',
        'views/consulation.xml',
        'views/appointment_line.xml',
        'views/dashboard.xml',
        'views/prescription.xml',
        'views/product.xml',

        # Menu
        'menu/menu.xml',
    ],

    'demo': [],

    'installable': True,
    'application': True,
    'auto_install': False,
}
