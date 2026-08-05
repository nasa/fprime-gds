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
 * Coerce a value to string like native JSON.parse's ToString: prefers toString() over valueOf()
 * and throws TypeError for Symbols
 * @param value: value to coerce
 * @return {string}: string form of the value
 */
function coerceLikeNativeParse(value) {
    return (typeof value === "string") ? value : `${value}`;
}

/**
 * Helper to determine if value is a function
 * @param value: value to check
 * @return {boolean}: true if function, false otherwise
 */
function isFunction(value) {
    return value instanceof Function || typeof value == "function";
}

// JSON number grammar: rejects values JSON.parse would never produce (hex, empty, bare "-", etc.)
const JSON_NUMBER = /^-?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?$/;

/**
 * Convert a string in JSON number form to a number
 * @param value: value to convert
 * @return {bigint|number}: number to return
 * @throws {SyntaxError}: when the value is not a valid JSON number
 */
function stringToNumber(value) {
    value = value.trim(); // Tolerate whitespace-padded flag-object values before the strict grammar check
    if (!JSON_NUMBER.test(value)) {
        throw new SyntaxError("Invalid JSON number: " + value);
    }
    // Process floats (containing . e or E)
    if (value.search(/[.eE]/) !== -1) {
        return Number.parseFloat(value);
    }
    // Negative zero round-trips as a number: its toString() is "0", which would misroute it to BigInt
    if (value === "-0") {
        return -0;
    }
    const number_value = Number.parseInt(value, 10);
    // When the big and normal numbers match, then return the normal number
    if (value !== number_value.toString()) {
        return BigInt(value);
    }
    return number_value;
}

/**
 * Convert an Infinity token string to its numeric value
 * @param value: "Infinity" or "-Infinity"
 * @return {number}: the signed infinity
 * @throws {SyntaxError}: when the value is not an Infinity token
 */
function stringToInfinity(value) {
    value = value.trim(); // Tolerate whitespace-padded flag-object values, matching stringToNumber
    if (value === "Infinity") {
        return Infinity;
    }
    if (value === "-Infinity") {
        return -Infinity;
    }
    throw new SyntaxError("Invalid Infinity token: " + value);
}

/**
 * Determine if a character is a JSON digit (0-9)
 * @param character: single character string
 * @return {boolean}: true if digit, false otherwise
 */
function isDigit(character) {
    return character >= "0" && character <= "9";
}

// Shortest digit-run length that can exceed the safe-integer range (16: the length of 2^53's decimal form)
const UNSAFE_DIGIT_RUN_LENGTH = String(Number.MAX_SAFE_INTEGER).length;

/**
 * Determine if a string contains a run of UNSAFE_DIGIT_RUN_LENGTH or more consecutive digits (the
 * length at which an integer can exceed Number.MAX_SAFE_INTEGER). Samples every
 * UNSAFE_DIGIT_RUN_LENGTH-th character: any such run must contain a sampled index, so no run can be
 * missed. Runs found are skipped over, keeping the scan near O(n / UNSAFE_DIGIT_RUN_LENGTH).
 * @param json_string: string to scan
 * @return {boolean}: true if a long digit run exists
 */
function hasLongDigitRun(json_string) {
    const length = json_string.length;
    for (let i = UNSAFE_DIGIT_RUN_LENGTH - 1; i < length; i += UNSAFE_DIGIT_RUN_LENGTH) {
        if (isDigit(json_string[i])) {
            let low = i;
            while (low > 0 && isDigit(json_string[low - 1])) {
                low--;
            }
            let high = i;
            while (high + 1 < length && isDigit(json_string[high + 1])) {
                high++;
            }
            if (high - low + 1 >= UNSAFE_DIGIT_RUN_LENGTH) {
                return true;
            }
            i = high; // Resume sampling past this (short) digit run
        }
    }
    return false;
}

/**
 * Scan a number token (digits, decimal point, exponent) starting at the given index. Deliberately lax:
 * ".", "e"/"E", "+", "-" are accepted at any position; malformed sequences are rejected later by
 * JSON.parse, and any such character marks the token non-integral so it is never BigInt-wrapped.
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
 * processing with flag objects that are revived into the real values during parsing.
 *
 * This is done by scanning unquoted text in a single linear pass and replacing Infinity, -Infinity, NaN, and
 * integers outside the safe-integer range (Number.isSafeInteger() false) with flag objects that are
 * revived during parsing.
 *
 * This parser will handle:
 * - -Infinity
 * - Infinity
 * - NaN
 * - null (handled natively by JSON.parse)
 * - BigInt
 *
 * Literal flag objects appearing in input are also revived for round-trip compatibility; revival is
 * validated, and malformed flag objects pass through unchanged rather than failing the whole parse:
 * one bad value must not take down an entire telemetry poll.
 *
 * preprocess() is retained as a public entry point for external callers; parse() does not use it.
 */
