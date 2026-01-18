# -*- coding: utf-8 -*-
from odoo import models, fields, api
import xmlrpc.client
import logging

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Common Mixin for Enterprise Connection & External Reference
# ---------------------------------------------------------------------------
class POSIntegrationMixin(models.AbstractModel):
    _name = 'pos.integration.mixin'
    _description = 'POS Integration Mixin'

    @api.model
    def _get_enterprise_connection(self):
        """Return a dict with xmlrpc proxies and credentials for Enterprise DB."""
        config = self.env['ir.config_parameter'].sudo()
        url = config.get_param('pos_community_enterprise_integration.url')
        db = config.get_param('pos_community_enterprise_integration.db')
        username = config.get_param('pos_community_enterprise_integration.username')
        password = config.get_param('pos_community_enterprise_integration.password')

        if not all([url, db, username, password]):
            raise Exception("POS Integration: Enterprise connection parameters are not set correctly.")

        common = xmlrpc.client.ServerProxy('%s/xmlrpc/2/common' % url)
        uid = common.authenticate(db, username, password, {})
        if not uid:
            raise Exception("POS Integration: Authentication to Enterprise DB failed.")

        models_proxy = xmlrpc.client.ServerProxy('%s/xmlrpc/2/object' % url)

        return {
            'url': url,
            'db': db,
            'uid': uid,
            'password': password,
            'models': models_proxy,
        }

    def _rpc_search(self, model, domain, limit=1):
        conn = self._get_enterprise_connection()
        return conn['models'].execute_kw(
            conn['db'], conn['uid'], conn['password'],
            model, 'search', [domain], {'limit': limit}
        )

    def _rpc_search_id(self, model, domain):
        ids = self._rpc_search(model, domain, limit=1)
        return ids[0] if ids else False

    def _rpc_create(self, model, vals):
        """Create a record in Enterprise database."""
        conn = self._get_enterprise_connection()
        return conn['models'].execute_kw(
            conn['db'], conn['uid'], conn['password'],
            model, 'create', [vals]
        )

    def _map_user_by_login(self, user):
        """Map user using login instead of name."""
        if not user or not user.login:
            return False
        return self._rpc_search_id(
            'res.users',
            [('login', '=', user.login)]
        )

    def _map_partner_by_name(self, partner):
        return partner and self._rpc_search_id(
            'res.partner', [('name', '=', partner.name)]
        )

    def _map_company_by_name(self, company):
        return company and self._rpc_search_id(
            'res.company', [('name', '=', company.name)]
        )

    def _map_user_by_name(self, user):
        return user and self._rpc_search_id(
            'res.users', [('name', '=', user.name)]
        )

    def _map_currency_by_name(self, currency):
        return currency and self._rpc_search_id(
            'res.currency', [('name', '=', currency.name)]
        )

    def _map_product_by_default_code(self, product):
        if not product or not product.default_code:
            return False
        return self._rpc_search_id(
            'product.product',
            [('default_code', '=', product.default_code)]
        )

    def _map_uom_by_name(self, uom):
        return uom and self._rpc_search_id(
            'uom.uom', [('name', '=', uom.name)]
        )

    def _map_taxes(self, taxes):
        tax_ids = []
        for tax in taxes:
            tax_id = self._rpc_search_id(
                'account.tax',
                [
                    ('name', '=', tax.name),
                    ('type_tax_use', '=', tax.type_tax_use),
                ]
            )
            if tax_id:
                tax_ids.append(tax_id)
        return tax_ids

    @api.model
    def _generate_external_reference(self, seq_code, prefix='POS'):
        """Generate a unique external reference using ir.sequence."""
        seq = self.env['ir.sequence'].next_by_code(seq_code) or '/'
        return '%s-%s' % (prefix or 'POS', seq)
