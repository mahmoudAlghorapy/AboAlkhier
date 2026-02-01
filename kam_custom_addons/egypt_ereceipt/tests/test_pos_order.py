import unittest
from unittest.mock import patch, MagicMock

from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError


class TestPosOrderEReceiptIntegration(TransactionCase):
    
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
        
        # Create test POS order
        self.pos_order = self.env['pos.order'].create({
            'partner_id': False,
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
    
    def test_pos_order_ereceipt_fields(self):
        """Test POS order e-receipt related fields"""
        # Test initial values
        self.assertEqual(len(self.pos_order.ereceipt_ids), 0)
        self.assertEqual(self.pos_order.ereceipt_status, 'none')
        self.assertEqual(self.pos_order.receipt_link, '')
    
    def test_ereceipt_status_computation(self):
        """Test e-receipt status computation"""
        # Create e-receipt in different states and test status computation
        
        # Test with draft receipt
        draft_ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.pos_order.id,
            'company_id': self.company.id,
            'state': 'draft',
        })
        self.pos_order._compute_ereceipt_status()
        self.assertEqual(self.pos_order.ereceipt_status, 'draft')  # Draft maps to draft
        
        # Test with submitted receipt
        draft_ereceipt.state = 'submitted'
        self.pos_order._compute_ereceipt_status()
        self.assertEqual(self.pos_order.ereceipt_status, 'submitted')
        
        # Test with accepted receipt
        draft_ereceipt.state = 'accepted'
        self.pos_order._compute_ereceipt_status()
        self.assertEqual(self.pos_order.ereceipt_status, 'accepted')
        
        # Test with rejected receipt
        draft_ereceipt.state = 'rejected'
        self.pos_order._compute_ereceipt_status()
        self.assertEqual(self.pos_order.ereceipt_status, 'rejected')
        
        # Test with error receipt
        draft_ereceipt.state = 'error'
        self.pos_order._compute_ereceipt_status()
        self.assertEqual(self.pos_order.ereceipt_status, 'error')
    
    def test_receipt_link_computation(self):
        """Test receipt link computation"""
        # Test without e-receipt
        self.pos_order._compute_receipt_link()
        self.assertEqual(self.pos_order.receipt_link, '')
        
        # Test with e-receipt but not accepted
        draft_ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.pos_order.id,
            'company_id': self.company.id,
            'state': 'draft',
        })
        self.pos_order._compute_receipt_link()
        self.assertEqual(self.pos_order.receipt_link, '')
        
        # Test with accepted e-receipt
        draft_ereceipt.state = 'accepted'
        draft_ereceipt.uuid = 'test-uuid-123'
        self.pos_order._compute_receipt_link()
        
        expected_link = f'https://invoicing.eta.gov.eg/receipts/search/test-uuid-123/share/{self.pos_order.date_order.strftime("%Y-%m-%dT%H:%M:%SZ")}'
        self.assertEqual(self.pos_order.receipt_link, expected_link)
    
    def test_ereceipt_submission_on_order_paid(self):
        """Test e-receipt submission when order is paid"""
        # Enable e-receipt for company
        self.company.egypt_ereceipt_enabled = True
        
        # Mock the submission method
        with patch('odoo.addons.egypt_ereceipt.models.pos_order.PosOrder._submit_ereceipt') as mock_submit:
            # Call action_pos_order_paid
            self.pos_order.action_pos_order_paid()
            
            # Verify submission was called
            mock_submit.assert_called_once()
    
    def test_no_ereceipt_submission_when_disabled(self):
        """Test no e-receipt submission when disabled"""
        # Disable e-receipt for company
        self.company.egypt_ereceipt_enabled = False
        
        # Mock the submission method
        with patch('odoo.addons.egypt_ereceipt.models.pos_order.PosOrder._submit_ereceipt') as mock_submit:
            # Call action_pos_order_paid
            self.pos_order.action_pos_order_paid()
            
            # Verify submission was not called
            mock_submit.assert_not_called()
    
    def test_no_ereceipt_submission_without_serial(self):
        """Test no e-receipt submission without POS serial"""
        # Enable e-receipt but remove serial
        self.company.egypt_ereceipt_enabled = True
        self.pos_config.pos_serial = False
        
        # Mock the submission method
        with patch('odoo.addons.egypt_ereceipt.models.pos_order.PosOrder._submit_ereceipt') as mock_submit:
            # Call action_pos_order_paid
            self.pos_order.action_pos_order_paid()
            
            # Verify submission was not called
            mock_submit.assert_not_called()
    
    def test_ereceipt_submission_method(self):
        """Test _submit_ereceipt method"""
        # Test submission for order without existing e-receipt
        with patch('odoo.addons.egypt_ereceipt.models.egypt_ereceipt.EgyptEReceipt.create') as mock_create:
            mock_ereceipt = MagicMock()
            mock_ereceipt.with_delay.return_value = mock_ereceipt
            mock_create.return_value = mock_ereceipt
            
            self.pos_order._submit_ereceipt()
            
            # Verify e-receipt was created
            mock_create.assert_called_once()
            create_args = mock_create.call_args[0][0]
            self.assertEqual(create_args['pos_order_id'], self.pos_order.id)
            self.assertEqual(create_args['company_id'], self.company.id)
            
            # Verify submission was called
            # We check both the direct call and call via with_delay mock
            self.assertTrue(mock_ereceipt._submit_to_api.called or mock_ereceipt.with_delay()._submit_to_api.called)
    
    def test_ereceipt_submission_method_skip_existing(self):
        """Test _submit_ereceipt method skips existing e-receipt"""
        # Create existing e-receipt
        existing_ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.pos_order.id,
            'company_id': self.company.id,
        })
        
        # Mock create to track if it's called
        with patch('odoo.addons.egypt_ereceipt.models.egypt_ereceipt.EgyptEReceipt.create') as mock_create:
            self.pos_order._submit_ereceipt()
            
            # Verify create was not called (existing receipt found)
            mock_create.assert_not_called()
    
    def test_manual_ereceipt_submission_action(self):
        """Test manual e-receipt submission action"""
        # Test action on order without e-receipt
        with patch('odoo.addons.egypt_ereceipt.models.pos_order.PosOrder._submit_ereceipt') as mock_submit:
            self.pos_order.action_submit_ereceipt()
            mock_submit.assert_called_once()
    
    def test_manual_ereceipt_submission_action_existing(self):
        """Test manual e-receipt submission action with existing e-receipt"""
        # Create existing e-receipt
        existing_ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.pos_order.id,
            'company_id': self.company.id,
            'state': 'draft',
        })
        
        # Test action calls receipt's action_submit_receipt
        with patch('odoo.addons.egypt_ereceipt.models.egypt_ereceipt.EgyptEReceipt.action_submit_receipt') as mock_action:
            self.pos_order.action_submit_ereceipt()
            mock_action.assert_called_once()
    
    def test_ereceipt_submission_with_delay(self):
        """Test e-receipt submission with delay"""
        # Test submission with with_delay (should not fail)
        with patch('odoo.addons.egypt_ereceipt.models.egypt_ereceipt.EgyptEReceipt.create') as mock_create:
            mock_ereceipt = MagicMock()
            mock_ereceipt.with_delay.return_value = mock_ereceipt
            mock_create.return_value = mock_ereceipt
            
            self.pos_order._submit_ereceipt()
            
            # Verify with_delay was called
            mock_ereceipt.with_delay.assert_called_once()
    
    def test_ereceipt_submission_fallback(self):
        """Test e-receipt submission fallback when with_delay fails"""
        # Create mock that raises exception on with_delay
        mock_ereceipt = MagicMock()
        mock_ereceipt.with_delay.side_effect = Exception("Delay failed")
        
        with patch('odoo.addons.egypt_ereceipt.models.egypt_ereceipt.EgyptEReceipt.create') as mock_create:
            mock_create.return_value = mock_ereceipt
            
            # Should not raise exception due to fallback
            self.pos_order._submit_ereceipt()
            
            # Verify fallback submission was called
            mock_ereceipt._submit_to_api.assert_called_once()
    
    def test_multiple_ereceipts_status_priority(self):
        """Test e-receipt status with multiple receipts"""
        # Create multiple e-receipts in different states
        draft_ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.pos_order.id,
            'company_id': self.company.id,
            'state': 'draft',
        })
        
        accepted_ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.pos_order.id,
            'company_id': self.company.id,
            'state': 'accepted',
        })
        
        # Status should be based on most recent (first) receipt
        self.pos_order._compute_ereceipt_status()
        self.assertEqual(self.pos_order.ereceipt_status, 'draft')  # First receipt is draft
        
        # Delete first receipt and test again
        draft_ereceipt.unlink()
        self.pos_order._compute_ereceipt_status()
        self.assertEqual(self.pos_order.ereceipt_status, 'accepted')  # Now first is accepted
    
    def test_ereceipt_ids_relationship(self):
        """Test ereceipt_ids relationship"""
        # Create e-receipt
        ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.pos_order.id,
            'company_id': self.company.id,
        })
        
        # Test relationship
        self.assertIn(ereceipt.id, self.pos_order.ereceipt_ids.ids)
        self.assertEqual(ereceipt.pos_order_id.id, self.pos_order.id)
        
        # Test cascade delete
        order_id = self.pos_order.id
        self.pos_order.unlink()
        
        # Verify e-receipt is also deleted
        found = self.env['egypt.ereceipt'].search([('pos_order_id', '=', order_id)])
        self.assertEqual(len(found), 0)
    
    def test_ereceipt_status_store(self):
        """Test ereceipt_status is stored properly"""
        # Create e-receipt
        ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.pos_order.id,
            'company_id': self.company.id,
            'state': 'submitted',
        })
        
        # Force recomputation
        self.pos_order._compute_ereceipt_status()
        
        # Verify status is stored
        self.assertEqual(self.pos_order.ereceipt_status, 'submitted')
        
        # Test database query
        orders = self.env['pos.order'].search([
            ('id', '=', self.pos_order.id),
            ('ereceipt_status', '=', 'submitted')
        ])
        self.assertEqual(len(orders), 1)
    
    def test_receipt_link_store(self):
        """Test receipt_link is stored properly"""
        # Create accepted e-receipt
        ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': self.pos_order.id,
            'company_id': self.company.id,
            'state': 'accepted',
            'uuid': 'test-uuid-123',
        })
        
        # Force recomputation
        self.pos_order._compute_receipt_link()
        
        # Verify link is stored
        expected_link = f'https://invoicing.eta.gov.eg/receipts/search/test-uuid-123/share/{self.pos_order.date_order.strftime("%Y-%m-%dT%H:%M:%SZ")}'
        self.assertEqual(self.pos_order.receipt_link, expected_link)
        
        # Test database query
        orders = self.env['pos.order'].search([
            ('id', '=', self.pos_order.id),
            ('receipt_link', '!=', '')
        ])
        self.assertEqual(len(orders), 1)


if __name__ == '__main__':
    unittest.main()