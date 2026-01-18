from odoo import fields, models, api
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.constrains('order_line','order_line.product_id')
    def _check_order_line_quantities(self):
        for order in self:
            for line in order.order_line:
                if line.product_id and line.product_id.based_on_quantity and line.product_id.minimum_qty:
                    if line.product_uom_qty < line.product_id.minimum_qty:
                        raise ValidationError(
                            f"Line {line.product_id.name}: Quantity ({line.product_uom_qty}) exceeds "
                            f"Minimum allowed ({line.product_id.minimum_qty})!"
                        )

