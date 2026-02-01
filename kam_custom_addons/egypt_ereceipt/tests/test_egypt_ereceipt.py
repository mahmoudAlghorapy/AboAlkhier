import json
import unittest
import random
import string
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError, ValidationError
from odoo import fields


class TestEgyptEReceipt(TransactionCase):
    
    def setUp(self):
        super().setUp()
        
        # Create test company
        self.company = self.env['res.company'].create({
            'name': 'Test Company',
            'vat': '123456789',
            'egypt_ereceipt_enabled': True,
            'activity_code': '4771',
            'l10n_eg_client_identifier': 'test_client_id',
            'l10n_eg_client_secret': 'test_client_secret',
        })
        
        # Create test POS config
        self.pos_config = self.env['pos.config'].create({
            'name': 'Test POS',
            'pos_serial': 'TEST123456',
            'pos_branch_code': '01',
            'pos_os_version': 'windows',
            'pos_model_framework': '1',
            'pos_client_code': 'test_client',
            'pos_secret_code': 'test_secret',
        })
        
        # Create test POS session
        self.pos_session = self.env['pos.session'].create({
            'config_id': self.pos_config.id,
            'user_id': self.env.user.id,
            'state': 'opened',
        })
        
        # Get tax group
        self.tax_group = self.env['account.tax.group'].search([('company_id', '=', self.company.id)], limit=1)
        if not self.tax_group:
            self.tax_group = self.env['account.tax.group'].search([], limit=1)
        if not self.tax_group:
            self.tax_group = self.env['account.tax.group'].create({'name': 'Test Tax Group', 'company_id': self.company.id})
        
        # Create test customer
        self.customer = self.env['res.partner'].create({
            'name': 'Test Customer',
            'country_id': self.env.ref('base.eg').id,
            'vat': '987654321',
        })
        
        # Create test product
        self.product = self.env['product.product'].create({
            'name': 'Test Product',
            'list_price': 100.0,
            'taxes_id': [(6, 0, [self._create_tax('VAT 14%', 14.0, 't1_v009').id])],
            'l10n_eg_eta_code': '123456',
        })
        
        # Create test POS order
        self.pos_order = self.env['pos.order'].create({
            'partner_id': self.customer.id,
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'amount_tax': 14.0,
            'amount_total': 114.0,
            'amount_paid': 114.0,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': self.product.id,
                'qty': 1.0,
                'price_unit': 100.0,
                'price_subtotal': 100.0,
                'price_subtotal_incl': 114.0,
                'tax_ids': [(6, 0, [self._create_tax('VAT 14%', 14.0, 't1_v009').id])],
            })],
        })
        
        # Create test e-receipt
        self.ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.pos_order.id,
            'company_id': self.company.id,
        })
    
    def _create_tax(self, name, amount, eta_code):
        """Helper method to create test tax"""
        return self.env['account.tax'].create({
            'name': '%s %s %s' % (name, self.company.id, ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))),
            'amount': amount,
            'type_tax_use': 'sale',
            'l10n_eg_eta_code': eta_code.lower(),
            'company_id': self.company.id,
            'tax_group_id': self.tax_group.id,
            'country_id': self.env.ref('base.eg').id,
        })
    
    def test_ereceipt_creation(self):
        """Test basic e-receipt creation"""
        self.assertEqual(self.ereceipt.pos_order_id.id, self.pos_order.id)
        self.assertEqual(self.ereceipt.company_id.id, self.company.id)
        self.assertEqual(self.ereceipt.state, 'draft')
        self.assertFalse(self.ereceipt.uuid)
        self.assertFalse(self.ereceipt.receipt_number)
    
    def test_ereceipt_fields_computation(self):
        """Test computed fields"""
        # Test related fields
        self.assertEqual(self.ereceipt.pos_session_id.id, self.pos_session.id)
        self.assertEqual(self.ereceipt.pos_config_id.id, self.pos_config.id)
        self.assertEqual(self.ereceipt.pos_date_order, self.pos_order.date_order)
        
        # Test previous_uuid computation
        self.assertFalse(self.ereceipt.previous_uuid)
    
    def test_ereceipt_state_transitions(self):
        """Test state field transitions"""
        # Test initial state
        self.assertEqual(self.ereceipt.state, 'draft')
        
        # Test state change to submitted
        self.ereceipt.state = 'submitted'
        self.assertEqual(self.ereceipt.state, 'submitted')
        
        # Test state change to accepted
        self.ereceipt.state = 'accepted'
        self.assertEqual(self.ereceipt.state, 'accepted')
        
        # Test state change to rejected
        self.ereceipt.state = 'rejected'
        self.assertEqual(self.ereceipt.state, 'rejected')
        
        # Test state change to error
        self.ereceipt.state = 'error'
        self.assertEqual(self.ereceipt.state, 'error')
    
    def test_ereceipt_receipt_number_generation(self):
        """Test receipt number generation"""
        receipt_number = self.ereceipt._get_receipt_number()
        
        # Check format: YYYY-MM-BRANCH-SEQ
        self.assertTrue(receipt_number.startswith(datetime.now().strftime('%Y-%m')))
        self.assertIn('-01-', receipt_number)  # Branch code 01
        
        # Test sequence increment
        ereceipt2 = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.pos_order.id,
            'company_id': self.company.id,
        })
        receipt_number2 = ereceipt2._get_receipt_number()
        
        # Second receipt should have higher sequence
        seq1 = int(receipt_number.split('-')[-1])
        seq2 = int(receipt_number2.split('-')[-1])
        self.assertGreater(seq2, seq1)
    
    def test_ereceipt_unlink(self):
        """Test e-receipt deletion"""
        ereceipt_id = self.ereceipt.id
        self.ereceipt.unlink()
        
        # Verify record is deleted
        found = self.env['egypt.ereceipt'].search([('id', '=', ereceipt_id)])
        self.assertEqual(len(found), 0)
    
    def test_ereceipt_name_get(self):
        """Test name_get method"""
        # Set receipt number
        self.ereceipt.receipt_number = '2023-12-01-0001'
        name = self.ereceipt.name_get()
        self.assertEqual(name[0][1], '2023-12-01-0001')
    
    def test_ereceipt_search_filtering(self):
        """Test search and filtering"""
        # Test search by state
        draft_receipts = self.env['egypt.ereceipt'].search([('state', '=', 'draft')])
        self.assertIn(self.ereceipt.id, draft_receipts.ids)
        
        # Test search by company
        company_receipts = self.env['egypt.ereceipt'].search([('company_id', '=', self.company.id)])
        self.assertIn(self.ereceipt.id, company_receipts.ids)
        
        # Test search by POS order
        order_receipts = self.env['egypt.ereceipt'].search([('pos_order_id', '=', self.pos_order.id)])
        self.assertIn(self.ereceipt.id, order_receipts.ids)
    
    def test_ereceipt_copy(self):
        """Test e-receipt copying"""
        # Set some values
        self.ereceipt.receipt_number = '2023-12-01-0001'
        self.ereceipt.uuid = 'test-uuid'
        
        # Copy the record
        copy_receipt = self.ereceipt.copy()
        
        # Verify copy has different ID but same related data
        self.assertNotEqual(copy_receipt.id, self.ereceipt.id)
        self.assertEqual(copy_receipt.pos_order_id.id, self.ereceipt.pos_order_id.id)
        self.assertEqual(copy_receipt.company_id.id, self.ereceipt.company_id.id)
        
        # Verify copy has default values for non-copied fields
        self.assertEqual(copy_receipt.state, 'draft')
        self.assertFalse(copy_receipt.receipt_number)
        self.assertFalse(copy_receipt.uuid)


