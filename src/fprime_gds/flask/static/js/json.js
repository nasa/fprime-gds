/**
 * json.js:
 *
 * Contains specialized JSON parser to handle non-standard JSON values from the JavaScript perspective. These values
 * are legal in Python and scala, but not in JavaScript. This parser will safely handle these values.
 *
 * @author mstarch
 */

/**
 * Helper to determine if value is a string
 * @param value: value to check.
 * @return {boolean}: true if string, false otherwise
 */
function isString(value) {
    return value instanceof String || typeof value === 'string';
}

/**
 * Helper to determine if value is a function
 * @param value: value to check
 * @return {boolean}: true if function, false otherwise
 */
function isFunction(value) {
    return value instanceof Function || typeof value == "function";
}

/**
 * Convert a string to a number
 * @param value: value to convert
 * @return {bigint|number}: number to return
 */
function stringToNumber(value) {
    value = value.trim(); // Should be unnecessary
    // Process floats (containing . e or E)
    if (value.search(/[.eE]/) !== -1) {
        return Number.parseFloat(value);
    }
    let number_value = Number.parseInt(value);
    // When the big and normal numbers match, then return the normal number
    if (value !== number_value.toString()) {
        return BigInt(value);
    }
    return number_value;
}

/**
 * Determine if a character is a JSON digit (0-9)
 * @param character: single character string
 * @return {boolean}: true if digit, false otherwise
 */
function isDigit(character) {
    return character >= "0" && character <= "9";
}

/**
 * Scan a number token (digits, decimal point, exponent) starting at the given index
 * @param json_string: full input string
 * @param start: index of the first character of the number body (after any leading "-")
 * @return {{end: number, is_integer: boolean}}: index past the token and whether it stayed integral
 */
function scanNumberToken(json_string, start) {
    const length = json_string.length;
    let is_integer = true;
    let i = start;
    while (i < length) {
        const token_character = json_string[i];
        if (isDigit(token_character)) {
            i++;
        } else if (token_character === "." || token_character === "e" || token_character === "E" ||
                   token_character === "+" || token_character === "-") {
            is_integer = false;
            i++;
        } else {
            break;
        }
    }
    return {end: i, is_integer: is_integer};
}

/**
 * Parser to safely handle potential JSON object from Python. Python can produce some non-standard values (infinities,
 * NaNs, etc.) These values then break on the JS Javascript parser. To localize these faults, they are replaced before
 * processing with strings and then formally set during parsing.
 *
 * This is done by scanning unquoted text in a single linear pass and replacing Infinity, -Infinity, NaN, and
 * integers exceeding Number.MAX_SAFE_INTEGER with flag objects that are revived during parsing.
 *
 * This parser will handle:
 * - -Infinity
 * - Infinity
 * - NaN
 * - null (handled natively by JSON.parse)
 * - BigInt
 */
export class SaferParser {
    static CONVERSION_KEY = "fprime{replacement";

    static CONVERSION_MAP = new Map([
        ["INFINITY", (value) => (value[0] === "-") ? -Infinity : Infinity],
        ["NAN", NaN],
        // Retained for literal flag objects in input; preprocess() no longer emits NULL (null parses natively)
        ["NULL", null],
        ["NUMBER", stringToNumber]
    ]);

    static STRINGIFY_TOKENS = [
        Infinity,
        -Infinity,
        NaN,
        "number",
        "bigint",
        null
    ];

    // Quick check for input that may need preprocessing: bare Infinity/NaN tokens or integers long enough
    // to exceed Number.MAX_SAFE_INTEGER (its smallest violator, 2^53, has 16 digits). False positives (e.g.
    // tokens inside strings) are acceptable: they merely trigger the single-pass scan below. This regex must
    // match every token type preprocess() replaces, or replacement is silently skipped.
    static NEEDS_PREPROCESS = /Infinity|NaN|\d{16}/;

    // Store the language variants the first time
    static language_parse = JSON.parse;
    static language_stringify = JSON.stringify;

