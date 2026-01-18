# -*- coding: utf-8 -*-
{
    "name": "POS Community-Enterprise Integration",
    "summary": "Sync POS data from Community DB to Enterprise DB via XML-RPC",
    "version": "19.0.1.0.0",
    "author": "Mahmoud Fathi",
    "website": "",
    "license": "LGPL-3",
    "depends": [
        "point_of_sale",
    ],
    "data": [
        "views/res_config_settings_views.xml",
        "views/purchase_order.xml",
        "views/pos_order.xml",
        "data/pos_integration_sequences.xml",
        "data/pos_integration_cron.xml",
    ],
    "installable": True,
    "application": False,
}
