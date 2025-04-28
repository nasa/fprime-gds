/**
 * json.js:
 *
 * Contains specialized JSON parser to handle non-standard JSON values from the JavaScript perspective. These values
 * are legal in Python and scala, but not in JavaScript. This parser will safely handle these values.
 *
 * @author mstarch
 */


/**
 * Lexer for JSON built using JSON
 */
class RegExLexer {
    static TOKEN_EXPRESSIONS = new Map([
        // String tokens: " then
        //    any number of:
        //        not a quote or \
        //        \ followed by not a quote
        //        even number of \
        //        odd number of \ then " (escaped quotation)
        //    then even number of \ then " (terminating non-escaped ")
        ["STRING", /^"([^"\\]|(\\[^"\\])|((\\\\)*)|(\\(\\\\)*)")*(?!\\(\\\\)*)"/],
        // Floating point tokens
        ["NUMBER", /^-?\d+(\.\d+)?([eE][+\-]?\d+)?/],
        // Infinity token
        ["INFINITY", /^-?Infinity/],
        // Null token
        ["NULL", /^null/],
        // NaN token
        ["NAN", /^NaN/],
        // boolean token
        ["BOOLEAN", /^(true)|^(false)/],
        // Open object token
        ["OPEN_OBJECT", /^\{/],
        // Close object token
        ["CLOSE_OBJECT", /^}/],
        // Field separator token
        ["FIELD_SEPARATOR", /^,/],
        // Open list token
        ["OPEN_ARRAY", /^\[/],
        // Close a list token
        ["CLOSE_ARRAY", /^]/],
        // Key Value Separator
        ["VALUE_SEPARATOR", /^:/],
        // Any amount of whitespace is an implicit token
        ["WHITESPACE", /^\s+/]
    ]);

    /**
     * Tokenize the input string based on JSON tokens.
     * @param input_string: input string to tokenize
     * @return {*[]}: list of tokens in-order
     */
    static tokenize(original_string) {
        let tokens = [];
        let input_string = original_string;
        let total_length = 0;
        let last_token_type = "--NONE--"
        // Consume the whole string
        while (input_string !== "") {
            let matched_something = false;
            for (let [token_type, token_matcher] of  RegExLexer.TOKEN_EXPRESSIONS.entries()) {
                let match = token_matcher.exec(input_string)

                // Token detected
                if (match != null && match.index == 0 ) {
                    matched_something = true;
                    let matched = match[0];
                    tokens.push([token_type, matched]);
                    // Consume the string
                    input_string = input_string.substring(matched.length);
                    total_length += matched.length;
                    last_token_type = token_type;
                    break;
                }
            }
            // Check for no token match
            if (!matched_something) {
                let say = "Failed to match valid token: '" + input_string.substring(0, 20);
                say += "' Context: '" + original_string.substring(Math.max(total_length - 20, 0), total_length + 20);
                say += "' Last token's type: " + last_token_type + ".";
                throw SyntaxError(say);
            }
        }
        return tokens;
    }
}

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
 * Parser to safely handle potential JSON object from Python. Python can produce some non-standard values (infinities,
 * NaNs, etc.) These values then break on the JS Javascript parser. To localize these faults, they are replaced before
 * processing with strings and then formally set during parsing.
 *
 * This is done by looking for tokens in unquoted text and replacing them with string representations.
 * 
 * This parser will handle:
 * - -Infinity
 * - Infinity
 * - NaN
 * - null
 * - BigInt
 */
export class SaferParser {
    static CONVERSION_KEY = "fprime{replacement";

    static CONVERSION_MAP = new Map([
        ["INFINITY", (value) => (value[0] === "-") ? -Infinity : Infinity],
        ["NAN", NaN],
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
     * @brief safely process F Prime JSON syntax
     *
     * Parse method that will replace JSON.parse. This method pre-processes the string data incoming (to be transformed
     * into JavaScript objects) for detection of entities not expressible in JavaScript's JSON implementation. This will
     * replace those entities with a JSON flag object.
     *
     * Then the data is processed by the JavaScript built-in JSON parser (now done safely).  The reviver function will
     * safely revive the flag objects into JavaScript representations of those object.
     *
     * Handles:
     * 1. BigInts
     * 2. Inf/-Inf
     * 3. NaN
     * 4. null
     *
     * @param json_string: JSON string data containing potentially bad values
     * @param reviver: reviver function to be combined with our reviver
     * @return {{}}: Javascript Object representation of data safely represented in JavaScript types
     */
    static parse(json_string, reviver) {
        let converted_data = SaferParser.preprocess(json_string);
        // Set up a composite reviver of the one passed in and ours
        let input_reviver = reviver || ((key, value) => value);
        let full_reviver = (key, value) => input_reviver(key, SaferParser.reviver(key, value));
        try {
            let language_parsed = SaferParser.language_parse(converted_data, full_reviver);
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
     * Apply process function to raw json string only for data that is not qu
     * @param json_string: JSON string to preprocess
     * @return {string}
     */
    static preprocess(json_string) {
        const CONVERSION_KEYS = Array.from(SaferParser.CONVERSION_MAP.keys());
        let tokens = RegExLexer.tokenize(json_string);
        let converted_text = tokens.map(
            ([token_type, token_text]) => {
                if (CONVERSION_KEYS.indexOf(token_type) !== -1) {
                    let replacement_object = {};
                    replacement_object[SaferParser.CONVERSION_KEY] = token_type;
                    replacement_object["value"] = token_text;
                    return SaferParser.language_stringify(replacement_object)
                }
                return token_text;
        });
        return converted_text.join("");
    }

    /**
     * Inverse of convert removing string and replacing back invalid JSON tokens.
     * @param key: JSON key
     * @param value: JSON value search for the converted value.
     * @return {*}: reverted value or value
     */
    static reviver(key, value) {
        // Look for fprime-replacement and quickly abort if not there
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
