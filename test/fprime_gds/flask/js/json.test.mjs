/**
 * json.test.mjs:
 *
 * Unit tests for the SaferParser in flask/static/js/json.js. Run with: node --test json.test.mjs
 *
 * @author mstarch
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { SaferParser } from "../../../../src/fprime_gds/flask/static/js/json.js";

// Tests exercise SaferParser directly; restore the built-in JSON functions
SaferParser.deregister();

test("basic values parse correctly", () => {
    const parsed = SaferParser.parse('{"a": 1, "b": "x", "c": true, "d": null, "e": [1.5, -2.5e3]}');
    assert.equal(parsed.a, 1);
    assert.equal(parsed.b, "x");
    assert.equal(parsed.c, true);
    assert.equal(parsed.d, null);
    assert.deepEqual(parsed.e, [1.5, -2.5e3]);
});

test("non-standard tokens are revived", () => {
    assert.equal(SaferParser.parse('{"a": Infinity}').a, Infinity);
    assert.equal(SaferParser.parse('{"a": -Infinity}').a, -Infinity);
    assert.ok(Number.isNaN(SaferParser.parse('{"a": NaN}').a));
    const values = SaferParser.parse('[NaN, Infinity, -Infinity]');
    assert.equal(values.length, 3);
    assert.ok(Number.isNaN(values[0]));
    assert.equal(values[1], Infinity);
    assert.equal(values[2], -Infinity);
});

test("unsafe integers become BigInt at the exact boundary", () => {
    assert.equal(SaferParser.parse('{"a": 9007199254740991}').a, Number.MAX_SAFE_INTEGER);
    assert.equal(typeof SaferParser.parse('{"a": 9007199254740991}').a, "number");
    assert.equal(SaferParser.parse('{"a": 9007199254740993}').a, 9007199254740993n);
    // 2^53 itself is exactly representable, so it round-trips back to a plain number
    assert.equal(SaferParser.parse('{"a": 9007199254740992}').a, 9007199254740992);
    assert.equal(typeof SaferParser.parse('{"a": 9007199254740992}').a, "number");
    assert.equal(SaferParser.parse('{"a": 18446744073709551615}').a, 18446744073709551615n);
    assert.equal(SaferParser.parse('{"a": -18446744073709551615}').a, -18446744073709551615n);
    assert.equal(typeof SaferParser.parse('{"a": -9007199254740991}').a, "number");
    assert.equal(SaferParser.parse('{"a": -9007199254740993}').a, -9007199254740993n);
    // Multiple replacements in one input exercise the piece-stitching bookkeeping
    assert.deepEqual(SaferParser.parse('[9007199254740993, 9007199254740995]'),
                     [9007199254740993n, 9007199254740995n]);
});

test("floats and exponent forms are never BigInt-wrapped", () => {
    assert.equal(SaferParser.parse('{"a": 1.5e10}').a, 1.5e10);
    assert.equal(SaferParser.parse('{"a": 12345678901234567890.5}').a, 12345678901234567890.5);
    assert.equal(SaferParser.parse('{"a": 1234567890123456789e2}').a, 1234567890123456789e2);
    // Signed exponents exercise the scanner's mid-token +/- branch
    assert.equal(SaferParser.parse('{"a": 1234567890123456789e+2}').a, 1234567890123456789e2);
    assert.equal(SaferParser.parse('{"a": 12345678901234567890e-1}').a, 12345678901234567890e-1);
});

test("leading-zero integers stay invalid JSON", () => {
    assert.throws(() => SaferParser.parse('{"a": 00009007199254740993}'), SyntaxError);
    assert.throws(() => SaferParser.parse('{"a": -00009007199254740993}'), SyntaxError);
});

test("tokens inside string literals are not replaced", () => {
    const text = "NaN Infinity -Infinity 99999999999999999999";
    assert.equal(SaferParser.parse('{"a": "' + text + '"}').a, text);
    const escaped = SaferParser.parse('{"a": "esc \\" NaN \\\\", "b": NaN}');
    assert.equal(escaped.a, 'esc " NaN \\');
    assert.ok(Number.isNaN(escaped.b));
});

test("preprocess returns identical string for clean input (fast path)", () => {
    const clean = '{"a": 1, "b": "text"}';
    assert.equal(SaferParser.preprocess(clean), clean);
    const boundary = '{"a": ' + String(Number.MAX_SAFE_INTEGER) + '}';
    assert.equal(SaferParser.preprocess(boundary), boundary);
    assert.notEqual(SaferParser.preprocess('{"a": 9007199254740993}'), '{"a": 9007199254740993}');
});

test("caller reviver runs on both fast and slow paths", () => {
    const doubler = (key, value) => (key === "a" ? value * 2 : value);
    assert.equal(SaferParser.parse('{"a": 5}', doubler).a, 10);
    assert.equal(SaferParser.parse('{"a": 5, "b": NaN}', doubler).a, 10);
    // False-positive path: token inside a string trips the gate but yields no replacement
    assert.equal(SaferParser.parse('{"a": 5, "b": "NaN"}', doubler).a, 10);
    // On the slow path the caller reviver must see the revived value, not the flag object
    const seen = {};
    SaferParser.parse('{"b": NaN}', (key, value) => { seen[key] = value; return value; });
    assert.ok(Number.isNaN(seen.b));
    // The composite reviver must preserve the holder binding (this), matching native JSON.parse
    let holder;
    SaferParser.parse('{"a": {"b": NaN}}', function (key, value) {
        if (key === "b") {
            holder = this;
        }
        return value;
    });
    assert.ok(Number.isNaN(holder.b));
});

test("literal flag objects are revived regardless of other content", () => {
    const flag = '{"x": {"fprime{replacement": "NAN", "value": "NaN"}}';
    assert.ok(Number.isNaN(SaferParser.parse(flag).x));
    const combined = SaferParser.parse(flag.slice(0, -1) + ', "y": Infinity}');
    assert.ok(Number.isNaN(combined.x));
    assert.equal(combined.y, Infinity);
    assert.equal(SaferParser.parse('{"x": {"fprime{replacement": "NULL", "value": null}}').x, null);
    // Flag-object keys spelled with unicode escapes (either hex range, either case) must still be revived
    assert.ok(Number.isNaN(SaferParser.parse('{"x": {"fprime\\u007breplacement": "NAN", "value": "NaN"}}').x));
    assert.ok(Number.isNaN(SaferParser.parse('{"x": {"fprime\\u007Breplacement": "NAN", "value": "NaN"}}').x));
    assert.ok(Number.isNaN(SaferParser.parse('{"x": {"\\u0066prime{replacement": "NAN", "value": "NaN"}}').x));
    // Non-Latin-1 escapes alone must not force the slow path
    const unicode_clean = '{"a": "\\u4e2d\\u6587"}';
    assert.equal(SaferParser.needsPreprocess(unicode_clean), false);
    assert.equal(SaferParser.parse(unicode_clean).a, "\u4e2d\u6587");
});

test("every token type preprocess() emits trips the needsPreprocess fast-path gate", () => {
    for (const token of [...SaferParser.GATE_TOKENS.keys(), "-Infinity", "9007199254740993"]) {
        const input = '{"a": ' + token + "}";
        assert.ok(SaferParser.needsPreprocess(input), token + " must trip needsPreprocess");
        assert.notEqual(SaferParser.preprocess(input), input, token + " must be replaced");
    }
    assert.ok(SaferParser.needsPreprocess('{"fprime{replacement": "NAN"}'), "flag objects must trip needsPreprocess");
    // The same coupling must hold through parse()'s own gate: every token must actually revive
    assert.ok(Number.isNaN(SaferParser.parse('{"a": NaN}').a));
    assert.equal(SaferParser.parse('{"a": Infinity}').a, Infinity);
    assert.equal(SaferParser.parse('{"a": -Infinity}').a, -Infinity);
    assert.equal(SaferParser.parse('{"a": 9007199254740993}').a, 9007199254740993n);
});

test("non-string input is coerced like native JSON.parse", () => {
    assert.equal(SaferParser.parse(123), 123);
    assert.equal(SaferParser.parse(true), true);
    assert.equal(SaferParser.parse(null), null);
    assert.throws(() => SaferParser.parse(undefined), SyntaxError);
    assert.throws(() => SaferParser.parse(Symbol("x")), TypeError);
    // ToString coercion prefers toString() over valueOf(), like native JSON.parse
    assert.deepEqual(SaferParser.parse({valueOf: () => 1, toString: () => '{"a":1}'}), {a: 1});
    // The public preprocess() entry point coerces the same way
    assert.equal(SaferParser.preprocess(123), "123");
    assert.notEqual(SaferParser.preprocess(9007199254740993), "9007199254740993");
});

test("non-callable revivers are ignored like native JSON.parse", () => {
    assert.equal(SaferParser.parse('{"a": 1}', ["a"]).a, 1);
    assert.equal(SaferParser.parse('{"a": Infinity}', ["a"]).a, Infinity);
});

test("malformed flag objects pass through unchanged instead of throwing", () => {
    // Missing value, non-string value, unknown type, and a value BigInt() rejects
    assert.deepEqual(SaferParser.parse('{"x": {"fprime{replacement": "INFINITY"}}').x,
                     {"fprime{replacement": "INFINITY"});
    assert.deepEqual(SaferParser.parse('{"x": {"fprime{replacement": "NUMBER", "value": 5}}').x,
                     {"fprime{replacement": "NUMBER", "value": 5});
    assert.deepEqual(SaferParser.parse('{"x": {"fprime{replacement": "BOGUS", "value": "1"}}').x,
                     {"fprime{replacement": "BOGUS", "value": "1"});
    assert.deepEqual(SaferParser.parse('{"x": {"fprime{replacement": "NUMBER", "value": "junk"}}').x,
                     {"fprime{replacement": "NUMBER", "value": "junk"});
    // Well-formed non-integer NUMBER flag objects revive through the float branch
    assert.equal(SaferParser.parse('{"x": {"fprime{replacement": "NUMBER", "value": "1.5"}}').x, 1.5);
    // Negative zero revives as the number -0, not BigInt 0n
    assert.ok(Object.is(SaferParser.parse('{"x": {"fprime{replacement": "NUMBER", "value": "-0"}}').x, -0));
    // The caller's reviver also runs on the flag-object-only path and sees the revived value
    const seen = {};
    SaferParser.parse('{"x": {"fprime{replacement": "NAN", "value": "NaN"}}', (key, value) => {
        seen[key] = value;
        return value;
    });
    assert.ok(Number.isNaN(seen.x));
    // Synthetic flag-object interior nodes never reach the caller's reviver, so a string-transforming
    // reviver cannot corrupt revival (and never sees keys native JSON.parse would not surface)
    assert.equal(SaferParser.parse("[9007199254740993]",
                                   (key, value) => (typeof value === "string" ? "X" : value))[0],
                 9007199254740993n);
    assert.equal("fprime{replacement" in seen, false);
    assert.equal("value" in seen, false);
    // Well-formed flag objects nested inside malformed ones still revive
    const nested = SaferParser.parse(
        '{"x": {"fprime{replacement": "NUMBER", "value": 5,' +
        ' "nested": {"fprime{replacement": "NAN", "value": "NaN"}}}}');
    assert.ok(Number.isNaN(nested.x.nested));
    // A caller reviver returning undefined deletes the key, on both the fast and composite paths
    const drop = (key, value) => (key === "a" ? undefined : value);
    assert.equal("a" in SaferParser.parse('{"a": 5, "b": NaN}', drop), false);
    assert.equal("a" in SaferParser.parse('{"a": 5}', drop), false);
    // Whitespace-padded values are tolerated (pins the load-bearing trim in stringToNumber)
    assert.equal(SaferParser.parse('{"x": {"fprime{replacement": "NUMBER", "value": " 9007199254740993 "}}').x,
                 9007199254740993n);
    assert.equal(SaferParser.parse('{"x": {"fprime{replacement": "INFINITY", "value": " Infinity "}}').x,
                 Infinity);
    // Values outside the JSON grammar (hex, junk Infinity spellings) pass through unchanged
    assert.deepEqual(SaferParser.parse('{"x": {"fprime{replacement": "NUMBER", "value": "0x10"}}').x,
                     {"fprime{replacement": "NUMBER", "value": "0x10"});
    assert.deepEqual(SaferParser.parse('{"x": {"fprime{replacement": "INFINITY", "value": "junk"}}').x,
                     {"fprime{replacement": "INFINITY", "value": "junk"});
    // Only SyntaxError is treated as malformed input; converter bugs must propagate
    SaferParser.CONVERSION_MAP.set("BOOM", () => { throw new TypeError("bug"); });
    try {
        assert.throws(() => SaferParser.parse('{"x": {"fprime{replacement": "BOOM", "value": "1"}}'), TypeError);
    } finally {
        SaferParser.CONVERSION_MAP.delete("BOOM");
    }
});

test("digit-run gate boundaries", () => {
    assert.equal(SaferParser.needsPreprocess('{"a": 123456789012345}'), false); // 15 digits: fast path
    assert.equal(SaferParser.needsPreprocess('[123456789012345, 123456789012345]'), false); // adjacent short runs
    assert.ok(SaferParser.needsPreprocess('{"a": 1234567890123456}')); // 16 digits trips the gate
    // A 16-digit run must trip the gate at every offset (pins the strided-sampling invariant)
    for (let offset = 0; offset < 48; offset++) {
        const input = "x".repeat(offset) + "1234567890123456";
        assert.ok(SaferParser.needsPreprocess(input), "digit run at offset " + offset + " must trip the gate");
    }
});

test("KEY_ESCAPE covers every escape-spelled CONVERSION_KEY character", () => {
    for (const character of SaferParser.CONVERSION_KEY) {
        const code = character.charCodeAt(0);
        assert.ok(code < 0x80, "CONVERSION_KEY must stay ASCII-only");
        const escape = "\\u00" + code.toString(16).padStart(2, "0");
        assert.ok(SaferParser.KEY_ESCAPE.test(escape), escape + " must match KEY_ESCAPE");
        assert.ok(SaferParser.KEY_ESCAPE.test(escape.toUpperCase().replace("\\U", "\\u")),
                  escape + " must match KEY_ESCAPE case-insensitively");
    }
    // Escapes of characters outside the key must not trip the gate (keeps the fast path precise)
    for (const escape of ["\\u0067", "\\u007a", "\\u0030"]) {
        assert.equal(SaferParser.KEY_ESCAPE.test(escape), false, escape + " must not match KEY_ESCAPE");
    }
});

test("reviver handles primitives and null", () => {
    assert.equal(SaferParser.reviver("k", 5), 5);
    assert.equal(SaferParser.reviver("k", null), null);
    assert.equal(SaferParser.reviver("k", "text"), "text");
    assert.ok(Number.isNaN(SaferParser.reviver("k", { "fprime{replacement": "NAN" })));
});

test("malformed input terminates and throws SyntaxError", () => {
    for (const bad of ['{"a": NaN, "b": Infin', '{"a": NaN, "b": -Inf}', '{"a": Infinity, "b": I}',
                       '{"a": -NaN}', '"' + "\\".repeat(51)]) {
        assert.throws(() => SaferParser.parse(bad), SyntaxError);
    }
});

// Hang-detection guard, not a benchmark: catastrophic backtracking here previously took minutes or
// overflowed the regex engine. node:test timeouts are best-effort for synchronous hangs; the pytest
// wrapper's subprocess timeout is the authoritative watchdog
test("pathological escape-heavy strings parse quickly", {timeout: 5000}, () => {
    const evil = '{"a": "' + "\\\\".repeat(50000) + '"}';
    assert.equal(SaferParser.parse(evil).a.length, 50000);
});

test("registered mode overrides the global JSON functions", () => {
    try {
        SaferParser.register();
        assert.ok(Number.isNaN(JSON.parse('{"a": NaN}').a));
        assert.equal(JSON.parse(JSON.stringify({ a: 123456789012345678901n })).a, 123456789012345678901n);
    } finally {
        SaferParser.deregister();
    }
    // deregister() must restore the native functions, or later tests silently run overridden
    assert.equal(JSON.parse, SaferParser.language_parse);
    assert.equal(JSON.stringify, SaferParser.language_stringify);
});

test("gate covers every token class the scanner replaces", () => {
    // Invariant: whenever scanAndReplace() would change the input, hasReplaceableToken() must be true
    for (const input of ['{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}',
                         '{"a": 9007199254740993}', '{"a": -9007199254740993}']) {
        assert.notEqual(SaferParser.scanAndReplace(input), input, "scanner must replace: " + input);
        assert.ok(SaferParser.hasReplaceableToken(input), "gate must cover replaced input: " + input);
    }
    // Clean inputs pass through both the scanner and the gate untouched
    for (const input of ['{"a": 1}', '{"a": "text"}', '{}']) {
        assert.equal(SaferParser.scanAndReplace(input), input);
        assert.equal(SaferParser.hasReplaceableToken(input), false);
    }
});

test("stringify round-trips non-standard values", () => {
    const data = { a: Infinity, b: NaN, c: 123456789012345678901n, d: null, e: -Infinity };
    const round = SaferParser.parse(SaferParser.stringify(data));
    assert.equal(round.a, Infinity);
    assert.ok(Number.isNaN(round.b));
    assert.equal(round.c, 123456789012345678901n);
    assert.equal(round.d, null);
    assert.equal(round.e, -Infinity);
});
