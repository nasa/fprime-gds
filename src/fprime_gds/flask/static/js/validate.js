/**
 * validate.js:
 *
 * Validation functionality for inputs as part of fprime.
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
    if (possible.indexOf(token) != -1) {
        return token;
    }
    if (token == null) {
        return null
    }
    token = token.toLowerCase();
    let matches = possible.filter(item => {return item.toLowerCase() == token});
    if (matches.length == 1) {
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
    } else if (argument.type == "String" && (argument.value == "" || argument.value == null)) {
        argument.error = "Supply general text";
    }
    return true;
}