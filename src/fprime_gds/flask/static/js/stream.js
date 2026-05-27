/**
 * stream.js:
 *
 * WebSocket telemetry stream client. Replaces the REST polling for the
 * /channels and /events endpoints when the server has the streaming route
 * registered.
 *
 * The client preserves the same on-the-wire shape used by the REST polling
 * handlers (each pushed message contains a single history-style item) so
 * the datastore can reuse its existing ListHistory/MappedHistory machinery
 * unchanged.
 *
 * The client subscribes to all channels and events by default. The active
 * subscription set may be narrowed via the advanced settings tab. Backoff
 * reconnection is built in so a momentary server restart does not require
 * a page reload.
 */

const ENVELOPE_TYPE_CHANNEL = "channel";
const ENVELOPE_TYPE_EVENT = "event";
const ENVELOPE_TYPE_COMMAND = "command";
const ENVELOPE_TYPE_HELLO = "hello";
const ENVELOPE_TYPE_ERROR = "error";

const RECONNECT_MS_MIN = 250;
const RECONNECT_MS_MAX = 5000;

class StreamClient {
    /**
     * @param {string} url - WebSocket URL (defaults to /api/stream on current origin).
     * @param {object} handlers - Map of endpoint name ("channels" | "events" | "command_history")
     *     to a function called with an array of new items. Same shape as a
     *     poller callback in the existing REST plumbing.
     */
    constructor(url, handlers) {
        this.url = url || StreamClient.defaultUrl();
        this.handlers = handlers || {};
        this.ws = null;
        this.connected = false;
        this.shutdown = false;
        this._reconnectMs = RECONNECT_MS_MIN;
        this._subscription = {
            channels: "all",
            events: true,
            commands: true,
        };
        this._listeners = {
            statechange: [],
        };
        this._counters = {
            received: 0,
            errors: 0,
            reconnects: 0,
        };
    }

    static defaultUrl() {
        let proto = (window.location.protocol === "https:") ? "wss:" : "ws:";
        return `${proto}//${window.location.host}/api/stream`;
    }

    /**
     * Open the connection. Idempotent; calling twice does nothing.
     */
    start() {
        if (this.shutdown || this.ws) {
            return;
        }
        this._open();
    }

    /**
     * Close the connection permanently. Use when switching transport modes.
     */
    stop() {
        this.shutdown = true;
        if (this.ws) {
            try {
                this.ws.close();
            } catch (e) {
                // ignore
            }
            this.ws = null;
        }
        this._setConnected(false);
    }

    /**
     * Replace the active subscription. Sends a `replace` op to the server.
     */
    setSubscription({channels, events, commands}) {
        if (channels !== undefined) {
            this._subscription.channels = channels;
        }
        if (events !== undefined) {
            this._subscription.events = events;
        }
        if (commands !== undefined) {
            this._subscription.commands = commands;
        }
        this._sendSubscription("replace");
    }

    /**
     * Subscribe to a listing of extra channel ids without disturbing existing.
     */
    subscribeChannels(channels) {
        if (this._subscription.channels === "all") {
            return;
        }
        if (!Array.isArray(this._subscription.channels)) {
            this._subscription.channels = [];
        }
        for (let id of channels) {
            if (this._subscription.channels.indexOf(id) === -1) {
                this._subscription.channels.push(id);
            }
        }
        this._send({op: "subscribe", channels: channels});
    }

    /**
     * Register a listener for connection state changes.
     */
    on(event, fn) {
        if (this._listeners[event]) {
            this._listeners[event].push(fn);
        }
    }

    counters() {
        return Object.assign({}, this._counters);
    }

    // ------------------------------------------------------------------
    // Internals
    // ------------------------------------------------------------------
    _open() {
        try {
            this.ws = new WebSocket(this.url);
        } catch (e) {
            this._scheduleReconnect();
            return;
        }
        this.ws.onopen = () => {
            this._reconnectMs = RECONNECT_MS_MIN;
            this._setConnected(true);
            // The server-side default is "subscribe to everything", so we
            // only send a ``replace`` payload when the caller has narrowed
            // the subscription away from "all".
            let sub = this._subscription;
            let narrowed = (sub.channels !== "all" && sub.channels !== true)
                || sub.events === false
                || sub.commands === false;
            if (narrowed) {
                this._sendSubscription("replace");
            }
        };
        this.ws.onclose = () => this._handleClose();
        this.ws.onerror = () => {
            this._counters.errors += 1;
        };
        this.ws.onmessage = (event) => this._dispatch(event.data);
    }

    _handleClose() {
        if (this.ws) {
            this.ws = null;
        }
        this._setConnected(false);
        if (!this.shutdown) {
            this._scheduleReconnect();
        }
    }

    _scheduleReconnect() {
        this._counters.reconnects += 1;
        let delay = this._reconnectMs;
        this._reconnectMs = Math.min(this._reconnectMs * 2, RECONNECT_MS_MAX);
        setTimeout(() => {
            if (!this.shutdown) {
                this._open();
            }
        }, delay);
    }

    _setConnected(value) {
        if (this.connected !== value) {
            this.connected = value;
            for (let fn of this._listeners.statechange) {
                try { fn(value); } catch (e) { /* swallow */ }
            }
        }
    }

    _sendSubscription(op) {
        this._send({
            op: op,
            channels: this._subscription.channels,
            events: this._subscription.events,
            commands: this._subscription.commands,
        });
    }

    _send(message) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            return false;
        }
        try {
            this.ws.send(JSON.stringify(message));
        } catch (e) {
            this._counters.errors += 1;
            return false;
        }
        return true;
    }

    _dispatch(raw) {
        let envelope;
        try {
            envelope = JSON.parse(raw);
        } catch (e) {
            this._counters.errors += 1;
            return;
        }
        this._counters.received += 1;
        switch (envelope.type) {
            case ENVELOPE_TYPE_CHANNEL:
                this._invoke("channels", envelope.data);
                break;
            case ENVELOPE_TYPE_EVENT:
                this._invoke("events", envelope.data);
                break;
            case ENVELOPE_TYPE_COMMAND:
                this._invoke("command_history", envelope.data);
                break;
            case ENVELOPE_TYPE_HELLO:
                // Server greeting; no-op
                break;
            case ENVELOPE_TYPE_ERROR:
                this._counters.errors += 1;
                console.warn("[stream] server reported error:", envelope.message);
                break;
            default:
                // Future envelope types are silently ignored.
                break;
        }
    }

    /**
     * Dispatch a batched envelope's data to the registered handler.
     *
     * Servers running this build send ``data`` as an array of samples
     * (potentially many per envelope, coalesced from a single drain
     * tick on the sender). Older servers used a scalar ``data`` field
     * with a single sample per envelope; the array form is the
     * preferred shape but the scalar fallback is supported so a
     * version-skewed client still works.
     */
    _invoke(endpoint, data) {
        let handler = this.handlers[endpoint];
        if (!handler) {
            return;
        }
        let items;
        if (Array.isArray(data)) {
            items = data;
        } else if (data == null) {
            return;
        } else {
            items = [data];
        }
        if (items.length === 0) {
            return;
        }
        try {
            handler(items);
        } catch (e) {
            this._counters.errors += 1;
            console.error("[stream] handler error:", e);
        }
    }
}

export {StreamClient};
