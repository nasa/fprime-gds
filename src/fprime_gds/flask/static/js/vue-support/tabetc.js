/**
 * vue-support/tabetc.js:
 *
 * A tabbed routed view into all three aspects of F´ (events 'e', channels/telemetry 't', commands 'c') that allows the
 * user to switch between the various parts of the F´ system using a set of tab buttons.
 *
 * @author mstarch
 */
import {config} from "../config.js"

// Child component imports ensures that the Vue components exist before using them
import "./channel.js"
import "./downlink.js"
import "./event.js"
import "./log.js"
import "./uplink.js"
import "./dashboard.js"
import {_datastore} from "../datastore.js";
import {_validator} from "../validate.js";
import {_settings} from "../settings.js";

/**
 * tabbed-ect:
 *
 * This component sets up a tabbed view for Events, Channels (Telemetry), and Commands. This is a composite of the
 * component-views that were composed into a tabbed-view.
 */
Vue.component("tabbed-etc", {
    template: "#tabetc-template",
    data:
        /**
         * Function to return a dictionary of data items. currentTab is set based on the initial URL.
         */
        function () {
            let hash = window.location.hash.replace("#", "");
            return {
                "currentTab": (hash === "")? "Commanding" : hash,
                "tabs": [
                    ["Commanding", "Cmd"], 
                    ["Events", "Evn"], 
                    ["Channels", "Chn"], 
                    ["Uplink", "UpL"], 
                    ["Downlink", "DnL"], 
                    ["Dictionaries", "Dct"],
                    ["Charts", "Chr"], 
                    ["Logs", "Log"],
                    ["Sequences", "Seq"],
                    ["Dashboard", "Dsh"],
                    ["Advanced", "Adv"]
                ],
                "config": config,
                "counts": _validator.counts,
                "flags": _datastore.flags,
                "settings": _settings.miscellaneous
            }
        },
    methods: {
        /**
         * Route the tab-change and place it in the Window's location
         * @param tab: tab to route to. No need for the #
         */
        route(tab) {
            window.location.hash = tab;
            this.currentTab = tab;
        },
        /**
         * Spawns a new window when the new window button is clicked.
         */
        spawn() {
            window.open(window.location);
        },
        /**
         * Make navbar collapse on small size window and allow user to expand
         * by pressing an expand button.
         */
        navbar_toggle() {
            for (const tab in this.tabs) {
                let elem = document.getElementById(this.tabs[tab][0]);
                if (elem.classList.contains("d-none")) {
                    elem.classList.remove("d-none");
                    elem.classList.add("d-block");
                } else if (elem.classList.contains("d-block")) {
                    elem.classList.remove("d-block");
                    elem.classList.add("d-none");
                } 
            }
        },
        /**
         * Check if the supplied tab is enabled w.r.t the configuration of the GUI.
         * @param tab: tab fullname to check against
         */
        tabEnabled(tab) {
            return true;
        }
    },
    computed: {
        /**
         * Determines if none are active by checking if active channels or events have been detected recently.
         * @return {boolean} no active data flow
         */
        orb() {
            let orb = false;
            for (let key in this.flags) {
                orb = orb || (key.startsWith("active_") && this.flags[key]);
            }
            return orb;
        },
        /**
         * Returns the number of errors detected this run
         * @returns {number} count of errors
         */
        error_count() {
            return this.errors.length;
        }

    }
});
