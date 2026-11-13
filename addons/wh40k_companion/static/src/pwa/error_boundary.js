/** @odoo-module **/

import { Component, onError, proxy, t, useProps, xml } from "@odoo/owl";

/**
 * Catches render errors so a single screen failure does not kill the PWA shell.
 */
export class Wh40kErrorBoundary extends Component {
    static template = xml`
        <t t-if="this.state.error">
            <section class="wh40k-panel">
                <h2>Something went wrong</h2>
                <p class="wh40k-error" t-esc="this.state.error"/>
                <button type="button" class="wh40k-btn wh40k-btn-primary" t-on-click="this.recover">
                    Back to home
                </button>
            </section>
        </t>
        <t t-else="">
            <t t-slot="default"/>
        </t>
    `;
    props = useProps({
        slots: t.object().optional(),
        onRecover: t.function().optional(),
    });

    setup() {
        this.state = proxy({ error: "" });
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