class TestEgyptEReceiptUUID(TransactionCase):
    
    def setUp(self):
        super().setUp()
        
        # Create test company
        self.company = self.env['res.company'].create({
            'name': 'Test Company UUID %s' % self.env.user.id,
            'vat': '123456789',
            'egypt_ereceipt_enabled': True,
        })
        
        # Get tax group
        self.tax_group = self.env['account.tax.group'].search([('company_id', '=', self.company.id)], limit=1)
        if not self.tax_group:
            self.tax_group = self.env['account.tax.group'].search([], limit=1)
        if not self.tax_group:
            self.tax_group = self.env['account.tax.group'].create({'name': 'Test Tax Group UUID %s' % self.company.id, 'company_id': self.company.id})

        self.pos_config = self.env['pos.config'].create({
            'name': 'Test POS',
            'pos_serial': 'TEST123456',
            'pos_branch_code': '01',
        })
        
        self.pos_session = self.env['pos.session'].create({
            'config_id': self.pos_config.id,
            'user_id': self.env.user.id,
            'state': 'opened',
        })
        
        self.product = self.env['product.product'].create({
            'name': 'Test Product',
            'list_price': 100.0,
        })
        
        self.pos_order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'amount_tax': 0.0,
            'amount_total': 100.0,
            'amount_paid': 100.0,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': self.product.id,
                'qty': 1.0,
                'price_unit': 100.0,
                'price_subtotal': 100.0,
                'price_subtotal_incl': 100.0,
            })],
        })
        
        self.ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.pos_order.id,
            'company_id': self.company.id,
        })
    
    def test_uuid_generation(self):
        """Test UUID generation"""
        # Generate UUID
        uuid = self.ereceipt._generate_receipt_uuid()
        
        # Verify UUID format
        self.assertEqual(len(uuid), 64)  # SHA256 hex
        self.assertTrue(all(c in '0123456789abcdef' for c in uuid.lower()))
        
        # Verify UUID is set on record
        self.ereceipt.uuid = uuid
        self.assertEqual(self.ereceipt.uuid, uuid)
    
    def test_uuid_consistency(self):
        """Test UUID generation consistency"""
        # Generate UUID twice
        uuid1 = self.ereceipt._generate_receipt_uuid()
        self.ereceipt.uuid = None  # Reset
        uuid2 = self.ereceipt._generate_receipt_uuid()
        
        # UUIDs should be the same for same data
        self.assertEqual(uuid1, uuid2)
    
    def test_uuid_uniqueness(self):
        """Test UUID uniqueness for different receipts"""
        # Create second receipt
        pos_order2 = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'amount_tax': 0.0,
            'amount_total': 200.0,
            'amount_paid': 200.0,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': self.product.id,
                'qty': 2.0,  # Different quantity
                'price_unit': 100.0,
                'price_subtotal': 200.0,
                'price_subtotal_incl': 200.0,
            })],
        })
        
        ereceipt2 = self.env['egypt.ereceipt'].create({
            'pos_order_id': pos_order2.id,
            'company_id': self.company.id,
        })
        
        # Generate UUIDs
        uuid1 = self.ereceipt._generate_receipt_uuid()
        uuid2 = ereceipt2._generate_receipt_uuid()
        
        # UUIDs should be different
        self.assertNotEqual(uuid1, uuid2)
    
    def test_uuid_with_empty_data(self):
        """Test UUID generation with minimal data"""
        # Create minimal receipt
        minimal_order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'amount_tax': 0.0,
            'amount_total': 0.0,
            'amount_paid': 0.0,
            'amount_return': 0.0,
        })
        
        minimal_ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': minimal_order.id,
            'company_id': self.company.id,
        })
        
        # Should still generate UUID
        uuid = minimal_ereceipt._generate_receipt_uuid()
        self.assertEqual(len(uuid), 64)
        self.assertTrue(all(c in '0123456789abcdef' for c in uuid.lower()))


