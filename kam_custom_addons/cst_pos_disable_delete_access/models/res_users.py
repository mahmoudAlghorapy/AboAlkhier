# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResUsers(models.Model):
    _inherit = 'res.users'

    restrict_delete_access = fields.Boolean(string="Restrict Delete Access")

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields = super(ResUsers, self)._load_pos_data_fields(config_id)
        if 'restrict_delete_access' not in fields:
            fields.append('restrict_delete_access')

        return fields
