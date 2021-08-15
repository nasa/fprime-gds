/**
 * vue-support/event.js:
 *
 * Event listing support for F´ that sets up the Vue.js components used to display events. These components allow the
 * user to render events. This file also provides EventMixins, which are the core functions needed to convert events to
 * something Vue.js can display. These should be mixed with any F´ objects wrapping Vue.js component creation.
 *
 * @author mstarch
 */
import {listExistsAndItemNameNotInList, timeToString} from "./utils.js";
import {_datastore} from "../datastore.js";

let OPREG = /Opcode (0x[0-9a-fA-F]+)/;

/**
 * events-list:
 *
 * Renders lists as a colorized table. This is a thin-wrapper to pass events to the fp-table component. It supplies the
 * needed method to configure fp-table to render events.
 */
Vue.component("event-list", {
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
        return {
            // NOTE: Events/command lists shared across all component instances
            "events": _datastore.events,
            "totalEventsSize": _datastore.events.length,
            "eventsStartOffset": 0,
            "eventsEndOffset": 100,
            "eventOffsetSize": 100,
            "scrollOffsetSize": 5,
            "isAutoUpdate": false,
            "scrollableElm": null,
            "scrollStatus": false,
            "currTime": 0,
            "prevTime": 0,
            "commands": _datastore.commands
        };
    },
    template: "#event-list-template",
    methods: {
        /**
         * Takes in a given event item, and harvests out the column values for display in the fp-table.
         * @param item: event object to harvest
         * @return {[string, *, *, void | string, *]}
         */
        columnify(item) {
            let display_text = item.display_text;
            // Remap command EVRs to expand opcode for visualization purposes
            let groups = null
            if (item.template.severity.value == "EventSeverity.COMMAND" && (groups = display_text.match(OPREG)) != null) {
                let component_mnemonic = "UNKNOWN"
                let id = parseInt(groups[1]);
                for (let command in this.commands) {
                    command = this.commands[command];
                    if (command.id == id) {
                        component_mnemonic = command.full_name;
                    }
                }
                const msg = '<span title="' + groups[0] + '">' + component_mnemonic + '</span>'
                display_text = display_text.replace(OPREG, msg);
            }
            return [timeToString(item.time), "0x" + item.id.toString(16), item.template.full_name,
                item.template.severity.value.replace("EventSeverity.", ""), display_text];
        },
        /**
         * Use the row's values and bounds to colorize the row. This function will color red and yellow items using
         * the boot-strap "warning" and "danger" calls.
         * @param item: item passed in with which to calculate style
         * @return {string}: style-class to use
         */
        style(item) {
            let severity = {
                "EventSeverity.FATAL":      "fp-color-fatal",
                "EventSeverity.WARNING_HI": "fp-color-warn-hi",
                "EventSeverity.WARNING_LO": "fp-color-warn-lo",
                "EventSeverity.ACTIVITY_HI": "fp-color-act-hi",
                "EventSeverity.ACTIVITY_LO": "fp-color-act-lo",
                "EventSeverity.COMMAND":     "fp-color-command",
                "EventSeverity.DIAGNOSTIC":  ""
            }
            return severity[item.template.severity.value];
        },
        /**
         * Take the given item and converting it to a unique key by merging the id and time together with a prefix
         * indicating the type of the item. Also strip spaces.
         * @param item: item to convert
         * @return {string} unique key
         */
        keyify(item) {
            return "evt-" + item.id + "-" + item.time.seconds + "-"+ item.time.microseconds;
        },
        /**
         * A function to clear this events pane by moving the offset to the end 
         * of the list. User call see the previous events again if scrolling back
         */
        clearEvents() {
            this.eventsStartOffset = this.events.length;
            this.eventsEndOffset = this.events.length + this.eventOffsetSize;
            this.isAutoUpdate = false;
        },
        /**
         * Returns if the given item should be hidden in the data table; by
         * default, shows all items. If the "itemsShown" property is set, only
         * show items with the given names
         *
         * @param item: The given F' data item
         * @return {boolean} Whether or not the item is shown
         */
        isItemHidden(item) {
            return listExistsAndItemNameNotInList(this.itemsShown, item);
        },
        /**
         * Check if the scroll bar is at the bottom or at the top of the 
         * scrollable div. If at the bottom of the page load the next group
         * of events into table. If at the top load the previous group.
         */
        onScroll(e) {
            let elmH = this.scrollableElm.scrollHeight;
            let elmT = this.scrollableElm.scrollTop;
            let elmC = this.scrollableElm.clientHeight;
            let isAtBottom = (Math.abs(elmH - elmT - elmC) <= 2.0) && (elmT !== 0);
            
            if (!this.isScrollable()) {
                // Disabling auto update user scrolls
                if (this.hasUserScrolled(e)) {
                    this.isAutoUpdate = false;
                }
                return;
            }

            // Turn off auto scrolling
            this.isAutoUpdate = false;

            if (isAtBottom) {
                // Scrollbar reached to the bottom
                this.updateNextOffsetRange(this.scrollOffsetSize);
            } else if (this.scrollableElm.scrollTop === 0) {
                // Scrollbar reached to the top
                this.updatePrevOffsetRange(this.scrollOffsetSize);
            }
        },
        /**
         * Jump to the top of the event list.
         */
        offsetToFirst() {
        this.scrollableElm.scrollTop = 0;
        this.isAutoUpdate = false;
        if (!this.isScrollable()) {
            return;
        }
        this.eventsStartOffset = 0;
        this.eventsEndOffset = this.eventOffsetSize;
        },
        /**
         * Jump to the bottom of the event list.
         */
        offsetToLast() {
            this.scrollableElm.scrollTop = this.scrollableElm.scrollHeight - this.scrollableElm.clientHeight;
            this.isAutoUpdate = true;
            if (!this.isScrollable()) {
                return;
            }
            this.eventsStartOffset = this.events.length - this.eventOffsetSize;
            this.eventsEndOffset = this.events.length;
        },
        /**
         * Load previous group of events
         */
        offsetToPrev() {
            if (!this.isScrollable()) {
                return;
            }
            this.isAutoUpdate = false;
            this.updatePrevOffsetRange(this.scrollOffsetSize);
        },
        /**
         * Load next group of events
         */
        offsetToNext() {
            if (!this.isScrollable()) {
                return;
            }
            this.isAutoUpdate = false;
            this.updateNextOffsetRange(this.scrollOffsetSize);
        },
        /**
         * If auto update is enabled load the new events and remove old events
         * in the given range.
         */
        updateAutoOffsetRange() {
            if ((this.isAutoUpdate) && 
                (this.eventsEndOffset < this.events.length) &&
                (this.events.length - this.eventOffsetSize) > 0) {
                    this.eventsStartOffset = this.events.length - this.eventOffsetSize;
                    this.eventsEndOffset = this.events.length;
            } 
        },
        /**
         * Utility function to keep the scroll bar at the bottom when auto scroll
         * is enabled.
         */
        updateScrollPos() {
            if (this.isAutoUpdate) {
                this.scrollableElm.scrollTop = this.getScrollBottomLimit();
            }
        },
        /**
         * Utility function to load previous group of events
         * @param {number} offset: specifies how much to move backward in the list
         */
         updatePrevOffsetRange(offset) {
            if ((this.eventsStartOffset - offset) > 0) {
                this.eventsStartOffset -= offset;
                this.eventsEndOffset -= offset;
                // Keep scrollbar down if there are more items to load
                this.scrollableElm.scrollTop = 20;
                // Turn off auto scrolling
                this.isAutoUpdate = false;
            } else {
                // Will not subtract more since we are at the start of the list
                this.eventsStartOffset = 0;
                this.eventsEndOffset = this.eventOffsetSize;
                // Move scrollbar to the top
                this.scrollableElm.scrollTop = 0;
                // Turn off auto scrolling
                this.isAutoUpdate = false;
            }
        },
        /**
         * Utility function to load next group of events
         * @param {number} offset: specifies how much to move forward in the list
         */
        updateNextOffsetRange(offset) {
            if ((this.eventsEndOffset + offset) >= this.events.length) {
                // Will not add more since we are at the end of the list
                this.eventsEndOffset = this.events.length;
                this.eventsStartOffset = this.eventsEndOffset - this.eventOffsetSize;
                this.scrollableElm.scrollTop = this.getScrollBottomLimit();
                // Turn on auto scrolling since we are at the end of the list
                this.isAutoUpdate = true;
            } else if ((this.eventsEndOffset+offset) < this.events.length) {
                this.eventsStartOffset += offset;
                this.eventsEndOffset += offset;
                let scrollbarTop = this.getScrollBottomLimit() - 20;
                this.scrollableElm.scrollTop = scrollbarTop > 0 ? scrollbarTop : 0;
                // Turn off auto scrolling
                this.isAutoUpdate = false;
            }
        },
        /**
         * Utility function to check if enough events to start scrolling 
         */
        isScrollable() {
            return (this.events.length - this.eventOffsetSize > 0);
        },
        /**
         * Utility function to check for scrollbar bottom limit
         */
        getScrollBottomLimit() {
            return this.scrollableElm.scrollHeight - this.scrollableElm.clientHeight;
        },
        /**
         * Check the timestamp of scroll event and if less than a certain 
         * millisecond interval it is a user triggered scroll
         */
        hasUserScrolled(e) {
            if (e === undefined) {
                return false;
            }
            this.prevTime = this.currTime;
            this.currTime = e.timeStamp;
            return (this.currTime - this.prevTime) < 800;
        }
    },
    computed: {
        /**
         * Returns a list of events that should be visible on this component
         * instance, to support instance-specific clearing
         *
         * @return {Array} The list of event items this instance can show
         */
        componentEvents() {
            this.updateAutoOffsetRange();
            this.updateScrollPos();
            this.scrollStatus = this.isScrollable();
            return this.events.slice(this.eventsStartOffset, this.eventsEndOffset);
        },
        /**
         * Update the total number of events in the list
         */
        updateTotalEventsSize() {
            this.totalEventsSize = this.events.length;
        },
    },
    /**
     * Add scroll event listener during mounting of element
     */
    mounted: function() {
        this.$nextTick(function(e) {
            this.scrollableElm = this.$el.querySelector("#fp-scrollable-id");
            this.scrollableElm.addEventListener('scroll', this.onScroll, true);
            this.onScroll(e); // needed for initial loading on page
        });
    },
    /**
     * Remove scroll event listener 
     */
    beforeDestroy: function() {
        this.scrollableElm.removeEventListener('scroll', this.onScroll);
    },
});
