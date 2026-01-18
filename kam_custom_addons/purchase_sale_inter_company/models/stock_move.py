from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)

class StockMove(models.Model):
    _inherit = 'stock.move'

    def _get_all_related_moves(self, move):
        """الحصول على جميع الحركات المرتبطة عبر جميع السيناريوهات - bidirectional"""
        related_moves = self.env['stock.move']
        product = move.product_id

        # 🔑 CASE 1: MTO Receipt (من purchase إلى sale)
        if move.picking_id and move.picking_id.purchase_id and move.picking_id.purchase_id.origin:
            sale_order = self.env['sale.order'].search([
                ('name', '=', move.picking_id.purchase_id.origin)
            ], limit=1)

            if sale_order:
                # كل حركات هذا الـ sale order لنفس المنتج
                sale_moves = sale_order.picking_ids.move_ids.filtered(
                    lambda m: m.product_id == product and m.state not in ('done', 'cancel')
                )
                related_moves |= sale_moves

                # البحث عن intercompany sales المرتبطة
                for sale_move in sale_moves:
                    if sale_move.sale_line_id:
                        # Intercompany receipt
                        if sale_move.sale_line_id.auto_purchase_line_id:
                            intercompany_moves = sale_move.sale_line_id.auto_purchase_line_id.move_ids.filtered(
                                lambda m: m.product_id == product and m.state not in ('done', 'cancel')
                            )
                            related_moves |= intercompany_moves

                        # Purchase lines العادية
                        for purchase_line in sale_move.sale_line_id.purchase_line_ids:
                            purchase_moves = purchase_line.move_ids.filtered(
                                lambda m: m.product_id == product and m.state not in ('done', 'cancel')
                            )
                            related_moves |= purchase_moves

        # 🔑 CASE 2: Intercompany receipt → البحث عن الـ sale order المرتبط
        elif move.purchase_line_id and move.purchase_line_id.intercompany_sale_line_id:
            sale_line = move.purchase_line_id.intercompany_sale_line_id

            # حركات الـ sale line
            sale_moves = sale_line.move_ids.filtered(
                lambda m: m.product_id == product and m.state not in ('done', 'cancel')
            )
            related_moves |= sale_moves

            # PO-MTO المرتبط (من خلال origin)
            for sale_move in sale_moves:
                if sale_move.picking_id.sale_id:
                    po_mto_moves = self.env['stock.move'].search([
                        ('product_id', '=', product.id),
                        ('picking_id.purchase_id.origin', '=', sale_move.picking_id.sale_id.name),
                        ('state', 'not in', ['done', 'cancel'])
                    ])
                    related_moves |= po_mto_moves

        # 🔑 CASE 3: Sale line (Delivery Order)
        elif move.sale_line_id:
            sale_line = move.sale_line_id

            # 🔄 البحث عن PO-MTO عبر origin (الاتجاه المعاكس)
            if sale_line.order_id:
                po_mto_moves = self.env['stock.move'].search([
                    ('product_id', '=', product.id),
                    ('picking_id.purchase_id.origin', '=', sale_line.order_id.name),
                    ('state', 'not in', ['done', 'cancel'])
                ])
                related_moves |= po_mto_moves

            # Intercompany purchases
            if sale_line.auto_purchase_line_id:
                intercompany_moves = sale_line.auto_purchase_line_id.move_ids.filtered(
                    lambda m: m.product_id == product and m.state not in ('done', 'cancel')
                )
                related_moves |= intercompany_moves

            # جميع purchase lines العادية
            for purchase_line in sale_line.purchase_line_ids:
                purchase_moves = purchase_line.move_ids.filtered(
                    lambda m: m.product_id == product and m.state not in ('done', 'cancel')
                )
                related_moves |= purchase_moves

        # 🔑 CASE 4: Origin PO Receipt (عادي - ليس MTO)
        # البحث في الاتجاه المعاكس عن sale orders مرتبطة
        elif move.purchase_line_id:
            purchase_line = move.purchase_line_id

            # البحث عن sale lines المرتبطة بهذا الـ purchase line
            sale_lines = self.env['sale.order.line'].search([
                ('purchase_line_ids', 'in', purchase_line.ids)
            ])

            for sale_line in sale_lines:
                # حركات الـ sale line
                sale_moves = sale_line.move_ids.filtered(
                    lambda m: m.product_id == product and m.state not in ('done', 'cancel')
                )
                related_moves |= sale_moves

                # البحث عن MTO receipts المرتبطة بهذا الـ sale order
                if sale_line.order_id:
                    po_mto_moves = self.env['stock.move'].search([
                        ('product_id', '=', product.id),
                        ('picking_id.purchase_id.origin', '=', sale_line.order_id.name),
                        ('state', 'not in', ['done', 'cancel'])
                    ])
                    related_moves |= po_mto_moves

        # إزالة الحركة الحالية
        return related_moves.filtered(lambda m: m.id != move.id)

    def write(self, vals):
        if self.env.context.get('skip_all_sync'):
            return super().write(vals)

        res = super().write(vals)

        if 'quantity' not in vals:
            return res

        for move in self:
            related_moves = move._get_all_related_moves(move)

            if related_moves:
                related_moves.with_context(skip_all_sync=True).write({
                    'quantity': move.quantity
                })

        return res


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _get_all_related_pickings(self, picking):
        """الحصول على جميع التحويلات المرتبطة عبر جميع السيناريوهات"""
        related_pickings = self.env['stock.picking']

        for move in picking.move_ids:
            product = move.product_id

            # 🔑 CASE 1: MTO Receipt (من purchase إلى sale)
            if move.picking_id.purchase_id and move.picking_id.purchase_id.origin:
                sale_order = self.env['sale.order'].search([
                    ('name', '=', move.picking_id.purchase_id.origin)
                ], limit=1)

                if sale_order:
                    # كل pickings لهذا الـ sale order لنفس المنتج
                    sale_pickings = sale_order.picking_ids.filtered(
                        lambda p: any(m.product_id == product for m in p.move_ids)
                                  and p.state not in ('done', 'cancel')
                    )
                    related_pickings |= sale_pickings

                    # البحث عن intercompany pickings
                    for sale_picking in sale_pickings:
                        for sale_move in sale_picking.move_ids.filtered(lambda m: m.product_id == product):
                            if sale_move.sale_line_id and sale_move.sale_line_id.auto_purchase_line_id:
                                intercompany_pickings = sale_move.sale_line_id.auto_purchase_line_id.move_ids.picking_id.filtered(
                                    lambda p: p.state not in ('done', 'cancel')
                                )
                                related_pickings |= intercompany_pickings

                            # Purchase pickings العادية
                            if sale_move.sale_line_id:
                                for purchase_line in sale_move.sale_line_id.purchase_line_ids:
                                    purchase_pickings = purchase_line.move_ids.picking_id.filtered(
                                        lambda p: p.state not in ('done', 'cancel')
                                    )
                                    related_pickings |= purchase_pickings

            # 🔑 CASE 2: Intercompany receipt → البحث عن الـ sale pickings المرتبطة
            elif move.purchase_line_id and move.purchase_line_id.intercompany_sale_line_id:
                sale_line = move.purchase_line_id.intercompany_sale_line_id

                # pickings الـ sale line
                sale_pickings = sale_line.move_ids.picking_id.filtered(
                    lambda p: p.state not in ('done', 'cancel')
                )
                related_pickings |= sale_pickings

                # PO-MTO المرتبط (من خلال origin)
                for sale_picking in sale_pickings:
                    if sale_picking.sale_id:
                        po_mto_pickings = self.env['stock.picking'].search([
                            ('purchase_id.origin', '=', sale_picking.sale_id.name),
                            ('state', 'not in', ['done', 'cancel']),
                            ('move_ids.product_id', '=', product.id)
                        ])
                        related_pickings |= po_mto_pickings

            # 🔑 CASE 3: Sale line (Delivery Order)
            elif move.sale_line_id:
                sale_line = move.sale_line_id

                # 🔄 البحث عن PO-MTO عبر origin (الاتجاه المعاكس)
                if sale_line.order_id:
                    po_mto_pickings = self.env['stock.picking'].search([
                        ('purchase_id.origin', '=', sale_line.order_id.name),
                        ('state', 'not in', ['done', 'cancel']),
                        ('move_ids.product_id', '=', product.id)
                    ])
                    related_pickings |= po_mto_pickings

                # Intercompany purchases
                if sale_line.auto_purchase_line_id:
                    intercompany_pickings = sale_line.auto_purchase_line_id.move_ids.picking_id.filtered(
                        lambda p: p.state not in ('done', 'cancel')
                    )
                    related_pickings |= intercompany_pickings

                # جميع purchase pickings العادية
                for purchase_line in sale_line.purchase_line_ids:
                    purchase_pickings = purchase_line.move_ids.picking_id.filtered(
                        lambda p: p.state not in ('done', 'cancel')
                    )
                    related_pickings |= purchase_pickings

            # 🔑 CASE 4: Origin PO Receipt (عادي - ليس MTO)
            elif move.purchase_line_id:
                purchase_line = move.purchase_line_id

                # البحث عن sale pickings المرتبطة بهذا الـ purchase line
                sale_lines = self.env['sale.order.line'].search([
                    ('purchase_line_ids', 'in', purchase_line.ids)
                ])

                for sale_line in sale_lines:
                    # pickings الـ sale line
                    sale_pickings = sale_line.move_ids.picking_id.filtered(
                        lambda p: p.state not in ('done', 'cancel')
                    )
                    related_pickings |= sale_pickings

                    # البحث عن MTO pickings المرتبطة بهذا الـ sale order
                    if sale_line.order_id:
                        po_mto_pickings = self.env['stock.picking'].search([
                            ('purchase_id.origin', '=', sale_line.order_id.name),
                            ('state', 'not in', ['done', 'cancel']),
                            ('move_ids.product_id', '=', product.id)
                        ])
                        related_pickings |= po_mto_pickings

        # إزالة الـ picking الحالي
        return related_pickings.filtered(lambda p: p.id != picking.id)

    def button_validate(self):
        """تأكيد التحويل ومزامنة جميع التحويلات المرتبطة"""
        if self.env.context.get('skip_intercompany_sync'):
            return super().button_validate()

        res = super().button_validate()

        for picking in self:
            # الحصول على جميع التحويلات المرتبطة
            related_pickings = picking._get_all_related_pickings(picking)

            if related_pickings:
                # تأكيد كل picking بشكل منفصل لتجنب مشكلة singleton
                for related_picking in related_pickings:
                    try:
                        related_picking.with_context(skip_intercompany_sync=True).button_validate()
                    except Exception as e:
                        # تسجيل الخطأ والمتابعة مع باقي التحويلات
                        _logger.warning(
                            f"Failed to auto-validate picking {related_picking.name}: {str(e)}"
                        )

        return res