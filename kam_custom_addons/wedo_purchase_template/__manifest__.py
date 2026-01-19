# -*- coding: utf-8 -*-

{
    'name': "Purchase Template",
    'version' : '19.0.1.0',
	'license' : 'OPL-1',
	'author': 'Mahmoud Fathi',
	'support' : 'mahmah273@gmail.com',
    'category': 'purchases',
    'sequence': 1,
    'description': """
	By creating custom quotation templates, you will save a lot of time.
	Indeed, with the use of templates, you will be able to send complete quotations at a fast pace
    """,
    'depends': ['purchase','stock','sale_management','account'],
	'images': ['images/main_screenshot.png'],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'views/account_move.xml',
        'views/purchase_template_views.xml',
        'views/custom_order_tag.xml',
        'views/product_template_view.xml',
        'views/product_category.xml',
        'views/product_packaging_views.xml',
        'views/sale_order.xml',
        'views/product_pricelist.xml',
    ],
    'demo': [
    ],
}
