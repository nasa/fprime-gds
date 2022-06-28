/**
 * utils.js:
 *
 * This file contains utility functions used by various parts of the vue-support system. Each item here intended for use
 * elsewhere should be "export"ed as then they can then be imported for use elsewhere.
 */
import {config} from "../config.js";

/**
 * Make it sentence case where the first letter is capitalized.
 * @param key: key to capitalize the first letter
 * @return string
 */
export function sentenceCase(key) {
    if (key.length > 0) {
        return key[0].toUpperCase() + key.slice(1);
    }
    return key;
}
/**
 * Preprocessing the matching tokens to make them easier to match match against. It takes the following steps:
 * 1. Ensure all tokens are defined
 * 2. Make all tokens lowercase, for case insensitivity
 * 3. Convert tokens into the following format (ANDed list of ORed sets) [[OR...] AND [OR...] AND [OR...]]
 * 4. Make sure all items in the ANDed list are not empty
 * @param matching_tokens: matching tokens to convert
 * @return tokens matched
 */
function preprocess_matchings(matching_tokens) {
    let matching_tokens_arr = !Array.isArray(matching_tokens) ? [matching_tokens] : matching_tokens;
    matching_tokens_arr = matching_tokens_arr.filter(item => typeof(item) !== "undefined");
    matching_tokens_arr = matching_tokens_arr.map(item => item.toLowerCase());

    let oring = false;
    let processed = [[]];
    for (let i = 0; i < matching_tokens_arr.length; i++) {
        // If token is -or- we will be oring next time
        if (matching_tokens_arr[i] === "-or-") {
            oring = true;
        }
        // Push as an ORed token to the last AND tokens
        else if (oring) {
            processed[processed.length - 1].push(matching_tokens_arr[i]);
            oring = false;
        }
        // Add a new AND tokens
        else {
            processed.push([matching_tokens_arr[i]]);
            oring = false;
        }
    }
    return processed.filter(array => array.length > 0);
}

/**
 * Filter the given items by looking for a the matching string inside the list of items.  Each item is converted to a
 * string using the ifun parameter, and then the matching parameter is searched for in that converted string. Everything
 * is done in lower-case to provide for case-independent matching.
 * @param items: list of items to filter
 * @param matching: (optional) string looked for in each item.  Case independent match. Default: match everything.
 * @param ifun: (optional) object to string function. Default: JSON.stringify
 * @return {[]}
 */
export function filter(items, matching, ifun) {
    matching = preprocess_matchings(matching);

    // Convert object to string using given ifun function, or JSON.stringify
    let stringer = ifun;
    if (typeof(stringer) === "undefined") {
        stringer = JSON.stringify;
    }
    let output = [];
    // Loop over the items, only adding to output list if we match
    for (let i = 0; i < items.length; i++) {
        let j = 0;
        let item = items[i];
        // ANDed loop, every iteration must match something in the sub list
        for (j = 0; j < matching.length; j++) {
            let stringified = stringer(item).toLowerCase();
            // Any of the OR array may match
            let any = matching[j].reduce((prev, current) => prev || stringified.indexOf(current) !== -1, false);
            // Not anything matches means this token does not match
            if (!any) {
                break;
            }
        }
        // Made it all the way through the loop, add item
        if (j === matching.length) {
            output.push(item);
        }
    }
    return output;
}

/**
 * Get a date object from a given time.
 * @param time: time object in fprime time format
 * @return {Date}: Javascript date object
 */
export function timeToDate(time) {
    let date = new Date((time.seconds * 1000) + (time.microseconds/1000));
    return date;
}

/**
 * Convert a given F´ time into a string for display purposes.
 * @param time: f´ time to convert
 * @return {string} stringified time
 */
export function timeToString(time) {
    let date = null;
    // If we have a workstation time, convert it to calendar time
    if (time instanceof Date) {
        date = time;
    }
    else if (time.base.value === 2) {
        date = timeToDate(time);
    }
    // Convert date
    if (date) {
        let dateFn = config.dateToString || ((date) => date.toISOString());
        return dateFn(date);
    }
    return time.seconds + "." + time.microseconds;
}

/**
 * Converts an attribute string with space-separated values into a string
 * array, counting items enclosed in the "encloseChar" as a single element
 *
 * (e.g. "Alpha Bravo 'Charlie Delta'" => ["Alpha", "Bravo", "Charlie Delta"]
 * @param {string} attributeString the string to convert to a list
 * @return {Array} Array of individual string items in attributeString
 */
