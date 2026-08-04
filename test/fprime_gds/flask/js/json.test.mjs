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
});

test("floats and exponent forms are never BigInt-wrapped", () => {
    assert.equal(SaferParser.parse('{"a": 1.5e10}').a, 1.5e10);
    assert.equal(SaferParser.parse('{"a": 12345678901234567890.5}').a, 12345678901234567890.5);
    assert.equal(SaferParser.parse('{"a": 1234567890123456789e2}').a, 1234567890123456789e2);
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
    // Flag-object key spelled with a unicode escape must still be revived
    assert.ok(Number.isNaN(SaferParser.parse('{"x": {"fprime\\u007breplacement": "NAN", "value": "NaN"}}').x));
    // Non-Latin-1 escapes alone must not force the slow path
    const unicode_clean = '{"a": "\\u4e2d\\u6587"}';
    assert.equal(SaferParser.needsPreprocess(unicode_clean), false);
    assert.equal(SaferParser.parse(unicode_clean).a, "\u4e2d\u6587");
});

test("every token type preprocess() emits trips the needsPreprocess fast-path gate", () => {
    for (const token of [...SaferParser.GATE_TOKENS, "-Infinity", "9007199254740993"]) {
        const input = '{"a": ' + token + "}";
        assert.ok(SaferParser.needsPreprocess(input), token + " must trip needsPreprocess");
        assert.notEqual(SaferParser.preprocess(input), input, token + " must be replaced");
    }
    assert.ok(SaferParser.needsPreprocess('{"fprime{replacement": "NAN"}'), "flag objects must trip needsPreprocess");
});

test("non-string input is coerced like native JSON.parse", () => {
    assert.equal(SaferParser.parse(123), 123);
    assert.equal(SaferParser.parse(true), true);
    assert.equal(SaferParser.parse(null), null);
    assert.throws(() => SaferParser.parse(undefined), SyntaxError);
});

test("reviver handles primitives and null", () => {
    assert.equal(SaferParser.reviver("k", 5), 5);
    assert.equal(SaferParser.reviver("k", null), null);
    assert.equal(SaferParser.reviver("k", "text"), "text");
    assert.ok(Number.isNaN(SaferParser.reviver("k", { "fprime{replacement": "NAN" })));
});

test("malformed input terminates and throws SyntaxError", () => {
    for (const bad of ['{"a": NaN, "b": Infin', '{"a": NaN, "b": -Inf}', '{"a": Infinity, "b": I}', '"' + "\\".repeat(51)]) {
        assert.throws(() => SaferParser.parse(bad), SyntaxError);
    }
});

test("pathological escape-heavy strings parse quickly", () => {
    const evil = '{"a": "' + "\\\\".repeat(50000) + '"}';
    const start = Date.now();
    assert.equal(SaferParser.parse(evil).a.length, 50000);
    // Coarse hang-detection guard (not a performance benchmark): catastrophic backtracking here
    // previously took seconds to minutes or overflowed the regex engine
    assert.ok(Date.now() - start < 5000);
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
