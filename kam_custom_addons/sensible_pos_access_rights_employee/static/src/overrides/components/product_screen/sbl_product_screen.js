import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";

patch(ProductScreen.prototype, {
    getNumpadButtons() {
        const buttons = super.getNumpadButtons();

        // Get current user - always available regardless of "Log in with Employees"
        const currentUser = this.pos.user_id || this.pos.cashier;

        if (!currentUser) {
            return buttons;
        }

        for (const button of buttons) {
            if (button.value === "quantity") {
                button.disabled = button.disabled || currentUser.sbl_disable_pos_qty;
            }
            if (button.value === "price") {
                button.disabled = button.disabled || currentUser.sbl_disable_pos_change_price;
            }
            if (button.value === "discount") {
                button.disabled = button.disabled || currentUser.sbl_disable_pos_discount_button;
            }
            if (button.value === "-") {
                button.disabled = button.disabled || currentUser.sbl_disable_pos_numpad_plus_minus;
            }
        }

        const clickButton = buttons.find(button => button.value === this.pos.numpadMode);
        if (clickButton) {
            for (const button of buttons) {
                if (!["quantity", "discount", "price", "-"].includes(button.value)) {
                    button.disabled = clickButton.disabled;
                }
            }
        }

        return buttons;
    },
});