export function attributeStringToList(attributeString, encloseChar="'") {
    const ec = encloseChar;
    // Will match enclosed strings AND include their enclosingChars, too
    const enclosedStringsRegex = new RegExp(`${ec}(.*?)${ec}`, "g");
    let enclosedStrings = attributeString.match(enclosedStringsRegex);

    if (enclosedStrings) {
        // Remove enclosing chars from these items
        const allEnclosing = new RegExp(ec, "g")
        enclosedStrings = enclosedStrings.map(x => x.replace(allEnclosing, ''));

        // Remove enclosed strings
        attributeString = attributeString.replace(enclosedStringsRegex, '').trim();
    }
    const otherStrings = attributeString.split(/\s+/);

    const allItems = otherStrings.concat(enclosedStrings);
    // filter out empty/null strings
    return allItems.filter(x => !!x);
}

/**
 * Converts an attribute string to an array if needed; if it's already an array,
 * leave it unchanged, otherwise convert it
 * @param {Array, String} stringOrArray
 * @return {Array} The array version of the input
 */
export function toArrayIfString(stringOrArray) {
    if (!stringOrArray) {
        // Return empty array if null
        return []
    }
    if (Array.isArray(stringOrArray)) {
        return stringOrArray;
    }
    return attributeStringToList(stringOrArray);
}

/**
 * Returns true if the given list has a length greater than 0 and the given
 * item is inside the list, false otherwise (will also accept strings)
 * @param {Array} list The list to check
 * @param {*} item Item to look for inside list
 * @return {boolean} True if list is non-empty and item is not inside, false otherwise
 *
 */
export function listExistsAndItemNameNotInList(list, item) {
    // TODO: Very specific conditions; should probably be broken into separate conditions, but this is what's used to hide rows on several components
    return list.length > 0 && !list.includes(item.template.name);
}

/**
 * ScrollHandler:
 *
 * A class/object used to manage the scrolling properties of a window. This allows the window to scroll through objects
 * acting as an infinite list, however; it does not display all those objects. It limits what is displayed to a finite
 * set as defined by this class. This helps prevent browser lag due to large numbers of HTML elements used to display
 * objects.
 */
export class ScrollHandler {
    /**
     * Build the scroll handler. It is passed the element to perform the actual scrolling and the data that is being
     * scrolled through. Both **must** be reference types. The scroll handler does not provide the ability to update or
     * change data. It assumes that the element and the data are updated independently.
     * @param displayed: displayed data store to be filled with the scrolled output
     * @param display_count: (optional) display count of items to show. Default: 100
     * @param scroll_step: (optional) step size of one unit of scroll. Default: 5
     */
    constructor(displayed, display_count, scroll_step) {
        this.element = null;
        this.data = null;
        this.displayed = displayed;

        this.metadata = {
            offset: 0,
            count: (display_count || 100),
            total: 0,
            status: false,
            locked: false,
            updating: false
        };

        this.offset = 0;
        this.count = (display_count || 100);

        this.step = (scroll_step || 5);
        this.updating = false;
        this.locked = false;

        this.prevTime = 0;
    }

    /**
     * Bind this scroller to scrolled data. Since the data is a non-reactive property this function should be called any
     * time the data is changed. It will do it's best to maintain a sensible offset following the following
     * algorithm:
     *
     * 1. If locked, or auto-update set offset to end of list
     * 2. Else, loop through previous data from offset to offset + count if item remains in data offset = index of item
     * 3. Else, clamp data to offset or 0/end-of-new-data
     *
     * @param scrolled_data: data being scrolled through
     */
    updateData(scrolled_data) {
        // Force data to exist preferring old data unless it is not set or was empty
        this.data = this.data || scrolled_data;
        // Handling case when staying
        if (this.updating || this.locked) {
            this.offset = this.data.length - this.count;
        }
        // Loop through previous data looking for remaining items and relocate offset there
        else if (this.offset >= 0 && this.offset < this.data.length) {
            for (let i = this.offset; i < (this.offset + this.count) && i < this.data.length; i++) {
                // Found an item that carried over
                let found_index = scrolled_data.indexOf(this.data[i]);
                if (found_index !== -1) {
                    this.offset = found_index;
                    break
                }
            }
        }
        // Safety clamp in all cases will maintain offset unless offset is out of valid range
        this.offset = Math.max(0, Math.min(this.offset, this.data.length - this.count));
        // Update data now that old data is no longer useful
        this.data = scrolled_data;

        // When auto-updating, filled, and not displaying the last this.count of items, then auto update the offset
        if (this.updating && this.filled() && (this.offset + this.count) < this.data.length) {
            this.offset = this.data.length - this.count;
            // Force scroll-bar to bottom
            this.element.scrollTop = this.element.scrollHeight - this.element.clientHeight;
        }
        this.update();
    }

