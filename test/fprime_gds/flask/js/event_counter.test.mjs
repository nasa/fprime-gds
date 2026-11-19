/**
 * event_counter.test.mjs:
 *
 * Unit tests for the event severity counters shown in the top right of the GDS (config.summaryFields). Events are
 * pushed through the real loader poller and the datastore's event processing chain. Run with:
 * node --test event_counter.test.mjs
 */
import { test } from "node:test";
import assert from "node:assert/strict";

// The GDS modules start browser timers on import (e.g. the responsiveness checker). Unref them so node can exit.
const nodeSetTimeout = globalThis.setTimeout;
globalThis.setTimeout = (...args) => nodeSetTimeout(...args).unref();
const js = "../../../../src/fprime_gds/flask/static/js/";
const { _datastore, _dictionaries } = await import(js + "datastore.js");
const { _loader } = await import(js + "loader.js");
const { _validator } = await import(js + "validate.js");

/**
 * Build an /events response item as encoded by flask/json.py minimal_event: time, id, and display_text only.
 */
function event(id) {
    return {time: {base: 0, context: 0, seconds: 1, microseconds: 0}, id: id, display_text: "test"};
}

test("events increment the WARNING_HI and FATAL counters", async (t) => {
    // Restore the shared singletons this test stubs or mutates so later tests start clean
    const saved = {
        registerPoller: _loader.registerPoller,
        load: _loader.load,
        events: _dictionaries.events,
        counts: {..._validator.counts},
    };
    t.after(() => {
        _loader.registerPoller = saved.registerPoller;
        _loader.load = saved.load;
        _dictionaries.events = saved.events;
        _validator.counts = saved.counts;
    });
    _dictionaries.events = {
        0:   {id: 0,   severity: {value: "EventSeverity.WARNING_HI"}},
        256: {id: 256, severity: {value: "EventSeverity.WARNING_HI"}},
        257: {id: 257, severity: {value: "EventSeverity.FATAL"}},
        258: {id: 258, severity: {value: "EventSeverity.ACTIVITY_HI"}},
        259: {id: 259}, // Malformed entry without a severity
    };
    // Capture the events processing chain instead of starting an interval timer
    let callback = null;
    let error_handler = null;
    _loader.registerPoller = (endpoint, cb, err) => {
        if (endpoint === "events") {
            callback = cb;
            error_handler = err;
        }
    };
    _datastore.reregisterPoller("events");
    assert.ok(callback, "events poller was not registered");
    assert.equal(_validator.counts.WARNING_HI, 0);
    assert.equal(_validator.counts.FATAL, 0);

    // Serve one /events response through the real loader poller
    // 258 has a severity outside config.summaryFields, 259 has no severity, and 999 is not in the dictionary
    const history = [event(256), event(256), event(257), event(258), event(0), event(259), event(999)];
    _loader.load = async () => ({history: history, validation: history.length, errors: []});
    _loader.poller(_loader.endpoints.events, callback, error_handler);
    await new Promise((resolve) => setImmediate(resolve));

    assert.equal(_validator.counts.WARNING_HI, 3);
    assert.equal(_validator.counts.FATAL, 1);
    assert.equal(_validator.counts.GDS_Errors, 0);
    // Non-summary severities and ids without a dictionary severity must not add (NaN) entries to the header counts
    assert.deepEqual(Object.keys(_validator.counts).sort(), ["FATAL", "GDS_Errors", "WARNING_HI"]);
    // Events still reach the event store, including those that were not counted
    assert.equal(_datastore.events.length, history.length);
});
