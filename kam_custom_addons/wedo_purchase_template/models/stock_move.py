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

    def _create_and_post_invoices(self, sale_orders):
        for so in sale_orders:
            # print('so.name',so.name)
            # print('so.name',so.company_id.name)
            if so.invoice_status != 'to invoice':
                continue

            invoices = so._create_invoices()
            for inv in invoices:


                inv.action_post()

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
