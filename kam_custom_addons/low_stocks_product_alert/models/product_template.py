# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2025-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo import api, fields, models


class ProductTemplate(models.Model):
    """
    This is an Odoo model for product templates. It inherits from the
    'product.template' model and extends its functionality by adding computed
    fields for product alert state and color field.

    Methods:
         _compute_alert_state: Computes the 'alert_state' and 'color_field'
         fields based on the product's stock quantity and low stock
    alert parameters

    """
    _inherit = 'product.template'

    alert_tag = fields.Char(
        string='Product Alert Tag',
        help='This field represents the alert tag of the product.', compute='_compute_alert_state')

    alert_state = fields.Boolean(string='Product Alert State',
                                 compute='_compute_alert_state',
                                 help='This field represents the alert state'
                                      'of the product')
    color_field = fields.Char(string='Background color',
                              help='This field represents the background '
                                   'color of the product.')

    @api.depends('qty_available')
    def _compute_alert_state(self):
        """ Computes the 'alert_state', 'color_field', and 'alert_tag' fields based on
        the product's stock quantity and low stock alert parameters."""
        stock_alert = self.env['ir.config_parameter'].sudo().get_param(
            'low_stocks_product_alert.is_low_stock_alert')

        min_low_stock_str = self.env['ir.config_parameter'].sudo().get_param(
            'low_stocks_product_alert.min_low_stock_alert')

        try:
            min_low_stock = int(min_low_stock_str) if min_low_stock_str else 0
        except ValueError:
            min_low_stock = 0

        for rec in self:
            if not stock_alert or stock_alert.lower() == 'false':
                rec.alert_state = False
                rec.color_field = 'white'
                rec.alert_tag = False
                continue

            if not rec.is_storable:
                rec.alert_state = False
                rec.color_field = 'white'
                rec.alert_tag = False
                continue

            # Check if stock is low
            is_low_stock = rec.qty_available <= min_low_stock

            if is_low_stock:
                rec.alert_state = True
                rec.color_field = '#fdc6c673'  # Light red/pink background
                rec.alert_tag = str(rec.qty_available)  # Show quantity as string
            else:
                rec.alert_state = False
                rec.color_field = 'white'
                rec.alert_tag = False

    @api.model
    def _load_pos_data_fields(self, config_id):
        """This method is used to load additional fields in the POS"""
        result = super()._load_pos_data_fields(config_id)
        result.append('alert_tag')
        result.append('lst_price')
        return result