/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { _t } from "@web/core/l10n/translation";

const numberBufferService = registry.category("services").get("number_buffer");
const originalStart = numberBufferService.start;

async function askPassword(component) {
    const pos = component.env.services.pos;
    const dialog = component.dialog;
    const notification = component.env.services.notification;

    const globalPwd = await pos.barcodeReader.orm.call(
        "pos.config",
        "fetch_global_refund_security",
        []
    );

    const password = globalPwd || pos.config.refund_security;
    if (!password) return true;

    return new Promise((resolve) => {
        dialog.add(NumberPopup, {
            title: _t("Enter Password"),
            placeholder: _t("Password"),
            formatDisplayedValue: (v) => v.replace(/./g, "•"),
            getPayload: (input) => {
                const ok = String(input) === String(password);
                if (!ok) {
                    notification.add(_t("Invalid Password"), {
                        type: "danger",
                        title: _t("Error"),
                    });
                }
                resolve(ok);
            },
        });
    });
}

patch(numberBufferService, {
    start(env, deps) {
        const buffer = originalStart.call(this, env, deps);
        const originalHandleInput = buffer._handleInput.bind(buffer);

        buffer._handleInput = async function (key) {
        const pos = this.component?.env?.services?.pos;
        const currentScreen = pos?.router?.state?.current;

        // 🚫 BLOCK KEYS IN PAYMENT SCREEN
        if (currentScreen === "PaymentScreen") {
            const blockedKeys = ["Delete", "Backspace", "0", "-"];
            if (blockedKeys.includes(key)) {
                return; // DO NOTHING
            }
        }

        const currentBuffer = this.get() || "";
        const isFirstInput = currentBuffer === "";

        let needsPassword = false;

        if (key === "Delete" || key === "Backspace") {
            needsPassword = true;
        } else if (key === "0" && (isFirstInput || currentBuffer === "-")) {
            needsPassword = true;
        } else if (key === "-") {
            needsPassword = true;
        }

        if (needsPassword) {
            const allowed = await askPassword(this.component);
            if (!allowed) {
                this.reset();
                return;
            }

            await this._performSensitiveAction(key);
            return;
        }

        return originalHandleInput(key);
    };

        // Add method to handle sensitive actions
        buffer._performSensitiveAction = async function (key) {
            const pos = this.component?.env?.services?.pos;
            if (!pos) return;

            const order = pos.getOrder();
            if (!order) {
                this.reset();
                return;
            }

            const selectedOrderline = order.getSelectedOrderline();
            if (!selectedOrderline) {
                this.reset();
                return;
            }

            // Handle Delete key
            if (key === "Delete") {
                order.removeOrderline(selectedOrderline);
                this.reset();
            }
            // Handle Backspace key - set quantity to 0 and remove if 0
            else if (key === "Backspace") {
                // Set quantity to 0
                selectedOrderline.qty = 0;
                // Remove the line since quantity is now 0
                order.removeOrderline(selectedOrderline);
                this.reset();  // Reset buffer after removing line
            }
            // Handle 0 key - remove if already 0, otherwise set to 0
            else if (key === "0") {
                // Check if quantity is already 0
                if (selectedOrderline.qty === 0) {
                    order.removeOrderline(selectedOrderline);
                    this.reset();  // Reset buffer after removing line
                } else {
                    // Set quantity to 0 and keep the line
                    selectedOrderline.qty = 0;
                    this.set("0");
                }
            }
            // Handle minus key - toggle sign
            else if (key === "-") {
                // Toggle sign
                selectedOrderline.qty = -selectedOrderline.qty;
                this.set(selectedOrderline.qty.toString());
            }
        };

        return buffer;
    },
});