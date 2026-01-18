# -*- coding: utf-8 -*-

{
    "name": "POS Disable Order Delete Access",
    "summary": "Restrict POS order deletion based on user settings.",
    "description": """
        This module adds an extra layer of control to the Point of Sale by restricting the ability to delete POS orders. 
        A new boolean option is added in the User configuration. When enabled for a user, the delete option will be hidden 
        in the POS Orders screen, preventing the user from deleting any POS order.
    
        Key Features:
        - Adds a boolean field in User settings to control POS order delete access.
        - If the restriction is enabled, the user cannot view the delete icon in POS Orders.
        - Users with restricted access are completely blocked from deleting POS orders.
        - Ensures better data security and prevents accidental or unauthorized deletions.
    """,
    "author": "CodeSphere Tech",
    "website": "https://www.codespheretech.in/",
    "category": 'Point Of Sale',
    "version": "19.0.1.0.0",
    'sequence': 0,
    "currency": "USD",
    "price": "0",
    "depends": ["base", "point_of_sale",],
    "data": [
        "views/res_users_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "cst_pos_disable_delete_access/static/src/**/*",
        ],
    },
    "images": ["static/description/Banner.png"],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
