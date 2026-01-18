/** @odoo-module */

import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { patch } from "@web/core/utils/patch";

patch(TicketScreen.prototype, {
       shouldHideDeleteButton(order) {
       const currentUser = this.pos?.user;
       if (currentUser && currentUser.restrict_delete_access) {
            return true;
        }

        return super.shouldHideDeleteButton(order);
       },
});