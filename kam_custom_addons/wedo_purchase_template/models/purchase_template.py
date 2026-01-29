from odoo import models, fields, api, _
from dateutil.relativedelta import relativedelta
from odoo.exceptions import AccessError, LockError, MissingError, ValidationError, UserError


class PurchaseOrderTemplate(models.Model):
    _name = 'purchase.order.template'
    # _inherit = "multi.company.abstract"
    _description = 'Purchase Template'

    name = fields.Char(required=True)
    vendor_ids = fields.Many2many('res.partner', string='Vendors')
    vendor_id = fields.Many2one(comodel_name="res.partner", string="Vendor", required=False, )
    sub_vendor_id = fields.Many2one(comodel_name="res.partner", string="Sub Vendor", required=False, )
    po_template_line_ids = fields.One2many('purchase.order.template.line', 'po_template_id', string='Lines', copy=True)
    note = fields.Text('Terms and conditions', translate=True)
    active = fields.Boolean('Active', default=True)
    company_id = fields.Many2one(string='Sub Vendor', comodel_name='res.company', default=lambda self: self.env.company)
    order_tag_ids = fields.Many2many(comodel_name="custom.order.tag", string="Order Tag", )
    company_ids = fields.Many2many(
        string="Companies",
        comodel_name="res.company",
    )
    internal_transfer = fields.Boolean(string="Push To Companies", )
    company_partner_ids = fields.Many2many(
        'res.partner',
        compute='_compute_company_partner_ids',
        store=False
    )

    def _compute_company_partner_ids(self):
        companies = self.env['res.company'].search([])
        partner_ids = companies.mapped('partner_id').ids
        for rec in self:
            rec.company_partner_ids = partner_ids


