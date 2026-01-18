

from odoo import models, fields, api, _
from dateutil.relativedelta import relativedelta
from odoo.exceptions import AccessError, LockError, MissingError, ValidationError, UserError



class SaleOrder(models.Model):
    _inherit = 'sale.order'

    pos_order_count = fields.Integer(
        string='POS Orders Count',
        # compute='_compute_pos_order_count',
        # store=True,
        # compute_sudo=True
    )

    sub_vendor_id = fields.Many2one(comodel_name="res.partner", string="Order For", required=False, )
    order_tag_ids = fields.Many2many(comodel_name="custom.order.tag", string="Order Tag", )
    ref_po_template_id = fields.Many2one('purchase.order.template', string='Ref Purchase template')
    auto_purchase_order_id = fields.Many2one(
        comodel_name="purchase.order",
        string="Source Purchase Order",
        readonly=True,
        copy=False,
    )