class TestEgyptEReceiptDataPreparation(TransactionCase):
    
    def setUp(self):
        super().setUp()

        # Get Egypt country and state
        self.country_eg = self.env.ref('base.eg')
        self.state_eg = self.env['res.country.state'].search([('country_id', '=', self.country_eg.id)], limit=1)
        if not self.state_eg:
             self.state_eg = self.env['res.country.state'].create({
                'name': 'Cairo',
                'code': 'CAI',
                'country_id': self.country_eg.id,
            })

        # Create test company
        self.company = self.env['res.company'].create({
            'name': 'Test Company',
            'vat': '123456789',
            'egypt_ereceipt_enabled': True,
            'activity_code': '4771',
            'state_id': self.state_eg.id,
            'city': 'Cairo',
            'street': 'Test Street',
        })
        
        # Create test POS config
        self.pos_config = self.env['pos.config'].create({
            'name': 'Test POS',
            'pos_serial': 'TEST123456',
            'pos_branch_code': '01',
        })
        
        # Create test POS session
        self.pos_session = self.env['pos.session'].create({
            'config_id': self.pos_config.id,
            'user_id': self.env.user.id,
            'state': 'opened',
        })
        
        # Get tax group
        self.tax_group = self.env['account.tax.group'].search([('company_id', '=', self.company.id)], limit=1)
        if not self.tax_group:
            self.tax_group = self.env['account.tax.group'].search([], limit=1)
        if not self.tax_group:
            self.tax_group = self.env['account.tax.group'].create({'name': 'Test Tax Group', 'company_id': self.company.id})

        # Create test tax
        self.tax = self.env['account.tax'].create({
            'name': 'VAT 14%% Data Prep %s' % self.company.id,
            'amount': 14.0,
            'type_tax_use': 'sale',
            'l10n_eg_eta_code': 't1_v009',
            'company_id': self.company.id,
            'tax_group_id': self.tax_group.id,
            'country_id': self.env.ref('base.eg').id,
        })
        
        # Create test product
        self.product = self.env['product.product'].create({
            'name': 'Test Product',
            'list_price': 100.0,
            'taxes_id': [(6, 0, [self.tax.id])],
            'l10n_eg_eta_code': '123456',
        })
        
        # Get Egypt country
        self.country_eg = self.env.ref('base.eg')
        
        # Get Egypt state
        self.state_eg = self.env['res.country.state'].search([('country_id', '=', self.country_eg.id)], limit=1)
        if not self.state_eg:
            self.state_eg = self.env['res.country.state'].create({
                'name': 'Cairo',
                'code': 'CAI',
                'country_id': self.country_eg.id,
            })
        
        # Create test customer
        self.customer = self.env['res.partner'].create({
            'name': 'Test Customer',
            'country_id': self.country_eg.id,
            'state_id': self.state_eg.id,
            'city': 'Cairo',
            'street': 'Test Street',
            'vat': '987654321',
            'mobile': '01234567890',
        })
        
        # Create test POS order
        self.pos_order = self.env['pos.order'].create({
            'partner_id': self.customer.id,
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'date_order': '2023-12-01 10:00:00',
            'amount_tax': 25.2,
            'amount_total': 205.2,
            'amount_paid': 205.2,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': self.product.id,
                'qty': 2.0,
                'price_unit': 100.0,
                'discount': 10.0,
                'price_subtotal': 180.0,
                'price_subtotal_incl': 205.2,
                'tax_ids': [(6, 0, [self.tax.id])],
            })],
        })
        
        # Create test e-receipt
        self.ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.pos_order.id,
            'company_id': self.company.id,
        })
    
    def test_receipt_data_structure(self):
        """Test receipt data structure and required fields"""
        receipt_data = self.ereceipt._prepare_receipt_data(include_uuid=False)
        
        # Verify main structure
        self.assertIn('receipts', receipt_data)
        self.assertEqual(len(receipt_data['receipts']), 1)
        
        receipt = receipt_data['receipts'][0]
        
        # Verify header
        self.assertIn('header', receipt)
        header = receipt['header']
        self.assertIn('dateTimeIssued', header)
        self.assertIn('receiptNumber', header)
        self.assertIn('currency', header)
        self.assertIn('orderdeliveryMode', header)
        
        # Verify document type
        self.assertIn('documentType', receipt)
        doc_type = receipt['documentType']
        self.assertIn('receiptType', doc_type)
        self.assertIn('typeVersion', doc_type)
        
        # Verify seller
        self.assertIn('seller', receipt)
        seller = receipt['seller']
        self.assertIn('rin', seller)
        self.assertIn('companyTradeName', seller)
        self.assertIn('branchCode', seller)
        self.assertIn('branchAddress', seller)
        self.assertIn('deviceSerialNumber', seller)
        self.assertIn('activityCode', seller)
        
        # Verify buyer
        self.assertIn('buyer', receipt)
        buyer = receipt['buyer']
        self.assertIn('type', buyer)
        self.assertIn('name', buyer)
        
        # Verify item data
        self.assertIn('itemData', receipt)
        self.assertIsInstance(receipt['itemData'], list)
        
        # Verify totals
        self.assertIn('totalSales', receipt)
        self.assertIn('netAmount', receipt)
        self.assertIn('totalAmount', receipt)
        self.assertIn('taxTotals', receipt)
        self.assertIn('paymentMethod', receipt)
    
    def test_receipt_header_data(self):
        """Test receipt header data preparation"""
        receipt_data = self.ereceipt._prepare_receipt_data(include_uuid=False)
        header = receipt_data['receipts'][0]['header']
        
        # Test date format
        self.assertEqual(header['dateTimeIssued'], '2023-12-01T10:00:00Z')
        
        # Test receipt number format
        receipt_number = header['receiptNumber']
        self.assertTrue(receipt_number.startswith('2023-12-01-'))
        
        # Test currency
        self.assertEqual(header['currency'], 'EGP')  # Default currency
        
        # Test order delivery mode
        self.assertEqual(header['orderdeliveryMode'], 'FC')
        
        # Test previous UUID (should be empty for first receipt)
        self.assertEqual(header['previousUUID'], '')
    
    def test_seller_data_preparation(self):
        """Test seller data preparation"""
        receipt_data = self.ereceipt._prepare_receipt_data(include_uuid=False)
        seller = receipt_data['receipts'][0]['seller']
        
        # Test company data
        self.assertEqual(seller['rin'], '123456789')
        self.assertEqual(seller['companyTradeName'], 'Test Company')
        self.assertEqual(seller['branchCode'], '01')
        self.assertEqual(seller['deviceSerialNumber'], 'TEST123456')
        self.assertEqual(seller['activityCode'], '4771')
        
        # Test branch address
        address = seller['branchAddress']
        self.assertEqual(address['country'], 'EG')
        self.assertEqual(address['governate'], self.company.state_id.name)
        self.assertEqual(address['regionCity'], 'Cairo')
        self.assertEqual(address['street'], 'Test Street')
        self.assertEqual(address['buildingNumber'], '0')
    
    def test_buyer_data_preparation(self):
        """Test buyer data preparation"""
        receipt_data = self.ereceipt._prepare_receipt_data(include_uuid=False)
        buyer = receipt_data['receipts'][0]['buyer']
        
        # Test customer data
        self.assertEqual(buyer['type'], 'P')  # Person (not company)
        self.assertEqual(buyer['id'], '987654321')
        self.assertEqual(buyer['name'], 'Test Customer')
        self.assertEqual(buyer['mobileNumber'], '01234567890')
        self.assertEqual(buyer['paymentNumber'], '')
    
    def test_buyer_data_for_foreign_customer(self):
        """Test buyer data for foreign customer"""
        # Create foreign customer
        foreign_customer = self.env['res.partner'].create({
            'name': 'Foreign Customer',
            'country_id': self.env.ref('base.us').id,
        })
        
        # Update order with foreign customer
        self.pos_order.partner_id = foreign_customer
        self.pos_order._compute_ereceipt_status()  # Trigger recomputation
        
        receipt_data = self.ereceipt._prepare_receipt_data(include_uuid=False)
        buyer = receipt_data['receipts'][0]['buyer']
        
        # Should be marked as foreign
        self.assertEqual(buyer['type'], 'F')
        self.assertEqual(buyer['name'], 'Foreign Customer')
    
    def test_buyer_data_for_company(self):
        """Test buyer data for company customer"""
        # Create company customer
        company_customer = self.env['res.partner'].create({
            'name': 'Company Customer',
            'is_company': True,
            'country_id': self.env.ref('base.eg').id,
            'vat': '111111111',
        })
        
        # Update order with company customer
        self.pos_order.partner_id = company_customer
        
        receipt_data = self.ereceipt._prepare_receipt_data(include_uuid=False)
        buyer = receipt_data['receipts'][0]['buyer']
        
        # Should be marked as business
        self.assertEqual(buyer['type'], 'B')
        self.assertEqual(buyer['id'], '111111111')
        self.assertEqual(buyer['name'], 'Company Customer')
    
    def test_buyer_data_for_cash_customer(self):
        """Test buyer data for cash customer (no partner)"""
        # Update order with no customer
        self.pos_order.partner_id = False
        
        receipt_data = self.ereceipt._prepare_receipt_data(include_uuid=False)
        buyer = receipt_data['receipts'][0]['buyer']
        
        # Should default to person with cash customer name
        self.assertEqual(buyer['type'], 'P')
        self.assertEqual(buyer['id'], '')
        self.assertEqual(buyer['name'], 'Cash Customer')
        self.assertEqual(buyer['mobileNumber'], '')
    
    def test_item_data_preparation(self):
        """Test item data preparation"""
        receipt_data = self.ereceipt._prepare_receipt_data(include_uuid=False)
        items = receipt_data['receipts'][0]['itemData']
        
        self.assertEqual(len(items), 1)
        item = items[0]
        
        # Test basic item data
        self.assertEqual(item['internalCode'], str(self.product.id))
        self.assertEqual(item['description'], 'Test Product')
        self.assertEqual(item['itemType'], 'GS1')
        self.assertEqual(item['itemCode'], '123456')
        self.assertEqual(item['unitType'], 'EA')
        self.assertEqual(item['quantity'], 2.0)
        self.assertEqual(item['unitPrice'], 100.0)
        
        # Test calculated values
        self.assertEqual(item['netSale'], 180.0)  # 2 * 100 * (1 - 0.1)
        self.assertEqual(item['totalSale'], 200.0)  # 2 * 100
        self.assertEqual(item['total'], 205.2)  # 180 + 14% VAT
        
        # Test discount data
        item_discount = item['itemDiscountData'][0]
        self.assertEqual(item_discount['amount'], 20.0)  # 200 * 10%
        self.assertEqual(item_discount['rate'], 10.0)
        self.assertEqual(item_discount['description'], 'Item Discount (10.0%)')
        
        # Test tax data
        self.assertIn('taxableItems', item)
        tax_items = item['taxableItems']
        self.assertEqual(len(tax_items), 1)
        
        tax = tax_items[0]
        self.assertEqual(tax['taxType'], 'T1')
        self.assertEqual(tax['subType'], 'V009')
        self.assertEqual(tax['rate'], 14.0)
        self.assertEqual(tax['amount'], 25.2)  # 180 * 14%
    
    def test_totals_calculation(self):
        """Test totals calculation"""
        receipt_data = self.ereceipt._prepare_receipt_data(include_uuid=False)
        receipt = receipt_data['receipts'][0]
        
        # Test calculated totals
        self.assertEqual(receipt['totalSales'], 200.0)  # 2 * 100
        self.assertEqual(receipt['totalItemsDiscount'], 20.0)  # 10% discount
        self.assertEqual(receipt['netAmount'], 180.0)  # 200 - 20
        self.assertEqual(receipt['totalAmount'], 205.2)  # 180 + 25.2 VAT
        self.assertEqual(receipt['feesAmount'], 0.0)
        self.assertEqual(receipt['adjustment'], 0.0)
        
        # Test tax totals
        tax_totals = receipt['taxTotals']
        self.assertEqual(len(tax_totals), 1)
        self.assertEqual(tax_totals[0]['taxType'], 'T1')
        self.assertEqual(tax_totals[0]['amount'], 25.2)
    
    def test_payment_method_detection(self):
        """Test payment method detection"""
        # Test with cash payment method
        cash_payment = self.env['pos.payment.method'].create({
            'name': 'Cash',
            'is_cash_count': True,
            'journal_id': self.env['account.journal'].create({'name': 'Cash Journal %s' % self.company.id, 'code': 'CASH%s' % self.company.id, 'type': 'cash'}).id,
        })
        
        # Add payment to order
        self.env['pos.payment'].create({
            'pos_order_id': self.pos_order.id,
            'payment_method_id': cash_payment.id,
            'amount': 205.2,
        })
        
        receipt_data = self.ereceipt._prepare_receipt_data(include_uuid=False)
        payment_method = receipt_data['receipts'][0]['paymentMethod']
        self.assertEqual(payment_method, 'C')
    
    def test_document_type_detection(self):
        """Test document type detection"""
        # Test sale receipt (positive amount)
        receipt_data = self.ereceipt._prepare_receipt_data(include_uuid=False)
        doc_type = receipt_data['receipts'][0]['documentType']
        self.assertEqual(doc_type['receiptType'], 'SR')  # Sale Receipt
        self.assertEqual(doc_type['typeVersion'], '1.2')
        
        # Test return receipt (negative amount)
        self.pos_order.amount_total = -205.2
        receipt_data = self.ereceipt._prepare_receipt_data(include_uuid=False)
        doc_type = receipt_data['receipts'][0]['documentType']
        self.assertEqual(doc_type['receiptType'], 'r')  # Return
    
    def test_receipt_data_json_storage(self):
        """Test receipt data JSON storage"""
        # Prepare receipt data
        self.ereceipt._prepare_receipt_data(include_uuid=True)
        
        # Verify JSON is stored
        self.assertTrue(self.ereceipt.receipt_data)
        
        # Verify JSON can be parsed
        receipt_data = json.loads(self.ereceipt.receipt_data)
        self.assertIn('receipts', receipt_data)
        self.assertEqual(len(receipt_data['receipts']), 1)
    
    def test_uuid_inclusion_in_receipt_data(self):
        """Test UUID inclusion in receipt data"""
        # Generate UUID first
        uuid = self.ereceipt._generate_receipt_uuid()
        self.ereceipt.uuid = uuid
        
        # Prepare receipt data with UUID
        receipt_data = self.ereceipt._prepare_receipt_data(include_uuid=True)
        header = receipt_data['receipts'][0]['header']
        
        # Verify UUID is included
        self.assertEqual(header['uuid'], uuid)
    
    def test_reference_uuid_for_returns(self):
        """Test reference UUID for return orders"""
        # Set up return scenario
        self.ereceipt.reference_uuid = 'test-reference-uuid'
        self.pos_order.amount_total = -205.2
        
        receipt_data = self.ereceipt._prepare_receipt_data(include_uuid=True)
        header = receipt_data['receipts'][0]['header']
        
        # Verify reference UUID is included for returns
        self.assertEqual(header['referenceUUID'], 'test-reference-uuid')


