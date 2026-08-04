/**
 * json.test.mjs:
 *
 * Unit tests for the SaferParser in flask/static/js/json.js. Run with: node --test json.test.mjs
 *
 * @author mstarch
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// json.js is an ES module, but its directory has no package.json declaring "type": "module",
// so Node would treat the .js file as CommonJS. Load its source through a data: URL instead.
const { SaferParser } = await import(
    "data:text/javascript," +
    encodeURIComponent(readFileSync(new URL("../../../../src/fprime_gds/flask/static/js/json.js", import.meta.url), "utf8"))
);

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
    assert.equal(SaferParser.parse('[NaN, Infinity, -Infinity]').length, 3);
});

test("unsafe integers become BigInt at the exact boundary", () => {
    assert.equal(SaferParser.parse('{"a": 9007199254740991}').a, Number.MAX_SAFE_INTEGER);
    assert.equal(typeof SaferParser.parse('{"a": 9007199254740991}').a, "number");
    assert.equal(SaferParser.parse('{"a": 9007199254740993}').a, 9007199254740993n);
    assert.equal(SaferParser.parse('{"a": 18446744073709551615}').a, 18446744073709551615n);
    assert.equal(SaferParser.parse('{"a": -18446744073709551615}').a, -18446744073709551615n);
});

test("floats and exponent forms are never BigInt-wrapped", () => {
    assert.equal(SaferParser.parse('{"a": 1.5e10}').a, 1.5e10);
    assert.equal(SaferParser.parse('{"a": 12345678901234567890.5}').a, 12345678901234567890.5);
    assert.equal(SaferParser.parse('{"a": 1234567890123456789e2}').a, 1234567890123456789e2);
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
});

test("literal flag objects are revived regardless of other content", () => {
    const flag = '{"x": {"fprime{replacement": "NAN", "value": "NaN"}}';
    assert.ok(Number.isNaN(SaferParser.parse(flag).x));
    assert.ok(Number.isNaN(SaferParser.parse(flag.slice(0, -1) + ', "y": Infinity}').x));
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
    assert.ok(Date.now() - start < 1000);
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
