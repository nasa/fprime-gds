/**
 * loader.js:
 *
 * This file is used to load F prime data from the REST endpoint. This allows for a central access-point for these types
 * of data. In addition, it can kick of polling in order to keep aware of the latest updates in the REST layer.
 *
 * It typically has two types  of data:
 *
 * 1. static data (i.e. dictionaries) that only need to be loaded once on startup
 * 2. dynamic data that will be polled to continuously updated
 *
 * @author mstarch
 */
import {config} from "./config.js";
import {_settings} from "./settings.js";
import {SaferParser} from "./json.js";
SaferParser.register();

/**
 * Function allowing for the saving of some data to a downloadable file.
 * @param data: data to download as file, should be text
 * @return: href link triggering file save
 */
export function saveTextFileViaHref(data) {
    return 'data:text/plain;charset=utf-8,' + encodeURIComponent(data);
}

/**
 * Function to load a text file via a file input dialog. Limited to files of < 1MiB
 * @param event: event triggered via the file input dialog
 * @return {Promise<unknown>}: promise yielding text data
 */
export function loadTextFileInputData(event) {
    return new Promise((callback, error_fn) => {
        let _self = this;
        let file = event.target.files[0];
        // Limit the size to 1MiB
        if (file.size < 1048576) {
            let filer = new FileReader();
            filer.readAsText(file);
            filer.onload = (_) => {
                if (FileReader.DONE === filer.DONE) {
                    callback(filer.result)
                }
            };
            filer.onerror = error_fn;
            filer.onabort = error_fn;
        } else {
            error("[ERROR] File too large: " + (file.size / 1024 / 1024).toLocaleString(undefined) + " MiB > 1MiB");
        }
    });
}

/**
 * Loader:
 *
 * Loader that is used to pull in data from the REST API. This loader is intended to be a singleton and thus will be
 * instantiated and exported once.
 */
class Loader {
    /**
     * Sets up the list of endpoints, and preps for the initial loading of the dictionaries.
     */
    constructor() {
        this.endpoints = {
            // Dictionary endpoints
            "session": {
                "url": "/session",
                "startup": true,
                "running": false,
                "queued": false,
                "blocking": true,
            },
            "command-dict": {
                "url": "/dictionary/commands",
                "startup": true,
                "running": false,
                "queued": false
            },
            "event-dict":{
                "url": "/dictionary/events",
                "startup": true,
                "running": false,
                "queued": false
            },
            "channel-dict": {
                "url": "/dictionary/channels",
                "startup": true,
                "running": false,
                "queued": false
            },
            // Data endpoints
            "command_history": {
                "url": "/commands",
                "last": null,
                "running": false,
                "queued": false
            },
            "events": {
                "url": "/events",
                "last": null,
                "running": false,
                "queued": false
            },
            "channels": {
                "url": "/channels",
                "last": null,
                "running": false,
                "queued": false
            },
            "logdata": {
                "url": "/logdata",
                "last": null,
                "running": false,
                "queued": false
            },
            "upfiles": {
                "url": "/upload/files",
                "last": null,
                "running": false,
                "queued": false
            },
            "downfiles": {
                "url": "/download/files",
                "last": null,
                "running": false,
                "queued": false
            },
            "stats": {
                "url": "/stats",
                "last": null,
                "running": false,
                "queued": false
            }
        };
        // Attach a name to each endpoint
        for (let endpoint in this.endpoints) {
            this.endpoints[endpoint].name = endpoint;
        }
    }
    /**
     * Sets up the loader by issuing the initial requests for the dictionary endpoints. Will "finish" when all the dicts
     * have been successfully loaded. This is based on a Promise architecture, so the user is expected to call .then()
     * and .catch() functions on it.
     */
    setup() {
        var _self = this;
        // Return a promise for when this is fully setup
        return new Promise(function(resolve, reject) {
            // Attempt to load each endpoint tracking number of pending loads
            var pending = 0;
            for (let endpoint in _self.endpoints) {
                endpoint = _self.endpoints[endpoint];
                // Send out request if not loaded, and update the pending count
                if (endpoint["startup"] && typeof(endpoint["data"]) === "undefined") {
                    pending = pending + 1;
                    _self.load(endpoint["url"]).then(
                        // Data successfully returned, lower pending count and set it
                        function(data) {
                            pending = pending - 1;
                            endpoint["data"] = data;
                            // When there are no pending items, then resolve the promise
                            if (pending == 0) {
                                resolve();
                            }
                        }
                    ).catch(reject);
                }
            }
        });
    }

