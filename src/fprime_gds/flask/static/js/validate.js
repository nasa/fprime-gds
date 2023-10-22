import {_loader} from "./loader.js";
import {_settings} from "./settings.js";

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
    token = (token == null) ? token : token.toString();
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
 * Validates a supplied argument of enumeration type. **WARNING:** this will rewrite the enumeration's value to be
 * properly case-sensitive.
 * @param argument: argument of enumeration type.
 * @returns {boolean} false on validation error, true otherwise
 */
export function validate_enum_input(argument) {
    console.assert(argument.type.ENUM_DICT, "Validation of enumeration input not called on enumeration");
    let possible = Object.keys(argument.type.ENUM_DICT);
    let valid_arg = find_case_insensitive(argument.value, possible);
    if (valid_arg == null) {
        argument.error = "Supply one of: " + possible.join(" ");
        return false;
    }
    argument.value = valid_arg;
    argument.error = "";
    return true;
}

/**
 * Validate any scalar (non-struct, non-array) arguments. Note: in some cases this may correct the value.
 * @param argument: argument to validate.
 * @returns {boolean} true if valid, false if not valid
 */
export function validate_scalar_input(argument) {
    console.assert(!argument.MEMBER_LIST, "Validation of scalar called on struct");
    console.assert(! argument.LENGTH, "Validation of scalar called on array");

    let type_without_type = argument.type.name.replace("Type", "");
    // Handle enumerations
    if (argument.type.ENUM_DICT) {
        return validate_enum_input(argument);
    }
    // Integer types
    else if (type_without_type in TYPE_LIMITS) {
        let value = null;
        try {
            value = (argument.value == null) ? null : BigInt(argument.value);
        } catch (e) {}
        let limits = TYPE_LIMITS[type_without_type];
        let message = (type_without_type.startsWith("U")) ? "binary, octal, decimal, or hexadecimal unsigned integer":
                      "signed decimal integer";

        if (value == null || value < limits[0] || value > limits[1]) {
            argument.error = "Supply " + message + "  between " + limits.join(" and ");
            return false;
        }
        argument.error = "";
        return true;
    }
    // Check for string values
    else if (argument.type.name.indexOf("String") !== -1) {
        let max_length = argument.type.MAX_LENGTH;
        if (argument.value === "" || argument.value == null || argument.value.length > max_length) {
            argument.error = "Supply general text of less than " +  max_length + " characters";
            return false;
        }
        argument.error = "";
        return true;
    }
    // Floating point types
    else if ((["F32Type", "F64Type"].indexOf(argument.type.name) !== -1)) {
        if (isNaN(parseFloat(argument.value))) {
            argument.error = "Supply floating point number";
            return false;
        }
        argument.error = "";
        return true;
    }
    // Boolean type handling
    else if (argument.type.name === "BoolType") {
        return (argument.value == null) ? null :
            ["yes", "no", "true", "false"].indexOf(argument.value.toString().toLowerCase()) >= 0;
    }
    console.assert(false, "Unknown scalar type: " + argument.type.name);
    argument.error = "";
    return true;
}

/**
 * Validates an array argument by validating each of the sub arguments of that array.
 * @param argument: array argument to validate
 */
export function validate_array_or_struct_input(argument) {
    console.assert(argument.type.LENGTH || argument.type.MEMBER_LIST,
        "Validation of array/struct input not called on array/struct");
    let expected_field_tokens = []
    if (argument.type.MEMBER_LIST) {
        expected_field_tokens = argument.type.MEMBER_LIST.map((item) => item[0]);
    } else if (argument.type.LENGTH) {
        expected_field_tokens = Array(argument.type.LENGTH).fill().map((_, i) => i);
    }

    let valid = true;
    let errors = []
    for (let i = 0; i < expected_field_tokens.length; i++) {
        // Do NOT short-circuit out validation by hiding behind a &&
        if (!(expected_field_tokens[i] in argument.value)) {
            errors.push(`Missing field: ${expected_field_tokens[i]}.`);
        } else {
            let current_valid = validate_input(argument.value[expected_field_tokens[i]]);
            valid &&= current_valid;
            if (!current_valid) {
                errors.push(`Error in field/index: ${expected_field_tokens[i]}.`);
            }
        }
    }
    if (!valid) {
        argument.error = errors.join(" ");
    } else {
        argument.error = "";
    }
    return valid;
}

/**
 * Validate an input argument of any type.
 * @param argument: argument to validate (will be updated with error)
 * @return {boolean}: true if valid, false otherwise
 */
export function validate_input(argument) {
    let valid = false;
    if (argument.type.MEMBER_LIST || argument.type.LENGTH) {
        valid = validate_array_or_struct_input(argument);
    } else {
        valid = validate_scalar_input(argument);
    }
    return valid;
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
        this.misc_counts = {};
        this.window_ms = 5 * 60 * 1000;

        // Implementation variables
        this.errors_to_console = errors_to_console || false;
        this.error_limit = error_backlog_limit || 100;
        this.validation_counts = {}
        this.falling_behind = {};
    }

    /**
     * Update an arbitrary counter by one.
     * @param count_key: counter key that will be updated
     * @param init: (optional) init the count but do not add to it
     */
    arbitraryCount(count_key, init) {
        this.misc_counts[count_key] = (this.misc_counts[count_key] || 0);
        if (!init) {
            this.misc_counts[count_key] += 1;
        }
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
        this.errors.push(...errors);
        this.errors.splice(0, this.errors.length - this.error_limit);
        // Log errors to the console when requested
        if (this.errors_to_console) {
            errors.forEach((error) => { console.error(error); });
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
            let polling_interval = parseInt(_settings.polling_intervals[key]) || 1000;
            let window_samples = Math.round(this.window_ms / polling_interval);
            this.times[key] = this.times[key] || [];
            this.times[key].push(last);
            this.times[key].splice(0, this.times[key].length - window_samples);

            // Update if this is falling behind
            let time_now = new Date();
            if (last <= (polling_interval/1000)) {
                this.falling_behind[key] = time_now;
            }
            // Error if last good time was more than 5 seconds ago
            else if ((time_now - (this.falling_behind[key] || time_now)) >= 5000) {
                this.updateErrors(["Polling for '" + key + "' is falling behind fore 5 seconds"]);
                this.falling_behind[key] = time_now;
            }
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
     * @param initials: initial value key-value mapping for field counter. Default: {}
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
            this.updateErrors(["[ERROR] '" + key + "' produced error: " +error]);
        };
        return handler.bind(this)
    }
}
export let _validator = new LoadValidator(100, true);
