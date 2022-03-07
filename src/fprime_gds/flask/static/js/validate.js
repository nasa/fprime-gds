import {_loader} from "./loader.js";

/**
 * validate.js:
 *
 * Validation functionality for various parts of the GDS system. Includes input validation checks, loading validators,
 * and other validation related code.
 */
let TYPE_LIMITS = {
    I8:  [-128n, 127n],
    U8:  [0n, 255n],
    I16: [-32768n, 32767n],
    U16: [0n, 65535n],
    I32: [-2147483648n, 2147483647n],
    U32: [0n, 4294967295n],
    I64: [-9223372036854775808n, 9223372036854775807n],
    U64: [0n, 18446744073709551615n]
};

/**
 * Finds a name in a list ignoring case.  Will return the name as seen in the list exactly, or null.  E.g. abc123 in
 * ABC123, hello, 123 would return ABC123. In the case of multiple matches, the first one is returned.
 *
 * It will first look for exact matches, and return that.  Then it will look for singular inexact "differs by case"
 * match. If multiple matches are found without an exact match or of no matches are found, null is returned to indicate
 * error.
 *
 * @param token: item to search for regardless of case
 * @param possible: list of possible values
 * @return {null|*}: matching item from possible or null if not found, or multiple inexact matches.
 */
export function find_case_insensitive(token, possible) {
    // Exact match
    if (possible.indexOf(token) !== -1) {
        return token;
    }
    if (token == null) {
        return null
    }
    token = token.toLowerCase();
    let matches = possible.filter(item => {return item.toLowerCase() === token});
    if (matches.length === 1) {
        return matches[0];
    }
    return null; // Not exactly one match
}

/**
 * Validate an input argument.
 * @param argument: argument to validate (will be updated with error)
 * @return {boolean}: true if valid, false otherwise
 */
export function validate_input(argument) {
    argument.error = "";
    // Integral types checking
    if (argument.type in TYPE_LIMITS) {
        let value = null;
        try {
            value = (argument.value == null) ? null : BigInt(argument.value);
        } catch (e) {}
        let limits = TYPE_LIMITS[argument.type];
        let message = (argument.type.startsWith("U")) ? "binary, octal, decimal, or hexadecimal unsigned integer":
                      "signed decimal integer";

        if (value == null || value < limits[0] || value > limits[1]) {
            argument.error = "Supply " + message + "  between " + limits.join(" and ");
            return false;
        }
    }
    // Floating point types
    else if (argument.type.startsWith("F") && isNaN(parseFloat(argument.value))) {
        argument.error = "Supply floating point number";
        return false;
    }
    // Enumeration types
    else if ("possible" in argument) {
        let valid_arg = find_case_insensitive(argument.value, argument.possible);
        if (valid_arg == null) {
            argument.error = "Supply one of: " + argument.possible.join(" ");
            return false;
        } else {
            argument.value = valid_arg;
        }
    } else if (argument.type === "String" && (argument.value === "" || argument.value == null)) {
        argument.error = "Supply general text";
    }
    return true;
}

/**
 * LoadValidator:
 *
 * A class used to intercept load responses from the backing server, process the internal validation tokens, and catalog
 * the results of the validation for distribution. Specifically it validates and provides the metrics from the
 * following:
 *
 * 1. Process faulted response error
 * 2. Process resulting errors included in response
 * 3. Validate the response with respect to the response validation tokens
 * 4. Track the request time of endpoints
 */
class LoadValidator {
    /**
     * Setup this particular load validation.
     * @param error_backlog_limit: limit to the error log. Limit: 100.
     * @param errors_to_console: log errors to console. Default: false.
     */
    constructor(error_backlog_limit, errors_to_console) {
        // Public tracking variables
        this.errors = [];
        this.counts = {};
        this.dropped = {};
        this.times = {};

        // Implementation variables
        this.errors_to_console = errors_to_console || false;
        this.error_limit = error_backlog_limit || 100;
        this.validation_counts = {}
    }

    /**
     * Update the tracked errors of this validator. This is done by counting these new errors, and then updating the
     * list of most recent errors. Note: the list of recent errors is effectively a rolling window and thus cannot be
     * used to capture error counts. This is tracked separately.
     *
     * errors: list of errors used to update
     */
    updateErrors(errors) {
        this.counts.GDS_Errors = (this.counts.GDS_Errors || 0) + errors.length;
        this.errors.push(errors);
        this.errors.splice(0, this.errors.length - this.error_limit);
        // Log errors to the console when requested
        if (this.errors_to_console) {
            errors.forEach(console.error);
        }
    }

    /**
     * Update the count of dropped packets. This is done by subtracting the total number of counted items to date from
     * the validation token in the message, which represents the server's total counted items to date.
     * @param key: key representing what we are counting and detecting drops within
     * @param history: list of new items to be counted
     * @param validation: validation token from the response
     */
    updateDropped(key, history, validation) {
        this.validation_counts[key] = (this.validation_counts[key] || 0) + (history || []).length;
        this.dropped[key] = (validation || this.validation_counts[key]) - this.validation_counts[key];
    }

    /**
     * Update the time tracking data.
     * @param key: key for tracking the timing.
     */
    updateTiming(key) {
        let last = _loader.endpoints[key].last || null;
        // Don't update window if there is no time detect or tracked
        if (last != null) {
            this.times[key] = this.times[key] || [];
            this.times[key].push(last);
            this.times[key].splice(0, window.length - 60);
        }
    }

    /**
     * Wrap a follow_on function in the code required to validate the response before passing the data onward. This
     * takes two items: a key to index into the validation, and a follow on function that process after validation.
     * @param key: key for indexing into the validation data
     * @param follow_on: function to process response post-validation. Must be bound with appropriate "this" context.
     */
    wrapResponseHandler(key, follow_on) {
        let handler = (data) => {
            this.updateDropped(key, (data.history || []), data.validation);
            this.updateErrors(data.errors || []);
            this.updateTiming(key);
            follow_on(data);
        };
        return handler.bind(this);
    }

    /**
     * Wrap a handler that inserts a counter based on a given field of the history items.
     * @param field: field to count as it is incoming
     * @param follow_on: function to process the data after counting
     * @param transformer: function to transform the value of a field. Default: item -> item
     * @param initials: initial value key-value maping for field counter. Default: {}
     */
    wrapFieldCounter(field, follow_on, transformer, initials) {
        let _self = this;
        transformer = transformer || ((item) => {return item;});
        let handler = (data) => {
            (data.history || []).forEach((item) => {
                let value = (item[field] || null);
                if (value !== null) {
                    let transformed_key = transformer(value);
                    _self.counts[transformed_key] += 1;
                }
            });
            follow_on(data);
        };
        Object.entries(initials || {}).forEach(([key, value]) => {_self.counts[key] = _self.counts[key] || value;});
        return handler.bind(this);
    }

    /**
     * Get an error response handler that will handle responses marked as errored.
     */
    getErrorHandler() {
        let handler = (key, error) => {
            this.updateTiming(key);
            this.updateErrors([error]);
        };
        return handler.bind(this)
    }
}
export let _validator = new LoadValidator(100, true);