import { patch } from "@web/core/utils/patch";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

// Refund password validation and popup
patch(TicketScreen.prototype, {
    setup() {
        // Initialize necessary services
        super.setup(...arguments);
        this.notification = useService("notification");
    },

    async onDoRefund() {
        try {
            // Fetch global and session refund passwords
            const globalRefundPassword = await this.pos.barcodeReader.orm.call("pos.config", "fetch_global_refund_security", []);
            const sessionRefundPassword = globalRefundPassword || this.pos.config.refund_security;

            // Determine the error message for invalid password
            const errorMessage = globalRefundPassword
                ? _t('Invalid Password, Enter your global password')
                : _t('Incorrect Password');

            // Trigger popup for password validation if sessionRefundPassword exists
            if (sessionRefundPassword) {
                this.dialog.add(NumberPopup, {
                    title: _t("Confirm ?"),
                    placeholder: _t("Enter Password"),
                    formatDisplayedValue: (input) => input.replace(/./g, "•"),
                    getPayload: (inputPassword) => {
                        if (inputPassword == sessionRefundPassword) {
                            // Proceed with refund if password is correct
                            super.onDoRefund(...arguments);
                        } else {
                            // Show notification if the password is incorrect
                            this.notification.add(errorMessage, {
                                type: "warning",
                                title: _t("Error"),
                            });
                        }
                    },
                });
            } else {
                // Proceed with refund without password validation
                super.onDoRefund(...arguments);
            }
        } catch (error) {
            // Handle any potential errors during the async process
            console.error("Error during refund password validation:", error);
        }
    },
});
