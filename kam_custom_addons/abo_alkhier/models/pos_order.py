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

    l10n_eg_long_id = fields.Char(string='ETA Long ID', compute='_compute_eta_long_id')
    l10n_eg_qr_code = fields.Char(string='ETA QR Code', compute='_compute_eta_qr_code_str')
    l10n_eg_submission_number = fields.Char(string='Submission ID', compute='_compute_eta_response_data', store=True,
                                            copy=False)
    l10n_eg_uuid = fields.Char(string='Document UUID', compute='_compute_eta_response_data', store=True, copy=False)
    l10n_eg_eta_json_doc_file = fields.Binary(
        string='ETA JSON Document',
        attachment=True,
        copy=False,
    )
    l10n_eg_signing_time = fields.Datetime('Signing Time', copy=False)
    l10n_eg_is_signed = fields.Boolean(copy=False, default=False)
    l10n_eg_eta_internal_id = fields.Char(string='ETA Internal ID', copy=False, readonly=True)
    l10n_eg_eta_hash_key = fields.Char(string='ETA Hash Key', copy=False, readonly=True)

    @api.depends('l10n_eg_eta_json_doc_file')
    def _compute_eta_long_id(self):
        for rec in self:
            if rec.l10n_eg_eta_json_doc_file:
                try:
                    response_data = json.loads(base64.b64decode(rec.l10n_eg_eta_json_doc_file)).get('response')
                    if response_data:
                        rec.l10n_eg_long_id = response_data.get('l10n_eg_long_id')
                    else:
                        rec.l10n_eg_long_id = False
                except (json.JSONDecodeError, TypeError):
                    rec.l10n_eg_long_id = False
            else:
                rec.l10n_eg_long_id = False

    @api.depends('date_order', 'l10n_eg_uuid', 'l10n_eg_long_id')
    def _compute_eta_qr_code_str(self):
        for order in self:
            if order.date_order and order.l10n_eg_uuid and order.l10n_eg_long_id:
                is_prod = order.company_id.l10n_eg_production_env
                # Get the ETA QR domain from the edi format
                base_url = self.env['account.edi.format']._l10n_eg_get_eta_qr_domain(production_environment=is_prod)
                qr_code_str = f'{base_url}/documents/{order.l10n_eg_uuid}/share/{order.l10n_eg_long_id}'
                order.l10n_eg_qr_code = qr_code_str
            else:
                order.l10n_eg_qr_code = ''

    @api.depends('l10n_eg_eta_json_doc_file')
    def _compute_eta_response_data(self):
        for rec in self:
            if rec.l10n_eg_eta_json_doc_file:
                try:
                    response_data = json.loads(base64.b64decode(rec.l10n_eg_eta_json_doc_file)).get('response')
                    if response_data:
                        rec.l10n_eg_uuid = response_data.get('l10n_eg_uuid')
                        rec.l10n_eg_submission_number = response_data.get('l10n_eg_submission_number')
                        rec.l10n_eg_eta_internal_id = response_data.get('l10n_eg_internal_id')
                        rec.l10n_eg_eta_hash_key = response_data.get('l10n_eg_hash_key')
                    else:
                        rec.l10n_eg_uuid = False
                        rec.l10n_eg_submission_number = False
                        rec.l10n_eg_eta_internal_id = False
                        rec.l10n_eg_eta_hash_key = False
                except (json.JSONDecodeError, TypeError):
                    rec.l10n_eg_uuid = False
                    rec.l10n_eg_submission_number = False
                    rec.l10n_eg_eta_internal_id = False
                    rec.l10n_eg_eta_hash_key = False
            else:
                rec.l10n_eg_uuid = False
                rec.l10n_eg_submission_number = False
                rec.l10n_eg_eta_internal_id = False
                rec.l10n_eg_eta_hash_key = False

    def action_post_sign_pos_orders(self):
        """Sign POS orders with ETA (similar to invoices)"""
        # Only sign orders that are paid/done and not yet sent to ETA
        orders = self.filtered(lambda r:
                               r.company_id.country_code == 'EG' and
                               r.state in ['paid', 'done'] and
                               not r.l10n_eg_submission_number
                               )

        if not orders:
            raise UserError(
                _('No valid POS orders found to sign. Please select paid orders from Egyptian companies that are not already signed.'))

        company_ids = orders.mapped('company_id')
        if len(company_ids) > 1:
            raise UserError(_('Please only sign POS orders from one company at a time'))

        company_id = company_ids[0]

        # Check if company has ETA settings configured
        if not company_id.l10n_eg_client_identifier or not company_id.l10n_eg_client_secret:
            raise ValidationError(_('Please configure ETA API credentials in company settings for %s', company_id.name))

        orders.write({'l10n_eg_signing_time': datetime.utcnow()})

        # Prepare and sign each order
        signed_orders = []
        for order in orders:
            try:
                # Prepare ETA receipt data
                eta_receipt = self._l10n_eg_prepare_eta_receipt(order)

                # Create JSON attachment (similar to invoices)
                self.env['ir.attachment'].create({
                    'name': _('ETA_RECEIPT_DOC_%s', order.name),
                    'res_id': order.id,
                    'res_model': order._name,
                    'res_field': 'l10n_eg_eta_json_doc_file',
                    'type': 'binary',
                    'raw': json.dumps(dict(request=eta_receipt)),
                    'mimetype': 'application/json',
                    'description': _('Egyptian Tax authority JSON receipt generated for %s.', order.name),
                })

                order.invalidate_recordset(fnames=['l10n_eg_eta_json_doc_file'])
                signed_orders.append(order)

            except Exception as e:
                _logger.error(f'Error preparing ETA receipt for POS order {order.name}: {str(e)}')
                continue

        if not signed_orders:
            raise UserError(_('Failed to prepare any POS orders for ETA signing'))

        # Send to ETA web service
        success_count = 0
        for order in signed_orders:
            try:
                result = self._l10n_eg_send_to_eta(order)
                if result.get('success'):
                    success_count += 1
                    order.write({
                        'l10n_eg_is_signed': True,
                        'l10n_eg_uuid': result.get('l10n_eg_uuid', ''),
                        'l10n_eg_long_id': result.get('l10n_eg_long_id', ''),
                        'l10n_eg_submission_number': result.get('l10n_eg_submission_number', ''),
                        'l10n_eg_eta_internal_id': result.get('l10n_eg_internal_id', ''),
                        'l10n_eg_eta_hash_key': result.get('l10n_eg_hash_key', ''),
                    })
            except Exception as e:
                _logger.error(f'Error sending POS order {order.name} to ETA: {str(e)}')

        if success_count > 0:
            message = _('Successfully signed %s POS order(s) with ETA') % success_count
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('ETA Signing Complete'),
                    'message': message,
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
        else:
            raise UserError(_('Failed to sign any POS orders with ETA. Please check the logs.'))

    def _l10n_eg_prepare_eta_receipt(self, order):
        """Prepare ETA receipt data structure (similar to invoice)"""
        company = order.company_id
        partner = order.partner_id or self.env['res.partner']

        # Get activity code from company settings
        activity_code = company.l10n_eg_activity_code or '8121'  # Default retail code

        # Prepare issuer (company)
        issuer = {
            'address': {
                'country': 'EG',
                'governate': company.state_id.name or 'Cairo',
                'regionCity': company.city or 'Iswan',
                'street': company.street or '12th dec. street',
                'buildingNumber': company.street2 or '10',
                'postalCode': company.zip or '',
                'branchID': '0',
            },
            'name': company.name or 'branch partner',
            'type': 'B',
            'id': company.vat or '456789123',
        }

        # Prepare receiver (customer)
        receiver = {
            'address': {
                'country': partner.country_id.code if partner.country_id else 'EG',
                'governate': partner.state_id.name if partner.state_id else 'Cairo',
                'regionCity': partner.city or 'Iswan',
                'street': partner.street or '12th dec. street',
                'buildingNumber': partner.street2 or '12',
                'postalCode': partner.zip or '',
            },
            'name': partner.name or _('Customer'),
            'type': 'P' if partner.company_type == 'person' else 'B',
            'id': partner.vat or '',
        }

        # Prepare receipt lines
        receipt_lines = []
        for line in order.lines:
            product = line.product_id

            # Calculate taxes
            tax_details = self._l10n_eg_calculate_line_taxes(line)

            # Prepare unit value
            unit_value = {
                'currencySold': 'EGP',
                'amountEGP': line.price_unit,
            }

            # Add exchange rate if different currency
            if order.currency_id and order.currency_id != company.currency_id:
                exchange_rate = self._l10n_eg_get_exchange_rate(order)
                unit_value.update({
                    'currencySold': order.currency_id.name,
                    'currencyExchangeRate': exchange_rate,
                    'amountSold': line.price_unit,
                })
                # Convert to EGP
                unit_value['amountEGP'] = line.price_unit * exchange_rate

            receipt_line = {
                'description': product.name or _('Product'),
                'itemType': product.l10n_eg_item_type or 'EGS',
                'itemCode': product.l10n_eg_item_code or 'EG-EGS-TEST',
                'unitType': product.uom_id.l10n_eg_unit_type or 'C62',
                'quantity': line.qty,
                'internalCode': product.default_code or '',
                'valueDifference': 0.0,
                'totalTaxableFees': 0.0,
                'itemsDiscount': 0.0,
                'unitValue': unit_value,
                'discount': {
                    'rate': (line.discount / (
                                line.price_unit * line.qty) * 100) if line.price_unit and line.qty else 0.0,
                    'amount': line.discount,
                },
                'taxableItems': tax_details['taxable_items'],
                'salesTotal': line.price_unit * line.qty,
                'netTotal': line.price_subtotal,
                'total': line.price_subtotal_incl,
            }
            receipt_lines.append(receipt_line)

        # Calculate tax totals
        tax_totals = []
        tax_amounts = {}
        for line in order.lines:
            tax_details = self._l10n_eg_calculate_line_taxes(line)
            for tax in tax_details['taxable_items']:
                tax_type = tax['taxType']
                if tax_type in tax_amounts:
                    tax_amounts[tax_type] += tax['amount']
                else:
                    tax_amounts[tax_type] = tax['amount']

        for tax_type, amount in tax_amounts.items():
            tax_totals.append({
                'taxType': tax_type,
                'amount': amount,
            })

        # Calculate totals
        total_discount = sum(order.lines.mapped('discount'))
        total_sales = sum(line.price_unit * line.qty for line in order.lines)
        net_amount = order.amount_total - sum(tax_amounts.values())

        # Prepare receipt data
        receipt_data = {
            'issuer': issuer,
            'documentType': 'i',  # 'i' for invoice/receipt
            'documentTypeVersion': '1.0',
            'dateTimeIssued': order.date_order.strftime(
                '%Y-%m-%dT%H:%M:%SZ') if order.date_order else fields.Datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
            'taxpayerActivityCode': activity_code,
            'internalID': order.name,
            'receiver': receiver,
            'invoiceLines': receipt_lines,
            'taxTotals': tax_totals,
            'totalDiscountAmount': total_discount,
            'extraDiscountAmount': 0.0,
            'totalItemsDiscountAmount': 0.0,
            'totalSalesAmount': total_sales,
            'netAmount': net_amount,
            'totalAmount': order.amount_total,
            'signatures': [],
        }

        # If it's a refund/return order
        if order.amount_total < 0:
            receipt_data['documentType'] = 'c'  # Credit note
            receipt_data['internalID'] = 'R' + order.name

        return receipt_data

    def _l10n_eg_calculate_line_taxes(self, line):
        """Calculate taxes for a POS order line"""
        taxable_items = []

        if line.tax_ids:
            for tax in line.tax_ids.filtered(lambda t: t.amount != 0):
                tax_type_info = self._l10n_eg_get_tax_type_info(tax)

                # Calculate tax amount
                if tax.amount_type == 'percent':
                    tax_amount = line.price_subtotal * tax.amount / 100
                elif tax.amount_type == 'fixed':
                    tax_amount = tax.amount * line.qty
                else:
                    tax_amount = 0

                taxable_items.append({
                    'taxType': tax_type_info['type'],
                    'amount': tax_amount,
                    'subType': tax_type_info['subtype'],
                    'rate': tax.amount,
                })
        else:
            # No tax
            taxable_items.append({
                'taxType': 'T1',
                'amount': 0.0,
                'subType': 'V009',
                'rate': 0.0,
            })

        return {
            'taxable_items': taxable_items
        }

    def _l10n_eg_get_tax_type_info(self, tax):
        """Map Odoo tax to ETA tax type"""
        tax_info = {
            'type': 'T1',
            'subtype': 'V009',
            'rate': 14.0,
        }

        # Check if tax has ETA code
        if hasattr(tax, 'l10n_eg_eta_code') and tax.l10n_eg_eta_code:
            code = tax.l10n_eg_eta_code.lower()
            if code.startswith('t1'):
                tax_info['type'] = 'T1'
                tax_info['subtype'] = code.split('_')[1].upper() if '_' in code else 'V009'
            elif code.startswith('t2'):
                tax_info['type'] = 'T2'
                tax_info['subtype'] = code.split('_')[1].upper() if '_' in code else ''
            elif code.startswith('t3'):
                tax_info['type'] = 'T3'
                tax_info['subtype'] = code.split('_')[1].upper() if '_' in code else ''
            elif code.startswith('t4'):
                tax_info['type'] = 'T4'
                tax_info['subtype'] = code.split('_')[1].upper() if '_' in code else ''

        tax_info['rate'] = tax.amount
        return tax_info

    def _l10n_eg_get_exchange_rate(self, order):
        """Get exchange rate for foreign currency"""
        company_currency = order.company_id.currency_id
        order_currency = order.currency_id

        if order_currency and order_currency != company_currency:
            # Get rate from currency rates
            rate_date = order.date_order or fields.Date.today()
            exchange_rate = self.env['res.currency']._get_conversion_rate(
                order_currency, company_currency, order.company_id, rate_date
            )
            return exchange_rate

        return 1.0

    def _l10n_eg_send_to_eta(self, order):
        """Send receipt to ETA web service (mock implementation)"""
        # In real implementation, you would:
        # 1. Get access token from ETA
        # 2. Prepare request with headers
        # 3. Send POST request to ETA API
        # 4. Handle response

        # Mock implementation
        try:
            # Simulate API call
            _logger.info(f'Sending POS order {order.name} to ETA')

            # For now, return mock response
            return {
                'success': True,
                'l10n_eg_uuid': f'POS-{order.name}-{fields.Datetime.now().strftime("%Y%m%d%H%M%S")}',
                'l10n_eg_long_id': f'LONG-POS-{order.id}',
                'l10n_eg_internal_id': order.name,
                'l10n_eg_hash_key': 'MOCK_HASH_KEY',
                'l10n_eg_submission_number': f'POS-{order.id}-{fields.Datetime.now().strftime("%Y%m%d")}',
            }
        except Exception as e:
            _logger.error(f'Error sending to ETA: {str(e)}')
            return {'success': False, 'error': str(e)}

    def action_get_eta_receipt_pdf(self):
        """Get PDF receipt from ETA"""
        self.ensure_one()
        if not self.l10n_eg_uuid:
            raise UserError(_('This POS order is not signed with ETA'))

        # This would call the actual ETA API to get PDF
        # For now, return mock
        pdf_data = b'%PDF-1.4\n%Mock PDF for ETA receipt\n'  # Mock PDF

        self.message_post(
            body=_('ETA receipt PDF has been downloaded'),
            attachments=[('ETA Receipt - %s.pdf' % self.name, pdf_data)]
        )

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/ir.attachment/{self.id}/datas?download=true',
            'target': 'self',
        }

    def action_sign_eta_invoices(self):
        """
        Create invoices from POS orders and send them to ETA
        """
        # 1) Validate orders
        orders = self.filtered(lambda o: o.state in ('paid', 'done'))
        if not orders:
            raise UserError(_('Please select paid POS orders only.'))

        orders = orders.filtered(lambda o: o.company_id.country_code == 'EG')
        if not orders:
            raise UserError(_('Selected orders are not for Egyptian companies.'))

        invoices = self.env['account.move']

        for order in orders:
            if order.account_move:
                invoices |= order.account_move
            else:
                # استخدم _generate_pos_order_invoice بدلاً من action_pos_order_invoice
                invoice = order._generate_pos_order_invoice()
                invoices |= invoice

        invoices.filtered(lambda m: m.state == 'draft').action_post()

        invoices.action_post_sign_invoices()

        message = _('Successfully created and signed %s invoice(s) with ETA') % len(invoices)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('ETA Signing Complete'),
                'message': message,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

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

    def action_transfer_orders_to_destination(self):
        orders = (self or self.env['pos.order'].browse(
            self.env.context.get("active_ids", [])
        )).filtered(lambda o: not o.is_transferred)
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
                    line_vals = {
                        'order_id': new_order.id,
                        'name': line.name,
                        'full_product_name': line.full_product_name,
                        'qty': line.qty,
                        'price_unit': line.price_unit,
                        'price_subtotal': line.price_subtotal,
                        'price_subtotal_incl': line.price_subtotal_incl,
                        'discount': line.discount,
                        'margin': getattr(line, 'margin', 0.0),
                        'margin_percent': getattr(line, 'margin_percent', 0.0),
                        'product_id': line.product_id.id,
                        'price_extra': line.price_extra,
                        'tax_ids': [(6, 0, line.tax_ids.ids)],
                        'tax_ids_after_fiscal_position': [(6, 0,
                                                           line.tax_ids_after_fiscal_position.ids)] if line.tax_ids_after_fiscal_position else False,
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
                    self.env['pos.order.line'].with_company(dest.id).sudo().create(line_vals)

                # Copy payments
                for payment in order.payment_ids:

                    mapped_method = self._map_payment_method(
                        payment.payment_method_id,
                        dest_pos_config
                    )
                    print('mapped_method',mapped_method)

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