class TestEgyptEReceiptAPISubmission(TransactionCase):
    
    def setUp(self):
        super().setUp()
        
        # Create test company
        self.company = self.env['res.company'].create({
            'name': 'Test Company',
            'vat': '123456789',
            'egypt_ereceipt_enabled': True,
            'l10n_eg_client_identifier': 'test_client_id',
            'l10n_eg_client_secret': 'test_client_secret',
        })
        
        # Create test POS config
        self.pos_config = self.env['pos.config'].create({
            'name': 'Test POS',
            'pos_serial': 'TEST123456',
            'pos_branch_code': '01',
            'pos_os_version': 'windows',
            'pos_model_framework': '1',
        })
        
        # Create test POS session
        self.pos_session = self.env['pos.session'].create({
            'config_id': self.pos_config.id,
            'user_id': self.env.user.id,
            'state': 'opened',
        })
        
        # Create test product
        self.product = self.env['product.product'].create({
            'name': 'Test Product',
            'list_price': 100.0,
        })
        
        # Create test POS order
        self.pos_order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'amount_tax': 0.0,
            'amount_total': 100.0,
            'amount_paid': 100.0,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': self.product.id,
                'qty': 1.0,
                'price_unit': 100.0,
                'price_subtotal': 100.0,
                'price_subtotal_incl': 100.0,
            })],
        })
        
        # Create test e-receipt
        self.ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.pos_order.id,
            'company_id': self.company.id,
        })
    
    @patch('requests.post')
    def test_auth_token_success(self, mock_post):
        """Test successful authentication token retrieval"""
        # Mock successful token response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'access_token': 'test_token_12345',
            'expires_in': 3600
        }
        mock_post.return_value = mock_response
        
        # Test token retrieval
        token = self.ereceipt._get_auth_token(self.pos_order, self.company)
        
        # Verify token is returned
        self.assertEqual(token, 'test_token_12345')
        
        # Verify token is stored on POS config
        self.assertEqual(self.pos_config.access_token, 'test_token_12345')
        self.assertIsNotNone(self.pos_config.token_expiration_date)
        
        # Verify API call was made with correct parameters
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn('client_credentials', call_args[1]['data']['grant_type'])
        self.assertEqual(call_args[1]['data']['client_id'], 'test_client_id')
        self.assertEqual(call_args[1]['data']['client_secret'], 'test_client_secret')
    
    @patch('requests.post')
    def test_auth_token_failure(self, mock_post):
        """Test authentication token failure"""
        # Mock failed token response
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = 'Invalid credentials'
        mock_post.return_value = mock_response
        
        # Test token retrieval
        token = self.ereceipt._get_auth_token(self.pos_order, self.company)
        
        # Verify None is returned on failure
        self.assertIsNone(token)
    
    @patch('requests.post')
    def test_auth_token_exception(self, mock_post):
        """Test authentication token exception handling"""
        # Mock exception
        mock_post.side_effect = Exception('Network error')
        
        # Test token retrieval
        token = self.ereceipt._get_auth_token(self.pos_order, self.company)
        
        # Verify None is returned on exception
        self.assertIsNone(token)
    
    def test_existing_token_reuse(self):
        """Test reuse of existing valid token"""
        # Set existing token with future expiration
        future_time = datetime.now() + timedelta(hours=1)
        self.pos_config.access_token = 'existing_token'
        self.pos_config.token_expiration_date = future_time
        
        # Test token retrieval
        token = self.ereceipt._get_auth_token(self.pos_order, self.company)
        
        # Verify existing token is reused
        self.assertEqual(token, 'existing_token')
    
    def test_existing_token_expired(self):
        """Test expired token is not reused"""
        # Set existing token with past expiration
        past_time = datetime.now() - timedelta(hours=1)
        self.pos_config.access_token = 'expired_token'
        self.pos_config.token_expiration_date = past_time
        
        # Test token retrieval (should return None since no new token is generated)
        token = self.ereceipt._get_auth_token(self.pos_order, self.company)
        
        # Verify expired token is not reused
        self.assertIsNone(token)
    
    @patch('requests.post')
    def test_api_call_success(self, mock_post):
        """Test successful API call"""
        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_post.return_value = mock_response
        
        # Test API call
        receipt_data = {'test': 'data'}
        response = self.ereceipt._call_api('test_token', receipt_data)
        
        # Verify response is returned
        self.assertEqual(response, mock_response)
        
        # Verify API call was made with correct parameters
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertEqual(call_args[1]['json'], receipt_data)
        self.assertEqual(call_args[1]['headers']['Authorization'], 'Bearer test_token')
        self.assertEqual(call_args[1]['headers']['Content-Type'], 'application/json')
    
    @patch('requests.post')
    def test_api_call_failure(self, mock_post):
        """Test API call failure"""
        # Mock failed API response
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_post.return_value = mock_response
        
        # Test API call
        receipt_data = {'test': 'data'}
        response = self.ereceipt._call_api('test_token', receipt_data)
        
        # Verify None is returned on failure
        self.assertIsNone(response)
    
    @patch('requests.post')
    def test_api_call_exception(self, mock_post):
        """Test API call exception handling"""
        # Mock exception
        mock_post.side_effect = Exception('Network error')
        
        # Test API call
        receipt_data = {'test': 'data'}
        response = self.ereceipt._call_api('test_token', receipt_data)
        
        # Verify None is returned on exception
        self.assertIsNone(response)
    
    @patch('requests.post')
    def test_submission_workflow_success(self, mock_post):
        """Test complete submission workflow success"""
        # Mock token response
        mock_token_response = MagicMock()
        mock_token_response.status_code = 200
        mock_token_response.json.return_value = {
            'access_token': 'test_token',
            'expires_in': 3600
        }
        
        # Mock submission response
        mock_submission_response = MagicMock()
        mock_submission_response.status_code = 202
        mock_submission_response.json.return_value = {
            'submissionId': 'submission_123',
            'header': {'requestTime': '2023-12-01T10:00:00.000000Z'},
            'acceptedDocuments': [{
                'uuid': 'receipt_uuid_123',
                'receiptNumber': '2023-12-01-01-0001',
                'longId': 'long_id_123'
            }]
        }
        
        # Mock details response
        mock_details_response = MagicMock()
        mock_details_response.status_code = 200
        mock_details_response.json.return_value = {
            'receipt': {'status': 'valid'}
        }
        
        # Configure mock to return different responses
        def side_effect(*args, **kwargs):
            if 'token' in args[0]:
                return mock_token_response
            elif 'receiptsubmissions' in args[0]:
                return mock_submission_response
            else:
                return mock_details_response
        
        mock_post.side_effect = side_effect
        
        # Test submission
        self.ereceipt._submit_to_api()
        
        # Verify receipt state is updated
        self.assertEqual(self.ereceipt.state, 'accepted')
        self.assertEqual(self.ereceipt.uuid, 'receipt_uuid_123')
        self.assertEqual(self.ereceipt.receipt_number, '2023-12-01-01-0001')
        self.assertEqual(self.ereceipt.submission_uuid, 'submission_123')
        self.assertEqual(self.ereceipt.eta_status, 'valid')
        self.assertIsNotNone(self.ereceipt.accepted_date)
    
    @patch('requests.post')
    def test_submission_workflow_rejection(self, mock_post):
        """Test submission workflow with rejection"""
        # Mock token response
        mock_token_response = MagicMock()
        mock_token_response.status_code = 200
        mock_token_response.json.return_value = {
            'access_token': 'test_token',
            'expires_in': 3600
        }
        
        # Mock submission response with rejection
        mock_submission_response = MagicMock()
        mock_submission_response.status_code = 202
        mock_submission_response.json.return_value = {
            'submissionId': 'submission_123',
            'header': {'requestTime': '2023-12-01T10:00:00.000000Z'},
            'rejectedDocuments': [{
                'receiptNumber': '2023-12-01-01-0001',
                'longId': 'long_id_123',
                'error': {
                    'code': 'INVALID_DATA',
                    'message': 'Invalid receipt data',
                    'details': [{'message': 'Missing required field'}]
                }
            }]
        }
        
        # Mock details response
        mock_details_response = MagicMock()
        mock_details_response.status_code = 200
        mock_details_response.json.return_value = {
            'receipt': {'status': 'invalid'}
        }
        
        # Configure mock to return different responses
        def side_effect(*args, **kwargs):
            if 'token' in args[0]:
                return mock_token_response
            elif 'receiptsubmissions' in args[0]:
                return mock_submission_response
            else:
                return mock_details_response
        
        mock_post.side_effect = side_effect
        
        # Test submission
        self.ereceipt._submit_to_api()
        
        # Verify receipt state is updated
        self.assertEqual(self.ereceipt.state, 'rejected')
        self.assertEqual(self.ereceipt.eta_status, 'invalid')
        self.assertFalse(self.ereceipt.uuid)
        self.assertIn('Invalid receipt data', self.ereceipt.error_message)
    
    @patch('requests.post')
    def test_submission_workflow_api_error(self, mock_post):
        """Test submission workflow with API error"""
        # Mock token response
        mock_token_response = MagicMock()
        mock_token_response.status_code = 200
        mock_token_response.json.return_value = {
            'access_token': 'test_token',
            'expires_in': 3600
        }
        
        # Mock submission response with error
        mock_submission_response = MagicMock()
        mock_submission_response.status_code = 500
        mock_submission_response.text = 'Internal Server Error'
        
        # Configure mock to return different responses
        def side_effect(*args, **kwargs):
            if 'token' in args[0]:
                return mock_token_response
            else:
                return mock_submission_response
        
        mock_post.side_effect = side_effect
        
        # Test submission
        self.ereceipt._submit_to_api()
        
        # Verify receipt state is updated
        self.assertEqual(self.ereceipt.state, 'error')
        self.assertFalse(self.ereceipt.uuid)
        self.assertIn('API call failed', self.ereceipt.error_message)
    
    def test_manual_submit_action(self):
        """Test manual submit action"""
        # Test action on draft receipt
        self.ereceipt.state = 'draft'
        
        with patch.object(self.ereceipt, '_submit_to_api') as mock_submit:
            self.ereceipt.action_submit_receipt()
            mock_submit.assert_called_once()
    
    def test_manual_submit_action_already_valid(self):
        """Test manual submit action on already valid receipt"""
        # Set receipt as valid
        self.ereceipt.state = 'accepted'
        self.ereceipt.eta_status = 'valid'
        
        # Test action raises error
        with self.assertRaises(UserError):
            self.ereceipt.action_submit_receipt()
    
    def test_manual_retry_action(self):
        """Test manual retry action"""
        # Set receipt as error
        self.ereceipt.state = 'error'
        self.ereceipt.retry_count = 2
        
        with patch.object(self.ereceipt, '_submit_to_api') as mock_submit:
            self.ereceipt.action_retry_submission()
            mock_submit.assert_called_once()
            
            # Verify retry count is reset
            self.assertEqual(self.ereceipt.retry_count, 0)
            self.assertEqual(self.ereceipt.state, 'retry')
    
    def test_manual_retry_action_not_error(self):
        """Test manual retry action on non-error receipt"""
        # Set receipt as draft
        self.ereceipt.state = 'draft'
        
        # Test action raises error
        with self.assertRaises(UserError):
            self.ereceipt.action_retry_submission()


