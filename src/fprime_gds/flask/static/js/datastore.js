/**
 * datastore.js:
 *
 * Creates a datastore object that handles the storing of the various data items in the system. It then allows for
 * accessing those data items by the components in this system.
 *
 *  @author mstarch
 */
import {config} from "./config.js";
import {_validator} from "./validate.js";
import {_settings} from "./settings.js";
import {_loader} from "./loader.js";
import {_performance} from "./performance.js";
import {timeToDate} from "./vue-support/utils.js";

/**
 * HistoryHelper: base class used to help process incoming histories into the supplied stores. Processing results from
 * the back-end was riddled with duplication in order to perform similar actions with minor deltas. This class sets up
 * the mechanics to handle that process in a more generic way.
 */
class HistoryHelper {
    /**
     * Constructor to setup the store.
     */
    constructor(store, flags, active_key) {
        this.store = store;
        this.flags = flags;
        this.active_key = active_key;
        this.consumers = [];
        this.active_timeout = null;
        this.counter = 0;
    }

    /**
     * Register a consumer object for processing new items.
     * @param consumer: consumer to be registered
     */
    register(consumer) {
        this.consumers.push(consumer);
    }

    /**
     * Deregister a consumer from processing new items.
     * @param consumer: consumer to be removed
     */
    deregister(consumer) {
        let index = this.consumers.indexOf(consumer);
        if (index !== -1) {
            this.consumers.splice(index, 1);
        }
    }

    /**
     * Base update method processes new items by dispatches to any consumers, trapping errors, and continuing.
     * @param new_items: new items to dispatch
     */
    update(new_items) {
        let _self = this;
        // Break our when no new items returned
        if (new_items.length === 0) { return; }
        new_items.filter((item) => item.time).forEach((item) => {
            item.datetime = timeToDate(item.time);
            item.incremental_id = this.counter++;
        });
        this.consumers.forEach((consumer) => {
            try {
                consumer.send(new_items);
            } catch (e) {
                _validator.updateErrors([e]);
            }
        });
        let timeout = config.dataTimeout * 1000;
        // Set active items, and register a timeout to turn it off again
        if (this.active_key in this.flags && new_items.length > 0) {
            this.flags[this.active_key] = true;
            clearTimeout(this.active_timeout);
            this.active_timeout = setTimeout(() => {_self.flags[this.active_key] = false;}, timeout);
        }
    }
}

/**
 * List history helper. Handles any histories that are lists of items (e.g. events, commands). Used to store lists that
 * are updated with deltas that append to the end of the list.
 */
class ListHistory extends HistoryHelper {
    /**
     * Constructor to setup the store.
     * @param store: store that is being managed
     * @param flags: flags storage object
     * @param active_key: active key to update when something arrives
     * @param history_limit_key: (optional) key to look-up a limit to the list in settings
     */
    constructor(store, flags, active_key, history_limit_key) {
        super(store, flags, active_key);
        this.history_limit_key = history_limit_key;
        this.register(this);
    }

    /**
     * Process new items as dispatched from the update method above.
     * @param new_items: new items being to be process
     */
    send(new_items) {
        this.store.push(...new_items);
        let limit = _settings.miscellaneous[this.history_limit_key] || -1;
        if (limit >= 0) {
            this.store.splice(0, this.store.length - limit);
        }
    }
}

/**
 * FullListHistory: history for processing lists of items that are loaded as a whole list, rather than deltas to a list.
 * This is used for logs, uplinking files, and downlinking files. Anywhere where the list can change, but isn't
 * guaranteed to only grow **and** the list is kept small.
 */
class FullListHistory extends ListHistory {
    /**
     * Process new items as dispatched from the update method above.
     * @param new_items: new items being to be process
     */
    send(new_items) {
        // When the lists are not the same, update the stored list otherwise keep the list to prevent unnecessary bound
        // data re-rendering.
        if (this.store.length !== new_items.length) {
            this.store.splice(0, this.store.length, ...new_items);
            return;
        }
        for (let i = 0; i < Math.min(this.store.length, new_items.length); i++) {
            if (this.store[i] !== new_items[i]) {
                this.store.splice(0, this.store.length, ...new_items);
                return;
            }
        }
    }
}

/**
 * MappedHistory: processes history items from the GDS that are displayed as a map or key-value paring. This is
 * predominately for the channels table.
 */
