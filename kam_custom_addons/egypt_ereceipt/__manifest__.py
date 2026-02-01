{
    'name': 'Egypt e-Receipt Integration',
    'version': '1.1',
    'category': 'Point of Sale',
    'summary': 'Integration with Egypt Tax Authority e-Receipt API',
    'description': """
        This module integrates Odoo POS with Egypt's Tax Authority e-Receipt API:
        
        Features:
        * Automatic e-Receipt submission on POS order validation
        * Token-based authentication with Egyptian Tax Authority
        * Multi-company support
        * Comprehensive logging and error handling
        * Manual resubmission capabilities
        
        Requirements:
        * Valid Egyptian Tax Registration Number
        * API credentials from Egyptian Tax Authority
        * Internet connection for real-time submissions
    """,
    'author': 'Mahmoud Kousa',
    'depends': ['point_of_sale', 'account', 'l10n_eg_edi_eta'],

    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/egypt_ereceipt_views.xml',
        'views/pos_order_views.xml',
        'views/res_company_views.xml',
        'data/ir_cron.xml',
    ],

    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