class TestEgyptEReceiptErrorHandling(TransactionCase):
    
    def setUp(self):
        super().setUp()
        
        # Create minimal test data
        self.company = self.env['res.company'].create({
            'name': 'Test Company',
            'vat': '123456789',
            'egypt_ereceipt_enabled': True,
            'l10n_eg_client_identifier': 'test_client_id',
            'l10n_eg_client_secret': 'test_client_secret',
        })
        
        self.pos_config = self.env['pos.config'].create({
            'name': 'Test POS',
            'pos_serial': 'TEST123456',
            'pos_branch_code': '01',
        })
        
        self.pos_session = self.env['pos.session'].create({
            'config_id': self.pos_config.id,
            'user_id': self.env.user.id,
            'state': 'opened',
        })
        
        self.product = self.env['product.product'].create({
            'name': 'Test Product',
            'list_price': 100.0,
        })
        
        self.pos_order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'amount_tax': 0.0,
            'amount_total': 100.0,
            'amount_paid': 100.0,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': self.product.id,
                'qty': 1.0,
                'price_unit': 100.0,
                'price_subtotal': 100.0,
                'price_subtotal_incl': 100.0,
            })],
        })
        
        self.ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.pos_order.id,
            'company_id': self.company.id,
        })
    
    def test_error_handling_first_retry(self):
        """Test error handling on first retry"""
        # Simulate first error
        self.ereceipt._handle_submission_error('Test error message')
        
        # Verify error state
        self.assertEqual(self.ereceipt.state, 'retry')
        self.assertEqual(self.ereceipt.retry_count, 1)
        self.assertEqual(self.ereceipt.error_message, 'Test error message')
        self.assertFalse(self.ereceipt.uuid)
        
        # Verify retry date is set (2 minutes for first retry)
        expected_time = datetime.now() + timedelta(minutes=2)
        actual_time = fields.Datetime.from_string(self.ereceipt.next_retry_date)
        time_diff = abs((actual_time - expected_time).total_seconds())
        self.assertLess(time_diff, 10)  # Allow 10 seconds difference
    
    def test_error_handling_second_retry(self):
        """Test error handling on second retry"""
        # Set first retry
        self.ereceipt.retry_count = 1
        self.ereceipt.state = 'retry'
        
        # Simulate second error
        self.ereceipt._handle_submission_error('Test error message')
        
        # Verify error state
        self.assertEqual(self.ereceipt.state, 'retry')
        self.assertEqual(self.ereceipt.retry_count, 2)
        
        # Verify retry date is set (4 minutes for second retry)
        expected_time = datetime.now() + timedelta(minutes=4)
        actual_time = fields.Datetime.from_string(self.ereceipt.next_retry_date)
        time_diff = abs((actual_time - expected_time).total_seconds())
        self.assertLess(time_diff, 10)
    
    def test_error_handling_max_retries(self):
        """Test error handling when max retries is reached"""
        # Set retry count to max - 1
        self.ereceipt.retry_count = 2
        self.ereceipt.state = 'retry'
        
        # Simulate final error
        self.ereceipt._handle_submission_error('Test error message')
        
        # Verify error state
        self.assertEqual(self.ereceipt.state, 'error')
        self.assertEqual(self.ereceipt.retry_count, 3)
        self.assertEqual(self.ereceipt.error_message, 'Test error message')
        self.assertFalse(self.ereceipt.uuid)
    
    def test_error_handling_custom_max_retries(self):
        """Test error handling with custom max retries"""
        # Set custom max retries
        self.ereceipt.max_retries = 5
        self.ereceipt.retry_count = 4
        self.ereceipt.state = 'retry'
        
        # Simulate error (should still retry)
        self.ereceipt._handle_submission_error('Test error message')
        
        # Receipt failed after 5 attempts -> state should be error
        self.assertEqual(self.ereceipt.state, 'error')
        self.assertEqual(self.ereceipt.retry_count, 5)
        
        # Simulate final error
        self.ereceipt._handle_submission_error('Test error message')
        
        # Verify error state
        self.assertEqual(self.ereceipt.state, 'error')
        self.assertEqual(self.ereceipt.retry_count, 6)
    
    def test_eta_request_time_parsing(self):
        """Test ETA request time parsing"""
        # Test standard format
        iso_str = '2023-12-01T10:00:00.123456Z'
        result = self.ereceipt._parse_eta_request_time(iso_str)
        
        # Verify result is in Odoo datetime format
        parsed = fields.Datetime.from_string(result)
        self.assertEqual(parsed.year, 2023)
        self.assertEqual(parsed.month, 12)
        self.assertEqual(parsed.day, 1)
        self.assertEqual(parsed.hour, 10)
        self.assertEqual(parsed.minute, 0)
        
        # Test format without microseconds
        iso_str = '2023-12-01T10:00:00Z'
        result = self.ereceipt._parse_eta_request_time(iso_str)
        parsed = fields.Datetime.from_string(result)
        self.assertEqual(parsed.year, 2023)
        
        # Test format with fewer microseconds
        iso_str = '2023-12-01T10:00:00.123Z'
        result = self.ereceipt._parse_eta_request_time(iso_str)
        parsed = fields.Datetime.from_string(result)
        self.assertEqual(parsed.year, 2023)