class MappedHistory extends HistoryHelper {
    /**
     * Constructor to setup the store.
     * @param store: store that is being managed
     * @param flags: flags storage object
     * @param active_key: active key to update when something arrives
     */
    constructor(store, flags, active_key) {
        super(store, flags, active_key);
        this.register(this);
    }
    /**
     * Update the mapped history with new items. This is done in a single assign call to reduce the impact of calling
     * individual set calls on each key in the map.
     * @param new_items: new items to be processed
     */
    send(new_items) {
        // Loop over all dictionaries, and merge to the last reading
        let updated = {};
        for (let i = 0; i < new_items.length; i++) {
            let item = new_items[i];
            // When displaying last received, update the value always
            if (_settings.miscellaneous.channels_display_last_received) {
                updated[item.id] = item;
            }
            // Otherwise check for a newer timestamp
            else if ((this.store[item.id] || null) === null || item.datetime >= this.store[item.id].datetime) {
                updated[item.id] = item;
            }
        }
        Object.assign(this.store, updated);
    }
}

/**
 * Wrapper for the dictionaries for a convenient and intuitive access to these types.
 */
export let _dictionaries = {};

/**
 * DataStore:
 *
 * Storage class for holding the one copy of the data. This is meant to be a *singleton* that distributes the known data
 * and thus only the single instance should be used and exported from this file.  This will wrap the loader for
 * automating the polling of the data.
 */
class DataStore {
    constructor() {
        this.flags = {loaded: false, uploading: false, active_channels: false, active_events: false};

        // Data stores used to store all data supplied to the system
        this.events = [];
        this.command_history = [];
        this.channels = {};
        this.commands = {};
        this.logs = [];
        this.downfiles = [];
        this.upfiles = [];

        // Listing of endpoints that will be polled in repetition for data.
        this.polling_info = [
            {
                endpoint: "events",
                handler: new ListHistory(this.events, this.flags, "active_events", "event_buffer_size"),
            },
            {
                endpoint: "command_history",
                handler: new ListHistory(this.command_history, this.flags, undefined, "command_buffer_size"),
            },
            {
                endpoint: "channels",
                handler: new MappedHistory(this.channels, this.flags, "active_channels"),
            },
            {
                endpoint: "logdata",
                handler: new FullListHistory(this.logs, this.flags),
            },
            {
                endpoint: "upfiles",
                handler: new FullListHistory(this.upfiles, this.flags, "uploading"),
            },
            {
                endpoint: "downfiles",
                handler: new FullListHistory(this.downfiles, this.flags),
            },
            {
                endpoint: "stats",
                handler: this.updateStats,
            }
        ];
        let polling_keys = this.polling_info.map((item) => { return item.endpoint; });
        _settings.setupPollingSettings(polling_keys);
    }

    /**
     * Function called on startup, once the dictionary data has been loaded. It allows the datastore to massage the data
     * that has been received into a form that supports this client. Specifically:
     *
     * 0. Load the dictionary data into a globally exported store.
     * 1. this.channels is setup to contain all the dictionary supplied keys. This is done because vue needs each key to
     *    exist before updates to it for reactivity to work.
     * 2. Command arguments are assigned a value and error property. This allows for arguments to be filled in this
     *    global store alongside the dictionary data.
     */
    startup() {
        // Assign the dictionaries into the global object
        Object.assign(_dictionaries, {
            commands: _loader.endpoints["command-dict"].data.dictionary,
            events: _loader.endpoints["event-dict"].data.dictionary,
            channels: _loader.endpoints["channel-dict"].data.dictionary,
            commands_by_id: Object.fromEntries(Object.values(_loader.endpoints["command-dict"].data.dictionary).map((value) => [value.id, value])),
            framework_version: _loader.endpoints["command-dict"].data.framework_version,
            project_version: _loader.endpoints["command-dict"].data.project_version,
            metadata: _loader.endpoints["command-dict"].data.metadata,
        });
        // Setup channels object in preparation for updates. Channel object need to be well formed, even if blank,
        // because rendering of edit-views is still possible.
        let channels = {};
        for (let key in _dictionaries.channels) {
            channels[key] = {id: key, time: null, datetime: null, val: null};
        }
        Object.assign(this.channels, channels); // Forces new channel map into Vue maintaining the original object
        this.commands = _dictionaries.commands;

        _datastore.registerConsumer("channels", _performance);
        _datastore.registerConsumer("events", _performance);

        // Setup initial commands data (clearing arguments and setting initial values)
        Object.values(_datastore.commands).forEach((command) => command.args.forEach(this.setupCommandArgument.bind(this)));
        this.flags.loaded = true;
        this.polling_info.forEach((item) => {
            this.reregisterPoller(item.endpoint);
        });
    }

