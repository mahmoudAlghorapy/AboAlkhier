from odoo import models, fields, api
from odoo.exceptions import AccessError, ValidationError


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.constrains('phone')
    def _check_mobile_length(self):
        for partner in self:
            if partner.phone and (not partner.phone.isdigit() or len(partner.phone) != 11):
                raise ValidationError("Mobile number must contain exactly 11 digits and only digits.")

    @api.model
    def _search_display_name(self, operator, value):
        if operator in ('ilike', ) and value:
            domain = ['|', ('phone', '=ilike', value + '%'), ('name', 'ilike', value)]

            return domain
        return super()._search_display_name(operator, value)

    # @api.depends('name', 'parent_id', 'phone')
    # def _compute_display_name(self):
    #     """ Return the categories' display name including phone number. """
    #     for category in self:
    #         names = []
    #         current = category
    #
    #         # Build the hierarchy path
    #         while current:
    #             # Include phone number if it exists
    #             display_text = current.name or ""
    #             if current.phone:
    #                 display_text += f" ({current.phone})"
    #             names.append(display_text)
    #             current = current.parent_id
    #
    #         # Join in reverse order (from root to leaf)
    #         category.display_name = ' / '.join(reversed(names))
