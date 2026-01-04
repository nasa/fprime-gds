/**
 * packet-selection/packet-selection-template.js:
 *
 * Vue JS component for handling file packet selection dialog.
 *
 * @author lestarch
 */
import {packet_selection_template} from "./packet-selection-template.js";

/**
 * 
 */
Vue.component("packet-selection", {
    props: ["selected"],
    data() { return {"packetInput": "", "error": ""}},
    template: packet_selection_template,
    mounted() {
        this.packetInput = this.selected.packets.join(", ");
    },
    methods: {
        validate() {
            let value = this.packetInput;
            value = value.trim();
            // Get a list of tokens that is processing only well-formed numbers without remainders, decimals, or
            // other things that could be a mistake.
            let tokens = (value == "") ? [] : value.split(",");
            // First, trim and remove empty tokens ("" is falsy)
            tokens = tokens.map(token => token.trim()).filter(Boolean);
            // Second, map to integers or NaN using a regex check to avoid parseInt oddities
            tokens = tokens.map(t => (/^[1-9]\d*$/.test(t) ? parseInt(t, 10) : NaN));
            // Look for any invalid entries, ensuring each entry is not NaN
            let valid = tokens.every(
                (token) => !Number.isNaN(token) && token > 0
            );
            // Set error if invalid
            if (!valid) {
                this.error = "Specify packet numbers as comma-separated list";
                return null;
            }
            this.error = "";
            return tokens;
        },
        save(event) {
            let tokens = this.validate(event);
            if (tokens !== null) {
                this.$emit("packets-selected", tokens);
            }
        },
        
    }
});