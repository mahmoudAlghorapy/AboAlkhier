from odoo import models, fields, api


class PosOrder(models.Model):
    _inherit = 'pos.order'

    ereceipt_ids = fields.One2many('egypt.ereceipt', 'pos_order_id', string='e-Receipts')
    ereceipt_status = fields.Selection([
        ('none', 'Not Submitted'),
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('error', 'Error')
    ], string='e-Receipt Status', compute='_compute_ereceipt_status', store=True)
    receipt_link = fields.Char(compute='_compute_receipt_link', store=True)

    @api.depends('ereceipt_ids', 'ereceipt_ids.state')
    def _compute_receipt_link(self):
        for rec in self:
            rec.receipt_link = ''
            if rec.ereceipt_ids:
                date_string = rec.date_order.strftime('%Y-%m-%dT%H:%M:%SZ')
                ereceipt_id = rec.ereceipt_ids.filtered(lambda r: r.state == 'accepted')
                if ereceipt_id and ereceipt_id[0].uuid:
                    uuid = ereceipt_id[0].uuid
                    url = 'https://invoicing.eta.gov.eg/receipts/search/%s/share/%s'
                    rec.receipt_link = url % (uuid, date_string)

    @api.depends('ereceipt_ids.state')
    def _compute_ereceipt_status(self):
        for order in self:
            if not order.ereceipt_ids:
                order.ereceipt_status = 'none'
            else:
                latest_receipt = order.ereceipt_ids[0]  # Most recent
                if latest_receipt.state == 'accepted':
                    order.ereceipt_status = 'accepted'
                elif latest_receipt.state == 'submitted':
                    order.ereceipt_status = 'submitted'
                elif latest_receipt.state == 'rejected':
                    order.ereceipt_status = 'rejected'
                elif latest_receipt.state == 'draft':
                    order.ereceipt_status = 'draft'
                else:
                    order.ereceipt_status = 'error'

    # def action_pos_order_paid(self):
    #     """Override to submit e-receipt when order is paid"""
    #     result = super().action_pos_order_paid()
    #
    #     # Check if e-receipt is enabled for this company
    #     # if self.config_id.pos_serial and not self.to_invoice and self.company_id.egypt_ereceipt_enabled:
    #     if self.config_id.pos_serial and self.company_id.egypt_ereceipt_enabled:
    #         self._submit_ereceipt()
    #
    #     return result

    def _submit_ereceipt(self):
        """Submit e-receipt for this order"""
        for order in self:
            # Check if already submitted
            if order.ereceipt_ids:
                continue

            # Create e-receipt record
            ereceipt_data = {
                'pos_order_id': order.id,
                'company_id': order.company_id.id,
            }

            ereceipt = self.env['egypt.ereceipt'].create(ereceipt_data)

            # Submit to API (async to avoid blocking POS)
            try:
                ereceipt.with_delay()._submit_to_api()
            except:
                # Fallback to immediate submission
                ereceipt._submit_to_api()

    def action_submit_ereceipt(self):
        """Manual e-receipt submission action"""
        for order in self:
            if not order.ereceipt_ids:
                order._submit_ereceipt()
            else:
                order.ereceipt_ids[0].action_submit_receipt()