class PurchaseOrderTemplateLine(models.Model):
    _name = 'purchase.order.template.line'
    _description = "Purchase Template Line"
    _order = 'po_template_id, sequence, id'

    po_template_id = fields.Many2one(
        'purchase.order.template', string='Purchase Template Reference',
        required=True, ondelete='cascade', index=True)
    name = fields.Text('Description', required=False, translate=True)
    product_id = fields.Many2one('product.product', 'Product', required=False, domain=[('purchase_ok', '=', True)])
    product_qty = fields.Float('Quantity', required=True, default=1)
    product_uom_id = fields.Many2one('uom.uom', 'Unit of Measure', readonly=False, compute='_compute_product_uom_id')
    # product_uom_category_id = fields.Many2one(related='product_id.uom_id.category_id', readonly=True)
    sequence = fields.Integer('Sequence', default=10)
    display_type = fields.Selection([
        ('line_section', "Section"),
        ('line_note', "Note")], default=False, help="Technical field for UX purpose.")
    # tax_ids = fields.Many2many('account.tax', string='Taxes', context={'active_test': False, 'hide_original_tax_ids': True})
    price_unit = fields.Float(
        string='Unit Price', required=True, readonly=False, digits='Product Price',
        compute='_compute_price_unit', store=True)

    @api.depends('product_id')
    def _compute_price_unit(self):
        for line in self:
            if line.product_id:
                line.price_unit = line.product_id.standard_price
            else:
                line.price_unit = 0.0

    @api.onchange('product_id')
    def _compute_product_uom_id(self):
        for rec in self:
            if rec.product_id:
                rec.product_uom_id = rec.product_id.uom_id.id

    @api.onchange('product_id')
    def _onchange_product_id(self):
        self.ensure_one()
        if self.product_id:
            name = self.product_id.display_name
            if self.product_id.description_purchase:
                name += '\n' + self.product_id.description_purchase
            self.name = name
            self.product_uom_id = self.product_id.uom_id.id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('display_type', self.default_get(['display_type'])['display_type']):
                vals.update(product_id=False, product_qty=0, product_uom_id=False)
        return super(PurchaseOrderTemplateLine, self).create(vals_list)

    def write(self, vals):
        if 'display_type' in vals and self.filtered(lambda line: line.display_type != vals.get('display_type')):
            raise UserError(
                _("You cannot change the type of a purchase quote line. Instead you should delete the current line and create a new line of the proper type."))
        return super(PurchaseOrderTemplateLine, self).write(vals)


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'
    date_planned = fields.Datetime(
        string='Expected Arrival', index=True, default=fields.Datetime.now,
        compute="_compute_price_unit_and_date_planned_and_name", readonly=False, store=True,
        help="Delivery date expected from vendor. This date respectively defaults to vendor pricelist lead time then today's date.")

    @api.depends('product_qty', 'product_uom_id', 'company_id', 'order_id.partner_id')
    def _compute_price_unit_and_date_planned_and_name(self):
        returned_lines = self.filtered(
            lambda l: l.order_id.is_returned_order
        )

        super(PurchaseOrderLine, self - returned_lines) \
            ._compute_price_unit_and_date_planned_and_name()

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    po_template_id = fields.Many2one('purchase.order.template', string='Purchase template')
    sub_vendor_id = fields.Many2one(comodel_name="res.partner", string="Order For", required=False, )
    order_tag_ids = fields.Many2many(comodel_name="custom.order.tag", string="Order Tag", )
    ref_po_template_id = fields.Many2one('purchase.order.template', string='Ref Purchase template')
    is_returned_order = fields.Boolean(string="Is Returned Order",  )

    def _prepare_invoice(self):
        invoice_vals = super()._prepare_invoice()
        invoice_vals['order_tag_ids'] = [(6, 0, self.order_tag_ids.ids)]
        invoice_vals['sub_vendor_id'] = self.sub_vendor_id.id
        return invoice_vals

    def write(self, vals):
        res = super().write(vals)

        # 🔁 Only when is_returned_order is explicitly changed
        if 'is_returned_order' in vals:
            for order in self:
                for line in order.order_line:
                    # Skip section / note lines
                    if line.display_type:
                        continue

                    if order.is_returned_order:
                        line.product_qty = -abs(line.product_qty)
                    else:
                        line.product_qty = abs(line.product_qty)

        return res

    # sub_company_id = fields.Many2one(string='Order For', comodel_name='res.company', default=lambda self: self.env.company)
    def button_confirm(self):
        # 1️⃣ Remove zero quantity lines before confirm
        for order in self:
            zero_qty_lines = order.order_line.filtered(lambda l: l.product_qty == 0)
            zero_qty_lines.unlink()

        # 2️⃣ Call standard Odoo confirm
        res = super(PurchaseOrder, self).button_confirm()

        # 3️⃣ After confirm → create related orders
        for order in self:
            if order.po_template_id:
                if order.po_template_id.internal_transfer:
                    order.with_context(skip_intercompany=True)._create_related_orders_from_template()
            if order.picking_ids:
                for pic in order.picking_ids:
                    for move in pic.move_ids:
                        move.quantity = 0.0


        return res

        # ---------------------------------------------------------
        # Prepare SO values
        # ---------------------------------------------------------

    def _prepare_so_vals(self, partner, company):
        self.ensure_one()

        warehouse = self.env['stock.warehouse'].with_company(company).sudo().search(
            [('company_id', '=', company.id)], limit=1)

        # if not warehouse:
        #     raise UserError(_("No warehouse found for company %s") % company.name)

        # Get MTO route
        mto_route = self.env.ref('stock.route_warehouse0_mto', raise_if_not_found=False)

        return {
            'partner_id': partner.id,
            'company_id': company.id,
            'sub_vendor_id': self.sub_vendor_id.id,
            'ref_po_template_id': self.po_template_id.id,
            'order_tag_ids': [(6, 0, self.po_template_id.order_tag_ids.ids)],
            # 'warehouse_id': warehouse.id,
            'origin': self.name,
            'order_line': [(0, 0, {
                'product_id': line.product_id.id,
                'name': line.name,
                'product_uom_qty': line.product_qty,
                'product_uom_id': line.product_uom_id.id,
                'price_unit': line.price_unit,
                'tax_ids': line.tax_ids.ids,
                # CORRECTED: Use route_ids instead of route_id
                # 'route_ids': [(6, 0, [mto_route.id])] if mto_route else [],
            }) for line in self.order_line if not line.display_type],
        }

        # ---------------------------------------------------------
        # Prepare PO values
        # ---------------------------------------------------------

    def _prepare_po_vals(self, partner, company):
        self.ensure_one()

        order_lines = []

        for line in self.order_line.filtered(lambda l: not l.display_type):
            product = line.product_id
            # print('company',company.name)
            # print('product',product)

            # 1️⃣ فلترة Vendor Pricelist حسب:
            # - Vendor
            # - Company (أو global)
            product_c = product.with_company(company)

            sellers = product_c.seller_ids.filtered(
                lambda s:
                (not s.company_id or s.company_id == company)
                and s.min_qty <= line.product_qty
            )

            seller = sellers.sorted(
                key=lambda s: s.min_qty, reverse=True
            )[:1]

            price_unit = seller.price if seller else product_c.standard_price

            order_lines.append((0, 0, {
                'product_id': product.id,
                'name': line.name,
                'product_qty': line.product_qty,
                'product_uom_id': line.product_uom_id.id,
                'price_unit': price_unit,
                'date_planned': fields.Datetime.now(),
            }))

        return {
            'partner_id': partner.id,
            'company_id': company.id,
            'ref_po_template_id': self.po_template_id.id,
            'origin': self.name,
            'sub_vendor_id': self.sub_vendor_id.id,
            'order_tag_ids': [(6, 0, self.po_template_id.order_tag_ids.ids)],
            'order_line': order_lines,
        }

        # ---------------------------------------------------------
        # Create related SO / PO
        # ---------------------------------------------------------

    def _create_related_orders_from_template(self):
        self = self.sudo()
        self.ensure_one()

        SaleOrder = self.env['sale.order']
        PurchaseOrder = self.env['purchase.order']
        Company = self.env['res.company']

        template = self.po_template_id
        po = False

        # =====================================================
        # 1️⃣ vendor_id → SO + PO (both confirmed)
        # =====================================================
        if template.vendor_id:
            vendor = template.vendor_id

            company = Company.sudo().search([('partner_id', '=', vendor.id)], limit=1)
            if not company:
                raise UserError(_("No company found for vendor %s") % vendor.display_name)

            # --- Sale Order ---
            origin_partner = self.env.company.partner_id
            order_for = template.sub_vendor_id or origin_partner
            so_vals = self._prepare_so_vals(origin_partner, company)
            so = SaleOrder.with_company(company).with_context(skip_intercompany=True).sudo().create(so_vals)
            if not self.partner_ref:
                self.partner_ref = so.name
                # print('self.partner_ref',self.partner_ref)
            so.with_company(company).with_context(skip_intercompany=True).sudo().action_confirm()

            # --- Purchase Order ---
            if template.sub_vendor_id:
                po_vals = self._prepare_po_vals(order_for, company)
                po = PurchaseOrder.with_context(skip_intercompany=True).with_company(company).sudo().create(po_vals)
                if not po.origin:
                    po.origin = so.name
                po.with_company(company).with_context(skip_intercompany=True).sudo().button_confirm()
                if po.picking_ids:
                    for pic in po.picking_ids:
                        for move in pic.move_ids:
                            move.quantity = 0.0

        # =====================================================
        # 2️⃣ sub_vendor_id → SO only (draft)
        # =====================================================
        if template.sub_vendor_id:
            sub_vendor = template.sub_vendor_id
            vendor = template.vendor_id

            company = Company.sudo().search([('partner_id', '=', sub_vendor.id)], limit=1)
            # if not company:
            #     raise UserError(_("No company found for sub vendor %s") % sub_vendor.display_name)
            if company:

                so_vals = self._prepare_so_vals(vendor, company)

                second_so = SaleOrder.with_context(skip_intercompany=True).with_company(company).sudo().create(so_vals)
                second_so.origin =  po.name
                po_lines = po.order_line.filtered(lambda l: not l.display_type)
                so_lines = second_so.order_line.filtered(lambda l: not l.display_type)

                for po_line, so_line in zip(po_lines, so_lines):
                    so_line.write({
                        'price_unit': po_line.price_unit
                    })

                second_so.with_company(company).with_context(skip_intercompany=True).sudo().action_confirm()
                if not po.partner_ref:
                    po.partner_ref = second_so.name
                # print('po.partner_ref',po.partner_ref)

    @api.onchange('po_template_id')
    def onchange_po_template_id(self):
        for rec in self:
            if not rec.po_template_id:
                continue

            rec.order_line = [(5, 0, 0)]
            rec.order_line = [(0, 0, {
                'name': g.name,
                'sequence': g.sequence,
                'product_id': g.product_id.id,
                'product_qty': g.product_qty,
                'product_uom_id': g.product_uom_id.id,
                'date_planned': fields.Datetime.now(),
                'price_unit': g.price_unit,
                'display_type': g.display_type,
            }) for g in rec.po_template_id.po_template_line_ids]

            rec.note = rec.po_template_id.note
            rec.partner_id = rec.po_template_id.vendor_id
            rec.sub_vendor_id = self.env.company.partner_id.id

            # ✅ Many2many assignment الصحيح
            rec.order_tag_ids = [(6, 0, rec.po_template_id.order_tag_ids.ids)]
            # for line in  rec.order_line:
            #     line.onchange_product_id()

    @api.onchange('is_returned_order')
    def _onchange_is_returned_order(self):
        for order in self:
            if not order.order_line:
                return

            for line in order.order_line:
                # Skip section / note lines
                if line.display_type:
                    continue

                if order.is_returned_order:
                    line.product_qty = -abs(line.product_qty)
                else:
                    line.product_qty = abs(line.product_qty)

    @api.constrains('is_returned_order', 'order_line')
    def _check_return_order_quantities(self):
        for order in self:
            if not order.is_returned_order:
                continue

            invalid_lines = order.order_line.filtered(
                lambda l: not l.display_type and l.product_qty > 0
            )

            if invalid_lines:
                raise ValidationError(_(
                    "This is a returned order.\n"
                    "All product quantities must be negative.\n\n"
                    "Please fix the quantities before saving."
                ))
