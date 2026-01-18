from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _trace_through_chain(self, start_name, visited=None, depth=0):
        """Recursively trace through the entire order chain, ignoring access rights"""
        if visited is None:
            visited = set()

        if start_name in visited or not start_name or depth > 10:  # Safety limit
            return set()

        visited.add(start_name)
        all_related_names = set([start_name])
        indent = "  " * depth
        _logger.info(f"{indent}🔍 Depth {depth}: Tracing from: {start_name}")

        # Use sudo() to ignore access rights
        PurchaseOrder = self.env['purchase.order'].sudo()
        SaleOrder = self.env['sale.order'].sudo()

        # Find POs
        pos = PurchaseOrder.search([
            '|', '|', '|',
            ('origin', '=', start_name),
            ('partner_ref', '=', start_name),
            ('name', '=', start_name),
            ('partner_ref', 'ilike', f'%{start_name}%')
        ])

        for po in pos:
            _logger.info(f"{indent}  📥 Found PO: {po.name}")
            all_related_names.add(po.name)
            if po.origin and po.origin != po.name:
                all_related_names.update(self._trace_through_chain(po.origin, visited, depth + 1))
            if po.partner_ref and po.partner_ref not in [po.name, po.origin]:
                all_related_names.update(self._trace_through_chain(po.partner_ref, visited, depth + 1))
            if po.name != start_name:
                all_related_names.update(self._trace_through_chain(po.name, visited, depth + 1))

        # Find SOs
        sos = SaleOrder.search([
            '|', '|',
            ('origin', '=', start_name),
            ('name', '=', start_name),
            ('client_order_ref', '=', start_name)
        ])

        for so in sos:
            _logger.info(f"{indent}  📤 Found SO: {so.name}")
            all_related_names.add(so.name)
            if so.origin and so.origin != so.name:
                all_related_names.update(self._trace_through_chain(so.origin, visited, depth + 1))
            if so.name != start_name:
                all_related_names.update(self._trace_through_chain(so.name, visited, depth + 1))

            print('all_related_names',all_related_names)

        return all_related_names

    def _get_all_related_moves(self, move):
        """Get all related moves, bypassing access rights"""
        related_moves = self.env['stock.move'].sudo()
        product = move.product_id
        _logger.info(f"🔍 Finding related moves for move {move.id} (Product: {product.name})")

        start_names = set()

        if move.picking_id:
            picking = move.picking_id.sudo()
            if picking.purchase_id:
                po = picking.purchase_id
                start_names.update([po.name, po.origin or '', po.partner_ref or ''])
            elif picking.sale_id:
                so = picking.sale_id
                start_names.update([so.name, so.origin or ''])

        if not start_names:
            return related_moves

        all_related_names = set()
        for start_name in start_names:
            if start_name:
                all_related_names.update(self._trace_through_chain(start_name))

        _logger.info(f"🔗 All related order names in chain: {sorted(all_related_names)}")

        Picking = self.env['stock.picking'].sudo()

        for order_name in all_related_names:
            if not order_name:
                continue

            # PO pickings
            po_pickings = Picking.search([
                ('purchase_id.name', '=', order_name),
                ('state', 'not in', ['done', 'cancel'])
            ])
            related_moves |= po_pickings.mapped('move_ids').filtered(
                lambda m: m.product_id == product and m.id != move.id and m.state not in ('done', 'cancel')
            )

            # SO pickings
            so_pickings = Picking.search([
                ('sale_id.name', '=', order_name),
                ('state', 'not in', ['done', 'cancel'])
            ])
            related_moves |= so_pickings.mapped('move_ids').filtered(
                lambda m: m.product_id == product and m.id != move.id and m.state not in ('done', 'cancel')
            )

        _logger.info(f"🎯 Total related moves found: {len(related_moves)}")
        return related_moves

    def write(self, vals):
        """Override write to sync quantities across all related moves with sudo"""
        if self.env.context.get('skip_all_sync'):
            return super().write(vals)

        if 'quantity' not in vals and 'product_uom_qty' not in vals:
            return super().write(vals)

        res = super().write(vals)

        for move in self:
            related_moves = move._get_all_related_moves(move)
            if related_moves:
                update_vals = {}
                if 'quantity' in vals:
                    update_vals['quantity'] = move.quantity
                if 'product_uom_qty' in vals:
                    update_vals['product_uom_qty'] = move.product_uom_qty
                if update_vals:
                    try:
                        related_moves.with_context(skip_all_sync=True).sudo().write(update_vals)
                    except Exception as e:
                        _logger.error(f"❌ Failed to sync related moves: {str(e)}")
        return res


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _get_super_env(self):
        company_ids = self.env['res.company'].sudo().search([]).ids
        return self.env['stock.picking'].sudo().with_context(
            allowed_company_ids=company_ids
        )

    def _get_all_related_pickings(self):
        related_pickings = self.browse()
        start_names = set()

        if self.purchase_id:
            po = self.purchase_id.sudo()
            start_names.update([po.name, po.origin or '', po.partner_ref or ''])
        elif self.sale_id:
            so = self.sale_id.sudo()
            start_names.update([so.name, so.origin or ''])

        if not start_names:
            return related_pickings

        StockMove = self.env['stock.move']
        all_related_names = set()
        for name in start_names:
            all_related_names |= StockMove._trace_through_chain(name)

        _logger.info(f"🔗 Related chain: {sorted(all_related_names)}")

        PickingEnv = self._get_super_env()

        for name in all_related_names:
            if not name:
                continue
            related_pickings |= PickingEnv.search([
                '|',
                ('purchase_id.name', '=', name),
                ('sale_id.name', '=', name),
                ('state', 'not in', ('done', 'cancel'))
            ])

        return related_pickings.filtered(lambda p: p.id != self.id)

    def button_validate(self):
        if self.env.context.get('skip_intercompany_sync'):
            return super().button_validate()

        _logger.info(f"🚀 Validating picking: {self.name}")
        PickingEnv = self._get_super_env()
        picking = PickingEnv.browse(self.id).with_company(self.company_id)

        # Validate current picking
        res = super(StockPicking, picking).button_validate()
        _logger.info(f"✅ Validated {picking.name}")

        # Validate related pickings
        related_pickings = picking._get_all_related_pickings()
        if not related_pickings:
            return res

        _logger.info(f"🔄 Auto-validating {len(related_pickings)} related pickings")

        for rp in related_pickings:
            try:
                rp = rp.with_company(rp.company_id).with_context(skip_intercompany_sync=True)
                for move in rp.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
                    qty = move.quantity

                    # 🔑 Force product_uom_qty to match synced quantity
                    move.sudo().write({'product_uom_qty': qty})
                    #
                    # if move.move_line_ids:
                    #     # Update qty_done
                    #     move.move_line_ids.sudo().write({'quantity': qty})
                    # else:
                    #     # Create move line if missing
                    #     self.env['stock.move.line'].sudo().create({
                    #         'move_id': move.id,
                    #         'product_id': move.product_id.id,
                    #         'product_uom_id': move.product_uom.id,
                    #         'location_id': move.location_id.id,
                    #         'location_dest_id': move.location_dest_id.id,
                    #         'qty_done': qty,
                    #         'product_uom_qty': qty,
                    #         'picking_id': move.picking_id.id,
                    #     })

                # Now validate safely
                super(StockPicking, rp).button_validate()
                _logger.info(f"✅ Auto-validated {rp.name}")

            except Exception as e:
                _logger.error(f"❌ Failed validating {rp.name}: {e}")

        return res
