
from odoo import models, fields


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

