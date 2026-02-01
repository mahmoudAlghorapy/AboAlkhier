from odoo import models, fields, api


class ResCompany(models.Model):
    _inherit = 'res.company'

    activity_code = fields.Char('Activity Code', help='Activity code of the company')
