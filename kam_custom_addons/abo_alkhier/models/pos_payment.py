from odoo import fields, models, _, api
from odoo.exceptions import UserError, ValidationError, AccessError, RedirectWarning


class PosPayment(models.AbstractModel):
    """The inherited class HrEmployee to add new fields to 'hr.employee' """
    _inherit = "pos.payment"

    @api.constrains('amount')
    def _check_amount(self):
        for payment in self:
            if payment.pos_order_id.state == 'done' or payment.pos_order_id.account_move:
                pass


    def action_transfer_payments(self):
        active_ids = self.env.context.get('active_ids', [])
        payments = self.env['pos.payment'].browse(active_ids)

        if not self.company_id.destination_company_id:
            raise UserError(_("Please enter the destination company."))

        dest_company = self.company_id.destination_company_id
        print('dest_company',dest_company.name)

        for payment in payments:
            values = {
                'company_id': dest_company.id,
                'session_id': payment.session_id.id,
                'pos_order_id': payment.pos_order_id.id,
                'payment_method_id': payment.payment_method_id.id,
                'name': payment.name ,
                'amount': payment.amount,
                'payment_date': payment.payment_date,

            }

            create = self.sudo().env['pos.payment'].create(values)
            create.company_id = dest_company.id
            # print('create.company_id',create.company_id)

        return {'type': 'ir.actions.act_window_close'}