    /**
     * Load a given endpoint with a promise for when this endpoint returns its data. This wraps the basic AJAX call for
     * the user such that they only need to call load.
     * @param endpoint: url to call on the backend server. e.g. /download/files/abc
     * @param method: HTTP method to use to communicate with server. Default: "GET"
     * @param data: data to send.  Only useful if method != "GET". Default: no data
     * @param jsonify: jsonify the data. Default: true.
     * @param raw: return raw response, not a json parsed dataset
     */
    load(endpoint, method, data, jsonify, raw) {
        let _self = this;
        // Default method argument to "GET"
        if (typeof(method) === "undefined") {
            method = "GET";
        }
        // JSONify data if supplied and jsonified data needed
        if (typeof(data) !== "undefined" && (typeof(jsonify) === "undefined" || jsonify)) {
            data = JSON.stringify(data);
        }
        // Kick-back a promise for this load
        return new Promise(function (resolve, reject) {
            var xhttp = new XMLHttpRequest();
            xhttp.onreadystatechange = function() {
                // Parse as JSON or send back raw error
                if (this.readyState === 4 && this.status === 200 && raw) {
                    resolve(this.responseText);
                } else if (this.readyState === 4 && this.status === 200) {
                    let dataObj = JSON.parse(this.responseText);
                    resolve(dataObj);
                } else if(this.readyState === 4) {
                    reject(this.responseText);
                }
            };
            let url = endpoint;
            let session = (_self.endpoints["session"].data || {}).session || null;

            let arg_pairs = [["session", session], ["limit", _settings.miscellaneous.response_object_limit]];
            arg_pairs = arg_pairs.filter(pair => pair[1]);
            let arg_string = arg_pairs.map(pair =>  pair[0] + "=" + pair[1]).join("&");
            url += (arg_string !== "") ? ("?"+ arg_string) : "";

            let is_async = true; // all calls will be async
            xhttp.open(method, url , is_async); 
            xhttp.setRequestHeader("Cache-Control", "no-cache");
            if (typeof(data) === "undefined") {
                xhttp.send();
            } else if (typeof(jsonify) === "undefined" || jsonify) {
                xhttp.setRequestHeader("Content-Type", "application/json");
                xhttp.send(data);
            } else {
                xhttp.send(data);
            }
        });
    }

    /**
     * Default error handler that prints to console
     * @param endpoint: endpoint being polled
     * @param error: error to print to console
     */
    error_handler(endpoint, error) {
        let details = "'" + (error.message || error)  + "' (" + (error.type || "unknown") + ")";
        console.error("[ERROR] " + endpoint + " erred with " + details);
    }

    poller(context, callback, error_handler) {
        let _self = this;
        // If already running, mark as queued and bail
        if (context.running) {
            context.queued = true;
            return;
        }
        // Running, reset queue
        context.running = true;
        context.queued = false;
        let start_time = new Date();
        // Load the endpoint and respond to the response
        _self.load(context.url).then((data) => {
            let data_items = data.history || data.files || data.logs || data;
            let data_errors = data.errors || [];

            context.last = (new Date() - start_time)/1000;

            data_errors.map(error_handler.bind(undefined, context.name));
            context.queued = context.queued || (data_items.length >= _settings.miscellaneous.response_object_limit);
            callback(data_items, data_errors);
        }).catch((error) => {
            context.last = (new Date() - start_time)/1000;
            error_handler(context.name, error)
        }).finally(() => {
            // Context variables reset after finishing
            context.running = false;
            // If a request has been asked, prepare a follow-up request
            if (context.queued) {
                _self.poller(context, callback, error_handler);
            }
        });
    }

    /**
     * Register a polling function to receive updates and post updates to the callback function. This takes an endpoint
     * name from the setup list of endpoints known by this Loader, and a callback to return data to on the clock.
     * @param endpoint: endpoint to load
     * @param callback: callback to return resulting data to.
     * @param error_handler: handler to call for each error found in the response and all communication errors
     * @param interval: polling interval to use. (Optional) Pulls from config when not set
     */
    registerPoller(endpoint, callback, error_handler, interval) {
        let current_endpoint = this.endpoints[endpoint];
        error_handler = (error_handler instanceof Function) ?  error_handler : this.error_handler;
        let handler = this.poller.bind(this, current_endpoint, callback, error_handler);

        // Clear old intervals
        if ("interval" in current_endpoint) {
            clearInterval(current_endpoint.interval);
        }
        interval = interval || config.dataPollIntervalsMs.default || 1000;
        current_endpoint.interval = setInterval(handler, interval);
    }
}
export let _loader = new Loader();

