import {dictionary_template, version_template} from "./addon-templates.js";
import {_dictionaries} from "../../js/datastore.js";
import {sentenceCase} from "../../js/vue-support/utils.js"

function copy(text) {
    navigator.clipboard.writeText(text);
}
/**
 * Sequencer component used to represent the composition and editing of sequences.
 */
Vue.component("dictionary", {
    template: dictionary_template,
    data() {
        return {
            dictionaries: {
                commands: Object.values(_dictionaries.commands_by_id),
                events: Object.values(_dictionaries.events),
                channels: Object.values(_dictionaries.channels)
            },
            active: "commands",
        };
    },
    methods: {
        capitalize(key) {
            return sentenceCase(key);
        },
        change(new_key) {
            this.active = new_key;
        },
        columnify(item) {
            return [this.keyify(item), item.full_name, item.description || item.ch_desc];
        },
        keyify(item) {
            return item.id || item.opcode;
        }
    }
});
Vue.component("dictionary-version", {
    template: version_template,
    data() {
        return {
            "framework_version": _dictionaries.framework_version,
            "project_version": _dictionaries.project_version
        }
    }
})