    /**
     * Set up a command argument by clearing the error, assigning default command values, and expanding complex types
     * into a structure of commands.
     * @param argument: argument to set up.
     */
    setupCommandArgument(argument) {
        let def = argument.value || null;
        argument.error = "";
        argument.value = def;
        // Enums are initialized to the first listed item
        if (argument.type.ENUM_DICT) {
            argument.value = Object.keys(argument.type.ENUM_DICT)[0];
        }
        // Booleans are initialized to True
        else if (argument.type.name === "BoolType") {
            argument.value = "True";
        }
        // Arrays expand to a set length of N pseudo-arguments
        else if (argument.type.LENGTH) {
            let array_length = argument.type.LENGTH;
            let values = Array(array_length).fill(def);
            argument.value = values.map((value, index) => {
                let append = "[" + index +"]";
                return this.setupCommandArgument({
                    "description": (argument.description) ? (argument.description + append) : argument.description,
                    "name": argument.name + append,
                    "type": argument.type.MEMBER_TYPE,
                });
            });
        }
        // Serializable type
        else if (argument.type.MEMBER_LIST) {
            let argument_list = argument.type.MEMBER_LIST.map((field_list) => {
                let name = field_list[0];
                let type = field_list[1];
                let description = field_list[3];
                return [name, this.setupCommandArgument({
                    "description": (description) ? description : argument.description,
                    "name": argument.name + "." + name,
                    "type": type,
                })];
            });
            argument.value = Object.fromEntries(argument_list);
        }
        return argument;
    }

    /**
     * (Re)registers the given endpoints polling. This is done after setup and any time that the polling interval
     * changes. This builds the mechanics to process the data returned from all these polls.
     * @param endpoint: name of the endpoint to start polling
     */
    reregisterPoller(endpoint) {
        let handler = ((this.polling_info.filter((item) => item.endpoint === endpoint)[0]) || {}).handler;
        if (handler && _settings.polling_intervals[endpoint] > -1) {
            let bound = (handler instanceof HistoryHelper) ? handler.update.bind(handler) : handler.bind(this);
            let processor = _validator.wrapResponseHandler(endpoint, bound);
            if (endpoint === "events") {
                let severity_processor = (severity) => {
                    return severity.value.replace("EventSeverity.", "");
                };
                processor = _validator.wrapFieldCounter(
                    "severity",
                    processor,
                    severity_processor,
                    Object.fromEntries(Object.keys(config.summaryFields).map((field_key) => [field_key, 0]))
                );
            }
            let error_fn = _validator.getErrorHandler();
            _loader.registerPoller(endpoint, processor, error_fn, _settings.polling_intervals[endpoint]);
        }
    }

    /**
     * Register a consumer of a specific key of data. The key should map to one of the polling endpoints.
     * @param key: key to be consumed. e.g. "channels" or "events".
     * @param consumer: consumer defining a send method.
     */
    registerConsumer(key, consumer) {
        this.polling_info.filter((item) => item.endpoint === key)[0].handler.register(consumer);
    }

    /**
     * Deregister a consumer of a specific key of data. The key should map to one of the polling endpoints. Must have
     * been previously registered using "registerConsumer".
     * @param key: key to be consumed. e.g. "channels" or "events".
     * @param consumer: consumer defining a send method.
     */
    deregisterConsumer(key, consumer) {
        this.polling_info.filter((item) => item.endpoint === key)[0].handler.deregister(consumer);
    }

    /**
     * Function used to update statistics when the statistics endpoint returns. Defers to the _performance object to
     * handle the statistics processing and archival.
     * @param statistics: statistics data to be processed
     * @param errors: errors list to be processed
     */
    updateStats(statistics, errors) {
        _performance.updateStats(statistics);
    }
}
// Exports the datastore
export let _datastore = new DataStore();
