/**
 * log.js:
 *
 * Vue support for the log viewing screen. This will allow users to view the various logs exported by the underlying
 * server.
 */
// Setup component for select
import "../../third-party/js/vue-select.js"
import {_datastore} from "../datastore.js"
import {_loader} from "../loader.js";


/**
 * Logs template used to display log information from the system. Contains a selectable list of logs and a
 panel that displays the raw text, with light highlighting.
 */
let template = `
<div class="fp-flex-repeater">
    <div class="fp-flex-header">
        <h2>Available Logs</h2>
        <div class="my-3">
            <v-select id="logselect"
                    :clearable="true" :searchable="true"
                    :filterable="true"  :options="logs"
                    v-model="selected">
            </v-select>
            <input name="scroll" type="checkbox" v-model="scroll" />
            <label for="scroll">Scroll Log Output</label>
        </div>
    </div>
    <div class="fp-scroll-container">
        <div class="fp-scrollable fp-color-logging">
            <pre><code>{{ text }}</code></pre>
        </div>
    </div>
    <div class="alert alert-danger" role="alert" v-if="error">{{ error }}</div>
</div>
`;


// Must provide v-select
Vue.component('v-select', VueSelect.VueSelect);

Vue.component("logging", {
    template: template,
    data() {return {"selected": "", "logs": _datastore.logs, text: "", "scroll": true, "error": ""}},
    mounted() {
        setInterval(this.update, 1000); // Grab log updates once a second
    },
    methods: {
        /**
         * Updates the log data such that new logs can be displayed.
         */
        update() {
            let _self = this;
            if (this.selected === "") {
                return;
            }
            _loader.load("/logdata/" + this.selected, "GET").then(
                (result) => {
                    _self.text = result[_self.selected];
                    // Update on next-tick so that the updated content has been drawn already
                    _self.$nextTick(() => {
                        let panes = _self.$el.getElementsByClassName("fp-scrollable");
                        if (panes && _self.scroll)
                        {
                            panes[0].scrollTop = panes[0].scrollHeight;
                        }
                    });
                    _self.error = "";
                }).catch((result) => {
                    if (result === "") {
                        _self.error = "[ERROR] Failed to update log content.";
                    } else {
                        _self.error = "[ERROR] " + result + ".";
                    }
                });
        }
    }
});
