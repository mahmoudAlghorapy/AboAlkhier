# -*- coding: utf-8 -*-
from odoo import models, fields


class POSConfigEnterprise(models.Model):
    _inherit = 'pos.config'

    x_external_reference = fields.Char(
        string="External Reference",
        help="Integration reference coming from Community POS Config",
        index=True,
    )


class POSSessionEnterprise(models.Model):
    _inherit = 'pos.session'

    x_external_reference = fields.Char(
        string="External Reference",
        help="Integration reference coming from Community POS Session",
        index=True,
    )


class POSOrderEnterprise(models.Model):
    _inherit = 'pos.order'

    x_external_reference = fields.Char(
        string="External Reference",
        help="Integration reference coming from Community POS Order",
        index=True,
    )


class POSPaymentEnterprise(models.Model):
    _inherit = 'pos.payment'

    x_external_reference = fields.Char(
        string="External Reference",
        help="Integration reference coming from Community POS Payment",
        index=True,
    )
class StockPickingInherit(models.Model):
    _inherit = 'stock.picking'

    x_external_reference = fields.Char(
        string="External Reference",
        help="Integration reference coming from Community POS Payment",
        index=True,
    )

    class PurchaseOrderInherit(models.Model):
        _inherit = 'purchase.order'

        x_external_reference = fields.Char(
            string="External Reference",
            help="Integration reference coming from Community POS Payment",
            index=True,
        )