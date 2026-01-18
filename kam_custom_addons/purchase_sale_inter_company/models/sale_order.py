# Copyright 2013-Today Odoo SA
# Copyright 2016-2019 Chafique DELLI @ Akretion
# Copyright 2018-2019 Tecnativa - Carlos Dauden
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models, Command


class SaleOrder(models.Model):
    _inherit = "sale.order"

    auto_purchase_order_id = fields.Many2one(
        comodel_name="purchase.order",
        string="Source Purchase Order",
        readonly=True,
        copy=False,
    )

    def action_confirm(self):
        for order in self.filtered("auto_purchase_order_id"):
            for line in order.order_line.sudo():
                if line.auto_purchase_line_id:
                    line.auto_purchase_line_id.price_unit = line.price_unit
        return super().action_confirm()
class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _prepare_purchase_order(self, company_id, origins, values):
        res = super()._prepare_purchase_order(company_id, origins, values)

        first_values = values[0]
        sale_line_id = first_values.get('sale_line_id')
        print('sale_line_id',sale_line_id)

        if sale_line_id:
            # 🔑 لو int → حوّله recordset
            if isinstance(sale_line_id, int):
                sale_line = self.env['sale.order.line'].browse(sale_line_id)
            else:
                sale_line = sale_line_id

            if sale_line and sale_line.exists():
                order = sale_line.order_id
                print('order',order.name)

                res.update({
                    'sub_vendor_id': order.sub_vendor_id.id if order.sub_vendor_id else False,
                    'po_template_id': order.ref_po_template_id.id if order.ref_po_template_id else False,
                    'order_tag_ids': (
                        [Command.set(order.ref_po_template_id.order_tag_ids.ids)]
                        if order.ref_po_template_id
                        else False
                    ),
                })

        return res