from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import format_datetime
import logging
from datetime import datetime
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    pos_order_ids = fields.One2many(
        'pos.order',
        'sale_order_id',
        string='POS Orders',
        help='POS orders created from this sale order'
    )

    is_converted_to_pos = fields.Boolean(
        string='Converted to POS',
        default=False,
        copy=False
    )

    pos_conversion_date = fields.Datetime(
        string='Conversion Date',
        copy=False
    )
    pos_order_count = fields.Integer(
        string='POS Orders Count',
        compute='_compute_pos_order_count',
        store=True,
        compute_sudo=True
    )


    @api.depends('pos_order_ids')
    def _compute_pos_order_count(self):
        for order in self:
            order.pos_order_count = len(order.pos_order_ids)

    def action_view_pos_orders(self):
        """
        Open the list view of POS orders created from this sale order
        """
        self.ensure_one()

        action = {
            'name': _('POS Orders'),
            'type': 'ir.actions.act_window',
            'res_model': 'pos.order',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.pos_order_ids.ids)],
            'context': {
                'create': False,  # Disable create button
                'edit': False,  # Disable edit button if needed
            },
        }

        # If there's only one POS order, open it directly in form view
        if len(self.pos_order_ids) == 1:
            action.update({
                'view_mode': 'form',
                'res_id': self.pos_order_ids.id,
                'views': [(False, 'form')],
            })

        return action

    def action_convert_to_pos_order(self):
        """
        Convert sale order to POS order and notify POS team
        """
        orders = self
        if not orders and self.env.context.get("active_ids"):
            orders = self.env['sale.order'].browse(self.env.context.get("active_ids", []))

        if not orders:
            return {'type': 'ir.actions.act_window_close'}

        created_pos_orders = []
        errors = []

        for sale_order in orders:
            try:
                # التحقق من بيانات البيع
                if not sale_order.partner_id:
                    raise UserError(_("Sale Order %s has no customer.") % sale_order.name)

                if not sale_order.partner_id.parent_id:
                    raise UserError(_("Customer %s has no company.") % sale_order.name)

                # الحصول على فرع POS المناسب (الشركة الفرعية)
                dest_company = self.env['res.company'].search([('partner_id', '=', sale_order.partner_id.parent_id.id)])
                print('dest_company',dest_company)

                # التحول إلى الشركة الهدف
                with self.env.cr.savepoint():
                    # البحث عن POS config للفرع باستخدام sudo للوصول عبر الشركات
                    pos_config = self.env['pos.config'].sudo().search([
                        ('company_id', '=', dest_company.id),
                        ('active', '=', True)
                    ], limit=1)

                    if not pos_config:
                        raise UserError(_("No active POS configuration found for company %s.") % dest_company.name)

                    # البحث عن جلسة POS مفتوحة
                    pos_session = self.env['pos.session'].sudo().search([
                        ('config_id', '=', pos_config.id),
                        ('state', '=', 'opened')
                    ], limit=1)

                    if not pos_session:
                        # محاولة فتح جلسة جديدة - نستخدم sudo للوصول عبر الشركات
                        try:
                            pos_session = pos_config.sudo().open_ui_pos_session()
                            if not pos_session:
                                raise UserError(_("Cannot open POS session for config %s.") % pos_config.name)
                        except Exception as e:
                            raise UserError(_("Cannot open POS session: %s") % str(e))

                    # إنشاء أمر POS باستخدام sudo
                    pos_order = self._create_pos_order_from_sale(sale_order, pos_session)

                    created_pos_orders.append({
                        'sale_order': sale_order,
                        'pos_order': pos_order,
                        'branch': dest_company,
                        'pos_session': pos_session
                    })

                    # إرسال الإشعارات
                    self._notify_pos_team(sale_order, pos_order, dest_company)

            except Exception as e:
                errors.append(_("Failed to convert sale order %s: %s") % (sale_order.name, str(e)))
                _logger.error("Error converting sale order %s to POS: %s", sale_order.name, str(e), exc_info=True)

        # إظهار رسالة الإنجاز
        return self._show_conversion_result(created_pos_orders, errors)

    def _create_pos_order_from_sale(self, sale_order, pos_session):
        """
        إنشاء POS order من sale order
        """
        # تحضير بيانات أمر POS
        pos_order_vals = {
            'name': 'SALE/' + sale_order.name,
            'session_id': pos_session.id,
            'partner_id': sale_order.partner_id.id,
            'date_order': fields.Datetime.now(),
            'company_id': pos_session.company_id.id,
            # 'sale_order_id': sale_order.id,  # رابط مع أمر البيع الأصلي
            'user_id': self.env.user.id,
            'amount_tax': sale_order.amount_tax,
            'amount_total': sale_order.amount_total,
            'sale_notes': html2plaintext(sale_order.note or ''),
            'amount_paid': 0,  # سيتم الدفع لاحقاً في POS
            'amount_return': 0,
            'state': 'draft',
        }

        # إنشاء أمر POS باستخدام sudo
        pos_order = self.env['pos.order'].sudo().with_company(pos_session.company_id.id).create(pos_order_vals)

        # إضافة المنتجات
        for line in sale_order.order_line:
            if line.display_type:
                continue
            self._create_pos_order_line(line, pos_order)

        # حفظ المرجع في أمر البيع
        sale_order.sudo().write({
            'pos_order_ids': [(4, pos_order.id)],
            'is_converted_to_pos': True,
            'pos_conversion_date': fields.Datetime.now(),
        })

        return pos_order

    def _create_pos_order_line(self, sale_line, pos_order):
        """
        إنشاء خط منتج في POS order
        """
        # البحث عن المنتج في POS باستخدام sudo
        product = self.env['product.product'].sudo().browse(sale_line.product_id.id)

        # التأكد من أن المنتج متاح في POS
        if not product.available_in_pos:
            product.sudo().write({'available_in_pos': True})

        # حساب الضرائب
        taxes = sale_line.tax_ids
        price_unit = sale_line.price_unit

        # إنشاء خط المنتج باستخدام sudo
        pos_line_vals = {
            'order_id': pos_order.id,
            'product_id': product.id,
            'qty': sale_line.product_uom_qty,
            'price_unit': price_unit,
            'price_subtotal': sale_line.price_subtotal,
            'price_subtotal_incl': sale_line.price_subtotal + sale_line.price_tax,
            'discount': sale_line.discount,
            'tax_ids': [(6, 0, taxes.ids)] if taxes else False,
            'name': sale_line.name,
            'full_product_name': sale_line.name,
            # 'sale_order_line_id': sale_line.id,  # رابط مع خط البيع الأصلي
        }

        # إنشاء خط المنتج مع السياق الصحيح للشركة
        return self.env['pos.order.line'].sudo().with_company(pos_order.company_id.id).create(pos_line_vals)

    def _notify_pos_team(self, sale_order, pos_order, dest_company):
        """
        إرسال إشعارات لتيم POS
        """
        # تحضير رسالة الإشعار
        message = _("""
🚀 New POS Order Created from Sale Order

✅ **Sale Order**: %(sale_order)s has been converted to POS Order
📍 **Branch**: %(branch)s
👤 **Customer**: %(customer)s
💰 **Amount**: %(amount)s
📦 **Items**: %(items_count)s products

You can open the POS order from the POS session.

POS Order: %(pos_order)s
""") % {
            'sale_order': sale_order.name,
            'branch': dest_company.name,
            'customer': sale_order.partner_id.name or 'Walk-in Customer',
            'amount': sale_order.amount_total,
            'items_count': len(sale_order.order_line),
            'pos_order': pos_order.name,
        }

        # الحصول على تيم POS للإشعارات في الشركة الهدف
        try:
            pos_group = self.env.ref('point_of_sale.group_pos_user')
            users_to_notify = self.env['res.users'].sudo().search([
                ('company_ids', 'in', [dest_company.id]),
                ('groups_id', 'in', [pos_group.id]),
                ('active', '=', True)
            ])
        except:
            users_to_notify = self.env['res.users']

        # إرسال إشعار داخلي
        notification_partner_ids = []
        for user in users_to_notify:
            if user.partner_id:
                notification_partner_ids.append(user.partner_id.id)

        if notification_partner_ids:
            try:
                # إرسال إشعار في أمر البيع
                sale_order.sudo().message_post(
                    body=message,
                    partner_ids=notification_partner_ids,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                    subject=_('POS Order Created from Sale Order')
                )

            except Exception as e:
                _logger.error("Failed to send internal notification: %s", str(e))

        # إرسال إشعارات Odoo Bot
        self._send_odoo_bot_notification(sale_order, pos_order, dest_company, users_to_notify)

    def _send_odoo_bot_notification(self, sale_order, pos_order, branch, users_to_notify):
        """
        إرسال إشعارات Odoo Bot لتيم POS
        """
        try:
            # إعداد رابط أمر POS
            base_url = sale_order.get_base_url()
            pos_order_url = f"{base_url}/web#id={pos_order.id}&model=pos.order&view_type=form"
            sale_order_url = f"{base_url}/web#id={sale_order.id}&model=sale.order&view_type=form"

            # إنشاء إشعار Odoo Bot
            notification_message = _("""
📋 **New POS Order Ready**

A new POS order has been created from Sale Order %(sale_order)s.

**Details:**
• Branch: %(branch)s
• Customer: %(customer)s
• Total Amount: %(amount)s %(currency)s
• Items: %(items_count)s products
• POS Order: %(pos_order)s

**Links:**
👉 [Open POS Order](%(pos_order_url)s)
📄 [View Sale Order](%(sale_order_url)s)

Please process this order in the POS system.
""") % {
                'sale_order': sale_order.name,
                'branch': branch.name,
                'customer': sale_order.partner_id.name or 'Walk-in Customer',
                'amount': sale_order.amount_total,
                'currency': sale_order.currency_id.symbol or '',
                'items_count': len(sale_order.order_line),
                'pos_order': pos_order.name,
                'pos_order_url': pos_order_url,
                'sale_order_url': sale_order_url,
            }

            # إرسال إشعار لكل مستخدم في تيم POS
            for user in users_to_notify:
                if user.active and user.partner_id:
                    try:
                        self.env['bus.bus'].sudo()._sendone(
                            user.partner_id,
                            'mail.message/notification',
                            {
                                'id': pos_order.id,
                                'message': notification_message,
                                'title': _('New POS Order Created'),
                                'type': 'info',
                                'sticky': True,
                            }
                        )
                    except Exception as e:
                        _logger.error("Failed to send bus notification to user %s: %s", user.name, str(e))

        except Exception as e:
            _logger.error("Failed to send Odoo bot notification: %s", str(e))

    def _show_conversion_result(self, created_pos_orders, errors):
        """
        عرض نتيجة التحويل
        """
        messages = []

        if created_pos_orders:
            success_msg = _("✅ Successfully converted %d sale order(s) to POS orders:") % len(created_pos_orders)
            messages.append(success_msg)

            for conv in created_pos_orders:
                messages.append(f"• {conv['sale_order'].name} → {conv['pos_order'].name} ({conv['branch'].name})")

        if errors:
            messages.append(_("❌ Errors:"))
            messages.extend(errors)

        if not created_pos_orders and not errors:
            messages.append(_("No orders were converted."))

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Conversion to POS Orders"),
                "message": "\n".join(messages),
                "sticky": True,
                "type": "success" if created_pos_orders and not errors else "warning",
            }
        }


class PosOrder(models.Model):
    _inherit = "pos.order"

    sale_order_id = fields.Many2one(
        'sale.order',
        string='Source Sale Order',
        ondelete='set null'
    )


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    sale_order_line_id = fields.Many2one(
        'sale.order.line',
        string='Source Sale Order Line',
        ondelete='set null'
    )