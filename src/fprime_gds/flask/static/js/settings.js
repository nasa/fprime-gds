import {config} from "./config_init.js";

/**
 * settings.js:
 *
 * A data store used to store active settings of the GDS and providing those settings as data for the rest of the
 * system. These settings are typically advanced but should be tracked for the user.
 */
class Settings {
    constructor() {
        this.miscellaneous = {
            event_buffer_size: -1,
            command_buffer_size: -1,
            response_object_limit: 6000,
            compact_commanding: false,
            channels_display_last_received: true
         };
         this.polling_intervals = {};
         // Transport for the events/channels/command_history endpoints.
         // "stream" uses a WebSocket push from the GDS (when available),
         // "poll" uses the legacy REST polling. The advanced settings UI
         // exposes a live switch backed by this value, and the choice is
         // persisted to localStorage so it survives reloads.
         //
         // Resolution order: persisted localStorage > server default
         // (set later via ``applyServerDefaultTransport``) > config default.
         // The persisted flag is recorded so a later server-default does
         // not stomp a user's per-browser choice.
         this.transport = {
             mode: (config.defaultTransport === "poll") ? "poll" : "stream",
             userPersisted: false,
         };
         try {
             let persisted = window.localStorage.getItem("fprime-gds-transport");
             if (persisted === "stream" || persisted === "poll") {
                 this.transport.mode = persisted;
                 this.transport.userPersisted = true;
             }
         } catch (e) { /* localStorage unavailable; ignore */ }
    }

    /**
     * Apply a server-provided default transport. Only takes effect when no
     * per-browser choice has been persisted; this lets a CLI flag
     * (``--ws-default-transport poll``) ship a poll-first first-load
     * experience without overriding a user's prior toggle.
     */
    applyServerDefaultTransport(mode) {
         if ((mode !== "stream" && mode !== "poll") || this.transport.userPersisted) {
             return;
         }
         this.transport.mode = mode;
    }

    /**
     * Persist the transport choice. Intended to be called by the UI live switch.
     */
    setTransport(mode) {
         if (mode !== "stream" && mode !== "poll") {
             return;
         }
         this.transport.mode = mode;
         this.transport.userPersisted = true;
         try {
             window.localStorage.setItem("fprime-gds-transport", mode);
         } catch (e) { /* ignore */ }
    }

    /**
     * Setup the polling settings from a set of keys representing pollers. Keys should be supplied as a list of names
     * and not as a list of anonymous objects.
     * @param keys: list of keys to setup polling settings.
     */
    setupPollingSettings(keys) {
        let _self = this;
        keys.forEach((key) => {
            _self.polling_intervals[key] = config.dataPollIntervalsMs[key] || config.dataPollIntervalsMs.default || 1000;
        });
    }
}
export let _settings = new Settings();
