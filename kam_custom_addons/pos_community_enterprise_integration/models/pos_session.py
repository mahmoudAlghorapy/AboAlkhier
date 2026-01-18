# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class POSPaymentIntegration(models.Model):
    _inherit = 'pos.payment'

    @api.constrains('amount')
    def _check_amount(self):
        # Disable the constraint for sync operations
        # The original constraint is:
        # if payment.pos_order_id.state == 'done' or payment.pos_order_id.account_move:
        #     raise ValidationError(_('You cannot edit a payment for a posted order.'))
        pass


class PosSessionIntegration(models.Model):
    _inherit = 'pos.session'

    x_external_reference = fields.Char(readonly=True, copy=False)
    sync_state = fields.Selection(
        [('pending', 'Pending'), ('synced', 'Synced'), ('failed', 'Failed')],
        default='pending',
        copy=False
    )
    sync_message = fields.Char(copy=False)
    sync_date = fields.Datetime(copy=False)

    # ---------------------------------------------------------
    # Sync logic with notifications
    # ---------------------------------------------------------
    def _sync_pos_session_to_enterprise(self):
        """Sync POS sessions to Enterprise with notifications"""
        conn = self._get_enterprise_connection()
        models_proxy = conn['models']

        success = []
        failed = []
        enterprise_ids = []

        # ✅ ONLY closed sessions that are pending or failed
        # Use self.ensure_one() to make sure only one session is being synced
        # Or filter by the specific session we want to sync
        sessions = self.filtered(
            lambda s: s.state == 'closed'
                      and s.sync_state in ('pending', 'failed')
        )

        if not sessions:
            raise UserError(_("No POS sessions to sync. All sessions are already synced or not closed."))

        _logger.info(f"Starting sync for {len(sessions)} session(s): {sessions.mapped('name')}")

        for session in sessions:
            try:
                # Generate external ref ONCE
                if not session.x_external_reference:
                    session.x_external_reference = self.env['ir.sequence'].next_by_code(
                        'pos.session.seq.integ'
                    )

                # Check if already exists in Enterprise
                rec_ids = models_proxy.execute_kw(
                    conn['db'], conn['uid'], conn['password'],
                    'pos.session', 'search',
                    [[('x_external_reference', '=', session.x_external_reference)]],
                    {'limit': 1}
                )

                if rec_ids:
                    _logger.warning(
                        f"POS session {session.name} already exists in Enterprise (ID {rec_ids[0]}), skipping")
                    success.append(f"{session.name} (already exists)")
                    continue

                # Prepare values
                vals = self._prepare_pos_session_vals(session, models_proxy, conn)
                session_e_id = models_proxy.execute_kw(
                    conn['db'], conn['uid'], conn['password'],
                    'pos.session', 'create', [vals]
                )

                # Create related records
                self._sync_related_records(session, session_e_id, models_proxy, conn)

                # Update sync status
                session.write({
                    'sync_state': 'synced',
                    'sync_message': f'Synced to Enterprise ID {session_e_id}',
                    'sync_date': fields.Datetime.now(),
                })

                success.append(session.name)
                enterprise_ids.append(session_e_id)
                _logger.info(f"✅ POS Session {session.name} synced to Enterprise ID {session_e_id}")

            except Exception as e:
                error_msg = str(e)
                session.write({
                    'sync_state': 'failed',
                    'sync_message': error_msg,
                    'sync_date': fields.Datetime.now(),
                })
                failed.append(f"{session.name}: {error_msg}")
                _logger.error(f"❌ POS Session {session.name} sync failed: {error_msg}")

        # Show notification
        if failed:
            error_message = "\n".join(failed[:10])
            if len(failed) > 10:
                error_message += f"\n... and {len(failed) - 10} more errors"

            self.env.cr.commit()
            raise UserError(
                _("⚠️ Sync Results:\n\n"
                  "✅ Success: %s session(s)\n"
                  "❌ Failed: %s session(s)\n\n"
                  "Errors:\n%s") %
                (len(success), len(failed), error_message)
            )
        else:
            if enterprise_ids:
                ids_message = f"\nEnterprise IDs: {', '.join(map(str, enterprise_ids))}"
            else:
                ids_message = ""

            self.env.cr.commit()
            raise UserError(
                _("✅ Sync Successful!\n\n"
                  "%s POS session(s) synced successfully to Enterprise.%s") %
                (len(success), ids_message)
            )

    def _sync_related_records(self, session, session_e_id, models_proxy, conn):
        """Sync related records (orders, payments, pickings)"""
        # Sync orders
        for order in session.order_ids.filtered(lambda o: o.state in ['paid', 'invoiced', 'done']):
            order_vals = self._prepare_pos_order_vals(order, session_e_id, models_proxy, conn)
            if order_vals:
                order_e_id = models_proxy.execute_kw(
                    conn['db'], conn['uid'], conn['password'],
                    'pos.order', 'create', [order_vals]
                )
                # Sync order lines
                self._sync_order_lines(order, order_e_id, models_proxy, conn)
                # Sync payments - IMPORTANT: create payments BEFORE confirming the order
                self._sync_payments(order, order_e_id, models_proxy, conn)
                # Set order to paid state
                self._set_order_paid(order_e_id, models_proxy, conn)

        # Sync pickings
        self._sync_pickings(session, session_e_id, models_proxy, conn)

    def _sync_pickings(self, session, session_e_id, models_proxy, conn):
        """Sync stock pickings associated with the session"""
        mixin = self.env['pos.integration.mixin']

        # Get all pickings related to this session
        all_pickings = session.picking_ids

        # Also get pickings from orders in this session
        order_pickings = session.order_ids.mapped('picking_ids')

        # Combine unique pickings
        pickings = (all_pickings | order_pickings).filtered(
            lambda p: p.state in ['done', 'assigned', 'confirmed']
        )

        _logger.info(f"Syncing {len(pickings)} pickings for session {session.name}")

        for picking in pickings:
            try:
                picking_vals = self._prepare_picking_vals(picking, session_e_id, models_proxy, conn)
                if picking_vals:
                    picking_e_id = models_proxy.execute_kw(
                        conn['db'], conn['uid'], conn['password'],
                        'stock.picking', 'create', [picking_vals]
                    )
                    # Sync picking move lines
                    self._sync_picking_move_lines(picking, picking_e_id, models_proxy, conn)
                    _logger.info(f"✅ Picking {picking.name} synced to Enterprise ID {picking_e_id}")
            except Exception as e:
                _logger.warning(f"Failed to sync picking {picking.name}: {e}")

    def _prepare_picking_vals(self, picking, session_e_id, models_proxy, conn):
        """Prepare values for stock picking"""
        mixin = self.env['pos.integration.mixin']

        # Map picking type
        picking_type_e_id = self._map_picking_type_by_name(picking.picking_type_id, mixin)
        if not picking_type_e_id:
            _logger.warning(f"Picking type {picking.picking_type_id.name} not found in Enterprise")
            return None

        # Map location
        location_e_id = self._map_location_by_complete_name(picking.location_id, mixin)
        location_dest_e_id = self._map_location_by_complete_name(picking.location_dest_id, mixin)

        if not location_e_id or not location_dest_e_id:
            _logger.warning(f"Location not found in Enterprise for picking {picking.name}")
            return None

        # Map partner
        partner_e_id = False
        if picking.partner_id:
            partner_e_id = mixin._map_partner_by_name(picking.partner_id)

        # Map company
        company_e_id = mixin._map_company_by_name(picking.company_id)
        if not company_e_id:
            _logger.warning(f"Company {picking.company_id.name} not found in Enterprise")
            return None

        vals = {
            'pos_session_id': session_e_id,
            'picking_type_id': picking_type_e_id,
            'location_id': location_e_id,
            'location_dest_id': location_dest_e_id,
            'partner_id': partner_e_id,
            'company_id': company_e_id,
            'state': picking.state,
            'name': picking.name,
            'origin': picking.origin or f"POS Session {session_e_id}",
            'scheduled_date': picking.scheduled_date or fields.Datetime.now(),
        }

        if picking.date_done:
            vals['date_done'] = picking.date_done

        return vals

    def _sync_picking_move_lines(self, picking, picking_e_id, models_proxy, conn):
        """Sync stock move lines for a picking"""
        mixin = self.env['pos.integration.mixin']

        for move in picking.move_ids:
            product_e_id = mixin._map_product_by_default_code(move.product_id)
            if not product_e_id:
                _logger.warning(f"Product {move.product_id.default_code} not found in Enterprise, skipping move")
                continue

            # Map UoM
            uom_e_id = mixin._map_uom_by_name(move.product_uom)
            if not uom_e_id:
                uom_e_id = mixin._map_uom_by_name(move.product_id.uom_id)

            move_vals = {
                'picking_id': picking_e_id,
                'product_id': product_e_id,
                'name': move.name or move.product_id.name,
                'product_uom_qty': move.product_uom_qty or 0.0,
                'quantity_done': move.quantity_done or 0.0,
                'product_uom': uom_e_id or 1,  # Default to Unit
                'location_id': self._map_location_by_complete_name(move.location_id, mixin),
                'location_dest_id': self._map_location_by_complete_name(move.location_dest_id, mixin),
                'state': move.state,
            }

            models_proxy.execute_kw(
                conn['db'], conn['uid'], conn['password'],
                'stock.move', 'create', [move_vals]
            )

    def _map_picking_type_by_name(self, picking_type, mixin):
        """Map picking type by name"""
        if not picking_type:
            return False
        return mixin._rpc_search_id(
            'stock.picking.type',
            [('name', '=', picking_type.name)]
        )

    def _map_location_by_complete_name(self, location, mixin):
        """Map location by complete name"""
        if not location:
            return False
        return mixin._rpc_search_id(
            'stock.location',
            [('complete_name', '=', location.complete_name)]
        )

    def _prepare_pos_session_vals(self, session, models_proxy, conn):
        """Prepare values for creating POS session in Enterprise"""
        mixin = self.env['pos.integration.mixin']

        # Map config_id - search by name
        config_e_id = mixin._rpc_search_id(
            'pos.config',
            [('name', '=', session.config_id.name)]
        )

        if not config_e_id:
            # Create config if not found
            company_e_id = mixin._map_company_by_name(session.company_id)
            if not company_e_id:
                raise UserError(_("Company '%s' not found in Enterprise") % session.company_id.name)

            # Get or create default journal
            journal_ids = mixin._rpc_search(
                'account.journal',
                [('type', '=', 'sale'), ('company_id', '=', company_e_id)]
            )
            journal_e_id = journal_ids[0] if journal_ids else False

            config_vals = {
                'name': session.config_id.name,
                'company_id': company_e_id,
            }
            if journal_e_id:
                config_vals['journal_id'] = journal_e_id

            config_e_id = models_proxy.execute_kw(
                conn['db'], conn['uid'], conn['password'],
                'pos.config', 'create', [config_vals]
            )

        # Map other required fields
        user_e_id = mixin._map_user_by_login(session.user_id)
        # if not user_e_id:
        #     raise UserError(_("User '%s' not found in Enterprise") % session.user_id.login)

        company_e_id = mixin._map_company_by_name(session.company_id)
        if not company_e_id:
            raise UserError(_("Company '%s' not found in Enterprise") % session.company_id.name)

        # Prepare base values
        vals = {
            'x_external_reference': session.x_external_reference,
            'config_id': config_e_id,
            'company_id': company_e_id,
            'user_id': user_e_id or False,
            'name': session.name,
            'start_at': session.start_at,
            'stop_at': session.stop_at or fields.Datetime.now(),
            'state': session.state,
            'opening_notes': session.opening_notes or '',
            'closing_notes': session.closing_notes or '',
            'cash_register_balance_start': session.cash_register_balance_start or 0.0,
            'cash_register_balance_end_real': session.cash_register_balance_end_real or 0.0,
            'cash_real_transaction': session.cash_real_transaction or 0.0,
        }

        return vals

    def _prepare_pos_order_vals(self, order, session_e_id, models_proxy, conn):
        """Prepare values for POS order"""
        mixin = self.env['pos.integration.mixin']

        # Map partner
        partner_e_id = False
        if order.partner_id:
            partner_e_id = mixin._map_partner_by_name(order.partner_id)

        # Map user
        user_e_id = mixin._map_user_by_login(order.user_id)
        if not user_e_id:
            # Use session user as fallback
            user_e_id = mixin._map_user_by_login(order.session_id.user_id)

        # Map company
        company_e_id = mixin._map_company_by_name(order.company_id)
        if not company_e_id:
            raise UserError(_("Company '%s' not found in Enterprise") % order.company_id.name)

        # IMPORTANT: Create order in 'draft' state first
        vals = {
            'session_id': session_e_id,
            'company_id': company_e_id,
            'partner_id': partner_e_id,
            'user_id': user_e_id,
            'date_order': order.date_order,
            'amount_total': order.amount_total or 0.0,
            'amount_tax': order.amount_tax or 0.0,
            'amount_paid': order.amount_paid or 0.0,
            'amount_return': order.amount_return or 0.0,
            'state': 'draft',  # Start in draft state
            'pos_reference': order.pos_reference,
        }

        return vals

    def _sync_order_lines(self, order, order_e_id, models_proxy, conn):
        """Sync order lines"""
        mixin = self.env['pos.integration.mixin']

        for line in order.lines:
            product_e_id = False
            if line.product_id:
                product_e_id = mixin._map_product_by_default_code(line.product_id)

            if not product_e_id:
                _logger.warning(
                    f"Product {line.product_id.default_code if line.product_id else 'Unknown'} not found in Enterprise, skipping line")
                continue

            line_vals = {
                'order_id': order_e_id,
                'product_id': product_e_id,
                'name': line.name or line.product_id.name,
                'qty': line.qty or 1.0,
                'price_unit': line.price_unit or 0.0,
                'discount': line.discount or 0.0,
            }

            models_proxy.execute_kw(
                conn['db'], conn['uid'], conn['password'],
                'pos.order.line', 'create', [line_vals]
            )

    def _sync_payments(self, order, order_e_id, models_proxy, conn):
        """Sync payments"""
        mixin = self.env['pos.integration.mixin']

        for payment in order.payment_ids:
            # Get payment method from Enterprise by name
            payment_method_e_id = self._get_or_create_payment_method(payment.payment_method_id, models_proxy, conn)

            if not payment_method_e_id:
                _logger.warning(
                    f"Payment method {payment.payment_method_id.name} not found/created in Enterprise, skipping payment")
                continue

            # Create payment for the order
            payment_vals = {
                'pos_order_id': order_e_id,
                'payment_method_id': payment_method_e_id,
                'amount': payment.amount or 0.0,
                'payment_date': payment.payment_date or fields.Datetime.now(),
            }

            models_proxy.execute_kw(
                conn['db'], conn['uid'], conn['password'],
                'pos.payment', 'create', [payment_vals]
            )

    def _set_order_paid(self, order_e_id, models_proxy, conn):
        """Set order to paid state after payments are created"""
        try:
            # Set order to 'paid' state
            models_proxy.execute_kw(
                conn['db'], conn['uid'], conn['password'],
                'pos.order', 'write',
                [[order_e_id], {'state': 'paid'}]
            )

            # Optionally set to 'done' if needed
            models_proxy.execute_kw(
                conn['db'], conn['uid'], conn['password'],
                'pos.order', 'write',
                [[order_e_id], {'state': 'done'}]
            )
        except Exception as e:
            _logger.warning(f"Could not set order {order_e_id} to paid/done state: {e}")

    def _get_or_create_payment_method(self, payment_method, models_proxy, conn):
        """Get or create payment method in Enterprise"""
        mixin = self.env['pos.integration.mixin']

        if not payment_method:
            return False

        # First, try to find by name
        payment_method_e_id = mixin._rpc_search_id(
            'pos.payment.method',
            [('name', '=', payment_method.name)]
        )

        if payment_method_e_id:
            return payment_method_e_id

        # If not found, try to find by type
        payment_method_e_id = mixin._rpc_search_id(
            'pos.payment.method',
            [('type', '=', payment_method.type)]
        )

        if payment_method_e_id:
            return payment_method_e_id

        # If still not found, create it
        company_e_id = mixin._map_company_by_name(payment_method.company_id)
        if not company_e_id:
            return False

        # Get appropriate journal based on payment method type
        journal_type = 'cash' if payment_method.type == 'cash' else 'bank'
        journal_ids = mixin._rpc_search(
            'account.journal',
            [('type', '=', journal_type), ('company_id', '=', company_e_id)]
        )

        journal_e_id = journal_ids[0] if journal_ids else False

        payment_method_vals = {
            'name': payment_method.name,
            'type': payment_method.type,
            'company_id': company_e_id,
        }

        if journal_e_id:
            payment_method_vals['journal_id'] = journal_e_id

        payment_method_e_id = models_proxy.execute_kw(
            conn['db'], conn['uid'], conn['password'],
            'pos.payment.method', 'create', [payment_method_vals]
        )

        return payment_method_e_id

    # ---------------------------------------------------------
    # Helper methods
    # ---------------------------------------------------------
    def _get_enterprise_connection(self):
        """Get connection to Enterprise database"""
        return self.env['pos.integration.mixin']._get_enterprise_connection()

    # ---------------------------------------------------------
    # UI Actions - FIXED to ensure single session sync
    # ---------------------------------------------------------
    def action_sync_to_enterprise(self):
        """Sync single POS session - FIXED to only sync the clicked session"""
        self.ensure_one()

        if self.state != 'closed':
            raise UserError(_("Only closed POS sessions can be synced."))

        if self.sync_state == 'synced':
            raise UserError(_("This POS session is already synced."))

        # Call sync on ONLY this session
        return self._sync_pos_session_to_enterprise()

    def action_batch_sync_to_enterprise(self):
        """Sync multiple POS sessions"""
        # Get only the selected sessions that are in list view
        selected_sessions = self.filtered(lambda s: s.state == 'closed')

        if not selected_sessions:
            raise UserError(_("No closed POS sessions selected."))

        # Check if any are already synced
        synced_sessions = selected_sessions.filtered(lambda s: s.sync_state == 'synced')
        if synced_sessions:
            raise UserError(
                _("%s session(s) are already synced. Please select only pending or failed orders.") %
                len(synced_sessions)
            )

        return selected_sessions._sync_pos_session_to_enterprise()

    # ---------------------------------------------------------
    # Reset action
    # ---------------------------------------------------------
    def action_reset_sync(self):
        """Reset sync to try again"""
        self.ensure_one()

        self.write({
            'sync_state': 'pending',
            'sync_message': False,
            'x_external_reference': False,
            'sync_date': False,
        })

        raise UserError(_("Sync reset for %s.") % self.name)

    # ---------------------------------------------------------
    # Cron job
    # ---------------------------------------------------------
    @api.model
    def cron_sync_pos_sessions_to_enterprise(self):
        """Automatic sync of pending POS sessions"""
        sessions = self.search([
            ('state', '=', 'closed'),
            ('sync_state', 'in', ('pending', 'failed'))
        ], limit=50)  # Limit to 50 per run

        if sessions:
            try:
                sessions._sync_pos_session_to_enterprise()
            except UserError as e:
                _logger.warning("Cron sync failed: %s", str(e))
            except Exception as e:
                _logger.error("Cron sync error: %s", str(e))