    /**
     * @brief safely process F Prime JSON syntax
     *
     * Parse method that will replace JSON.parse. This method pre-processes the string data incoming (to be transformed
     * into JavaScript objects) for detection of entities not expressible in JavaScript's JSON implementation. This will
     * replace those entities with a JSON flag object.
     *
     * Then the data is processed by the JavaScript built-in JSON parser (now done safely).  The reviver function will
     * safely revive the flag objects into JavaScript representations of those object. When the input contains no
     * such tokens (and no flag objects), it is parsed directly with only the caller-supplied reviver.
     *
     * Handles:
     * 1. BigInts
     * 2. Inf/-Inf
     * 3. NaN
     * 4. null (natively)
     *
     * @param json_string: JSON string data containing potentially bad values
     * @param reviver: reviver function to be combined with our reviver
     * @return {{}}: Javascript Object representation of data safely represented in JavaScript types
     */
    static parse(json_string, reviver) {
        // Match native JSON.parse semantics, which coerce non-string input to string
        json_string = (typeof json_string === "string") ? json_string : String(json_string);
        const converted_data = SaferParser.preprocess(json_string);
        // When no replacements were made and no literal flag objects can be present, parse with only the
        // caller's reviver (or none), avoiding the significant cost of a per-node reviver callback
        let full_reviver = reviver;
        if (converted_data !== json_string || json_string.includes(SaferParser.CONVERSION_KEY)) {
            const input_reviver = reviver || ((key, value) => value);
            full_reviver = (key, value) => input_reviver(key, SaferParser.reviver(key, value));
        }
        try {
            const language_parsed = SaferParser.language_parse(converted_data, full_reviver);
            return language_parsed;
        } catch (e) {
            let message = e.toString();
            const matcher = /line (\d+) column (\d+)/

            // Process the match
            let snippet = "";
            let match = message.match(matcher);
            if (match != null) {
                let lines = converted_data.split("\n");
                let line = lines[Number.parseInt(match[1]) - 1]
                snippet = line.substring(Number.parseInt(match[2]) - 6, Number.parseInt(match[2]) + 5);
                message += ". Offending snippet: " + snippet;
                throw new SyntaxError(message);
            }
            throw e;
        }
    }

    /**
     * @brief safely write the F Prime JSON syntax
     *
     * Stringify method that will replace JSON.stringify. This method post-processes the string data outgoing from
     * JavaScript's built-in stringify method to replace flag-objects with the correct F Prime representation in
     * JavaScript.
     *
     * This uses the javascript stringify handler method to pre-convert unsupported types into a flag object. This flag
     * object is post-converted into a normal string after JSON.stringify has done its best.
     *
     * Handles:
     * 1. BigInts
     * 2. Inf/-Inf
     * 3. NaN
     * 4. null
     *
     * @param data: data object to stringify
     * @param replacer: replacer Array or Function
     * @param space: space for passing into JSON.stringify
     * @return {{}}: JSON string using JSON support for big-ints Int/-Inf, NaN and null.
     */
    static stringify(data, replacer, space) {
        let full_replacer = (key, value) => {
            // Handle array case for excluded field
            if (Array.isArray(replacer) && replacer.indexOf(key) === -1) {
                return undefined;
            }
            // Run input replacer first
            else if (isFunction(replacer)) {
                value = replacer(key, value);
            }
            // Then run our safe replacer
            let replaced = SaferParser.replaceFromObject(key, value);
            return replaced;
        };
        // Stringify JSON using built-in JSON parser and the special replacer
        let json_string = SaferParser.language_stringify(data, full_replacer, space);
        // Post-process JSON string to rework JSON into the wider specification
        let post_replace =  SaferParser.postReplacer(json_string);
        return post_replace
    }

    /**
     * Get replacement object from a JavaScript type
     * @param _: unused
     * @param value: value to replace
     */
    static replaceFromObject(_, value) {
        for (let i = 0; i < SaferParser.STRINGIFY_TOKENS.length; i++) {
            let replacer_type = SaferParser.STRINGIFY_TOKENS[i];
            let mapper_is_string = isString(replacer_type);
            if ((!mapper_is_string && value === replacer_type) || (mapper_is_string && typeof value === replacer_type)) {
                let replace_object = {};
                replace_object[SaferParser.CONVERSION_KEY] = (value == null) ? "null" : value.toString();
                return replace_object;
            }
        }
        return value;
    }

    /**
     * Replace JSON notation for fprime-replacement objects with the wider JSON specification
     *
     * Replace {"fprime-replacement: "some value"} with <some value> restoring the full JSON specification for items not
     * supported by JavaScript.
     *
     * @param json_string: JSON string to rework
     * @return reworked JSON string
     */
    static postReplacer(json_string) {
        return json_string.replace(/\{\s*"fprime\{replacement"\s*:\s*"([^"]+)"\s*}/sg, "$1");
    }

