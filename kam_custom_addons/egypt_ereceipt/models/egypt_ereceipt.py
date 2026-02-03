import json
import hashlib
import logging
import ssl
import requests
import urllib3

from datetime import datetime, timedelta
from odoo import models, fields, api
from odoo.tools import _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

apiBaseUrl = 'https://api.invoicing.eta.gov.eg'
idSrvBaseUrl = 'https://id.eta.gov.eg'


class CustomHttpAdapter(requests.adapters.HTTPAdapter):
    def __init__(self, ssl_context=None, **kwargs):
        self.ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        self.poolmanager = urllib3.poolmanager.PoolManager(
            num_pools=connections, maxsize=maxsize,
            block=block, ssl_context=self.ssl_context)


class EgyptEReceipt(models.Model):
    _name = 'egypt.ereceipt'
    _description = 'Egypt e-Receipt Record'
    _order = 'create_date desc'
    _rec_name = 'receipt_number'

    # Core fields
    pos_order_id = fields.Many2one('pos.order', string='POS Order', required=True, ondelete='cascade')
    pos_session_id = fields.Many2one('pos.session', related='pos_order_id.session_id', store=True, readonly=True)
    pos_config_id = fields.Many2one('pos.config', related='pos_session_id.config_id', store=True, readonly=True)
    pos_date_order = fields.Datetime(related='pos_order_id.date_order', string='Order Date', store=True, readonly=True)
    uuid = fields.Char(string='UUID')
    previous_uuid = fields.Char('Previous Receipt UUID', compute='_compute_previous_uuid', store=True)
    reference_uuid = fields.Char('Reference UUID', help="UUID of original receipt for returns")
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)

    # Status tracking
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('accepted', 'Accepted'),
        ('valid', 'Valid'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
        ('retry', 'Retry Pending')
    ], string='Status', default='draft', required=True, tracking=True)
    eta_status = fields.Selection([('invalid', 'Invalid'), ('valid', 'Valid'), ('undetected', 'Undetected')],
                                  copy=False, string='ETA Status')

    # API Response data
    submission_uuid = fields.Char(string='Submission UUID', copy=False, index=True)
    receipt_number = fields.Char(string='Receipt Number', copy=False)
    qr_code = fields.Text(string='QR Code Data', copy=False)
    long_id = fields.Text(string='Long ID', copy=False)

    # Timestamps
    request_date = fields.Datetime(string='Request Date', copy=False)
    accepted_date = fields.Datetime(string='Acceptance Date', copy=False)

    # Error handling
    error_message = fields.Text(string='Error Message', copy=False)
    retry_count = fields.Integer(string='Retry Count', default=0, copy=False)
    max_retries = fields.Integer(string='Max Retries', default=3)
    next_retry_date = fields.Datetime(string='Next Retry Date', copy=False)

    # JSON data storage
    receipt_data = fields.Text(string='Receipt Data JSON', copy=False)
    api_response = fields.Text(string='API Response JSON', copy=False)

    @api.depends('pos_order_id')
    def _compute_previous_uuid(self):
        for rec in self:
            rec.previous_uuid = ''

            if rec.pos_order_id:
                previous_receipt = self.search([
                    ('pos_config_id', '=', rec.pos_config_id.id),
                    ('uuid', '!=', False),
                    ('state', '=', 'accepted'),
                    ('id', '!=', rec.id)
                ], order='pos_date_order desc', limit=1)

                rec.previous_uuid = previous_receipt.uuid if previous_receipt else ''

    def action_submit_receipt(self):
        """Manual submission action"""
        for record in self:
            if record.eta_status in ['valid']:
                raise UserError(_('Receipt is already submitted or accepted.'))

            self.uuid = False
            record._submit_to_api()

    def action_retry_submission(self):
        """Manual retry action"""
        for record in self:
            if record.state != 'error':
                raise UserError(_('Only failed receipts can be retried.'))

            record.retry_count = 0
            record.uuid = False
            record.state = 'retry'
            record._submit_to_api()

    def _process_api_response(self, response):
        """Process API response from ETA eReceipt submission"""
        self.api_response = response.text

        if response.status_code in [200, 202]:
            try:
                response_data = response.json()

                self.submission_uuid = response_data.get('submissionId')
                self.request_date = self._parse_eta_request_time(response_data.get('header', {}).get('requestTime'))
                # Handle accepted documents
                accepted_docs = response_data.get('acceptedDocuments', [])
                if accepted_docs:
                    doc = accepted_docs[0]
                    self.uuid = doc.get('uuid')
                    self.receipt_number = doc.get('receiptNumber')
                    # self.qr_code = doc.get('qrCode')
                    self.long_id = doc.get('longId')
                    self.state = 'accepted'
                    self._get_eta_receipt_details()
                    self.accepted_date = fields.Datetime.now()
                    _logger.info(f"[ETA] Receipt accepted: {self.receipt_number} | UUID: {self.uuid}")

                # Handle rejected documents
                rejected_docs = response_data.get('rejectedDocuments', [])
                if rejected_docs:
                    doc = rejected_docs[0]
                    self.uuid = False
                    self.receipt_number = doc.get('receiptNumber')
                    self.long_id = doc.get('longId')
                    self._get_eta_receipt_details()
                    error = doc.get('error', {})
                    code = error.get('code', 'UNKNOWN')
                    message = error.get('message', 'Unknown error')
                    details = error.get('details', [])
                    detail_messages = ', '.join([d.get('message', '') for d in details])

                    full_error = f"[ETA] Receipt rejected: {message} (Code: {code}). Details: {detail_messages}"
                    self._handle_submission_error(full_error)
                    self.state = 'rejected'

            except json.JSONDecodeError:
                self.uuid = False
                self._handle_submission_error("Invalid JSON response from ETA")
        else:
            self.uuid = False
            self._handle_submission_error(f"API call failed: {response.status_code} - {response.text}")

    def _submit_to_api(self):
        """Submit receipt to Egyptian Tax Authority API"""
        self.ensure_one()

        try:
            order = self.pos_order_id
            company = self.company_id

            # Get authentication token
            token = self._get_auth_token(order, company)
            if not token:
                raise UserError(_('Failed to obtain authentication token.'))

            # Prepare receipt data
            receipt_data = self._prepare_receipt_data()

            # Submit to API
            response = self._call_api(token, receipt_data)

            # Process response
            self._process_api_response(response)

        except Exception as e:
            self._handle_submission_error(str(e))

    def _get_exist_access_token(self):
        DEVICE_CONFIG = self.pos_config_id
        if DEVICE_CONFIG.access_token and DEVICE_CONFIG.token_expiration_date and datetime.now() <= DEVICE_CONFIG.token_expiration_date:
            return DEVICE_CONFIG.access_token
        return False

    def _get_auth_token(self, order, company):
        """Authenticate POS with ETA eReceipt system and retrieve access token."""
        token = self._get_exist_access_token()
        if token:
            return token

        try:
            auth_url = f"{idSrvBaseUrl}/connect/token"

            headers = {
                'posserial': order.config_id.pos_serial,
                'pososversion': order.config_id.pos_os_version,
                'posmodelframework': '',
                'presharedkey': '',
                'Content-Type': 'application/x-www-form-urlencoded'
            }

            data = {
                'grant_type': 'client_credentials',
                # 'client_id': company.l10n_eg_client_identifier,
                # 'client_secret': company.l10n_eg_client_secret,
                'client_id': order.config_id.pos_client_code,
                'client_secret': order.config_id.pos_secret_code
            }

            session = requests.session()
            ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            ctx.options |= 0x4
            session.mount('https://', CustomHttpAdapter(ctx))

            response = session.request(
                'POST',
                auth_url,
                headers=headers,
                data=data,
                timeout=30
            )

            if response.status_code == 200:
                token_data = response.json()
                token = token_data.get('access_token')

                DEVICE_CONFIG = order.config_id
                DEVICE_CONFIG.access_token = token
                DEVICE_CONFIG.token_expiration_date = datetime.now() + timedelta(
                    seconds=token_data.get('expires_in'))

                _logger.debug(f"POS Authentication successful: {token_data}")
                return token
            else:
                _logger.error(f"POS Authentication failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            _logger.error(f"Exception during POS Authentication: {str(e)}")
            return None

    def _prepare_receipt_data(self, include_uuid=True):
        """Prepare receipt data for API submission"""
        order = self.pos_order_id
        company = self.company_id

        # Prepare receipt lines
        payment_method = self.env['pos.payment.method'].sudo()

        if any(payment_method.browse(l.payment_method_id.id).is_cash_count for l in order.payment_ids):
            payment_method = "C"  # Cash
        elif any(not payment_method.browse(l.payment_method_id.id).is_cash_count and payment_method.browse(
                l.payment_method_id.id).journal_id for l in order.payment_ids):
            payment_method = "V"  # Visa
        else:
            payment_method = "O"  # Other

        total_sales = 0
        total_discount = 0

        receipt_lines = []
        for line in order.lines:
            discount_rate = line.discount or 0
            line_total = abs(line.qty) * line.price_unit
            discount_amount = line_total * discount_rate / 100.0

            total_sales += line_total
            total_discount += discount_amount

            item_code = line.product_id.l10n_eg_eta_code or line.product_id.barcode or ''
            line_data = {
                'internalCode': str(line.product_id.id),
                'description': line.product_id.name,
                'itemType': item_code.startswith('EG') and 'EGS' or 'GS1',  # Goods and Services
                'itemCode': item_code,
                'unitType': 'EA',  # Each
                'quantity': abs(line.qty),
                "unitPrice": round(line.price_unit, 2),
                "netSale": round(abs(line.price_subtotal), 2),
                'totalSale': round(line_total, 2),
                'total': round(abs(line.price_subtotal_incl), 2),
                "commercialDiscountData": [
                    {
                        "amount": 0,
                        "description": "CDESC",
                        "rate": 0
                    }
                ],
                "itemDiscountData": [
                    {
                        "amount": round(discount_amount, 2),
                        "description": f"Item Discount ({discount_rate}%)" if discount_rate else "IDESC",
                        "rate": round(discount_rate, 2)
                    }
                ],
                "additionalCommercialDiscount": {
                    "amount": 0,
                    "description": "ADESC",
                    "rate": 0
                },
                "additionalItemDiscount": {
                    "amount": 0,
                    "description": "AIDESC",
                    "rate": 0
                },
                'valueDifference': 0,
                'taxableItems': self._get_tax_data(line)
            }
            receipt_lines.append(line_data)

        if order.partner_id and order.partner_id.country_id and order.partner_id.country_id.code == 'EG':
            partner_type = "P" if order.partner_id.is_company == False else "B"
        elif order.partner_id and order.partner_id.country_id:
            partner_type = "F"
        else:
            partner_type = "P"

        # Main receipt structure
        receipt_data = {
            "receipts": [{
                "header": {
                    "dateTimeIssued": order.date_order.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    "receiptNumber": self._get_receipt_number(),
                    "uuid": '',  # Will be set later
                    "previousUUID": self.previous_uuid or '',
                    "currency": order.currency_id.name or 'EGP',
                    "exchangeRate": 0 if order.currency_id.name == 'EGP' else order.currency_id.rate,
                    "orderdeliveryMode": "FC",
                },
                "documentType": {
                    "receiptType": "SR" if order.amount_total > 0 else "r",
                    "typeVersion": "1.2"
                },
                "seller": {
                    "rin": company.vat,
                    "companyTradeName": company.name,
                    "branchCode":  self.pos_config_id.pos_branch_code or "0",
                    "branchAddress": {
                        "country": 'EG',
                        "governate": company.state_id.name if company.state_id else "",
                        "regionCity": company.city or "",
                        "street": company.street or "",
                        "buildingNumber": "0",
                        "postalCode": "",
                        "floor": "",
                        "room": "",
                        "landmark": "",
                        "additionalInformation": ""
                    },
                    "deviceSerialNumber": order.config_id.pos_serial,
                    "activityCode": company.activity_code or "4771",  # Default to Retail Trade
                },
                "buyer": {
                    "type": partner_type,
                    "id": order.partner_id.vat if order.partner_id and order.partner_id.vat else "",
                    "name": order.partner_id.name if order.partner_id else "Cash Customer",
                    "mobileNumber": order.partner_id.mobile if order.partner_id and order.partner_id.mobile else "",
                    "paymentNumber": "",
                },
                "itemData": receipt_lines,
                "totalSales": round(total_sales, 5),
                "totalCommercialDiscount": 0,
                "totalItemsDiscount": round(total_discount, 5),
                "extraReceiptDiscountData": [],
                "netAmount": round(total_sales - total_discount, 5),
                "feesAmount": 0,
                "totalAmount": round(abs(order.amount_total), 5),
                "taxTotals": self._get_order_tax_totals(order),
                "paymentMethod": payment_method,
                "adjustment": 0
            }]
        }

        if include_uuid:
            # Generate UUID if not already set
            if not self.uuid:
                self.uuid = self._generate_receipt_uuid()

            # Set UUID in receipt header
            receipt_data["receipts"][0]["header"]["uuid"] = self.uuid

        if order.amount_total < 0.0 and self.reference_uuid:
            receipt_data["receipts"][0]["header"]["referenceUUID"] = self.reference_uuid
        elif order.amount_total < 0.0:
            receipt_data["receipts"][0]["documentType"]["receiptType"] = "RWR"

        # Store receipt data
        self.receipt_data = json.dumps(receipt_data, indent=2, ensure_ascii=False)

        return receipt_data

    def _get_tax_data(self, line):
        """Get tax data for receipt line"""
        tax_data = []

        for tax in line.tax_ids_after_fiscal_position:
            if tax.amount > 0:
                taxType, subType = tax.l10n_eg_eta_code.split('_') if tax.l10n_eg_eta_code else ("T1", "V009")
                tax_info = {
                    "taxType": taxType.upper(),  # VAT
                    "amount": round((abs(line.price_subtotal) * tax.amount / 100), 5),
                    "subType": subType.upper(),  # Standard VAT rate
                    "rate": tax.amount
                }
                tax_data.append(tax_info)

        return tax_data

    def _get_order_tax_totals(self, order):
        """Get order-level tax totals in ETA Retail Receipt format"""
        tax_totals_map = {}

        for line in order.lines:
            line_base = abs(line.price_subtotal)

            for tax in line.tax_ids_after_fiscal_position:
                if tax.amount > 0:
                    taxType, subType = tax.l10n_eg_eta_code.split('_') if tax.l10n_eg_eta_code else ("T1", "V009")

                    rate = tax.amount
                    tax_type = taxType.upper()
                    sub_type = subType.upper()

                    # Group only by tax_type, not by rate or sub_type
                    key = tax_type  # Changed from (tax_type, rate, sub_type)
                    tax_amount = line_base * rate / 100

                    if key not in tax_totals_map:
                        tax_totals_map[key] = 0
                    tax_totals_map[key] += tax_amount

        # Format the result
        tax_totals = []
        for tax_type, amount in tax_totals_map.items():
            tax_totals.append({
                "taxType": tax_type,
                "amount": round(amount, 5)
            })

        return tax_totals

    def _call_api(self, token, receipt_data):
        """Submit receipt(s) to the Egyptian Tax Authority's eReceipt system."""
        try:
            submit_url = f"{apiBaseUrl}/api/v1/receiptsubmissions"

            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }

            response = requests.post(
                submit_url,
                json=receipt_data,
                headers=headers,
                timeout=30
            )

            if response.status_code == 202:
                return response
            else:
                _logger.error(f"Receipt submission failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            _logger.error(f"Exception during receipt submission: {str(e)}")
            return None

    def _parse_eta_request_time(self, iso_str):
        # Example input: "2025-07-12T04:50:07.1372626Z"
        if '.' in iso_str:
            base, frac = iso_str.split('.')
            frac = frac.rstrip('Z')[:6].ljust(6, '0')  # Max 6 digits for Python datetime
            iso_cleaned = f"{base}.{frac}Z"
        else:
            iso_cleaned = iso_str

        # Parse to Python datetime
        dt = datetime.strptime(iso_cleaned, "%Y-%m-%dT%H:%M:%S.%fZ")

        # Convert to Odoo datetime string (UTC)
        return fields.Datetime.to_string(dt)

    def _handle_submission_error(self, error_message):
        """Handle submission errors"""
        self.error_message = error_message
        self.retry_count += 1

        if self.retry_count >= self.max_retries:
            self.uuid = False
            self.state = 'error'
            _logger.error(f"Receipt {self.uuid} failed after {self.retry_count} attempts: {error_message}")
        else:
            self.uuid = False
            self.state = 'retry'
            # Schedule retry with exponential backoff
            retry_delay = 2 ** self.retry_count  # 2, 4, 8 minutes
            self.next_retry_date = fields.Datetime.now() + timedelta(minutes=retry_delay)
            _logger.warning(f"Receipt {self.uuid} will retry in {retry_delay} minutes: {error_message}")

    def _generate_receipt_uuid(self):
        """
        Generate receipt UUID according to ETA documentation:
        1. Ensure UUID field is empty
        2. Serialize and normalize the receipt object
        3. Create SHA256 hash
        4. Convert to 64-character hexadecimal string
        """

        # Step 1: Make a copy and ensure UUID is empty
        receipt_data = self._prepare_receipt_data(False)
        receipt_obj = receipt_data['receipts'][0]

        receipt_copy = json.loads(json.dumps(receipt_obj, ensure_ascii=False, separators=(',', ':')))
        receipt_copy["header"]["uuid"] = ""

        # Step 2: Serialize the receipt object
        serialized = self._serialize_json_receipt(receipt_copy)

        # Step 3: Normalize Unicode characters
        unicode_escaped = serialized.encode('unicode_escape').decode('ascii')

        # Step 4: Create SHA256 hash
        hash_bytes = hashlib.sha256(unicode_escaped.encode('ascii')).digest()

        # Step 5: Convert to 64-character hexadecimal string
        uuid_hex = hash_bytes.hex()

        return uuid_hex

    def _serialize_json_receipt(self, obj):
        """
            Precise serialization according to ETA documentation with exact ordering.
            This implementation follows the exact rules from the ETA documentation.
            """
        if obj is None:
            return '""'

        # Handle simple value types (string, number, boolean)
        if isinstance(obj, (str, int, float, bool)):
            # Convert to string and enclose in quotes
            return f'"{obj}"'

        # Handle arrays/lists
        if isinstance(obj, list):
            return ""  # This shouldn't happen at root level for arrays

        # Handle objects/dictionaries
        if isinstance(obj, dict):
            serialized = ""

            # Process dictionary items in their original order
            for key, value in obj.items():
                key_upper = key.upper()

                # Handle arrays specially
                if isinstance(value, list):
                    # Add array property name first
                    serialized += f'"{key_upper}"'
                    # Then add each array element with the array property name
                    for item in value:
                        serialized += f'"{key_upper}"'
                        serialized += self._serialize_json_receipt(item)
                else:
                    # Add property name
                    serialized += f'"{key_upper}"'
                    # Add property value
                    serialized += self._serialize_json_receipt(value)

            return serialized

        return f'"{obj}"'

    def _get_eta_receipt_details(self):
        for rec in self:
            uuid = rec.uuid

            if not uuid:
                raise ValidationError(_('UUID not found to check the status for %s' % (rec.receipt_number)))

            get_url = 'https://api.invoicing.eta.gov.eg/api/v1/receipts/%s/raw'
            if get_url:
                access_token = rec._get_auth_token(self.pos_order_id, self.company_id)

                headers = {
                    'Authorization': 'Bearer %s' % access_token,
                    'Content-Type': 'application/json'
                }

                ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
                ctx.options |= 0x4

                session = requests.session()
                session.mount('https://', CustomHttpAdapter(ctx))

                get_response = session.request("GET", (get_url) % uuid, headers=headers, data={})
                get_response_data = get_response.json()

                if get_response_data.get('receipt') and get_response_data['receipt'].get('status'):
                    rec.eta_status = get_response_data['receipt'].get('status').lower()
                else:
                    rec.eta_status = 'undetected'

    def _get_receipt_number(self):
        """Generate a unique receipt number"""
        now = self.pos_order_id.date_order or fields.Datetime.now()
        year = now.strftime('%Y')
        month = now.strftime('%m')
        branch_code = self.pos_config_id.pos_branch_code or "0"
        branch_code = str(branch_code).zfill(2)

        # Filter existing records for same year, month, branch
        domain = [
            ('receipt_number', 'like', f"{year}-{month}-{branch_code}-%"),
            ('id', '!=', self.id)
        ]
        existing = self.search(domain, order='receipt_number desc', limit=1)

        if existing:
            # Get the numeric part and increment it
            last_seq = existing.receipt_number.split('-')[-1]
            next_seq = str(int(last_seq) + 1).zfill(4)
        else:
            next_seq = '0001'

        return f"{year}-{month}-{branch_code}-{next_seq}"

    def cron_sync_pos_receipts(self):
        """Cron job to sync receipts"""
        pending_receipt = self.env['egypt.ereceipt'].search([
            ('state', 'in', ['rejected', 'error', 'retry']),
        ], limit=1)

        if pending_receipt:
            _logger.info(f"Pending receipt found!, skipping creation.")
            return

        orders = self.env['pos.order'].sudo().search([
            ('ereceipt_status', '=', 'none'),
            ('amount_total', '!=', 0.0),
            ('create_date', '>', '2025-12-21 00:00:00'),
        ])

        for order in sorted(orders, key=lambda o: o.date_order):
            referenceUUID = ""
            if order.amount_total < 0.0:
                for line in order.lines:
                    if line.refunded_orderline_id:
                        ereceipt_id = self.search(
                            [('pos_order_id', '=', line.refunded_orderline_id.order_id.id)], limit=1)
                        referenceUUID = ereceipt_id.uuid if ereceipt_id else ""
                        break

            ereceipt_data = {
                'pos_order_id': order.id,
                'company_id': order.company_id.id,
                'reference_uuid': referenceUUID,
            }

            exist_ereceipt = self.env['egypt.ereceipt'].search([
                ('pos_order_id', '=', order.id),
            ], limit=1)

            if exist_ereceipt:
                _logger.info(f"Receipt already exists for order {order.id}, skipping creation.")
                continue

            ereceipt = self.env['egypt.ereceipt'].create(ereceipt_data)

            # Submit to API (async to avoid blocking POS)
            try:
                ereceipt._submit_to_api()
            except Exception as e:
                _logger.error(f"Failed to submit receipt for order {order.id}: {str(e)}")
                ereceipt._handle_submission_error(str(e))

    @api.model
    def cron_get_status(self):
        records = self.search([('state', '=', 'accepted'), ('eta_status', '=', 'undetected')])
        records._get_eta_receipt_details()

    @api.model
    def cron_retry_failed_submissions(self):
        """Cron job to retry failed submissions"""
        retry_records = self.search([
            ('state', '=', 'retry'),
            ('next_retry_date', '<=', fields.Datetime.now()),
            ('retry_count', '<', 3)
        ])

        for record in retry_records:
            try:
                record._submit_to_api()
            except Exception as e:
                _logger.error(f"Retry failed for receipt {record.uuid}: {str(e)}")
