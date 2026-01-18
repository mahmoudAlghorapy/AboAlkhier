from odoo import fields, models, api
from odoo.tools import SQL


class AccountInvoiceReport(models.Model):
    _inherit = 'account.invoice.report'

    brand_id = fields.Many2one('product.brand', string='Product Brand', readonly=True)
    standard_price = fields.Float(string='Product Cost', readonly=True)

    def _select(self) -> SQL:
        return SQL(
            "%s, template.brand_id as brand_id, "
            "COALESCE(product.standard_price -> line.company_id::text, to_jsonb(0.0))::float as standard_price",
            super()._select()
        )
