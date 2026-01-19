
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    sub_vendor_id = fields.Many2one(comodel_name="res.partner", string="Order For", required=False, )
    order_tag_ids = fields.Many2many(comodel_name="custom.order.tag", string="Order Tag", )