export class SaferParser {
    // Must stay ASCII-only: mayContainFlagObject()'s \u00 escape gate depends on it
    static CONVERSION_KEY = "fprime{replacement";

    // Bare tokens the scanner (scanAndReplace) replaces, mapped to conversion type and sign
    // admissibility. Both the gate (hasReplaceableToken) and the scanner consume this single
    // authoritative token list
    static GATE_TOKENS = new Map([
        ["NaN", {conversion_type: "NAN", allows_sign: false}],
        ["Infinity", {conversion_type: "INFINITY", allows_sign: true}]
    ]);

    // First characters of the gate tokens: a cheap scanner filter before the startsWith checks
    static GATE_TOKEN_STARTS = new Set([...SaferParser.GATE_TOKENS.keys()].map((token) => token[0]));

    // Escapes that can spell a CONVERSION_KEY character, generated from the key itself so the two can
    // never drift; other escapes (\u0067, \u00b0, \u4e2d) keep the fast path
    static KEY_ESCAPE = new RegExp("\\\\u00(?:" + [...new Set(SaferParser.CONVERSION_KEY)]
        .map((character) => character.charCodeAt(0).toString(16).padStart(2, "0")).join("|") + ")", "i");

    static CONVERSION_MAP = new Map([
        ["INFINITY", stringToInfinity],
        ["NAN", NaN],
        // Retained for literal flag objects appearing in input; preprocess() never emits NULL (null parses natively)
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

    // Store the language variants the first time
    static language_parse = JSON.parse;
    static language_stringify = JSON.stringify;

    /**
     * Quick check for bare tokens needing replacement: Infinity/NaN or integers that may exceed
     * Number.MAX_SAFE_INTEGER. False positives (e.g. tokens inside strings) are acceptable: they
     * merely trigger the single-pass scan. This check must cover every token type scanAndReplace()
     * replaces, or replacement is silently skipped.
     * @param json_string: JSON string to check
     * @return {boolean}: true if the replacement scan is needed
     */
    static hasReplaceableToken(json_string) {
        for (const token of SaferParser.GATE_TOKENS.keys()) {
            if (json_string.includes(token)) {
                return true;
            }
        }
        return hasLongDigitRun(json_string);
    }

    /**
     * Single owner of the preprocessing gate decision: whether a literal flag object may be present
     * (needing the reviver) and whether the replacement scan is needed at all.
     * @param json_string: JSON string to check
     * @return {{may_contain_flag: boolean, needs_scan: boolean}}
     */
    static preprocessDecision(json_string) {
        const may_contain_flag = SaferParser.mayContainFlagObject(json_string);
        return {
            may_contain_flag: may_contain_flag,
            needs_scan: may_contain_flag || SaferParser.hasReplaceableToken(json_string)
        };
    }

    /**
     * Quick check for input that may need preprocessing: a replaceable bare token or a literal flag
     * object needing revival.
     * @param json_string: JSON string to check
     * @return {boolean}: true if the scan/reviver path is needed
     */
    static needsPreprocess(json_string) {
        return SaferParser.preprocessDecision(json_string).needs_scan;
    }

    /**
     * Match a gate token (see GATE_TOKENS) at the given index.
     * @param json_string: full input string
     * @param index: index at which to match
     * @return {{token: string, conversion_type: string, allows_sign: boolean}|null}: match or null
     */
    static matchGateToken(json_string, index) {
        for (const [token, properties] of SaferParser.GATE_TOKENS) {
            if (json_string.startsWith(token, index)) {
                return {token: token, conversion_type: properties.conversion_type,
                        allows_sign: properties.allows_sign};
            }
        }
        return null;
    }

    /**
     * Determine if the input may contain a literal flag object needing revival. The escape check catches
     * keys spelled with unicode escapes (e.g. "fprime\u007breplacement"), which parse to CONVERSION_KEY
     * but would not match a literal substring check.
     * @param json_string: JSON string to check
     * @return {boolean}: true if a flag object may be present
     */
    static mayContainFlagObject(json_string) {
        return json_string.includes(SaferParser.CONVERSION_KEY) || SaferParser.KEY_ESCAPE.test(json_string);
    }

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
     * @param json_string: JSON string data containing potentially bad values; non-string input is
     *                     coerced to string to match native JSON.parse semantics
     * @param reviver: reviver function to be combined with our reviver
     * @return {{}}: Javascript Object representation of data safely represented in JavaScript types
     */
    static parse(json_string, reviver) {
        json_string = coerceLikeNativeParse(json_string);
        // When decision.needs_scan is false, no replacement is needed and no flag object can be present:
        // parse with only the caller's reviver (or none), avoiding the significant cost of a per-node
        // reviver callback. The quick check is the only overhead on this common clean-payload path.
        let converted_data = json_string;
        let full_reviver = reviver;
        const decision = SaferParser.preprocessDecision(json_string);
        if (decision.needs_scan) {
            converted_data = SaferParser.scanAndReplace(json_string);
            // False positives (e.g. tokens inside strings) yield no replacement and need no reviver,
            // unless a literal flag object may be present and must be revived
            if (converted_data !== json_string || decision.may_contain_flag) {
                // Non-callable revivers are ignored, matching native JSON.parse
                const input_reviver = isFunction(reviver) ? reviver : ((key, value) => value);
                // Preserve the holder binding (this) and any extra arguments for the caller's reviver
                full_reviver = function (key, value, context) {
                    return input_reviver.call(this, key, SaferParser.reviver(key, value), context);
                };
            }
        }
        try {
            return SaferParser.language_parse(converted_data, full_reviver);
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
     * Replace JSON notation for flag objects (see CONVERSION_KEY) with the wider JSON specification
     *
     * Replace {"fprime{replacement": "some value"} with <some value> restoring the full JSON specification for items
     * not supported by JavaScript.
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
     * Replace tokens invalid in JavaScript JSON (Infinity, -Infinity, NaN, and integers outside the
     * safe-integer range, Number.isSafeInteger() false) with flag objects, leaving all other text
     * untouched. Input without any such tokens is returned as-is.
     *
     * @param json_string: JSON string to preprocess
     * @return {string}
     */
    static preprocess(json_string) {
        // Fast path for direct external callers; parse() gates itself and calls scanAndReplace() directly
        json_string = coerceLikeNativeParse(json_string);
        if (!SaferParser.needsPreprocess(json_string)) {
            return json_string;
        }
        return SaferParser.scanAndReplace(json_string);
    }

    /**
     * Ungated single linear pass; called by parse() directly and by preprocess() after its gate.
     * String literals are skipped (honoring escape sequences), and no per-token substring copies of
     * the remaining input are made. Any token type emitted here MUST also be covered by
     * hasReplaceableToken(), or its replacement is silently skipped on the gated paths.
     * @param json_string: JSON string to preprocess
     * @return {string}
     */
    static scanAndReplace(json_string) {
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
            // Gate token (NaN, Infinity), optionally signed, or a number (possibly requiring BigInt)
            if (SaferParser.GATE_TOKEN_STARTS.has(character) || character === "-" || isDigit(character)) {
                const start = i;
                if (character === "-") {
                    i++;
                }
                // A sign prefix is only valid where the token allows it (e.g. "-Infinity", never "-NaN")
                const gate_match = SaferParser.matchGateToken(json_string, i);
                if (gate_match !== null && (start === i || gate_match.allows_sign)) {
                    i += gate_match.token.length;
                    emit(start, i, gate_match.conversion_type);
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
                const digits = (token_text[0] === "-") ? token_text.substring(1) : token_text;
                // Integers only (a bare "-" does not end in a digit); floats never need BigInt handling,
                // and leading-zero tokens are left for JSON.parse to reject as invalid JSON
                const ends_in_digit = isDigit(token_text[token_text.length - 1]);
                const has_leading_zero = digits.length > 1 && digits[0] === "0";
                const exceeds_safe_range = !Number.isSafeInteger(Number(token_text));
                if (is_integer && ends_in_digit && !has_leading_zero && exceeds_safe_range) {
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
     * Reviver that converts flag objects (see CONVERSION_KEY) back into their JavaScript values.
     * @param key: JSON key
     * @param value: JSON value search for the converted value.
     * @return {*}: revived value, or the input value unchanged when the flag object is malformed
     *              (unknown type, missing/non-string "value", or revival throws SyntaxError);
     *              other revival errors propagate
     */
    static reviver(key, value) {
        // Look for the CONVERSION_KEY flag and quickly abort if not there
        if (value === null || typeof value !== "object") {
            return value;
        }
        const replacement_type = value[SaferParser.CONVERSION_KEY];
        if (!SaferParser.CONVERSION_MAP.has(replacement_type)) {
            return value;
        }
        const replacer = SaferParser.CONVERSION_MAP.get(replacement_type);
        // Constant conversions (NAN, NULL) need no "value" member, so no shape check applies
        if (!isFunction(replacer)) {
            return replacer;
        }
        // Malformed flag objects (missing or non-string value) pass through unchanged rather than throwing
        const string_value = value["value"];
        if (typeof string_value !== "string") {
            return value;
        }
        try {
            return replacer(string_value);
        } catch (e) {
            // Malformed values (SyntaxError) are intentionally non-fatal and pass through unchanged;
            // anything else is a converter bug and must surface
            if (!(e instanceof SyntaxError)) {
                throw e;
            }
            return value;
        }
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
