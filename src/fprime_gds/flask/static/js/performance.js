/**
 * Performance and statistics engine for tracking the performance of various portions of the GDS system. This is
 * designed to collect statistics, performance metrics, and other data within the system that can be used to gauge
 * performance and possibly intervene.
 */

import {_validator} from "./validate.js";
import {_datastore} from "./datastore.js";
import {timeToDate} from "./vue-support/utils.js";

/**
 * Class tracking the responsiveness of the javascript application through set timeout. This class runs setTimeout
 * back-to-back looking at how long it takes to actually execute the function since the runtime. This gives a (crude)
 * measure of responsiveness of the webpage. These readings are windowed and the maximum value is returned from within
 * that window upon request.
 */
class ResponsiveChecker {
    /**
     * Build the responsiveness checker from a resolution time and a window size.
     * @param resolution_ms: time between polling. Default: 100ms
     * @param window_size: readings count tracked. Maximum is returned as responsiveness. Default: 100 (10 S)
     */
    constructor(resolution_ms, window_size) {
        this.start = null;
        this.last = [];
        this.resolution = resolution_ms || 100;
        this.window_size = window_size || 100;
        this.checker_fn = this.checker.bind(this);
        setTimeout(this.checker_fn, this.resolution)
    }
    /**
     * Function that runs updating the time since last run minus the resolution time (which is to be expected).
     */
    checker() {
        let now = new Date();
        this.last.push(now - (this.start || now) - this.resolution);

        this.start = now;
        setTimeout(this.checker_fn, this.resolution);
        this.last.splice(0, this.last.length - this.window_size);
    }

    /**
     * Responsiveness metric. Returns the maximum of the see responsiveness.
     * @returns maximum delay in ms of last (window) samples
     */
    responsiveness() {
        return Math.max(...this.last);
    }
}

/**
 * Performance tracking class. This catalogs some metrics of performance here in the GDS and catalogs some performance
 * metrics down in the server.
 */
class Performance {
    /**
     * Construct the performance engine.
     */
    constructor() {
        this.response_checker = new ResponsiveChecker();
        this.statistics = {
            "Active Clients": {},
            "History Sizes": {},
            "Page Performance": {},
            "Cached Items": {},
            "Request Times": {},
            "Dropped Items": _validator.dropped,
            "Misc. Counts": _validator.misc_counts
        };
        // Implementation variables
        this.cached_objects = {};
        this.rt_delay = new Date();
    }

    /**
     * Function used to handle the new statistics coming in from the server. Uses this opportunity to update local
     * (client) statistics as well.
     * @param server_statistics: new statistics information.
     */
    updateStats(server_statistics) {
        let new_times = Object.fromEntries(Object.keys(_validator.times).map((key) => [key, Math.max(..._validator.times[key])]));
        let mem_data = window.performance.memory || {};
        let formatter = (data) => {return (data / 1048576).toLocaleString(undefined) + " MiB"};

        let page_performance = {
            "memory used": formatter(mem_data.usedJSHeapSize),
            "memory allocated": formatter(mem_data.totalJSHeapSize),
            "memory limit": formatter(mem_data.jsHeapSizeLimit),
            "response delay": this.response_checker.responsiveness() + " ms",
            "realtime delay": (this.rt_delay/1000) + " S"
        };
        let cached_items = {
            "total": _datastore.events.length + _datastore.command_history.length + Object.keys(_datastore.channels).length,
            "events": _datastore.events.length,
            "commands": _datastore.command_history.length,
            "channels": Object.keys(_datastore.channels).length
        };
        let cached_object_entries = Object.entries(this.cached_objects);
        Object.assign(cached_items, Object.fromEntries(cached_object_entries.map(
            ([key, object]) => [key, object.length]
        )));

        let client_statistics = {
            "Cached Items": cached_items,
            "Request Times": new_times,
            "Page Performance": page_performance
        };
        Object.assign(this.statistics, server_statistics);
        Object.assign(this.statistics, client_statistics);
    }

    /**
     * Adds caching object given the name and the object to track. Name should be unique and the object should have a
     * .length property to read the size from.
     * @param name: name of the cached item
     * @param object: object to track .length of
     */
    addCachingObject(name, object) {
        this.cached_objects[name] = object;
    }

    /**
     * Remove caching object from the caching object tracking.
     * @param name: name of the cached item
     */
    removeCachingObject(name) {
        delete this.cached_objects[name];
    }

    send(new_items) {
        let now = new Date();
        let delays = new_items.map((item) => now - (item.datetime || timeToDate(item.time) || now));
        this.rt_delay = Math.max(...delays);
    }
}
export let _performance = new Performance();
