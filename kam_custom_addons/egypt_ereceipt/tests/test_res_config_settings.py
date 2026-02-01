import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo.tests.common import TransactionCase


class TestResConfigSettings(TransactionCase):
    
    def setUp(self):
        super().setUp()
        
        # Create test company
        self.company = self.env['res.company'].create({
            'name': 'Test Company',
            'vat': '123456789',
        })
        
        # Create test POS config
        self.pos_config = self.env['pos.config'].create({
            'name': 'Test POS',
        })
        
        # Create settings record
        self.settings = self.env['res.config.settings'].create({
            'company_id': self.company.id,
            'pos_config_id': self.pos_config.id,
        })
    
    def test_ereceipt_enabled_field(self):
        """Test egypt_ereceipt_enabled field"""
        # Test default value
        self.assertFalse(self.settings.egypt_ereceipt_enabled)
        
        # Test setting value
        self.settings.egypt_ereceipt_enabled = True
        self.assertTrue(self.settings.egypt_ereceipt_enabled)
        
        # Test related field on company
        self.company.egypt_ereceipt_enabled = True
        settings = self.env['res.config.settings'].create({
            'company_id': self.company.id,
        })
        self.assertTrue(settings.egypt_ereceipt_enabled)
    
    def test_pos_config_fields_relation(self):
        """Test POS config fields relation"""
        # Set values on POS config
        self.pos_config.pos_client_code = 'test_client'
        self.pos_config.pos_secret_code = 'test_secret'
        self.pos_config.pos_serial = 'TEST123456'
        self.pos_config.pos_branch_code = '01'
        self.pos_config.pos_os_version = 'windows'
        self.pos_config.pos_model_framework = '1'
        self.pos_config.pre_shared_key = 'test_key'
        
        # Test related fields on settings
        self.assertEqual(self.settings.pos_client_code, 'test_client')
        self.assertEqual(self.settings.pos_secret_code, 'test_secret')
        self.assertEqual(self.settings.pos_serial, 'TEST123456')
        self.assertEqual(self.settings.pos_branch_code, '01')
        self.assertEqual(self.settings.pos_os_version, 'windows')
        self.assertEqual(self.settings.pos_model_framework, '1')
        self.assertEqual(self.settings.pre_shared_key, 'test_key')
    
    def test_settings_modify_company(self):
        """Test settings can modify company fields"""
        # Enable e-receipt via settings
        self.settings.egypt_ereceipt_enabled = True
        self.settings.execute()
        
        # Verify company is updated
        self.company.invalidate_recordset()
        self.assertTrue(self.company.egypt_ereceipt_enabled)
    
    def test_settings_modify_pos_config(self):
        """Test settings can modify POS config fields"""
        # Set values via settings
        self.settings.pos_client_code = 'new_client'
        self.settings.pos_secret_code = 'new_secret'
        self.settings.pos_serial = 'NEW123456'
        self.settings.pos_branch_code = '02'
        self.settings.execute()
        
        # Verify POS config is updated
        self.pos_config.invalidate_recordset()
        self.assertEqual(self.pos_config.pos_client_code, 'new_client')
        self.assertEqual(self.pos_config.pos_secret_code, 'new_secret')
        self.assertEqual(self.pos_config.pos_serial, 'NEW123456')
        self.assertEqual(self.pos_config.pos_branch_code, '02')
    
    def test_settings_default_values(self):
        """Test settings default values"""
        # Create new settings without explicit values
        new_settings = self.env['res.config.settings'].create({
            'company_id': self.company.id,
            'pos_config_id': self.pos_config.id,
        })
        
        # Test defaults
        self.assertFalse(new_settings.egypt_ereceipt_enabled)
        self.assertFalse(new_settings.pos_client_code)
        self.assertFalse(new_settings.pos_secret_code)
        self.assertFalse(new_settings.pos_serial)
        self.assertFalse(new_settings.pos_branch_code)
        self.assertEqual(new_settings.pos_os_version, 'windows')
        self.assertEqual(new_settings.pos_model_framework, '1')
        self.assertEqual(new_settings.pre_shared_key, '')


class TestResCompany(TransactionCase):
    
    def setUp(self):
        super().setUp()
        
        # Create test company
        self.company = self.env['res.company'].create({
            'name': 'Test Company',
            'vat': '123456789',
        })
    
    def test_activity_code_field(self):
        """Test activity_code field"""
        # Test default value
        self.assertFalse(self.company.activity_code)
        
        # Test setting value
        self.company.activity_code = '4771'
        self.assertEqual(self.company.activity_code, '4771')
        
        # Test field is searchable
        companies = self.env['res.company'].search([
            ('activity_code', '=', '4771')
        ])
        self.assertIn(self.company.id, companies.ids)
    
    def test_ereceipt_enabled_field(self):
        """Test egypt_ereceipt_enabled field"""
        # Test default value
        self.assertFalse(self.company.egypt_ereceipt_enabled)
        
        # Test setting value
        self.company.egypt_ereceipt_enabled = True
        self.assertTrue(self.company.egypt_ereceipt_enabled)
        
        # Test field is searchable
        companies = self.env['res.company'].search([
            ('egypt_ereceipt_enabled', '=', True)
        ])
        self.assertIn(self.company.id, companies.ids)
    
    def test_company_fields_in_ereceipt_context(self):
        """Test company fields are used in e-receipt context"""
        # Set required fields
        self.company.write({
            'egypt_ereceipt_enabled': True,
            'activity_code': '4771',
            'l10n_eg_client_identifier': 'test_client_id',
            'l10n_eg_client_secret': 'test_client_secret',
        })
        
        # Create test e-receipt to verify fields are accessible
        pos_config = self.env['pos.config'].create({
            'name': 'Test POS',
            'pos_serial': 'TEST123456',
            'pos_branch_code': '01',
        })
        
        pos_session = self.env['pos.session'].create({
            'config_id': pos_config.id,
            'user_id': self.env.user.id,
            'state': 'opened',
        })
        
        product = self.env['product.product'].create({
            'name': 'Test Product',
            'list_price': 100.0,
        })
        
        pos_order = self.env['pos.order'].create({
            'session_id': pos_session.id,
            'company_id': self.company.id,
            'amount_tax': 0.0,
            'amount_total': 100.0,
            'amount_paid': 100.0,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': product.id,
                'qty': 1.0,
                'price_unit': 100.0,
                'price_subtotal': 100.0,
                'price_subtotal_incl': 100.0,
            })],
        })
        
        ereceipt = self.env['egypt.ereceipt'].create({
            'pos_order_id': pos_order.id,
            'company_id': self.company.id,
        })
        
        # Verify company fields are accessible through ereceipt
        self.assertEqual(ereceipt.company_id.id, self.company.id)
        self.assertEqual(ereceipt.company_id.activity_code, '4771')
        self.assertEqual(ereceipt.company_id.egypt_ereceipt_enabled, True)


