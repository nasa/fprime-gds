/**
 * channel-render.js: Vue components for channel rendering.
 *
 * channel-render and channel-row are used to override the individual rendering of a given fptable row for channel
 * display. This code inherits from fptable's implementation and adds in specific channel value handling such that
 * complex channel types may be expanded.
 *
 * @author lestarch
 */
import {channel_render_template, channel_row_template} from "./channel-render-template.js"
import {_dictionaries} from "../../js/datastore.js";
import {fp_row_base_component} from "../../js/vue-support/fp-row.js";

/**
 * channel-render Vue component. This vue uses dictionary information to expand the rendering of complex types into
 * a table that displays each subfield. It has the appropriate expand icons such that this table may be collapsed if
 * not needed.
 */
Vue.component("channel-render", {
    props: {
        // item is used at the top level before the field-recursion takes place
        item: {
            default: null, // Fallback to null when item is not set
        },
        // val takes place when in the field recursion
        val: {
            default: null, // Fallback when item is supplying the information
        },
        // element_type specifies the type of the element
        element_type: {
            default: null, // Element type is not specified and force by-dictionary lookup
        },
        // display_val is the pre-formatted display value from the backend (e.g. "123 mV")
        display_val: {
            default: null,
        }
    },
    template: channel_render_template,
    /**
     * Function to return the local-data object. This object only tracks expanded/collapsed state.
     * @returns {{expanded: boolean}} the data object
     */
    data() { return {"expanded": false}},
    methods: {
        /**
         * Expand this particular element
         */
        expand() {
            this.expanded = true;
        },
        /**
         * Collapse this element
         */
        collapse() {
            this.expanded = false;
        },
        /**
         * Calculates the type of the child element. This fills in the element_type bound property of the child. This is
         * calculated by the inferred type of the object and the given index.
         * @param index: index of the child (number for arrays, field name for structures)
         * @returns {null|*}: type object of the given child or null if children are not possible.
         */
        childType(index) {
            // Check for arrays given the MEMBER_TYPE property is only set for arrays
            if (this.type.MEMBER_TYPE) {
                return this.type.MEMBER_TYPE;
            }
            // Check for serializable types given MEMBER_LIST is only set for serializable types
            else if (this.type.MEMBER_LIST) {
                let matching = this.type.MEMBER_LIST.filter((item) => item[0] === index);
                return  matching[0][1];
            }
            // No other types allow children
            return null;
        }
    },
    computed: {
        /**
         * Calculate the set of indices (0..N for arrays, or field names for serializable types) for this particular
         * element's children. The field set will be iterated to display the children.
         * @returns list of indices of child fields
         */
        childIndices() {
            // Arrays have sequential indices
            if (this.type.LENGTH) {
                return [...Array(this.type.LENGTH).keys()];
            }
            // Serializable types use named indices
            else if (this.type.MEMBER_LIST) {
                return this.type.MEMBER_LIST.map((list_entry) => list_entry[0]);
            }
            // Other types have no children
            return [];
        },
        /**
         * Calculate the type of the item. This equates to element_type when set and a dictionary lookup when not sey.
         * @returns: type of current item
         */
        type() {
            // Check if element type was defined, if so return it
            if (this.element_type) {
                return this.element_type;
            }
            // Otherwise, fallback to a dictionary lookup
            let entry = _dictionaries.channels[this.item.id];
            return entry.type_obj;
        },
        /**
         * The pre-formatted display value for this element. At the top level this comes from
         * item.display_text (computed by the Python backend); in recursion it comes from the
         * display_val prop passed by the parent.
         * @returns: formatted display value (string for leaves, dict/list for complex types)
         */
        displayVal() {
            return this.item?.display_text ?? this.display_val;
        },
        /**
         * Display text of the given element. Prefers the backend-formatted display value when
         * available, falling back to raw val.
         * @returns: display text of item/child item
         */
        displayText() {
            let possibles = [this.displayVal, this.item?.val, this.val];
            for (let i = 0; i < possibles.length; i++) {
                if (typeof(possibles[i]) !== "undefined" && possibles[i] !== null) {
                    return possibles[i];
                }
            }
            return "";
        }

    }
});
// Copy in fp_row data and overlay a different display template
let channel_row_data = {
    ...fp_row_base_component,
    ...{template: channel_row_template},
};
/**
 * channel-row replaces fp-row in display template only.
 */
Vue.component("channel-row", channel_row_data);
