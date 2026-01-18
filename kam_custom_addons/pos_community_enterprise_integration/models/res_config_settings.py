# -*- coding: utf-8 -*-
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    _description = 'Integration Configuration'

    url = fields.Char(
        string="URL",
        required=True,
        config_parameter='pos_community_enterprise_integration.url',
    )
    db = fields.Char(
        string="Database Name",
        required=True,
        config_parameter='pos_community_enterprise_integration.db',
    )
    username = fields.Char(
        string="Username",
        required=True,
        config_parameter='pos_community_enterprise_integration.username',
    )
    password = fields.Char(
        string="API Key",
        required=True,
        config_parameter='pos_community_enterprise_integration.password',
    )
