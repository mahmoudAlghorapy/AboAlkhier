# -*- coding: utf-8 -*-
##############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2024-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
from odoo import api, fields, models, _


class StockPicking(models.Model):
    """This class extends the 'stock.picking' model to add a method for
    retrieving credit notes and debit notes related
    to the picking, and generating actions for viewing them."""
    _inherit = 'stock.picking'

    picking_type_name = fields.Char(string='Picking Type Name',
                                    help='Name of picking type')
    return_invoice_count = fields.Char(string="Counts",
                                       compute='_compute_return_invoice_count',
                                       help="counts of return invoices")
    is_paid = fields.Boolean(string='Is Paid',
                             help='Value will be True when order has paid '
                                  'otherwise False.')
    credit_note_count = fields.Integer(
        compute='_compute_credit_note_count',
        string='Credit Notes'
    )

    def action_view_credit_notes(self):
        self.ensure_one()
        company = self.company_id
        currency = company.currency_id
        invoice_line_vals = []

        for move_line in self.move_ids:
            product = move_line.product_id
            if not product:
                continue

            account = (
                    product.property_account_expense_id
                    or product.categ_id.property_account_expense_categ_id
            )

            if not account:
                account = self.env['account.account'].search([
                    ('company_id', '=', company.id),
                    ('internal_group', '=', 'expense'),
                    ('deprecated', '=', False),
                ], limit=1)

            invoice_line_vals.append((0, 0, {
                'product_id': product.id,
                'name': product.display_name,
                'quantity': move_line.quantity or move_line.product_uom_qty,
                'product_uom_id': product.uom_id.id,
                'price_unit': product.standard_price,
                'account_id': account.id,
            }))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Vendor Credit Note'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [
                ('move_type', '=', 'in_refund'),
                ('picking_id', '=', self.id),
            ],
            'context': {
                'default_move_type': 'in_refund',
                'default_picking_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_company_id': company.id,
                'default_currency_id': currency.id,
                'default_invoice_line_ids': invoice_line_vals,
            },
        }

    def _compute_credit_note_count(self):
        for picking in self:
            picking.credit_note_count = self.env['account.move'].search_count([
                ('move_type', '=', 'in_refund'),
                ('picking_id', '=', picking.id),
                ('state', '!=', 'cancel'),
            ])


    @api.model_create_multi
    def create(self, vals_list):
        """Discard changes in company_id field if company_ids has been given."""
        for vals in vals_list:
            if 'picking_type_id' in vals:
                picking_type = self.env['stock.picking.type'].browse(vals['picking_type_id'])
                if picking_type.exists():
                    vals['picking_type_name'] = picking_type.sequence_code
            # If picking_type_id is not in vals but we need to compute it from default
            elif 'picking_type_name' not in vals:
                # You can also compute from default picking_type_id if needed
                # This is optional depending on your requirements
                pass
            # print('1111111111111111111111',vals['picking_type_name'])

        return super().create(vals_list)

    # @api.model_create_multi
    # def create(self, vals):
    #     """This method overrides the default create method to set the
    #     'picking_type_name' field based on the 'picking_type_id' field
    #     before creating the record."""
    #
    #     self.picking_type_name = self.picking_type_id.sequence_code
    #     return super(StockPicking, self).create(vals)

    def action_get_credit_note(self):
        """Generates an action to view reversal credit notes
         based on the context."""
        self.ensure_one()
        credit_notes = self.sale_id.invoice_ids.filtered(
            lambda x: x.move_type == 'out_refund')
        return {
            'type': 'ir.actions.act_window',
            'name': _(
                'Reversal of Credit Note: %s') % self.sale_id.invoice_ids.filtered(
                lambda x: x.move_type == 'out_invoice').name,
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', credit_notes.ids)],
        }

    def action_get_debit_note(self):
        """Generates an action to view reversal  debit notes
                based on the context."""
        debit_notes = self.purchase_id.invoice_ids.filtered(
            lambda x: x.move_type == 'in_refund')
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _(
                'Reversal of Debit Note: %s') % self.purchase_id.invoice_ids.filtered(
                lambda x: x.move_type == 'in_invoice').name,
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', debit_notes.ids)]
        }

    @api.depends('return_invoice_count')
    def _compute_return_invoice_count(self):
        for record in self:
            record.return_invoice_count = record.return_count
