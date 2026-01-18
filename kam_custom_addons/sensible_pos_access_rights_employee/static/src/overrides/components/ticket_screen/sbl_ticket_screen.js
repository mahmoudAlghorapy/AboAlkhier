import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { patch } from "@web/core/utils/patch";

patch(TicketScreen.prototype, {
    shouldHideDeleteButton(order) {
        const currentUser = this.pos.user_id || this.pos.cashier;
        if (currentUser && currentUser.sbl_hide_pos_delete_order_button) {
            return true;
        }
        return super.shouldHideDeleteButton(order);
    },
    getFilteredOrderList() {
        let orders = super.getFilteredOrderList();
        const currentUser = this.pos.user_id || this.pos.cashier;

        // If using employees, filter by employee_id, otherwise filter by user_id
        if (currentUser && this.pos.employees && this.pos.employees.length > 0) {
            // "Log in with Employees" is enabled
            orders = orders.filter(order => !order.employee_id || order.employee_id.id === currentUser.id);
        } else {
            // "Log in with Employees" is disabled
            orders = orders.filter(order => !order.user_id || order.user_id.id === currentUser.id);
        }
        return orders;
    },
    isHighlighted(order) {
        if (!this.getFilteredOrderList().length) {
            return false;
        }
        return super.isHighlighted(order);
    }
});