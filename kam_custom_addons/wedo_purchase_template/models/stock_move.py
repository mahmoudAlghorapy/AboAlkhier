from odoo import models, fields, api, _
import logging
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)
class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def write(self, vals):
        if any(k in vals for k in ['quantity', 'product_uom_qty']):
            for line in self:
                if line.move_id.qty_confirmed or line.picking_id.qty_confirmed:
                    raise UserError(_("Quantity confirmed: you cannot change done quantity."))
        return super().write(vals)

class StockMove(models.Model):
    _inherit = 'stock.move'
    qty_confirmed = fields.Boolean(string="Quantity Confirmed", default=False)

    def _action_assign(self, force_qty=False):
        for move in self:
            if move.qty_confirmed or (move.picking_id and move.picking_id.qty_confirmed):
                return True
        return super()._action_assign(force_qty=force_qty)

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

            # print('all_related_names', all_related_names)

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
        if not self.env.context.get('skip_qty_confirmed_check'):
            if any(k in vals for k in ['quantity', 'product_uom_qty']):
                for move in self.sudo():
                    if move.qty_confirmed or (move.picking_id and move.picking_id.qty_confirmed):
                        raise UserError(_("Quantity is confirmed and cannot be changed."))
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

    sub_vendor_id = fields.Many2one(comodel_name="res.partner", string="Order For", store=True, redonly=False,
                                    required=False, compute="compute_sub_vendor_id")
    order_tag_ids = fields.Many2many(comodel_name="custom.order.tag", string="Order Tag",
                                     compute="compute_sub_vendor_id")
    ref_po_template_id = fields.Many2one('purchase.order.template', string='Ref Purchase template',
                                         compute="compute_sub_vendor_id")
    qty_confirmed = fields.Boolean(string="Quantity Confirmed", default=False)

    def action_confirm_quantity(self):
        for picking in self.sudo():
            related_pickings = picking._get_all_related_pickings()
            all_pickings = picking | related_pickings

            all_pickings.sudo().write({'qty_confirmed': True})

            # lock moves too
            all_pickings.mapped('move_ids').sudo().write({'qty_confirmed': True})

    def force_set_quantity(self):

        for rec in self.move_ids:
            rec.quantity = rec.product_uom_qty

    @api.depends('sale_id.sub_vendor_id', 'sale_id.order_tag_ids', 'purchase_id.sub_vendor_id',
                 'purchase_id.order_tag_ids', )
    def compute_sub_vendor_id(self):
        for rec in self:
            if rec.sale_id:
                rec.sub_vendor_id = rec.sale_id.sub_vendor_id.id
                rec.ref_po_template_id = rec.sale_id.ref_po_template_id.id
                rec.order_tag_ids = [(6, 0, rec.sale_id.order_tag_ids.ids)]
            elif rec.purchase_id:
                rec.sub_vendor_id = rec.purchase_id.sub_vendor_id.id
                rec.ref_po_template_id = rec.purchase_id.po_template_id.id
                rec.order_tag_ids = [(6, 0, rec.purchase_id.order_tag_ids.ids)]
            else:
                rec.sub_vendor_id = False
                rec.ref_po_template_id = False
                rec.order_tag_ids = False

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
                ('state', 'not in', ('cancel'))
            ])

        return related_pickings.filtered(lambda p: p.id != self.id)

    def _get_all_related_orders_across_companies(self):
        self.ensure_one()

        SaleOrder = self.env['sale.order'].sudo()
        PurchaseOrder = self.env['purchase.order'].sudo()

        start_names = set()

        if self.purchase_id:
            start_names.update([
                self.purchase_id.name,
                self.purchase_id.origin or '',
                self.purchase_id.partner_ref or '',
            ])

        if self.sale_id:
            start_names.update([
                self.sale_id.name,
                self.sale_id.origin or '',
            ])

        start_names = {n for n in start_names if n}

        if not start_names:
            return SaleOrder.browse(), PurchaseOrder.browse()

        # 🔥 TRACE FULL CHAIN
        all_names = set()
        for name in start_names:
            all_names |= self.env['stock.move']._trace_through_chain(name)

        _logger.info(f"🧾 Accounting chain resolved: {sorted(all_names)}")

        # 🔥 FETCH ALL ORDERS (ALL COMPANIES)
        sale_orders = SaleOrder.search([
            '|',
            ('name', 'in', list(all_names)),
            ('origin', 'in', list(all_names)),
        ])

        purchase_orders = PurchaseOrder.search([
            '|',
            ('name', 'in', list(all_names)),
            ('origin', 'in', list(all_names)),
        ])
        # print('sale_orders',sale_orders)
        # print('purchase_orders',purchase_orders)

        return sale_orders, purchase_orders

    def _create_and_post_bills(self, purchase_orders):
        for po in purchase_orders:
            po = po.sudo().with_company(po.company_id)

            # 🔄 Force recompute after receipt
            # po._compute_invoice_status()

            if po.invoice_status != 'to invoice':
                _logger.info(f"⏭️ PO {po.name} not invoiceable (status={po.invoice_status})")
                continue

            # ❌ Prevent duplicates
            if po.invoice_ids.filtered(lambda m: m.state != 'cancel'):
                continue

            invoice_action = po.action_create_invoice()
            if not invoice_action or not invoice_action.get('res_id'):
                continue

            bill = self.env['account.move'].browse(invoice_action['res_id'])
            bill.invoice_date = fields.Date.today()
            bill.action_post()

            _logger.info(f"🧾 Bill created & posted for PO {po.name}")

    def _so_has_negative_qty(self, so):
        return any(
            line.product_uom_qty < 0
            for line in so.order_line
            if not line.display_type
        )

    def _get_delivered_qty(self, so):
        return sum(
            line.qty_delivered
            for line in so.order_line
            if not line.display_type
        )

    def _is_so_fully_invoiced_for_delivery(self, so):
        for line in so.order_line.filtered(lambda l: not l.display_type):
            if abs(line.qty_invoiced) < abs(line.qty_delivered):
                return False
        return True

    def _create_refund_from_sale_order(self, so):
        Move = self.env['account.move']

        invoice_vals = so._prepare_invoice()
        invoice_vals.update({
            'move_type': 'out_refund',
            'invoice_origin': so.name,
        })

        lines = []
        for line in so.order_line.filtered(
                lambda l: not l.display_type and l.qty_delivered < 0
        ):
            lines.append((0, 0, {
                'product_id': line.product_id.id,
                'name': line.name,
                'quantity': abs(line.qty_delivered),  # 🔑 DELIVERED QTY
                'price_unit': line.price_unit,
                'tax_ids': [(6, 0, line.tax_ids.ids)],
                'sale_line_ids': [(6, 0, line.ids)],
            }))

        if not lines:
            return self.env['account.move']

        invoice_vals['invoice_line_ids'] = lines

        refund = Move.sudo().with_company(so.company_id).create(invoice_vals)
        refund.action_post()

        _logger.info("🧾 Refund created: %s for SO %s", refund.name, so.name)
        return refund

    def _create_and_post_invoices(self, sale_orders):
        created_moves = self.env['account.move']

        for so in sale_orders:
            so = so.sudo().with_company(so.company_id)

            delivered_qty = self._get_delivered_qty(so)
            if not delivered_qty:
                continue

            # 🔒 PREVENT DUPLICATES (THE FIX)
            if self._is_so_fully_invoiced_for_delivery(so):
                _logger.info("⏭️ SO %s already invoiced for delivered qty", so.name)
                continue

            # 🔴 RETURN → CREDIT NOTE
            if delivered_qty < 0:
                refund = self._create_refund_from_sale_order(so)
                created_moves |= refund

            # 🟢 NORMAL DELIVERY → INVOICE
            else:
                Move = self.env['account.move']

                invoice_vals = so._prepare_invoice()
                invoice_vals.update({
                    'move_type': 'out_invoice',
                    'invoice_origin': so.name,
                })

                lines = []
                for line in so.order_line.filtered(
                        lambda l: not l.display_type and l.qty_delivered > 0
                ):
                    lines.append((0, 0, {
                        'product_id': line.product_id.id,
                        'name': line.name,
                        'quantity': line.qty_delivered,
                        'price_unit': line.price_unit,
                        'tax_ids': [(6, 0, line.tax_ids.ids)],
                        'sale_line_ids': [(6, 0, line.ids)],
                    }))

                if not lines:
                    continue

                invoice_vals['invoice_line_ids'] = lines

                invoice = Move.sudo().with_company(so.company_id).create(invoice_vals)
                invoice.action_post()
                created_moves |= invoice

        _logger.info(
            "🧾 Customer moves created: %s",
            ", ".join(created_moves.mapped('name'))
        )

        return created_moves

    def write(self, vals):
        if not self.env.context.get('skip_qty_confirmed_check'):
            if 'move_ids' in vals or 'move_line_ids' in vals:
                for picking in self:
                    if picking.qty_confirmed:
                        raise UserError(_("This picking quantity is confirmed and cannot be modified."))

        return super().write(vals)

    def action_assign(self):
        for move in self:
            if move.qty_confirmed or (move.picking_id and move.picking_id.qty_confirmed):
                return True
        return super().action_assign()


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
                    move.sudo().with_context(skip_qty_confirmed_check=True).write({'product_uom_qty': qty})



                # Now validate safely
                super(StockPicking, rp).button_validate()
                _logger.info(f"✅ Auto-validated {rp.name}")

            except Exception as e:
                _logger.error(f"❌ Failed validating {rp.name}: {e}")
        sale_orders, purchase_orders = picking._get_all_related_orders_across_companies()


        # Vendor Bills (PO)
        picking._create_and_post_bills(purchase_orders)

        # Customer Invoices (SO)
        picking._create_and_post_invoices(sale_orders)

        return res
