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
                    :filterable="true"  :options="options"
                    v-model="selected">
            </v-select>
        </div>
    </div>
    <div class="fp-scroll-container">
        <div class="fp-scrollable fp-color-logging">
            <pre><code>{{ text }}</code></pre>
        </div>
    </div>
</div>
`;


// Must provide v-select
Vue.component('v-select', VueSelect.VueSelect);

Vue.component("logging", {
    template: template,
    data() {return {"selected": "", "logs": _datastore.logs, text: ""}},
    mounted() {
        setInterval(this.update, 1000); // Grab log updates once a second
    },
    computed:{
        /**
         * Computes the appropriate log files available.
         * @return {string[]}
         */
        options: function () {
            return this.logs;
        }
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
                    this.$el.scrollTop = this.$el.scrollHeight
                }).catch((result) => {_self.text = "[ERROR] "+ result});
        }
    }
});
