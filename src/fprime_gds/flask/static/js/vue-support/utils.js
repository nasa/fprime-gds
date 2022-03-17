/**
 * utils.js:
 *
 * This file contains utility functions used by various parts of the vue-support system. Each item here intended for use
 * elsewhere should be "export"ed as then they can then be imported for use elsewhere.
 */
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
    // Loop through all of the tokens, spliting them itn
    for (let i = 0; i < matching_tokens_arr.length; i++) {
        // If token is -or- we eill be oring next time
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
    // If we have a workstation time, convert it to calendar time
    if (time.base.value == 2) {
        let date = timeToDate(time);
        return date.toISOString();
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
