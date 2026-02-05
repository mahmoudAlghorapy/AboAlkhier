from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.misc import format_datetime
import logging
import re
from odoo.exceptions import ValidationError, UserError
import base64
import json
from datetime import datetime

_logger = logging.getLogger(__name__)

ETA_TEST_RESPONSE = {
    'l10n_eg_uuid': 'UUIDXIL9182712KMHJQ',
    'l10n_eg_long_id': 'LIDMN12132LASKXXA',
    'l10n_eg_internal_id': 'INTLA1212MMKA12',
    'l10n_eg_hash_key': 'BaK12lX1kASdma12',
    'l10n_eg_submission_number': '12125523452353',
}


class PosOrder(models.Model):
    _inherit = "pos.order"
    sale_order_id = fields.Many2one(comodel_name="sale.order", string="", required=False)
    is_transferred = fields.Boolean(
        string="Transferred to Destination Company",
        default=False,
        copy=False,
        index=True,
    )
    sale_notes = fields.Text("Sale Notes")

    def _get_destination_or_raise(self, order):
        if not order.company_id:
            raise UserError(_("Order %s has no company set.") % (order.name or order.id))
        dest = order.company_id.destination_company_id
        if not dest:
            raise UserError(_("No destination company configured for company '%s' on order %s.") %
                            (order.company_id.name, order.name or order.id))
        return dest

    def _get_highest_sequence_numbers(self, dest_company):
        """Get the highest sequence numbers currently in the destination company"""
        try:
            # DEBUG: Log what we're searching for
            _logger.info("Looking for highest sequences in company: %s (ID: %s)", dest_company.name, dest_company.id)

            # Find the highest Order Ref in destination company
            # Use SQL for more reliable search
            self.env.cr.execute("""
                SELECT name 
                FROM pos_order 
                WHERE company_id = %s 
                AND name LIKE 'Order - %%'
                ORDER BY 
                    CAST(SUBSTRING(name FROM 'Order - (\d+)') AS INTEGER) DESC,
                    id DESC
                LIMIT 1
            """, (dest_company.id,))

            result = self.env.cr.fetchone()
            max_order_number = 0
            if result and result[0]:
                try:
                    match = re.search(r'Order - (\d{1,})$', result[0])
                    if match:
                        max_order_number = int(match.group(1))
                        _logger.info("Found highest order number: %s", max_order_number)
                except Exception as e:
                    _logger.error("Error parsing order number: %s", str(e))

            # Find the highest Receipt Number in destination company
            self.env.cr.execute("""
                SELECT pos_reference 
                FROM pos_order 
                WHERE company_id = %s 
                AND pos_reference LIKE 'RCPT-%%'
                ORDER BY 
                    CAST(SUBSTRING(pos_reference FROM 'RCPT-(\d+)') AS INTEGER) DESC,
                    id DESC
                LIMIT 1
            """, (dest_company.id,))

            result = self.env.cr.fetchone()
            max_receipt_number = 0
            if result and result[0]:
                try:
                    match = re.search(r'RCPT-(\d{1,})$', result[0])
                    if match:
                        max_receipt_number = int(match.group(1))
                        _logger.info("Found highest receipt number: %s", max_receipt_number)
                except Exception as e:
                    _logger.error("Error parsing receipt number: %s", str(e))

            # Fallback to Odoo search if SQL doesn't work
            if max_order_number == 0:
                highest_order = self.env['pos.order'].search([
                    ('company_id', '=', dest_company.id),
                    ('name', 'like', 'Order - %'),
                ], order='id desc', limit=1)

                if highest_order:
                    try:
                        match = re.search(r'Order - (\d{1,})$', highest_order.name)
                        if match:
                            max_order_number = int(match.group(1))
                    except:
                        pass

            if max_receipt_number == 0:
                highest_receipt = self.env['pos.order'].search([
                    ('company_id', '=', dest_company.id),
                    ('pos_reference', 'like', 'RCPT-%'),
                ], order='id desc', limit=1)

                if highest_receipt:
                    try:
                        match = re.search(r'RCPT-(\d{1,})$', highest_receipt.pos_reference)
                        if match:
                            max_receipt_number = int(match.group(1))
                    except:
                        pass

            _logger.info("Final highest numbers - Order: %s, Receipt: %s", max_order_number, max_receipt_number)
            return max_order_number, max_receipt_number

        except Exception as e:
            _logger.error("Error getting highest sequence numbers: %s", str(e))
            return 0, 0

    def _map_payment_method(self, source_payment_method, dest_pos_config):
        """
        Find a payment method in destination POS config
        with the same name as the source one.
        """
        if not source_payment_method or not dest_pos_config:
            return False

        # Allowed methods in destination config
        allowed_methods = dest_pos_config.payment_method_ids

        # Match by name (case-insensitive)
        mapped_method = allowed_methods.filtered(
            lambda m: m.name.strip().lower() == source_payment_method.name.strip().lower()
        )

        return mapped_method[:1] if mapped_method else False

    def _next_pos_order_name(self, company):
        Sequence = self.env['ir.sequence'].sudo()

        sequence = Sequence.search([
            ('code', '=', 'pos.order.manual'),
            ('company_id', '=', company.id),
        ], limit=1)

        if not sequence:
            sequence = Sequence.create({
                'name': f'POS Order Manual - {company.name}',
                'code': 'pos.order.manual',
                'prefix': 'ORDER - ',
                'padding': 6,
                'company_id': company.id,
                'implementation': 'no_gap',
            })

        return sequence.next_by_id()

    def _map_taxes_to_destination_company(self, source_taxes, dest_company):
        """
        Map taxes from source company to destination company
        by name + amount + type
        """
        mapped_tax_ids = []

        for tax in source_taxes:

            dest_tax = self.env['account.tax'].sudo().search([
                ('company_id', '=', dest_company.id),
                ('amount', '=', tax.amount),
                ('amount_type', '=', tax.amount_type),
                ('type_tax_use', '=', tax.type_tax_use),
            ], limit=1)

            if dest_tax:
                mapped_tax_ids.append(dest_tax.id)
            else:
                _logger.warning(
                    "No matching tax found in destination company for tax '%s' (%.2f%%)",
                    tax.name, tax.amount
                )

        return mapped_tax_ids

    def action_transfer_orders_to_destination(self):
        orders = (self or self.env['pos.order'].browse(
            self.env.context.get("active_ids", [])
        )).filtered(lambda o: not o.is_transferred)
        for order in orders:
            for line in order.lines:
                taxes = line.tax_ids_after_fiscal_position or line.tax_ids
                tax_rate = sum(t.amount for t in taxes) / 100.0

                subtotal_incl = line.qty * line.price_unit
                subtotal = subtotal_incl / (1 + tax_rate) if tax_rate else subtotal_incl

                line.write({
                    'price_subtotal': subtotal,
                    'price_subtotal_incl': subtotal_incl,
                })

        if not orders:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Nothing to transfer"),
                    "message": _("All selected orders were already transferred."),
                    "sticky": False,
                },
            }

        # if not orders:
        #     return {'type': 'ir.actions.act_window_close'}

        transferred = 0
        skipped = 0
        errors = []

        # Get the POS payment users who should be notified
        pos_payment_group = self.env.ref('point_of_sale.group_pos_user', raise_if_not_found=False)
        users_to_notify = pos_payment_group.user_ids if pos_payment_group else self.env['res.users']

        # Sort orders by date to maintain chronological order
        sorted_orders = orders.sorted(key=lambda r: r.date_order)

        # Get the destination company (should be the same for all orders)
        dest = None
        for order in sorted_orders:
            try:
                dest = self._get_destination_or_raise(order)
                break  # Get destination from first valid order
            except UserError:
                continue

        if not dest:
            errors.append(_("No valid destination company found for any order"))
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Error"),
                    "message": _("No valid destination company found for any order"),
                    "sticky": False
                },
            }

        # DEBUG: Log destination company info
        _logger.info("Creating copies for company: %s (ID: %s)", dest.name, dest.id)

        # Get the highest existing numbers in the destination company
        max_order_num, max_receipt_num = self._get_highest_sequence_numbers(dest)

        # DEBUG: Log the found numbers
        _logger.info("Starting from - Order: %s, Receipt: %s", max_order_num, max_receipt_num)

        # Start counters from the next number after the highest existing
        current_order_number = max_order_num + 1
        current_receipt_number = max_receipt_num + 1

        # DEBUG: Log starting numbers
        _logger.info("Counters start at - Order: %s, Receipt: %s", current_order_number, current_receipt_number)

        # Get destination company's POS config
        dest_pos_config = self.env['pos.config'].sudo().search([
            ('company_id', '=', dest.id),
            ('active', '=', True)
        ], limit=1)
        print('dest.id', dest.id)
        print('dest_pos_config', dest_pos_config)
        print('55555555555', self.env['pos.config'].sudo().search([
            ('company_id', '=', dest.id),
        ], limit=1))

        if not dest_pos_config:
            errors.append(_("No active POS configuration found for destination company %s") % dest.name)
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Error"),
                    "message": _("No active POS configuration found for destination company %s") % dest.name,
                    "sticky": False
                },
            }

        # Process each order to create a copy
        for order in sorted_orders:
            try:
                # Verify destination is the same for all orders
                order_dest = self._get_destination_or_raise(order)
                if order_dest.id != dest.id:
                    errors.append(_("Order %s has different destination company") % (order.name or order.id))
                    skipped += 1
                    continue

                # Generate sequential numbers for the new copy
                # new_order_name = f"Order - {current_order_number:06d}"
                new_order_name = self._next_pos_order_name(dest)
                new_pos_reference = f"RCPT-{current_receipt_number:06d}"

                # DEBUG: Log generated numbers
                _logger.info("Creating copy of order %s as: Name=%s, Ref=%s",
                             order.name or order.id, new_order_name, new_pos_reference)

                # Prepare data for the new order
                order_vals = {
                    'name': new_order_name,
                    'pos_reference': new_pos_reference,
                    'company_id': dest.id,
                    'session_id': False,  # No session since it's a manual copy
                    'config_id': dest_pos_config.id,
                    'partner_id': order.partner_id.id,
                    'employee_id': order.employee_id.id,
                    'date_order': order.date_order,
                    'amount_tax': order.amount_tax,
                    'amount_total': order.amount_total,
                    'amount_paid': order.amount_paid,
                    'amount_return': order.amount_return,
                    'state': order.state,
                    'sale_order_id': order.sale_order_id.id if order.sale_order_id else False,
                    # 'note': order.note,
                    'pricelist_id': order.pricelist_id.id,
                    'currency_id': order.currency_id.id,
                    'currency_rate': order.currency_rate,
                    'user_id': self.env.user.id,  # User who created the copy
                    'sequence_number': 1,
                    'access_token': False,
                    'to_invoice': order.to_invoice,
                    'is_tipped': order.is_tipped,
                    'tip_amount': order.tip_amount,
                    'fiscal_position_id': order.fiscal_position_id.id if order.fiscal_position_id else False,
                    # 'invoice_group': order.invoice_group,
                }

                # Set team if available
                # if dest_pos_config.team_id:
                #     order_vals['team_id'] = dest_pos_config.team_id.id

                # Create the new order
                new_order = self.env['pos.order'].with_company(dest.id).sudo().create(order_vals)
                order.sudo().write({
                    'is_transferred': True,
                })

                # Copy order lines
                for line in order.lines:
                    source_taxes = (
                        line.tax_ids_after_fiscal_position
                        if line.tax_ids_after_fiscal_position
                        else line.tax_ids
                    )

                    mapped_taxes = self._map_taxes_to_destination_company(
                        source_taxes,
                        dest
                    )
                    tax_rate = 0.0
                    if mapped_taxes:
                        taxes = self.env['account.tax'].sudo().browse(mapped_taxes)
                        tax_rate = sum(t.amount for t in taxes) / 100.0

                    subtotal = (line.qty * line.price_unit) / (1 + tax_rate) if tax_rate else (
                                line.qty * line.price_unit)
                    subtotal_incl = line.qty * line.price_unit

                    line_vals = {
                        'order_id': new_order.id,
                        'name': line.name,
                        'full_product_name': line.full_product_name,
                        'qty': line.qty,
                        'price_unit': line.price_unit,
                        'price_subtotal': subtotal,
                        'price_subtotal_incl': subtotal_incl,
                        'discount': line.discount,
                        'margin': getattr(line, 'margin', 0.0),
                        'margin_percent': getattr(line, 'margin_percent', 0.0),
                        'product_id': line.product_id.id,
                        'price_extra': line.price_extra,
                        'tax_ids': [(6, 0, mapped_taxes)],
                        'tax_ids_after_fiscal_position': [(6, 0, mapped_taxes)],
                        'pack_lot_ids': False,  # Don't copy lot/serial numbers
                        'note': line.note,
                        'customer_note': line.customer_note,
                        'refunded_orderline_id': line.refunded_orderline_id.id if line.refunded_orderline_id else False,
                        'refunded_qty': line.refunded_qty,
                        'sale_order_line_id': line.sale_order_line_id.id if line.sale_order_line_id else False,
                        # 'mp_skip': line.mp_skip,
                        'reward_id': line.reward_id.id if line.reward_id else False,
                        'coupon_id': line.coupon_id.id if line.coupon_id else False,
                        'points_cost': line.points_cost,
                        'reward_identifier_code': line.reward_identifier_code,
                    }

                    # Set UOM
                    if line.product_uom_id:
                        line_vals['product_uom_id'] = line.product_uom_id.id

                    # Set price list
                    # if line.price_list_id:
                    #     line_vals['price_list_id'] = line.price_list_id.id

                    # Create the line
                    new_line = self.env['pos.order.line'].with_company(dest.id).sudo().create(line_vals)
                    # source_taxes = (
                    #     line.tax_ids_after_fiscal_position
                    #     if line.tax_ids_after_fiscal_position
                    #     else line.tax_ids
                    # )
                    #
                    # mapped_taxes = self._map_taxes_to_destination_company(
                    #     line.tax_ids_after_fiscal_position or line.tax_ids,
                    #     dest
                    # )

                    new_line.write({
                        'tax_ids': [(6, 0, mapped_taxes)],
                        'tax_ids_after_fiscal_position': [(6, 0, mapped_taxes)],
                    })

                # Copy payments
                for payment in order.payment_ids:

                    mapped_method = self._map_payment_method(
                        payment.payment_method_id,
                        dest_pos_config
                    )
                    print('mapped_method', mapped_method)

                    if not mapped_method:
                        _logger.warning(
                            "Skipping payment %.2f: no matching payment method '%s' in POS config '%s'",
                            payment.amount,
                            payment.payment_method_id.name,
                            dest_pos_config.name
                        )
                        continue  # Skip this payment safely

                    payment_vals = {
                        'pos_order_id': new_order.id,
                        'amount': payment.amount,
                        'payment_method_id': mapped_method.id,
                        'payment_date': payment.payment_date,
                        'company_id': dest.id,
                        'session_id': payment.session_id.id,
                    }
                    # Create the payment
                    self.env['pos.payment'].with_company(dest.id).sudo().create(payment_vals)

                # Increment counters for next order
                current_order_number += 1
                current_receipt_number += 1
                transferred += 1

                # Send notification about the copied order
                if users_to_notify:
                    self._send_copy_notification(
                        order, new_order, order.company_id, dest, users_to_notify
                    )

                # Link the original order to the copy for reference
                # You can add a field to track this if needed
                # order.message_post(
                #     body=_("A copy of this order was created in company %s as order %s") %
                #          (dest.name, new_order.name),
                #     subject=_("Order Copied")
                # )

                # Link the copy back to the original
                new_order.message_post(
                    body=_("This order is a copy of order %s from company %s") %
                         (order.name, order.company_id.name),
                    subject=_("Copied Order")
                )

            except UserError as e:
                errors.append(str(e))
                skipped += 1
                continue
            except Exception as e:
                errors.append(f"Order {order.name or order.id}: {str(e)}")
                _logger.error("Error creating copy of order %s: %s", order.name or order.id, str(e), exc_info=True)
                skipped += 1
                continue

        # Final notification to user who performed the copy
        msg = []
        if transferred:
            msg.append(_("%d order(s) copied to destination company.") % transferred)
        if skipped:
            msg.append(_("%d order(s) skipped.") % skipped)
        if errors:
            msg.append(_("Errors: %s") % ("; ".join(errors[:5])))  # Show first 5 errors

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Copy POS orders"),
                "message": " ".join(msg) or _("No orders copied."),
                "sticky": False,
                "next": {
                    "type": "ir.actions.act_window_close",
                }
            },
        }

    def _send_copy_notification(self, original_order, copied_order, source_company, dest_company, users_to_notify):
        """Send notification about the copied order"""

        message_plain = _("""
POS Order has been copied from %(source_company)s to %(dest_company)s.

Original Order: %(original_name)s
New Order: %(new_name)s

Original Order Details:
- Order Ref: %(original_name)s
- Receipt Number: %(original_reference)s
- Amount: %(original_amount)s
- Date: %(original_date)s
- Customer: %(original_customer)s

New Order Details:
- Order Ref: %(new_name)s
- Receipt Number: %(new_reference)s
- Amount: %(new_amount)s
- Date: %(new_date)s
- Customer: %(new_customer)s

Copied by: %(user)s
""") % {
            'source_company': source_company.name if source_company else _('Unknown'),
            'dest_company': dest_company.name,
            'original_name': original_order.name,
            'new_name': copied_order.name,
            'original_reference': original_order.pos_reference,
            'new_reference': copied_order.pos_reference,
            'original_amount': original_order.amount_total,
            'new_amount': copied_order.amount_total,
            'original_date': format_datetime(self.env, original_order.date_order),
            'new_date': format_datetime(self.env, copied_order.date_order),
            'original_customer': original_order.partner_id.name if original_order.partner_id else _('Walk-in Customer'),
            'new_customer': copied_order.partner_id.name if copied_order.partner_id else _('Walk-in Customer'),
            'user': self.env.user.name,
        }

        # Create internal notification (Inbox message)
        notification_partner_ids = []
        for user in users_to_notify:
            if user.partner_id:
                notification_partner_ids.append(user.partner_id.id)

        if notification_partner_ids:
            try:
                # Post message on both orders
                original_order.sudo().message_post(
                    body=_("This order was copied to company %s as order %s") % (dest_company.name, copied_order.name),
                    partner_ids=notification_partner_ids,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                )

                copied_order.sudo().message_post(
                    body=message_plain,
                    partner_ids=notification_partner_ids,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                )
            except Exception as e:
                _logger.error("Failed to post message for order copy: %s", str(e))

        # Send email notification
        self._send_copy_email_notification(
            original_order, copied_order, source_company, dest_company, users_to_notify
        )

    def _send_copy_email_notification(self, original_order, copied_order, source_company, dest_company,
                                      users_to_notify):
        """Send email notification about order copy"""
        try:
            # Prepare email content
            customer_name = original_order.partner_id.name if original_order.partner_id else _('Walk-in Customer')
            source_company_name = source_company.name if source_company else _('Unknown')

            # Create email body
            email_body = f"""Hello,

POS Order has been copied from {source_company_name} to {dest_company.name}.

Original Order Details:
- Order: {original_order.name}
- Receipt: {original_order.pos_reference}
- Amount: {original_order.amount_total} {original_order.currency_id.symbol or ''}
- Date: {format_datetime(self.env, original_order.date_order)}
- Customer: {customer_name}

New Order Details:
- Order: {copied_order.name}
- Receipt: {copied_order.pos_reference}
- Amount: {copied_order.amount_total} {copied_order.currency_id.symbol or ''}
- Date: {format_datetime(self.env, copied_order.date_order)}
- Customer: {customer_name}

Copied by: {self.env.user.name}

View original order: {original_order.get_base_url()}/web#id={original_order.id}&model=pos.order&view_type=form
View new order: {copied_order.get_base_url()}/web#id={copied_order.id}&model=pos.order&view_type=form

Best regards,
{dest_company.name}
"""

            # Send email to all POS payment users
            for user in users_to_notify:
                if user.email and user.active:
                    try:
                        mail_values = {
                            'subject': f'POS Order Copied: {original_order.name} → {copied_order.name}',
                            'body_html': f'<pre>{email_body}</pre>',
                            'email_to': user.email,
                            'email_from': self.env.user.email or self.env.company.email,
                            'model': 'pos.order',
                            'res_id': copied_order.id,
                        }

                        mail = self.env['mail.mail'].sudo().create(mail_values)
                        mail.send()

                    except Exception as e:
                        _logger.error("Failed to send email to %s for order copy: %s",
                                      user.email, str(e))

        except Exception as e:
            _logger.error("Failed in email notification process for order copy: %s", str(e))
