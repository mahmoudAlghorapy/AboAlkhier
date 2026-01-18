/** @odoo-module */

import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { patch } from "@web/core/utils/patch";

patch(ReceiptScreen.prototype, {
    setup() {
        super.setup();
    },

    get hideNewOrderButton() {
        const currentUser = this.pos.user_id || this.pos.cashier;
        return currentUser && currentUser.sbl_hide_pos_new_order_button || false;
    }
});