# ---------------------------------------------------------------------------
# POS CONFIG INTEGRATION
# ---------------------------------------------------------------------------
# class POSConfigIntegration(models.Model):
#     _inherit = 'pos.config'
#
#     x_external_reference = fields.Char(
#         string="External Reference",
#         readonly=True,
#         help="Unique reference for integration with Enterprise POS Config",
#     )
#     sync_state = fields.Selection(
#         [
#             ('pending', 'Pending'),
#             ('synced', 'Synced'),
#             ('failed', 'Failed'),
#         ],
#         default='pending',
#         string="Sync State",
#     )
#     sync_message = fields.Char(string="Sync Message")
#     sync_date = fields.Datetime(string="Last Sync Date")
#
#     def _prepare_pos_config_vals_for_enterprise(self):
#         """Prepare values to create/update pos.config in Enterprise."""
#         self.ensure_one()
#         vals = {
#             'x_external_reference': self.x_external_reference,
#             'name': self.name,
#             'company_id': self.company_id.id if self.company_id else False,
#             'journal_id': self.journal_id.id if self.journal_id else False,
#             'invoice_journal_id': self.invoice_journal_id.id if self.invoice_journal_id else False,
#             'picking_type_id': self.picking_type_id.id if self.picking_type_id else False,
#             # 'stock_location_id': self.stock_location_id.id if self.stock_location_id else False,
#             'iface_tipproduct': self.iface_tipproduct,
#             'currency_id': self.currency_id.id if self.currency_id else False,
#             'receipt_header': self.receipt_header,
#             'receipt_footer': self.receipt_footer,
#         }
#         return vals
#
#     def _sync_config_to_enterprise(self):
#         conn = self.env['pos.session']._get_enterprise_connection()
#         models_proxy = conn['models']
#         db = conn['db']
#         uid = conn['uid']
#         pwd = conn['password']
#
#         for config in self:
#             try:
#                 if not config.x_external_reference:
#                     config.x_external_reference = self.env['pos.session']._generate_external_reference(
#                         'pos.config.seq.integ', prefix='POSCFG'
#                     )
#
#                 rec_ids = models_proxy.execute_kw(
#                     db, uid, pwd, 'pos.config', 'search',
#                     [[['x_external_reference', '=', config.x_external_reference]]]
#                 )
#                 vals = config._prepare_pos_config_vals_for_enterprise()
#                 if rec_ids:
#                     models_proxy.execute_kw(
#                         db, uid, pwd, 'pos.config', 'write',
#                         [[rec_ids[0]], vals]
#                     )
#                 else:
#                     models_proxy.execute_kw(
#                         db, uid, pwd, 'pos.config', 'create', [vals]
#                     )
#
#                 config.write({
#                     'sync_state': 'synced',
#                     'sync_message': False,
#                     'sync_date': fields.Datetime.now(),
#                 })
#             except Exception as e:
#                 _logger.error("Error syncing POS Config %s to Enterprise: %s", config.id, e)
#                 config.write({
#                     'sync_state': 'failed',
#                     'sync_message': str(e),
#                     'sync_date': fields.Datetime.now(),
#                 })
#
#     @api.model
#     def cron_sync_pos_configs_to_enterprise(self, limit=50):
#         """Sync pending/failed/unsynced pos.config from Community to Enterprise."""
#         configs = self.search([
#             '|',
#             ('sync_state', 'in', ['pending', 'failed']),
#             ('sync_state', '=', False),
#         ], limit=limit)
#         configs._sync_config_to_enterprise()
#
#
# # ---------------------------------------------------------------------------
# # POS SESSION INTEGRATION
# # ---------------------------------------------------------------------------
# class POSSessionIntegration(models.Model):
#     _inherit = 'pos.session'
#
#     x_external_reference = fields.Char(
#         string="External Reference",
#         readonly=True,
#         help="Unique reference for integration with Enterprise POS session",
#     )
#     sync_state = fields.Selection(
#         [
#             ('pending', 'Pending'),
#             ('synced', 'Synced'),
#             ('failed', 'Failed'),
#         ],
#         default='pending',
#         string="Sync State",
#     )
#     sync_message = fields.Char(string="Sync Message")
#     sync_date = fields.Datetime(string="Last Sync Date")
#
#     @api.model
#     def _get_enterprise_connection(self):
#         return self.env['pos.integration.mixin']._get_enterprise_connection()
#
#     @api.model
#     def _generate_external_reference(self, seq_code, prefix='POS'):
#         return self.env['pos.integration.mixin']._generate_external_reference(seq_code, prefix)
#
#     def _prepare_pos_session_vals_for_enterprise(self, config_e_id=False):
#         """Prepare values to create/update pos.session in Enterprise.
#
#         config_e_id is the Enterprise ID of the pos.config.
#         """
#         self.ensure_one()
#         vals = {
#             'x_external_reference': self.x_external_reference,
#             'name': self.name,
#             'config_id': config_e_id or False,
#             'user_id': self.user_id.id if self.user_id else False,
#             'state': self.state,
#             'start_at': self.start_at,
#             'stop_at': self.stop_at,
#             'company_id': self.company_id.id if self.company_id else False,
#         }
#         return vals
#
#     def _sync_session_to_enterprise(self):
#         conn = self._get_enterprise_connection()
#         models_proxy = conn['models']
#         db = conn['db']
#         uid = conn['uid']
#         pwd = conn['password']
#
#         for session in self:
#             try:
#                 if not session.x_external_reference:
#                     session.x_external_reference = self._generate_external_reference(
#                         'pos.session.seq.integ', prefix=session.name or 'POSSESSION'
#                     )
#
#                 # Map config to Enterprise by x_external_reference
#                 config_e_id = False
#                 if session.config_id and session.config_id.x_external_reference:
#                     cfg_ids = models_proxy.execute_kw(
#                         db, uid, pwd, 'pos.config', 'search',
#                         [[['x_external_reference', '=', session.config_id.x_external_reference]]]
#                     )
#                     config_e_id = cfg_ids and cfg_ids[0] or False
#
#                 rec_ids = models_proxy.execute_kw(
#                     db, uid, pwd, 'pos.session', 'search',
#                     [[['x_external_reference', '=', session.x_external_reference]]]
#                 )
#                 vals = session._prepare_pos_session_vals_for_enterprise(config_e_id=config_e_id)
#                 if rec_ids:
#                     models_proxy.execute_kw(
#                         db, uid, pwd, 'pos.session', 'write',
#                         [[rec_ids[0]], vals]
#                     )
#                 else:
#                     models_proxy.execute_kw(
#                         db, uid, pwd, 'pos.session', 'create', [vals]
#                     )
#
#                 session.write({
#                     'sync_state': 'synced',
#                     'sync_message': False,
#                     'sync_date': fields.Datetime.now(),
#                 })
#             except Exception as e:
#                 _logger.error("Error syncing POS Session %s to Enterprise: %s", session.id, e)
#                 session.write({
#                     'sync_state': 'failed',
#                     'sync_message': str(e),
#                     'sync_date': fields.Datetime.now(),
#                 })
#
#     @api.model
#     def cron_sync_pos_sessions_to_enterprise(self, limit=100):
#         """Sync pending/failed/unsynced pos.session from Community to Enterprise."""
#         sessions = self.search([
#             '|',
#             ('sync_state', 'in', ['pending', 'failed']),
#             ('sync_state', '=', False),
#         ], limit=limit)
#         sessions._sync_session_to_enterprise()
#
#
# # ---------------------------------------------------------------------------
# # POS ORDER INTEGRATION
# # ---------------------------------------------------------------------------
# class POSOrderIntegration(models.Model):
#     _inherit = 'pos.order'
#
#     x_external_reference = fields.Char(
#         string="External Reference",
#         readonly=True,
#         help="Unique reference for integration with Enterprise POS order",
#     )
#     sync_state = fields.Selection(
#         [
#             ('pending', 'Pending'),
#             ('synced', 'Synced'),
#             ('failed', 'Failed'),
#         ],
#         default='pending',
#         string="Sync State",
#     )
#     sync_message = fields.Char(string="Sync Message")
#     sync_date = fields.Datetime(string="Last Sync Date")
#
#     @api.model
#     def _get_enterprise_connection(self):
#         return self.env['pos.session']._get_enterprise_connection()
#
#     @api.model
#     def _generate_external_reference(self, seq_code, prefix='POS'):
#         return self.env['pos.session']._generate_external_reference(seq_code, prefix)
#
#     def _prepare_pos_order_vals_for_enterprise(
#         self,
#         include_lines=False,
#         session_e_id=False,
#         config_e_id=False,
#     ):
#         """Prepare values to create/update pos.order in Enterprise.
#
#         session_e_id / config_e_id are IDs in the ENTERPRISE database.
#         """
#         self.ensure_one()
#         vals = {
#             'x_external_reference': self.x_external_reference,
#             'name': self.name,
#             'session_id': session_e_id or False,
#             'config_id': config_e_id or False,
#             'partner_id': self.partner_id.id if self.partner_id else False,
#             'pricelist_id': self.pricelist_id.id if self.pricelist_id else False,
#             'user_id': self.user_id.id if self.user_id else False,
#             'company_id': self.company_id.id if self.company_id else False,
#             'amount_total': self.amount_total,
#             'amount_tax': self.amount_tax,
#             'amount_paid': self.amount_paid,
#             'amount_return': self.amount_return,
#             'date_order': self.date_order,
#             'state': self.state,
#         }
#
#         if include_lines:
#             line_commands = []
#             for line in self.lines:
#                 line_vals = {
#                     'product_id': line.product_id.id if line.product_id else False,
#                     'qty': line.qty,
#                     'price_unit': line.price_unit,
#                     'price_subtotal': line.price_subtotal,
#                     'price_subtotal_incl': line.price_subtotal_incl,
#                     'margin': getattr(line, 'margin', 0.0),
#                     'margin_percent': getattr(line, 'margin_percent', 0.0),
#                     'discount': line.discount,
#                     'tax_ids_after_fiscal_position': [
#                         (6, 0, line.tax_ids_after_fiscal_position.ids)
#                     ] if getattr(line, 'tax_ids_after_fiscal_position', False) else False,
#                     'company_id': line.company_id.id if line.company_id else False,
#                 }
#                 line_commands.append((0, 0, line_vals))
#             if line_commands:
#                 vals['lines'] = line_commands
#
#         return vals
#
#     def _sync_order_to_enterprise(self):
#         conn = self._get_enterprise_connection()
#         models_proxy = conn['models']
#         db = conn['db']
#         uid = conn['uid']
#         pwd = conn['password']
#
#         for order in self:
#             try:
#                 if not order.x_external_reference:
#                     order.x_external_reference = self._generate_external_reference(
#                         'pos.order.seq.integ', prefix=order.name or 'POSORDER'
#                     )
#
#                 # Map session to Enterprise
#                 session_e_id = False
#                 if order.session_id and order.session_id.x_external_reference:
#                     sess_ids = models_proxy.execute_kw(
#                         db, uid, pwd, 'pos.session', 'search',
#                         [[['x_external_reference', '=', order.session_id.x_external_reference]]]
#                     )
#                     session_e_id = sess_ids and sess_ids[0] or False
#
#                 # Map config to Enterprise
#                 config_e_id = False
#                 if order.config_id and order.config_id.x_external_reference:
#                     cfg_ids = models_proxy.execute_kw(
#                         db, uid, pwd, 'pos.config', 'search',
#                         [[['x_external_reference', '=', order.config_id.x_external_reference]]]
#                     )
#                     config_e_id = cfg_ids and cfg_ids[0] or False
#
#                 if not session_e_id:
#                     raise Exception("No matching pos.session in Enterprise for order %s" % order.id)
#
#                 rec_ids = models_proxy.execute_kw(
#                     db, uid, pwd, 'pos.order', 'search',
#                     [[['x_external_reference', '=', order.x_external_reference]]]
#                 )
#
#                 if rec_ids:
#                     vals = order._prepare_pos_order_vals_for_enterprise(
#                         include_lines=False,
#                         session_e_id=session_e_id,
#                         config_e_id=config_e_id,
#                     )
#                     models_proxy.execute_kw(
#                         db, uid, pwd, 'pos.order', 'write',
#                         [[rec_ids[0]], vals]
#                     )
#                 else:
#                     vals = order._prepare_pos_order_vals_for_enterprise(
#                         include_lines=True,
#                         session_e_id=session_e_id,
#                         config_e_id=config_e_id,
#                     )
#                     models_proxy.execute_kw(
#                         db, uid, pwd, 'pos.order', 'create', [vals]
#                     )
#
#                 order.write({
#                     'sync_state': 'synced',
#                     'sync_message': False,
#                     'sync_date': fields.Datetime.now(),
#                 })
#             except Exception as e:
#                 _logger.error("Error syncing POS Order %s to Enterprise: %s", order.id, e)
#                 order.write({
#                     'sync_state': 'failed',
#                     'sync_message': str(e),
#                     'sync_date': fields.Datetime.now(),
#                 })
#
#     @api.model
#     def cron_sync_pos_orders_to_enterprise(self, limit=100):
#         """Sync pending/failed/unsynced pos.order from Community to Enterprise."""
#         orders = self.search([
#             '|',
#             ('sync_state', 'in', ['pending', 'failed']),
#             ('sync_state', '=', False),
#         ], limit=limit)
#         orders._sync_order_to_enterprise()
#
#     @api.model
#     def cron_sync_all_pos_to_enterprise(self,
#                                         limit_configs=50,
#                                         limit_sessions=100,
#                                         limit_orders=100,
#                                         limit_payments=200,
#                                         limit_pickings=200):
#         """Single entry point: sync all POS-related data to Enterprise."""
#         self.env['pos.config'].cron_sync_pos_configs_to_enterprise(limit=limit_configs)
#         self.env['pos.session'].cron_sync_pos_sessions_to_enterprise(limit=limit_sessions)
#         self.env['pos.order'].cron_sync_pos_orders_to_enterprise(limit=limit_orders)
#         self.env['pos.payment'].cron_sync_pos_payments_to_enterprise(limit=limit_payments)
#         self.env['stock.picking'].cron_sync_pos_pickings_to_enterprise(limit=limit_pickings)
#
#
# # ---------------------------------------------------------------------------
# # POS PAYMENT INTEGRATION
# # ---------------------------------------------------------------------------
# class POSPaymentIntegration(models.Model):
#     _inherit = 'pos.payment'
#
#     x_external_reference = fields.Char(
#         string="External Reference",
#         readonly=True,
#         help="Unique reference for integration with Enterprise POS payment",
#     )
#     sync_state = fields.Selection(
#         [
#             ('pending', 'Pending'),
#             ('synced', 'Synced'),
#             ('failed', 'Failed'),
#         ],
#         default='pending',
#         string="Sync State",
#     )
#     sync_message = fields.Char(string="Sync Message")
#     sync_date = fields.Datetime(string="Last Sync Date")
#
#     @api.model
#     def _get_enterprise_connection(self):
#         return self.env['pos.session']._get_enterprise_connection()
#
#     @api.model
#     def _generate_external_reference(self, seq_code, prefix='POS'):
#         return self.env['pos.session']._generate_external_reference(seq_code, prefix)
#
#     def _prepare_pos_payment_vals_for_enterprise(
#         self,
#         order_e_id=False,
#         session_e_id=False,
#     ):
#         """Prepare values to create pos.payment in Enterprise.
#
#         order_e_id / session_e_id are IDs in the ENTERPRISE database.
#         """
#         self.ensure_one()
#         return {
#             'x_external_reference': self.x_external_reference,
#             'name': self.name,  # keep same label
#             'amount': self.amount,
#             'payment_method_id': self.payment_method_id.id if self.payment_method_id else False,
#             'pos_order_id': order_e_id or False,
#             'session_id': session_e_id or False,
#             'company_id': self.company_id.id if self.company_id else False,
#             'currency_id': self.currency_id.id if self.currency_id else False,
#             'payment_date': self.payment_date,
#         }
#
#     def _sync_payment_to_enterprise(self):
#         conn = self._get_enterprise_connection()
#         models_proxy = conn['models']
#         db = conn['db']
#         uid = conn['uid']
#         pwd = conn['password']
#
#         for pay in self:
#             try:
#                 if not pay.x_external_reference:
#                     pay.x_external_reference = self._generate_external_reference(
#                         'pos.payment.seq.integ', prefix='POSPAY'
#                     )
#
#                 # Map order to Enterprise
#                 order_e_id = False
#                 if pay.pos_order_id and pay.pos_order_id.x_external_reference:
#                     ord_ids = models_proxy.execute_kw(
#                         db, uid, pwd, 'pos.order', 'search',
#                         [[['x_external_reference', '=', pay.pos_order_id.x_external_reference]]]
#                     )
#                     order_e_id = ord_ids and ord_ids[0] or False
#
#                 # Map session to Enterprise
#                 session_e_id = False
#                 if pay.session_id and pay.session_id.x_external_reference:
#                     sess_ids = models_proxy.execute_kw(
#                         db, uid, pwd, 'pos.session', 'search',
#                         [[['x_external_reference', '=', pay.session_id.x_external_reference]]]
#                     )
#                     session_e_id = sess_ids and sess_ids[0] or False
#
#                 if not session_e_id:
#                     # No session in Enterprise, don't try to create payment
#                     raise Exception("No matching pos.session in Enterprise for payment %s" % pay.id)
#
#                 # If a payment already exists in Enterprise, NEVER edit it
#                 rec_ids = models_proxy.execute_kw(
#                     db, uid, pwd, 'pos.payment', 'search',
#                     [[['x_external_reference', '=', pay.x_external_reference]]]
#                 )
#                 if rec_ids:
#                     pay.write({
#                         'sync_state': 'synced',
#                         'sync_message': False,
#                         'sync_date': fields.Datetime.now(),
#                     })
#                     continue
#
#                 # ---------- Try CREATE with pos_order_id ----------
#                 vals = pay._prepare_pos_payment_vals_for_enterprise(
#                     order_e_id=order_e_id,
#                     session_e_id=session_e_id,
#                 )
#
#                 try:
#                     models_proxy.execute_kw(
#                         db, uid, pwd, 'pos.payment', 'create', [vals]
#                     )
#                 except Exception as e_remote:
#                     msg = str(e_remote)
#                     # If Enterprise complains about posted order, retry without order link
#                     if "You cannot edit a payment for a posted order" in msg:
#                         vals_no_order = dict(vals, pos_order_id=False)
#                         models_proxy.execute_kw(
#                             db, uid, pwd, 'pos.payment', 'create', [vals_no_order]
#                         )
#                     else:
#                         # Other error: re-raise to be caught by outer except
#                         raise
#
#                 pay.write({
#                     'sync_state': 'synced',
#                     'sync_message': False,
#                     'sync_date': fields.Datetime.now(),
#                 })
#
#             except Exception as e:
#                 _logger.error("Error syncing POS Payment %s to Enterprise: %s", pay.id, e)
#                 pay.write({
#                     'sync_state': 'failed',
#                     'sync_message': str(e),
#                     'sync_date': fields.Datetime.now(),
#                 })
#
#     @api.model
#     def cron_sync_pos_payments_to_enterprise(self, limit=200):
#         """Sync pending/failed/unsynced pos.payment from Community to Enterprise."""
#         pays = self.search([
#             '|',
#             ('sync_state', 'in', ['pending', 'failed']),
#             ('sync_state', '=', False),
#         ], limit=limit)
#         pays._sync_payment_to_enterprise()
#
# # ---------------------------------------------------------------------------
# # STOCK PICKING (PICKINGS) INTEGRATION
# # ---------------------------------------------------------------------------
# class StockPickingIntegration(models.Model):
#     _inherit = 'stock.picking'
#
#     x_external_reference = fields.Char(
#         string="External Reference",
#         readonly=True,
#         help="Unique reference for integration with Enterprise Picking",
#     )
#     sync_state = fields.Selection(
#         [
#             ('pending', 'Pending'),
#             ('synced', 'Synced'),
#             ('failed', 'Failed'),
#         ],
#         default='pending',
#         string="Sync State",
#     )
#     sync_message = fields.Char(string="Sync Message")
#     sync_date = fields.Datetime(string="Last Sync Date")
#
#     def _get_enterprise_connection(self):
#         return self.env['pos.session']._get_enterprise_connection()
#
#     def _generate_external_reference(self, seq_code, prefix='PICK'):
#         return self.env['pos.session']._generate_external_reference(seq_code, prefix)
#
#     def _prepare_picking_vals_for_enterprise(self, order_e_id=False):
#         """Prepare values to create/update stock.picking in Enterprise.
#
#         Assumes product/location IDs are identical between DBs.
#         """
#         self.ensure_one()
#         vals = {
#             'x_external_reference': self.x_external_reference,
#             'name': self.name,
#             'picking_type_id': self.picking_type_id.id if self.picking_type_id else False,
#             'location_id': self.location_id.id if self.location_id else False,
#             'location_dest_id': self.location_dest_id.id if self.location_dest_id else False,
#             'scheduled_date': self.scheduled_date,
#             'origin': self.origin,
#             'company_id': self.company_id.id if self.company_id else False,
#             'partner_id': self.partner_id.id if self.partner_id else False,
#             'pos_order_id': order_e_id or False,
#             'state': self.state,
#         }
#
#         move_commands = []
#         for move in self.move_ids_without_package:
#             mv_vals = {
#                 'name': move.name,
#                 'product_id': move.product_id.id if move.product_id else False,
#                 'product_uom_qty': move.product_uom_qty,
#                 'product_uom': move.product_uom.id if move.product_uom else False,
#                 'location_id': move.location_id.id if move.location_id else False,
#                 'location_dest_id': move.location_dest_id.id if move.location_dest_id else False,
#                 'company_id': move.company_id.id if move.company_id else False,
#             }
#             move_commands.append((0, 0, mv_vals))
#         if move_commands:
#             vals['move_ids_without_package'] = move_commands
#
#         return vals
#
#     def _sync_picking_to_enterprise(self):
#         conn = self._get_enterprise_connection()
#         models_proxy = conn['models']
#         db = conn['db']
#         uid = conn['uid']
#         pwd = conn['password']
#
#         for picking in self:
#             try:
#                 if not picking.x_external_reference:
#                     picking.x_external_reference = self._generate_external_reference(
#                         'stock.picking.seq.integ', prefix='PICK'
#                     )
#
#                 # Map related POS order (if any) to Enterprise
#                 order_e_id = False
#                 if getattr(picking, 'pos_order_id', False) and picking.pos_order_id.x_external_reference:
#                     ord_ids = models_proxy.execute_kw(
#                         db, uid, pwd, 'pos.order', 'search',
#                         [[['x_external_reference', '=', picking.pos_order_id.x_external_reference]]]
#                     )
#                     order_e_id = ord_ids and ord_ids[0] or False
#
#                 rec_ids = models_proxy.execute_kw(
#                     db, uid, pwd, 'stock.picking', 'search',
#                     [[['x_external_reference', '=', picking.x_external_reference]]]
#                 )
#
#                 if rec_ids:
#                     vals = picking._prepare_picking_vals_for_enterprise(order_e_id=order_e_id)
#                     models_proxy.execute_kw(
#                         db, uid, pwd, 'stock.picking', 'write',
#                         [[rec_ids[0]], vals]
#                     )
#                 else:
#                     vals = picking._prepare_picking_vals_for_enterprise(order_e_id=order_e_id)
#                     models_proxy.execute_kw(
#                         db, uid, pwd, 'stock.picking', 'create', [vals]
#                     )
#
#                 picking.write({
#                     'sync_state': 'synced',
#                     'sync_message': False,
#                     'sync_date': fields.Datetime.now(),
#                 })
#             except Exception as e:
#                 _logger.error("Error syncing Picking %s to Enterprise: %s", picking.id, e)
#                 picking.write({
#                     'sync_state': 'failed',
#                     'sync_message': str(e),
#                     'sync_date': fields.Datetime.now(),
#                 })
#
#     @api.model
#     def cron_sync_pos_pickings_to_enterprise(self, limit=200):
#         """Sync pickings related to POS orders (pos_order_id not False)."""
#         pickings = self.search([
#             ('pos_order_id', '!=', False),
#             '|',
#             ('sync_state', 'in', ['pending', 'failed']),
#             ('sync_state', '=', False),
#         ], limit=limit)
#         pickings._sync_picking_to_enterprise()