    /**
     * Set the element for the scroller since it is only available right after it renders.
     * @param scroller_element: scrolled element to attach this scroller to
     */
    setElement(scroller_element) {
        this.element = scroller_element;
        this.element.addEventListener('scroll', this.onScroll.bind(this), true);
    }

    /**
     * Un set the element for destruction time to cleanup the event listener.
     */
    unsetElement() {
        if (this.element != null) {
            this.element.removeEventListener('scroll', this.onScroll.bind(this));
            this.element = null;
        }
    }

    /**
     * Has the data filled at least one display size.
     * @return {boolean}: filled or not
     */
    filled() {
        return this.data.length > this.count;
    }

    /**
     * Toggle the lock state and force a move to the bottom of the data list.
     */
    toggleLock() {
        this.locked = !this.locked;
        this.last();
    }

    /**
     * Returns to the first "page" of the data. Resets the scroll position and index into the data to the top of the
     * supplied list. Turns off updates such that the scrolling does not pull us away from the top of the list.
     */
    first() {
        this.element.scrollTop = 0;
        this.updating = false;
        if (this.filled()) {
            this.offset = 0;
        }
        this.update();
    }

    /**
     * Moves to the last "page" of the data. Resets the scroll position to the bottom and move the index into the data
     * as low as it can go while still displaying a page of data.
     */
    last() {
        this.element.scrollTop = this.element.scrollHeight - this.element.clientHeight;
        this.updating = true;
        if (this.filled()) {
            this.offset = this.data.length - this.count;
        }
        this.update();
    }

    /**
     * Only when filled, turn off auto-updating and move one step previous. Otherwise do nothing.
     */
    prev() {
        // Do nothing when not full
        if (this.filled()) {
            this.updating = false;
            this.move(-this.step);
        }
        this.update();
    }

    /**
     * Only when filled, turn off auto-updating and move one step forward. Otherwise do nothing.
     */
    next() {
        if (this.filled()) {
            this.updating = false;
            this.move(this.step);
        }
        this.update();
    }

    /**
     * Update the data elements for handling the automatic updates.
     */
    update() {
        this.metadata.count = this.count;
        this.metadata.offset = this.offset;
        this.metadata.total = this.data.length;
        this.metadata.status = this.filled();
        this.metadata.locked = this.locked;
        this.metadata.updating = this.updating;
        let data_slice = this.data.slice(this.offset, this.offset + this.count);
        this.displayed.splice(0, this.displayed.length, ...data_slice);
    }

    /**
     * Handle a scroll event. This turns off auto-updating when the user triggered the scroll and meters in elements
     * only when the scroll is at the top or bottom of the element.
     * @param e: scroll event being handled
     */
    onScroll(e) {
        // Ignore scrolling when locked
        if (this.locked) {
            return;
        }
        let user_scrolled = this.userScrolled(e);
        // Only when the user scrolls should we change the view
        if (this.filled() && user_scrolled) {
            let elmH = this.element.scrollHeight;
            let elmT = this.element.scrollTop;
            let elmC = this.element.clientHeight;
            let isAtBottom = (Math.abs(elmH - elmT - elmC) <= 2.0) && (elmT !== 0);

            // When scrolled to the bottom or top update range
            if (isAtBottom) {
                this.next(this.step);
            } else if (this.element.scrollTop === 0) {
                this.prev(this.step);
            }
        }
    }

    /**
     * Move the offset by the given change. Change is usually +this.step or -this.step. If the change would result in
     * before the beginning or past the end of the data, this will delegate to first/last as appropriate. Otherwise this
     * will move by the change and offset the scrollbar slightly to keep within range.
     * @param change: number of elements to move by
     */
    move(change) {
        let new_offset = this.offset + change;

        // Hit the end of the list thus handle appropriately
        if ((new_offset + this.count) >= this.data.length) {
            this.last();
        }
        // Hit beginning of list
        else if (new_offset <= 0) {
            this.first();
        }
        // Standard move: change offset, turn off updating, and back-off the scroll bar a bit
        else {
            this.offset = new_offset;
            this.updating = false;

            let top = (change >= 0) ? (this.element.scrollHeight - this.element.clientHeight) - 20 : 20;
            this.element.scrollTop = top > 0 ? top : 0;
        }
    }

    /**
     * Check the timestamp of scroll event and if less than a certain millisecond interval (800ms) it is a user
     * triggered scroll. If no event triggered the scroll, then it is not considered a user scroll.
     * @param e: scroll event
     * @return: true on user scroll, false otherwise
     */
    userScrolled(e) {
        if (e === undefined) {
            return false;
        }
        let current = e.timeStamp;
        let user_scrolled = (current - this.prevTime) < 800;
        this.prevTime = current;
        return user_scrolled;
    }
}
