
from odoo import fields, models, api
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    """Adding field to product template"""
    _inherit = 'product.template'

    brand_id = fields.Many2one('product.brand', string='Brand',
                               help="Brand of the Product")
    eta_type = fields.Selection(string="ETA Item Code Type", selection=[('gs1', 'GS1'), ('egs', 'EGS'), ], required=False, )
    eta_code = fields.Char(string="ETA Item Code ", required=False, )
    based_on_quantity = fields.Boolean(string="Based On Quantity ",  )
    minimum_qty = fields.Float(string="Minimum Quantity",  required=False, )

    @api.constrains('minimum_qty')
    def _check_minimum_qty(self):
        for product in self:
            if product.minimum_qty < 0:
                raise ValidationError("Minimum quantity cannot be negative!")

