from odoo import api, models, fields
from odoo.exceptions import AccessError, LockError, MissingError, ValidationError, UserError


class PosConfig(models.Model):
    """Inherit pos configuration and add new fields."""
    _inherit = 'pos.config'

    refund_security = fields.Integer(string='POS access Security',
                                     help="Refund security password, used for that specified shop")

    @api.model
    def fetch_global_refund_security(self):
        """
        Fetches the global refund security parameter from system settings.

        This method retrieves the value of the configuration parameter
        'pos_refund_password.global_refund_security' stored in the `ir.config_parameter` model.

        Returns:
            str or None: The value of the global refund security parameter if set, otherwise None.
        """
        param = self.env['ir.config_parameter'].sudo().get_param('pos_refund_password.global_refund_security')
        return param


class ProductProductInherit(models.Model):
    _inherit = 'product.product'

    @api.model
    def _load_pos_data_fields(self, config):
        fields = super()._load_pos_data_fields(config)
        return fields + ['based_on_quantity', 'minimum_qty']


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _load_pos_data_fields(self, config):
        fields = super()._load_pos_data_fields(config)
        return fields + ['based_on_quantity', 'minimum_qty']


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    @api.constrains('qty', 'product_id')
    def _check_min_qty_pos(self):
        for line in self:
            p = line.product_id
            if p.based_on_quantity and p.minimum_qty and line.qty < p.minimum_qty:
                raise ValidationError(
                    f"Line {p.display_name}: Quantity ({line.qty}) is less than "
                    f"Minimum allowed ({p.minimum_qty})!"
                )