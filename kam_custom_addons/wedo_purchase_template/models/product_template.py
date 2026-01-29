
from odoo import models, fields,api


class ProductTemplate(models.Model):
    _inherit = "product.template"

    company_ids = fields.Many2many(
        string="Companies",
        comodel_name="res.company",
    )

class ProductCategory(models.Model):
    _inherit = "product.category"

    company_ids = fields.Many2many(
        string="Companies",
        comodel_name="res.company",
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        params = super()._load_pos_data_fields(config_id)
        params += ['company_ids']
        return params

