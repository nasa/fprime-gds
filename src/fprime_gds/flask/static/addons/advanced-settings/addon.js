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
                    description: "Miscellaneous settings for GDS UI operations." +
                        "<small><ul>" +
                        "<li>event_buffer_size: maximum event records. Default: -1, infinite.</li>" +
                        "<li>command_buffer_size: maximum command history records. Default: -1, infinite.</li>" +
                        "<li>response_object_limit: maximum results to load per polling request. Default: 6000</li>" +
                        '<li>compact_commanding: use compact "flattened" style for commanding complex arguments.</li>' +
                        "</ul></small>",
                    settings: _settings.miscellaneous
                }
            },
            old_polling: {..._settings.polling_intervals},
            errors: _validator.errors
        };
    },
    methods: {
        /**
         * Clear the errors that occurred within the GDS and reset the counts.
         */
        clearErrors() {
            _validator.errors.splice(0, _validator.errors.length);
            _validator.counts.GDS_Errors = 0;
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
        }
    }
});
