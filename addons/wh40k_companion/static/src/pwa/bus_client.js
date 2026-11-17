/** @odoo-module **/

import { busSubscribeFrame, busWebsocketUrl, parseBusFrame } from "./battle_helpers";

/**
 * Same-origin Odoo bus socket for one ``wh40k.match.<partner_id>`` channel.
 *
 * The standalone PWA does not boot the web client's bus service or its
 * SharedWorker. This talks to the same ``/websocket`` endpoint, with the
 * session cookie the browser already has. No second port.
 *
 * When the socket fails or drops, ``onConnection(false)`` tells the app to
 * keep using ``/wh40k/api/match/watch``.
 */
export function createMatchBus({
    partnerId,
    lastId = 0,
    version = "",
    onNotification,
    onConnection,
    WebSocketImpl,
    location: loc,
} = {}) {
    const WS = WebSocketImpl || (typeof WebSocket !== "undefined" ? WebSocket : null);
    let stopped = false;
    let connected = false;
    let socket = null;
    let retryMs = 1000;
    let last = Number.isInteger(lastId) ? lastId : 0;
    let retryTimer = null;

    function setConnected(value) {
        connected = !!value;
        if (onConnection) {
            onConnection(connected);
        }
    }

    function schedule() {
        if (stopped || retryTimer) {
            return;
        }
        const delay = retryMs;
        retryMs = Math.min(retryMs * 2, 15000);
        retryTimer = setTimeout(() => {
            retryTimer = null;
            connect();
        }, delay);
    }

    function connect() {
        if (stopped || !WS || !partnerId) {
            setConnected(false);
            return;
        }
        let next;
        try {
            next = new WS(busWebsocketUrl(loc, version));
        } catch (_e) {
            setConnected(false);
            schedule();
            return;
        }
        socket = next;
        next.onopen = () => {
            retryMs = 1000;
            try {
                next.send(JSON.stringify(busSubscribeFrame(partnerId, last)));
                setConnected(true);
            } catch (_e) {
                setConnected(false);
                try {
                    next.close();
                } catch (_close) {
                    // The close handler schedules the watch fallback.
                }
            }
        };
        next.onmessage = (ev) => {
            if (typeof ev.data !== "string") {
                return;
            }
            const frame = parseBusFrame(ev.data);
            if (Number.isInteger(frame.lastIdReset)) {
                last = frame.lastIdReset;
            }
            for (const note of frame.notifications) {
                if (Number.isInteger(note.id) && note.id > last) {
                    last = note.id;
                }
                if (onNotification && note.payload) {
                    onNotification(note.payload);
                }
            }
        };
        next.onerror = () => {
            setConnected(false);
        };
        next.onclose = (ev) => {
            setConnected(false);
            if (socket === next) {
                socket = null;
            }
            // An outdated worker version will not start working on retry.
            if (ev && ev.reason === "OUTDATED_VERSION") {
                stopped = true;
                return;
            }
            schedule();
        };
    }

    connect();
    return {
        get connected() {
            return connected;
        },
        stop() {
            stopped = true;
            if (retryTimer) {
                clearTimeout(retryTimer);
                retryTimer = null;
            }
            setConnected(false);
            if (socket) {
                const current = socket;
                socket = null;
                try {
                    current.close();
                } catch (_e) {
                    // Already closed.
                }
            }
        },
    };
}
