# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.
{
    'name': 'ABO Alkhier ',
    'version': '19.0.0.0',
    'category': 'base',
    'summary': 'Abo alkhier updates',

    'author': 'MahmoudFathi',
    'depends': ['base','point_of_sale','product_brand_inventory','account','sale','pos_sale'],
    'data': [
        'security/groups.xml',
        'views/report_pos_order.xml',
        'views/account_invoice_report.xml',
        'views/company_view.xml',
        'views/sale_order.xml',
        'views/pos_order.xml',
        'views/res_partner_view.xml',
        'data/pos_transfer.xml',
    ],
    # 'assets':{
    #     'point_of_sale._assets_pos': [
    #         '/bi_pos_restrict_zero_qty/static/src/app/models/models.js',
    #      ],
    # },
    'demo': [],
    'test': [],
    'license':'OPL-1',
    'installable': True,
    'auto_install': False,
}
