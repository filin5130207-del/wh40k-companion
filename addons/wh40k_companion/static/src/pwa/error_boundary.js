/** @odoo-module **/

import { Component, xml, onError } from "@odoo/owl";

/**
 * Catches render errors so a single screen failure does not kill the PWA shell.
 */
export class Wh40kErrorBoundary extends Component {
    static template = xml`
        <t t-if="state.error">
            <section class="wh40k-panel">
                <h2>Something went wrong</h2>
                <p class="wh40k-error" t-esc="state.error"/>
                <button type="button" class="wh40k-btn wh40k-btn-primary" t-on-click="recover">
                    Back to home
                </button>
            </section>
        </t>
        <t t-else="">
            <t t-slot="default"/>
        </t>
    `;
    static props = {
        slots: { type: Object, optional: true },
        onRecover: { type: Function, optional: true },
    };

    setup() {
        this.state = { error: "" };
        onError((error) => {
            const message =
                (error && (error.cause?.message || error.message)) ||
                "Unexpected UI error";
            this.state.error = String(message);
            console.error("WH40k UI error", error);
        });
    }

    recover() {
        this.state.error = "";
        if (this.props.onRecover) {
            this.props.onRecover();
        }
    }
}
