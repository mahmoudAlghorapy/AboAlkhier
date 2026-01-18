# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models, tools
class ProductTemplateInherit(models.Model):
    _inherit = 'product.template'

    stored_qty_available = fields.Float('Stock On Hand Quantity', related='qty_available',store=True)
    stored_standard_price = fields.Float('Stock Value', related='standard_price',store=True)



class ReportPosOrderInherit(models.Model):
    _inherit = 'report.pos.order'

    brand_id = fields.Many2one('product.brand', string='Brand', readonly=True)
    pos_categ_id = fields.Many2one('pos.category', string='Point of Sale Category',
                                   readonly=True, group_operator=None)
    qty_available = fields.Float(string='Stock On Hand Quantity', readonly=True, group_operator="max")
    stored_standard_price = fields.Float(string='Stock Value', readonly=True, group_operator="max")


    def _select(self):
        """Add brand_id to the SELECT clause"""
        return super()._select() + ',pt.brand_id AS brand_id, pt.stored_qty_available as qty_available, pt.stored_standard_price as stored_standard_price'

    def _group_by(self):
        """Add brand_id to the GROUP BY clause if needed"""
        # Note: Looking at the original code, there's no GROUP BY clause initially
        # So we need to check if parent has _group_by or create one
        group_by = super()._group_by()
        if group_by:
            return group_by + ',pt.brand_id, pt.stored_qty_available'
        return ',pt.brand_id'