    /**
     * Build the flag-object JSON text for a detected token
     * @param token_type: conversion type key (e.g. "INFINITY", "NAN", "NUMBER")
     * @param token_text: raw token text from the input
     * @return {string}: JSON string of the flag object
     */
    static replacementFor(token_type, token_text) {
        const replacement_object = {};
        replacement_object[SaferParser.CONVERSION_KEY] = token_type;
        replacement_object["value"] = token_text;
        return SaferParser.language_stringify(replacement_object);
    }

    /**
     * Replace tokens invalid in JavaScript JSON (Infinity, -Infinity, NaN, and integers exceeding
     * Number.MAX_SAFE_INTEGER) with flag objects, leaving all other text untouched.
     *
     * Runs in a single linear pass over the input: string literals are skipped (honoring escape
     * sequences), and no per-token substring copies of the remaining input are made. Input without
     * any such tokens is returned as-is.
     *
     * @param json_string: JSON string to preprocess
     * @return {string}
     */
    static preprocess(json_string) {
        // Fast path: no problematic token can be present. Any token type emitted below MUST also be
        // matched by NEEDS_PREPROCESS above, or its replacement is silently skipped.
        if (!SaferParser.NEEDS_PREPROCESS.test(json_string)) {
            return json_string;
        }
        const length = json_string.length;
        const pieces = [];
        let copied_index = 0; // Start of the pending un-copied region
        // Emit the pending clean region followed by the flag object for the token in [token_start, token_end)
        const emit = (token_start, token_end, token_type) => {
            pieces.push(json_string.substring(copied_index, token_start),
                        SaferParser.replacementFor(token_type, json_string.substring(token_start, token_end)));
            copied_index = token_end;
        };
        let i = 0;
        while (i < length) {
            const character = json_string[i];
            // Skip string literals entirely, honoring backslash escapes
            if (character === '"') {
                i++;
                while (i < length && json_string[i] !== '"') {
                    i += (json_string[i] === "\\") ? 2 : 1;
                }
                i++; // Consume closing quote
                continue;
            }
            // Bare NaN token
            if (character === "N" && json_string.startsWith("NaN", i)) {
                emit(i, i + "NaN".length, "NAN");
                i += "NaN".length;
                continue;
            }
            // Infinity, -Infinity, or a number (possibly requiring BigInt)
            if (character === "I" || character === "-" || isDigit(character)) {
                const start = i;
                if (character === "-") {
                    i++;
                }
                if (json_string.startsWith("Infinity", i)) {
                    i += "Infinity".length;
                    emit(start, i, "INFINITY");
                    continue;
                }
                // Scan the number token: digits, decimal, and exponent
                const scan = scanNumberToken(json_string, i);
                const is_integer = scan.is_integer;
                i = scan.end;
                // Guarantee forward progress on malformed input (e.g. a stray "I" that is not "Infinity")
                if (i === start) {
                    i++;
                    continue;
                }
                const token_text = json_string.substring(start, i);
                // Integers only (the last-char digit check rejects a bare "-"); floats never need BigInt handling
                if (is_integer && isDigit(token_text[token_text.length - 1]) && !Number.isSafeInteger(Number(token_text))) {
                    emit(start, i, "NUMBER");
                }
                continue;
            }
            i++;
        }
        // Fully clean input: avoid the copy altogether
        if (copied_index === 0) {
            return json_string;
        }
        pieces.push(json_string.substring(copied_index));
        return pieces.join("");
    }

    /**
     * Inverse of convert removing string and replacing back invalid JSON tokens.
     * @param key: JSON key
     * @param value: JSON value search for the converted value.
     * @return {*}: reverted value or value
     */
    static reviver(key, value) {
        // Look for fprime-replacement and quickly abort if not there
        if (value === null || typeof value !== "object") {
            return value;
        }
        let replacement_type = value[SaferParser.CONVERSION_KEY];
        if (typeof replacement_type === "undefined") {
            return value;
        }
        let string_value = value["value"];
        let replacer = SaferParser.CONVERSION_MAP.get(replacement_type);
        return isFunction(replacer) ? replacer(string_value) : replacer;
    }

     /**
     * @brief force all calls to JSON.parse and JSON.stringify to use the SafeParser
     */
    static register() {
        // Override the singleton
        JSON.parse = SaferParser.parse;
        JSON.stringify = SaferParser.stringify;
    }

    /**
     * @brief remove the JSON.parse safe override
     */
    static deregister() {
        JSON.parse = SaferParser.language_parse;
        JSON.stringify = SaferParser.language_stringify;
    }
}
// Take over all JSON.parse and JSON.stringify calls
SaferParser.register();
