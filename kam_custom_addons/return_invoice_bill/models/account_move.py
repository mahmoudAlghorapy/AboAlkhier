from odoo import api, fields, models, _

class AccountMove(models.Model):
    _inherit = 'account.move'

    picking_id = fields.Many2one(
        'stock.picking',
        string='Transfer',
        index=True
    )
