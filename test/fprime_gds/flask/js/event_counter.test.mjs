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

test("events increment the WARNING_HI and FATAL counters", async () => {
    _dictionaries.events = {
        0:   {id: 0,   severity: {value: "EventSeverity.WARNING_HI"}},
        256: {id: 256, severity: {value: "EventSeverity.WARNING_HI"}},
        257: {id: 257, severity: {value: "EventSeverity.FATAL"}},
        258: {id: 258, severity: {value: "EventSeverity.ACTIVITY_HI"}},
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
    const history = [event(256), event(256), event(257), event(258), event(0)];
    _loader.load = async () => ({history: history, validation: history.length, errors: []});
    _loader.poller(_loader.endpoints.events, callback, error_handler);
    await new Promise((resolve) => setImmediate(resolve));

    assert.equal(_validator.counts.WARNING_HI, 3);
    assert.equal(_validator.counts.FATAL, 1);
    assert.equal(_validator.counts.GDS_Errors, 0);
    // Events still reach the event store
    assert.equal(_datastore.events.length, history.length);
});
