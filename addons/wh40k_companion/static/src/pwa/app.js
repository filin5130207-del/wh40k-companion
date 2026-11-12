/** @odoo-module **/

import { whenReady } from "@odoo/owl";
import { mountComponent } from "@web/env";
import { Wh40kCompanionApp } from "./companion_app";

whenReady(() => {
    mountComponent(Wh40kCompanionApp, document.body, {
        name: "WH40k Battle App",
    });
    // Register service worker for installable shell / static asset cache.
    if ("serviceWorker" in navigator) {
        navigator.serviceWorker.register("/wh40k/sw.js", { scope: "/wh40k/" }).catch(() => {
            // Non-fatal: PWA still works without offline shell.
        });
    }
});
