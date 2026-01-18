
from odoo import models, fields


class ProductPriceList(models.Model):
    _inherit = "product.pricelist"

    company_ids = fields.Many2many(
        string="Companies",
        comodel_name="res.company",
    )