class TestEgyptEReceiptCronJobs(TransactionCase):
    
    def setUp(self):
        super().setUp()
        
        # Create test company
        self.company = self.env['res.company'].create({
            'name': 'Test Company',
            'vat': '123456789',
            'egypt_ereceipt_enabled': True,
            'l10n_eg_client_identifier': 'test_client_id',
            'l10n_eg_client_secret': 'test_client_secret',
        })
        
        # Create test POS config
        self.pos_config = self.env['pos.config'].create({
            'name': 'Test POS',
            'pos_serial': 'TEST123456',
            'pos_branch_code': '01',
        })
        
        # Create test POS session
        self.pos_session = self.env['pos.session'].create({
            'config_id': self.pos_config.id,
            'user_id': self.env.user.id,
            'state': 'opened',
        })
        
        # Create test product
        self.product = self.env['product.product'].create({
            'name': 'Test Product',
            'list_price': 100.0,
        })
    
    def test_cron_sync_pos_receipts_no_pending(self):
        """Test cron sync when no pending receipts"""
        # Create some orders without e-receipts
        order1 = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'amount_tax': 0.0,
            'amount_total': 100.0,
            'amount_paid': 100.0,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': self.product.id,
                'qty': 1.0,
                'price_unit': 100.0,
                'price_subtotal': 100.0,
                'price_subtotal_incl': 100.0,
            })],
        })
        
        order2 = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'amount_tax': 0.0,
            'amount_total': 100.0,
            'amount_paid': 100.0,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': self.product.id,
                'qty': 2.0,
                'price_unit': 50.0,
                'price_subtotal': 100.0,
                'price_subtotal_incl': 100.0,
            })],
        })
        
        # Test cron job
        with patch.object(self.env['egypt.ereceipt'], 'create') as mock_create:
            self.env['egypt.ereceipt'].cron_sync_pos_receipts()
            
            # Verify e-receipts were created for orders
            self.assertEqual(mock_create.call_count, 2)
            
            # Verify create calls
            create_calls = mock_create.call_args_list
            self.assertEqual(create_calls[0][0][0]['pos_order_id'], order1.id)
            self.assertEqual(create_calls[1][0][0]['pos_order_id'], order2.id)
    
    def test_cron_sync_pos_receipts_with_pending(self):
        """Test cron sync when there are pending receipts"""
        # Create pending receipt
        pending_ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.env['pos.order'].create({
                'session_id': self.pos_session.id,
                'company_id': self.company.id,
                'amount_tax': 0.0,
                'amount_total': 100.0,
                'amount_paid': 100.0,
                'amount_return': 0.0,
                'lines': [(0, 0, {
                    'product_id': self.product.id,
                    'qty': 1.0,
                    'price_unit': 100.0,
                    'price_subtotal': 100.0,
                    'price_subtotal_incl': 100.0,
                })],
            }).id,
            'company_id': self.company.id,
            'state': 'retry',
        })
        
        # Create another order without e-receipt
        order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'amount_tax': 0.0,
            'amount_total': 100.0,
            'amount_paid': 100.0,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': self.product.id,
                'qty': 1.0,
                'price_unit': 100.0,
                'price_subtotal': 100.0,
                'price_subtotal_incl': 100.0,
            })],
        })
        
        # Test cron job (should skip due to pending)
        with patch.object(self.env['egypt.ereceipt'], 'create') as mock_create:
            self.env['egypt.ereceipt'].cron_sync_pos_receipts()
            
            # Verify no new e-receipts were created
            mock_create.assert_not_called()
    
    def test_cron_sync_pos_receipts_existing_ereceipt(self):
        """Test cron sync skips orders with existing e-receipts"""
        # Create order with existing e-receipt
        order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'amount_tax': 0.0,
            'amount_total': 100.0,
            'amount_paid': 100.0,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': self.product.id,
                'qty': 1.0,
                'price_unit': 100.0,
                'price_subtotal': 100.0,
                'price_subtotal_incl': 100.0,
            })],
        })
        
        existing_ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': order.id,
            'company_id': self.company.id,
        })
        
        # Test cron job
        with patch.object(self.env['egypt.ereceipt'], 'create') as mock_create:
            self.env['egypt.ereceipt'].cron_sync_pos_receipts()
            
            # Verify no new e-receipt was created
            mock_create.assert_not_called()
    
    def test_cron_sync_pos_receipts_return_orders(self):
        """Test cron sync with return orders"""
        # Create original order
        original_order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'amount_tax': 0.0,
            'amount_total': 100.0,
            'amount_paid': 100.0,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': self.product.id,
                'qty': 1.0,
                'price_unit': 100.0,
                'price_subtotal': 100.0,
                'price_subtotal_incl': 100.0,
            })],
        })
        
        # Create e-receipt for original order
        original_ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': original_order.id,
            'company_id': self.company.id,
            'state': 'accepted',
            'uuid': 'test-uuid-123',
        })
        
        # Create return order
        return_order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'amount_tax': 0.0,
            'amount_total': -100.0,
            'amount_paid': 0.0,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': self.product.id,
                'qty': -1.0,
                'price_unit': 100.0,
                'price_subtotal': -100.0,
                'price_subtotal_incl': -100.0,
                'refunded_orderline_id': original_order.lines[0].id,
            })],
        })
        
        # Test cron job
        with patch.object(self.env['egypt.ereceipt'], 'create') as mock_create:
            self.env['egypt.ereceipt'].cron_sync_pos_receipts()
            
            # Verify e-receipt was created with reference UUID
            mock_create.assert_called_once()
            create_args = mock_create.call_args[0][0]
            self.assertEqual(create_args['pos_order_id'], return_order.id)
            self.assertEqual(create_args['reference_uuid'], 'test-uuid-123')
    
    def test_cron_get_status(self):
        """Test cron job to get ETA status"""
        # Create accepted receipts with undetected status
        ereceipt1 = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.env['pos.order'].create({
                'session_id': self.pos_session.id,
                'company_id': self.company.id,
                'amount_tax': 0.0,
                'amount_total': 100.0,
                'amount_paid': 100.0,
                'amount_return': 0.0,
                'lines': [(0, 0, {
                    'product_id': self.product.id,
                    'qty': 1.0,
                    'price_unit': 100.0,
                    'price_subtotal': 100.0,
                    'price_subtotal_incl': 100.0,
                })],
            }).id,
            'company_id': self.company.id,
            'state': 'accepted',
            'eta_status': 'undetected',
            'uuid': 'test-uuid-1',
        })
        
        ereceipt2 = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.env['pos.order'].create({
                'session_id': self.pos_session.id,
                'company_id': self.company.id,
                'amount_tax': 0.0,
                'amount_total': 100.0,
                'amount_paid': 100.0,
                'amount_return': 0.0,
                'lines': [(0, 0, {
                    'product_id': self.product.id,
                    'qty': 1.0,
                    'price_unit': 100.0,
                    'price_subtotal': 100.0,
                    'price_subtotal_incl': 100.0,
                })],
            }).id,
            'company_id': self.company.id,
            'state': 'accepted',
            'eta_status': 'valid',  # Already has status
            'uuid': 'test-uuid-2',
        })
        
        # Test cron job
        with patch.object(ereceipt1, '_get_eta_receipt_details') as mock_details:
            self.env['egypt.ereceipt'].cron_get_status()
            
            # Verify details were called only for undetected receipt
            mock_details.assert_called_once()
    
    def test_cron_retry_failed_submissions(self):
        """Test cron job to retry failed submissions"""
        from datetime import datetime, timedelta
        
        # Create retry receipts
        past_time = datetime.now() - timedelta(minutes=1)
        future_time = datetime.now() + timedelta(minutes=1)
        
        retry_ereceipt1 = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.env['pos.order'].create({
                'session_id': self.pos_session.id,
                'company_id': self.company.id,
                'amount_tax': 0.0,
                'amount_total': 100.0,
                'amount_paid': 100.0,
                'amount_return': 0.0,
                'lines': [(0, 0, {
                    'product_id': self.product.id,
                    'qty': 1.0,
                    'price_unit': 100.0,
                    'price_subtotal': 100.0,
                    'price_subtotal_incl': 100.0,
                })],
            }).id,
            'company_id': self.company.id,
            'state': 'retry',
            'next_retry_date': past_time,  # Should retry
            'retry_count': 1,
        })
        
        retry_ereceipt2 = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.env['pos.order'].create({
                'session_id': self.pos_session.id,
                'company_id': self.company.id,
                'amount_tax': 0.0,
                'amount_total': 100.0,
                'amount_paid': 100.0,
                'amount_return': 0.0,
                'lines': [(0, 0, {
                    'product_id': self.product.id,
                    'qty': 1.0,
                    'price_unit': 100.0,
                    'price_subtotal': 100.0,
                    'price_subtotal_incl': 100.0,
                })],
            }).id,
            'company_id': self.company.id,
            'state': 'retry',
            'next_retry_date': future_time,  # Should not retry yet
            'retry_count': 1,
        })
        
        retry_ereceipt3 = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.env['pos.order'].create({
                'session_id': self.pos_session.id,
                'company_id': self.company.id,
                'amount_tax': 0.0,
                'amount_total': 100.0,
                'amount_paid': 100.0,
                'amount_return': 0.0,
                'lines': [(0, 0, {
                    'product_id': self.product.id,
                    'qty': 1.0,
                    'price_unit': 100.0,
                    'price_subtotal': 100.0,
                    'price_subtotal_incl': 100.0,
                })],
            }).id,
            'company_id': self.company.id,
            'state': 'retry',
            'next_retry_date': past_time,
            'retry_count': 3,  # Max retries reached
        })
        
        # Test cron job
        with patch.object(retry_ereceipt1, '_submit_to_api') as mock_submit1, \
             patch.object(retry_ereceipt2, '_submit_to_api') as mock_submit2, \
             patch.object(retry_ereceipt3, '_submit_to_api') as mock_submit3:
            
            self.env['egypt.ereceipt'].cron_retry_failed_submissions()
            
            # Verify submission was called
            # We check both the direct call and call via with_delay mock
            self.assertTrue(mock_submit1.called or retry_ereceipt1.with_delay()._submit_to_api.called)
            mock_submit2.assert_not_called()  # Future time
            mock_submit3.assert_not_called()  # Max retries reached


