from odoo import models, fields, api


class ResCompany(models.Model):
    _inherit = "res.company"

    destination_company_id = fields.Many2one(
        'res.company',
        string='Destination Company',
        # required=True
    )
    # is_azora = fields.Boolean(string="IS Azora",  )