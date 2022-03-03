import {advanced_template} from "./addon-templates.js";
import {_datastore} from "../../js/datastore.js";
import {_loader} from "../../js/loader.js";


/**
 * Sequencer component used to represent the composition and editing of sequences.
 */
Vue.component("advanced-settings", {
    template: advanced_template,
    data() {
        return {
            stats: _datastore.stats,
            polling_info: _datastore.polling_info,
            settings: {
                "Data Settings": _datastore.settings
            }
        };
    },
    methods: {
        reregister() {
            this.polling_info.forEach((item) => {_datastore.reregisterPoller(item.endpoint)});
        }
    }
});
