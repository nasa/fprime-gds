import {advanced_template} from "./addon-templates.js";
import {_datastore} from "../../js/datastore.js";
import {_performance} from "../../js/performance.js"
import {_settings} from "../../js/settings.js";
import {_loader} from "../../js/loader.js";


/**
 * Sequencer component used to represent the composition and editing of sequences.
 */
Vue.component("advanced-settings", {
    template: advanced_template,
    data() {
        return {
            statistics: _performance.statistics,
            settings: {
                "Polling_Intervals": _settings.polling_intervals,
                "Miscellaneous": _settings.miscellaneous
            },
            old_polling: {..._settings.polling_intervals}
        };
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