class TestEgyptEReceiptJSONSerialization(TransactionCase):
    
    def setUp(self):
        super().setUp()
        
        # Create minimal test data
        self.company = self.env['res.company'].create({
            'name': 'Test Company JSON %s' % self.env.user.id,
            'vat': '123456789',
            'egypt_ereceipt_enabled': True,
        })
        
        # Get tax group
        self.tax_group = self.env['account.tax.group'].search([('company_id', '=', self.company.id)], limit=1)
        if not self.tax_group:
            self.tax_group = self.env['account.tax.group'].search([], limit=1)
        if not self.tax_group:
            self.tax_group = self.env['account.tax.group'].create({'name': 'Test Tax Group JSON %s' % self.company.id, 'company_id': self.company.id})

        self.pos_config = self.env['pos.config'].create({
            'name': 'Test POS',
            'pos_serial': 'TEST123456',
            'pos_branch_code': '01',
        })
        
        self.pos_session = self.env['pos.session'].create({
            'config_id': self.pos_config.id,
            'user_id': self.env.user.id,
            'state': 'opened',
        })
        
        self.product = self.env['product.product'].create({
            'name': 'Test Product',
            'list_price': 100.0,
        })
        
        self.pos_order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'amount_tax': 0.0,
            'amount_total': 100.0,
            'amount_paid': 100.0,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': self.product.id,
                'qty': 1.0,
                'price_unit': 100.0,
                'price_subtotal': 100.0,
                'price_subtotal_incl': 100.0,
            })],
        })
        
        self.ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.pos_order.id,
            'company_id': self.company.id,
        })
        
        # Get tax group
        self.tax_group = self.env['account.tax.group'].search([('company_id', '=', self.company.id)], limit=1)
        if not self.tax_group:
            self.tax_group = self.env['account.tax.group'].search([], limit=1)
        if not self.tax_group:
            self.tax_group = self.env['account.tax.group'].create({'name': 'Test Tax Group', 'company_id': self.company.id})
    
    def test_json_serialization_string(self):
        """Test JSON serialization of string values"""
        result = self.ereceipt._serialize_json_receipt('test_string')
        self.assertEqual(result, '"test_string"')
        
        result = self.ereceipt._serialize_json_receipt('')
        self.assertEqual(result, '""')
    
    def test_json_serialization_number(self):
        """Test JSON serialization of numeric values"""
        result = self.ereceipt._serialize_json_receipt(123)
        self.assertEqual(result, '"123"')
        
        result = self.ereceipt._serialize_json_receipt(123.45)
        self.assertEqual(result, '"123.45"')
    
    def test_json_serialization_boolean(self):
        """Test JSON serialization of boolean values"""
        result = self.ereceipt._serialize_json_receipt(True)
        self.assertEqual(result, '"True"')
        
        result = self.ereceipt._serialize_json_receipt(False)
        self.assertEqual(result, '"False"')
    
    def test_json_serialization_none(self):
        """Test JSON serialization of None values"""
        result = self.ereceipt._serialize_json_receipt(None)
        self.assertEqual(result, '""')
    
    def test_json_serialization_object(self):
        """Test JSON serialization of object/dictionary"""
        test_obj = {
            'field1': 'value1',
            'field2': 123,
            'nested': {
                'subfield': 'subvalue'
            }
        }
        
        result = self.ereceipt._serialize_json_receipt(test_obj)
        
        # Verify field names are uppercase
        self.assertIn('"FIELD1"', result)
        self.assertIn('"FIELD2"', result)
        self.assertIn('"NESTED"', result)
        self.assertIn('"SUBFIELD"', result)
        
        # Verify values are quoted
        self.assertIn('"value1"', result)
        self.assertIn('"123"', result)
        self.assertIn('"subvalue"', result)
    
    def test_json_serialization_array(self):
        """Test JSON serialization of arrays"""
        test_obj = {
            'items': [
                {'name': 'item1'},
                {'name': 'item2'}
            ]
        }
        
        result = self.ereceipt._serialize_json_receipt(test_obj)
        
        # Verify array property name is included
        self.assertIn('"ITEMS"', result)
        
        # Verify array property name is repeated for each item
        items_count = result.count('"ITEMS"')
        self.assertGreaterEqual(items_count, 3)  # Once for property, twice for items
    
    def test_tax_data_calculation(self):
        """Test tax data calculation for receipt lines"""
        # Create tax
        tax = self.env['account.tax'].create({
            'name': 'VAT 14%% %s %s' % (self.company.id, ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))),
            'amount': 14.0,
            'type_tax_use': 'sale',
            'l10n_eg_eta_code': 't1_v009',
            'company_id': self.company.id,
            'tax_group_id': self.tax_group.id,
            'country_id': self.env.ref('base.eg').id,
        })
        
        # Create line with tax
        line = self.env['pos.order.line'].create({
            'order_id': self.pos_order.id,
            'product_id': self.product.id,
            'qty': 2.0,
            'price_unit': 100.0,
            'price_subtotal': 200.0,
            'price_subtotal_incl': 228.0,
            'tax_ids': [(6, 0, [tax.id])],
        })
        
        # Test tax data calculation
        tax_data = self.ereceipt._get_tax_data(line)
        
        self.assertEqual(len(tax_data), 1)
        tax_info = tax_data[0]
        
        self.assertEqual(tax_info['taxType'], 'T1')
        self.assertEqual(tax_info['subType'], 'V009')
        self.assertEqual(tax_info['rate'], 14.0)
        self.assertEqual(tax_info['amount'], 28.0)  # 200 * 14%
    
    def test_order_tax_totals_calculation(self):
        """Test order-level tax totals calculation"""
        # Create taxes
        tax1 = self.env['account.tax'].create({
            'name': 'VAT 14%% Totals %s' % self.company.id,
            'amount': 14.0,
            'type_tax_use': 'sale',
            'l10n_eg_eta_code': 't1_v009',
            'company_id': self.company.id,
            'tax_group_id': self.tax_group.id,
            'country_id': self.env.ref('base.eg').id,
        })
        
        tax2 = self.env['account.tax'].create({
            'name': 'VAT 5%% Totals %s' % self.company.id,
            'amount': 5.0,
            'type_tax_use': 'sale',
            'l10n_eg_eta_code': 't1_v005',
            'company_id': self.company.id,
            'tax_group_id': self.tax_group.id,
            'country_id': self.env.ref('base.eg').id,
        })
        
        # Create lines with different taxes
        line1 = self.env['pos.order.line'].create({
            'order_id': self.pos_order.id,
            'product_id': self.product.id,
            'qty': 1.0,
            'price_unit': 100.0,
            'price_subtotal': 100.0,
            'price_subtotal_incl': 114.0,
            'tax_ids': [(6, 0, [tax1.id])],
        })
        
        line2 = self.env['pos.order.line'].create({
            'order_id': self.pos_order.id,
            'product_id': self.product.id,
            'qty': 1.0,
            'price_unit': 200.0,
            'price_subtotal': 200.0,
            'price_subtotal_incl': 210.0,
            'tax_ids': [(6, 0, [tax2.id])],
        })
        
        # Test tax totals calculation
        tax_totals = self.ereceipt._get_order_tax_totals(self.pos_order)
        
        # Should group by tax type (T1)
        self.assertEqual(len(tax_totals), 1)
        tax_total = tax_totals[0]
        
        self.assertEqual(tax_total['taxType'], 'T1')
        self.assertEqual(tax_total['amount'], 24.0)  # 14 + 10
    
    def test_tax_data_without_tax(self):
        """Test tax data calculation without tax"""
        # Create line without tax
        line = self.env['pos.order.line'].create({
            'order_id': self.pos_order.id,
            'product_id': self.product.id,
            'qty': 1.0,
            'price_unit': 100.0,
            'price_subtotal': 100.0,
            'price_subtotal_incl': 100.0,
        })
        
        # Test tax data calculation
        tax_data = self.ereceipt._get_tax_data(line)
        
        self.assertEqual(len(tax_data), 0)
    
    def test_tax_data_with_zero_tax(self):
        """Test tax data calculation with zero tax"""
        # Create zero tax
        tax = self.env['account.tax'].create({
            'name': 'Zero Tax %s %s' % (self.company.id, ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))),
            'amount': 0.0,
            'type_tax_use': 'sale',
            'l10n_eg_eta_code': 't1_v004',
            'company_id': self.company.id,
            'tax_group_id': self.tax_group.id,
            'country_id': self.env.ref('base.eg').id,
        })
        
        # Create line with zero tax
        line = self.env['pos.order.line'].create({
            'order_id': self.pos_order.id,
            'product_id': self.product.id,
            'qty': 1.0,
            'price_unit': 100.0,
            'price_subtotal': 100.0,
            'price_subtotal_incl': 100.0,
            'tax_ids': [(6, 0, [tax.id])],
        })
        
        # Test tax data calculation
        tax_data = self.ereceipt._get_tax_data(line)
        
        # Zero tax should be ignored
        self.assertEqual(len(tax_data), 0)


if __name__ == '__main__':
    unittest.main()