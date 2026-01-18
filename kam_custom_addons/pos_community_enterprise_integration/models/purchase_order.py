# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class PurchaseOrderIntegration(models.Model):
    _inherit = 'purchase.order'

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
    def _sync_purchase_order_to_enterprise(self):
        """Sync purchase orders to Enterprise with notifications"""
        conn = self._get_enterprise_connection()
        models_proxy = conn['models']

        success = []
        failed = []
        enterprise_ids = []

        # ✅ ONLY pending or failed
        orders = self.filtered(
            lambda p: p.state == 'purchase'
                      and p.sync_state in ('pending', 'failed')
        )

        if not orders:
            raise UserError(_("No purchase orders to sync. All orders are already synced or not confirmed."))

        for po in orders:
            try:
                # Generate external ref ONCE
                if not po.x_external_reference:
                    po.x_external_reference = self.env['ir.sequence'].next_by_code(
                        'purchase.order.seq.integ'
                    )

                # Check if already exists in Enterprise
                rec_ids = models_proxy.execute_kw(
                    conn['db'], conn['uid'], conn['password'],
                    'purchase.order', 'search',
                    [[('x_external_reference', '=', po.x_external_reference)]],
                    {'limit': 1}
                )

                if rec_ids:
                    raise UserError(
                        _("PO already exists in Enterprise (ID %s).") % rec_ids[0]
                    )

                # Prepare values
                vals = self._prepare_purchase_order_vals(po)
                po_e_id = models_proxy.execute_kw(
                    conn['db'], conn['uid'], conn['password'],
                    'purchase.order', 'create', [vals]
                )

                # Confirm PO
                models_proxy.execute_kw(
                    conn['db'], conn['uid'], conn['password'],
                    'purchase.order', 'button_confirm', [[po_e_id]]
                )

                # Update sync status
                po.write({
                    'sync_state': 'synced',
                    'sync_message': f'Synced to Enterprise ID {po_e_id}',
                    'sync_date': fields.Datetime.now(),
                })

                success.append(po.name)
                enterprise_ids.append(po.name)
                _logger.info(f"✅ PO {po.name} synced to Enterprise ID {po.name}")

            except Exception as e:
                error_msg = str(e)
                po.write({
                    'sync_state': 'failed',
                    'sync_message': error_msg,
                    'sync_date': fields.Datetime.now(),
                })
                failed.append(f"{po.name}: {error_msg}")
                _logger.error(f"❌ PO {po.name} sync failed: {error_msg}")

        # Show notification
        if failed:
            error_message = "\n".join(failed[:10])
            if len(failed) > 10:
                error_message += f"\n... and {len(failed) - 10} more errors"

            self.env.cr.commit()
            raise UserError(
                _("⚠️ Sync Results:\n\n"
                  "✅ Success: %s order(s)\n"
                  "❌ Failed: %s order(s)\n\n"
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
                  "%s purchase order(s) synced successfully to Enterprise.%s") %
                (len(success), ids_message)
            )

    # ---------------------------------------------------------
    # Helper methods
    # ---------------------------------------------------------
    def _get_enterprise_connection(self):
        """Get connection to Enterprise database"""
        return self.env['pos.integration.mixin']._get_enterprise_connection()

    def _prepare_purchase_order_vals(self, po):
        """Prepare values for creating PO in Enterprise"""
        mixin = self.env['pos.integration.mixin']

        # Map required fields
        user_e_id = mixin._map_user_by_login(po.user_id)
        # if not user_e_id:
        #     raise UserError(_("User '%s' not found in Enterprise") % po.user_id.login)

        partner_e_id = mixin._map_partner_by_name(po.partner_id)
        if not partner_e_id:
            raise UserError(_("Vendor '%s' not found in Enterprise") % po.partner_id.name)

        company_e_id = mixin._map_company_by_name(po.company_id)
        if not company_e_id:
            raise UserError(_("Company '%s' not found in Enterprise") % po.company_id.name)

        currency_e_id = mixin._map_currency_by_name(po.currency_id)
        if not currency_e_id:
            raise UserError(_("Currency '%s' not found in Enterprise") % po.currency_id.name)

        # Prepare base values
        vals = {
            'x_external_reference': po.x_external_reference,
            'name': po.name,
            'partner_id': partner_e_id,
            'company_id': company_e_id,
            'user_id': user_e_id or False,
            'currency_id': currency_e_id,
            'date_order': po.date_order,
        }

        # Add order lines
        line_commands = []
        for line in po.order_line:
            product_e_id = mixin._map_product_by_default_code(line.product_id)
            if not product_e_id:
                raise UserError(_("Product '%s' not found in Enterprise") % line.product_id.default_code)

            uom_e_id = mixin._map_uom_by_name(line.product_uom_id)
            if not uom_e_id:
                raise UserError(_("Unit of Measure '%s' not found in Enterprise") % line.product_uom_id.name)

            tax_ids = mixin._map_taxes(line.tax_ids)

            line_vals = {
                'product_id': product_e_id,
                'name': line.name,
                'product_qty': line.product_qty,
                'price_unit': line.price_unit,
                'date_planned': line.date_planned,
                'product_uom_id': uom_e_id,
                'tax_ids': [(6, 0, tax_ids)],
            }
            line_commands.append((0, 0, line_vals))

        if line_commands:
            vals['order_line'] = line_commands

        return vals

    # ---------------------------------------------------------
    # UI Actions
    # ---------------------------------------------------------
    def action_sync_to_enterprise(self):
        """Sync single purchase order"""
        self.ensure_one()

        if self.state != 'purchase':
            raise UserError(_("Only confirmed purchase orders can be synced."))

        if self.sync_state == 'synced':
            raise UserError(_("This purchase order is already synced."))

        return self._sync_purchase_order_to_enterprise()

    def action_batch_sync_to_enterprise(self):
        """Sync multiple purchase orders"""
        selected_orders = self.filtered(lambda o: o.state == 'purchase')

        if not selected_orders:
            raise UserError(_("No confirmed purchase orders selected."))

        # Check if any are already synced
        synced_orders = selected_orders.filtered(lambda o: o.sync_state == 'synced')
        if synced_orders:
            raise UserError(
                _("%s order(s) are already synced. Please select only pending or failed orders.") %
                len(synced_orders)
            )

        return selected_orders._sync_purchase_order_to_enterprise()

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
    def cron_sync_purchase_orders_to_enterprise(self):
        """Automatic sync of pending purchase orders"""
        orders = self.search([
            ('state', '=', 'purchase'),
            ('sync_state', 'in', ('pending', 'failed'))
        ], limit=50)  # Limit to 50 per run

        if orders:
            try:
                orders._sync_purchase_order_to_enterprise()
            except UserError as e:
                _logger.warning("Cron sync failed: %s", str(e))
            except Exception as e:
                _logger.error("Cron sync error: %s", str(e))