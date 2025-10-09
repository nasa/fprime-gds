/**
 * vue-support/channel.js:
 *
 * This file contains the necessary Vue definitions for displaying the channel table for F´. It also has the channel
 * mixin definitions to use channel Vue components in other compositions.
 *
 * @author mstarch
 */
import {listExistsAndItemNameNotInList, timeToString} from "./utils.js"
import "./fptable.js";
import {_datastore, _dictionaries} from "../datastore.js";
/**
 * channel-table:
 *
 * Manages the full channel table. This includes calculating the filtered channels based on a given filtering function.
 */
Vue.component("channel-table", {
    props: {
        /**
         * fields:
         *
         * Fields to display on this object. This should be null, unless the user is specifically trying to minimize
         * this object's display.
         */
        fields: {
            type: [Array, String],
            default: ""
        },
        /**
         * The search text to initialize the table filter with (defaults to
         * nothing)
         */
        filterText: {
            type: String,
            default: ""
        },
        /**
         * A list of item ID names saying what rows in the table should be
         * shown; defaults to an empty list, meaning "show all items"
         */
        itemsShown: {
            type: [Array, String],
            default: ""
        },
        /**
         * 'compact' allows the user to hide filters/buttons/headers/etc. to
         * only show the table itself for a cleaner view
         */
        compact: {
            type: Boolean,
            default: false
        }
    },
    data: function() {
        return {"channels": _datastore.channels};
    },
    template: "#channel-table-template",
    // Defined methods
    methods: {
        /**
         * Returns a list of column values for the input channel item. These items will be rendered.
         * @param item: channel item to convert to column values
         * @return {*[]}
         */
        columnify(item) {
            let template = _dictionaries.channels[item.id];
            if (item.time == null || item.val == null) {
                return ["", "0x" + item.id.toString(16), template.full_name, ""];
            }
            return [timeToString(item.time || item.datetime), "0x" + item.id.toString(16), template.full_name,
                (typeof(item.display_text) !== "undefined")? item.display_text : item.val]
        },
        /**
         * Converts a channel to a unique rendering key. For channels, ids are unique, and thus just use that.
         * @param item: channel item to provide
         * @return {*}
         */
        keyify(item) {
            return item.id;
        },
        /**
         * Use the row's values and bounds to colorize the row. This function will color red and yellow items using
         * the boot-strap "warning" and "danger" calls.
         * @param item: channel item
         * @return {string}: style-class to use
         */
        calculateRowStyle(item) {
            if (item.val == null) {
                // No channel value yet
                return "";
            }
            let template = _dictionaries.channels[item.id];
            // Check if any bounds are actually set
            if ((template.low_red == null) && (template.low_orange == null) && (template.low_yellow == null) &&
                (template.high_red == null) && (template.high_orange == null) && (template.high_yellow == null)) {
                return "";
            }
            let bounds = [
                {
                    "class": "fp-color-fatal",
                    "bounds": [template.low_red, template.high_red]
                },
                {
                    "class": "fp-color-warn-hi",
                    "bounds": [template.low_orange, template.high_orange]
                },
                {
                    "class": "fp-color-warn-lo",
                    "bounds": [template.low_yellow, template.high_yellow]
                }
            ];
            // Check bounds.
            for (let i = 0; i < bounds.length; i++) {
                let bound = bounds[i];
                if ((bound.bounds[0] != null && item.val < bound.bounds[0]) ||
                    (bound.bounds[1] != null && item.val > bound.bounds[1])) {
                    return bound.class;
                }
            }
            return "table-success";
        },
        /**
         * Converts an item to a name for use with the views functionality.
         * @param item: the channel item to convert to its name
         * @return item name
         */
        itemToName(item) {
            let template = _dictionaries.channels[item.id];
            return template.full_name;
        },
        /**
         * Function that hides items with null time or value.
         * @param item: channel to hide
         * @return {boolean}
         */
        channelHider(item) {
            // Never hide channels if all channels are null
            let all_null = Object.values(_datastore.channels).reduce((accumulator, channel) => accumulator && channel.val == null);
            if (all_null && this.itemsShown.length == 0) {
                return false;
            }
            return item.val == null
                || item.time == null
                || listExistsAndItemNameNotInList(this.itemsShown, item);
        },
        /**
         * Function that clears all channels
         */
        clearChannels() {
            let channels = {}
            for (let key in _dictionaries.channels) {
                channels[key] = {id: key, time: null, datetime: null, val: null};
            }
            Object.assign(_datastore.channels, channels);
            this.$refs.fptable.send([]);
        }
    }
});
