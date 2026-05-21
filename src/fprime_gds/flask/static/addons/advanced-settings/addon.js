import {advanced_template} from "./addon-templates.js";
import {_datastore} from "../../js/datastore.js";
import {_performance} from "../../js/performance.js"
import {_settings} from "../../js/settings.js";
import {_validator} from "../../js/validate.js";


/**
 * Sequencer component used to represent the composition and editing of sequences.
 */
Vue.component("advanced-settings", {
    template: advanced_template,
    data() {
        return {
            statistics: _performance.statistics,
            settings: {
                "Polling_Intervals": {
                    description: "Interval (in milliseconds) to poll the datastore for each of the given data types.",
                    settings: _settings.polling_intervals
                },
                "Miscellaneous": {
                    description: "Miscellaneous settings for GDS UI operations.",
                    descriptions: {
                        event_buffer_size: "Maximum number of events stored by the GDS. When exceeded, oldest events are dropped " +
                                            "Lower this value if performance drops on the Events tab. Default: -1, no limit.",
                        command_buffer_size: "Maximum number of commands stored by the GDS. When exceeded, oldest commands are dropped " +
                                                "Lower this value if performance drops on the Commanding tab. Default: -1, no limit.",
                        response_object_limit: "Limit to the number of objects returned by one POLL request to the backend. " +
                                                "Lower this value if polling times are longer than polling intervals. Default: 6000.",
                        compact_commanding: "Use the compact form for command arguments. In this form, Array and Serializable type " +
                                            "inputs are flattened into a sequential set of input boxes without extraneous structure.",
                        channels_display_last_received: "When set, any channel received will update the displayed value. Otherwise " +
                                                        "only channels with newer timestamps update the displayed value."
                    },
                    settings: _settings.miscellaneous
                }
            },
            transport: _settings.transport,
            stream_status: {active: null, enabled: null, clients: 0, dropped: 0},
            stream_status_interval: null,
            old_polling: {..._settings.polling_intervals},
            errors: _validator.errors
        };
    },
    mounted() {
        this.refreshStreamStatus();
        this.stream_status_interval = setInterval(this.refreshStreamStatus.bind(this), 2000);
    },
    beforeDestroy() {
        if (this.stream_status_interval) {
            clearInterval(this.stream_status_interval);
            this.stream_status_interval = null;
        }
    },
    methods: {
        /**
         * Clear the errors that occurred within the GDS and reset the counts.
         */
        clearErrors() {
            _validator.errors.splice(0, _validator.errors.length);
            _validator.counts.GDS_Errors = 0;
        },
        /**
         * Refresh the visible stream-status panel from the /api/stream/status endpoint.
         */
        refreshStreamStatus() {
            fetch("/api/stream/status")
                .then((response) => response.ok ? response.json() : null)
                .then((data) => {
                    if (!data) {
                        this.stream_status = {active: false, enabled: false, clients: 0, dropped: 0};
                        return;
                    }
                    this.stream_status = Object.assign({active: null, enabled: null, clients: 0, dropped: 0}, data);
                })
                .catch(() => {
                    this.stream_status = {active: false, enabled: false, clients: 0, dropped: 0};
                });
        }
    },
    watch: {
        /**
         * This is used to update polling intervals. This is because even though the data can change, we need to restart
         * the setInterval call to kick the process off again. Thus we watch this specific setting, check for changes,
         * and kick-off a new poller when it has changes.
         */
        "settings.Polling_Intervals": {
            // Handler for on-change
            handler(polling) {
                Object.keys(polling).forEach((key) => {
                   if (polling[key] !== this.old_polling[key]) {
                       _datastore.reregisterPoller(key);
                   }
                });
                this.old_polling = {...polling};
            },
            // Must watch sub-keys
            deep: true
        },
        /**
         * Live transport toggle. Persist the change and let the datastore
         * swap between the WebSocket stream and the REST poller without a
         * page reload.
         */
        "transport.mode": {
            handler(mode) {
                _settings.setTransport(mode);
                _datastore.applyTransport();
            }
        }
    }
});
