/** @odoo-module */

import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

patch(PosStore.prototype, {
    async pay() {
        var self = this;
        let order = this.env.services.pos.getOrder();
        let lines = order.getOrderlines();
        let call_super = true;

        // تحقق إذا كان الإعداد مفعلًا
        if(this.env.services.pos.config.restrict_zero_qty){
            let prod_used_qty = {};
            let restrict = false;

            for (let line of lines) {
                let prd = line.product_id;
                let line_qty = line.qty;

                // تخطي إذا كانت الكمية سالبة (إرجاع)
                if (line_qty < 0) {
                    continue;
                }

                if (prd.type == 'consu'){
                    // تجميع الكميات للمنتجات
                    if(prd.id in prod_used_qty){
                        let old_qty = prod_used_qty[prd.id][1];
                        prod_used_qty[prd.id] = [prd.qty_available, line_qty + old_qty];
                    } else {
                        prod_used_qty[prd.id] = [prd.qty_available, line_qty];
                    }
                }

                // تحقق إذا كان المنتج نفذ من المخزون
                if (prd.type == 'consu' && line_qty > 0){
                    console.log('prd', prd);
                    console.log('prd.name', prd.name);
                    console.log('prd.is_storable', prd.is_storable);

                    // Only check stock for storable products
                    if(prd.qty_available <= 0 && prd.is_storable){
                        restrict = true;
                        call_super = false;
                        let warning = prd.display_name + ' is out of stock.';
                        this.dialog.add(AlertDialog, {
                            title: _t("Zero Quantity Not allowed"),
                            body: _t(warning),
                        });
                    }
                }
            }

            // تحقق الكمية الإجمالية فقط للكميات الموجبة
            if(restrict === false){
                for (let [product_id, pq] of Object.entries(prod_used_qty)) {
                    let product = self.models['product.product'].getBy('id', parseInt(product_id));
                    let available_qty = pq[0];
                    let ordered_qty = pq[1];

                    console.log('product', product);  // Changed from prd to product
                    console.log('product.name', product.name);
                    console.log('product.is_storable', product.is_storable);

                    // تحقق فقط إذا كانت الكمية المطلوبة موجبة
                    if (ordered_qty > 0 && product.is_storable) {  // Added is_storable check
                        let check = available_qty - ordered_qty;
                        let warning = product.display_name + ' is out of stock.';

                        if (product.type == 'consu'){
                            if (check < 0){
                                call_super = false;
                                this.dialog.add(AlertDialog, {
                                    title: _t('Deny Order'),
                                    body: _t(warning),
                                });
                            }
                        }
                    }
                }
            }
        }

        if(call_super){
            await super.pay();  // Added await
        }
    },
});