class TestPosConfig(TransactionCase):
    
    def setUp(self):
        super().setUp()
        
        # Create test POS config
        self.pos_config = self.env['pos.config'].create({
            'name': 'Test POS',
        })
    
    def test_pos_config_fields(self):
        """Test POS config e-receipt fields"""
        # Test default values
        self.assertFalse(self.pos_config.pos_client_code)
        self.assertFalse(self.pos_config.pos_secret_code)
        self.assertFalse(self.pos_config.pos_serial)
        self.assertFalse(self.pos_config.pos_branch_code)
        self.assertEqual(self.pos_config.pos_os_version, 'windows')
        self.assertEqual(self.pos_config.pos_model_framework, '1')
        self.assertEqual(self.pos_config.pre_shared_key, '')
        
        # Test setting values
        self.pos_config.write({
            'pos_client_code': 'test_client',
            'pos_secret_code': 'test_secret',
            'pos_serial': 'TEST123456',
            'pos_branch_code': '01',
            'pos_os_version': 'custom_os',
            'pos_model_framework': '2',
            'pre_shared_key': 'test_key',
        })
        
        # Verify values
        self.assertEqual(self.pos_config.pos_client_code, 'test_client')
        self.assertEqual(self.pos_config.pos_secret_code, 'test_secret')
        self.assertEqual(self.pos_config.pos_serial, 'TEST123456')
        self.assertEqual(self.pos_config.pos_branch_code, '01')
        self.assertEqual(self.pos_config.pos_os_version, 'custom_os')
        self.assertEqual(self.pos_config.pos_model_framework, '2')
        self.assertEqual(self.pos_config.pre_shared_key, 'test_key')
    
    def test_access_token_fields(self):
        """Test access token fields"""
        # Test default values
        self.assertFalse(self.pos_config.access_token)
        self.assertFalse(self.pos_config.token_expiration_date)
        
        # Test setting values
        from datetime import datetime, timedelta
        future_time = datetime.now() + timedelta(hours=1)
        
        self.pos_config.write({
            'access_token': 'test_token_12345',
            'token_expiration_date': future_time,
        })
        
        # Verify values
        self.assertEqual(self.pos_config.access_token, 'test_token_12345')
        self.assertEqual(self.pos_config.token_expiration_date, future_time)
    
    def test_pos_config_fields_search(self):
        """Test POS config fields are searchable"""
        # Set values
        self.pos_config.write({
            'pos_serial': 'SEARCH123',
            'pos_branch_code': '99',
        })
        
        # Test search by serial
        configs = self.env['pos.config'].search([
            ('pos_serial', '=', 'SEARCH123')
        ])
        self.assertIn(self.pos_config.id, configs.ids)
        
        # Test search by branch code
        configs = self.env['pos.config'].search([
            ('pos_branch_code', '=', '99')
        ])
        self.assertIn(self.pos_config.id, configs.ids)
    
    def test_pos_config_required_for_ereceipt(self):
        """Test POS config is required for e-receipt functionality"""
        # Create company with e-receipt enabled
        company = self.env['res.company'].create({
            'name': 'Test Company',
            'egypt_ereceipt_enabled': True,
        })
        
        # Create POS config without serial
        pos_config = self.env['pos.config'].create({
            'name': 'Test POS',
        })
        
        # Create POS order
        pos_session = self.env['pos.session'].create({
            'config_id': pos_config.id,
            'user_id': self.env.user.id,
            'state': 'opened',
        })
        
        product = self.env['product.product'].create({
            'name': 'Test Product',
            'list_price': 100.0,
        })
        
        pos_order = self.env['pos.order'].create({
            'session_id': pos_session.id,
            'company_id': company.id,
            'amount_tax': 0.0,
            'amount_total': 100.0,
            'amount_paid': 100.0,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': product.id,
                'qty': 1.0,
                'price_unit': 100.0,
                'price_subtotal': 100.0,
                'price_subtotal_incl': 100.0,
            })],
        })
        
        # Test that e-receipt submission is skipped without serial
        with patch('odoo.addons.egypt_ereceipt.models.pos_order.PosOrder._submit_ereceipt') as mock_submit:
            pos_order.action_pos_order_paid()
            # Should not be called because pos_serial is missing
            mock_submit.assert_not_called()
        
        # Set serial and test again
        pos_config.pos_serial = 'TEST123456'
        with patch('odoo.addons.egypt_ereceipt.models.pos_order.PosOrder._submit_ereceipt') as mock_submit:
            pos_order.action_pos_order_paid()
            # Should be called now
            mock_submit.assert_called_once()


if __name__ == '__main__':
    unittest.main()