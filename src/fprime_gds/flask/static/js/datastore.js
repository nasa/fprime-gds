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

/**
 * DataStore:
 *
 * Storage class for holding the one copy of the data. This is meant to be a *singleton* that distributes the known data
 * and thus only the single instance should be used and exported from this file.  This will wrap the loader for
 * automating the polling of the data.
 *
 * This will support the following types of data:
 *
 * - Commands
 * - Events
 * - Channels
 */
export class DataStore {

    constructor() {
        // Activity timeout for checking spacecraft health and "the orb" (ours, not Keynes')
        this.active = [false, false];
        this.active_timeout = null;

        // Data stores used to store all data supplied to the system
        this.events = [];
        this.command_history = [];
        this.channels = {};
        this.commands = {};
        this.logs = [];
        this.stats = {"Active Clients": {}, "History Sizes": {}}

        // File data stores used for file handling
        this.downfiles = [];
        this.upfiles = [];
        this.uploading = {"running": false}; // Cannot bind directly to a boolean

        // Consumers
        this.channel_consumers = [];

        this.polling_info = [
            {
                "endpoint": "events",
                "handler": this.updateEvents,
            },
            {
                "endpoint": "commands",
                "handler": this.updateCommandHistory,
            },
            {
                "endpoint": "channels",
                "handler": this.updateChannels,
            },
            {
                "endpoint": "logdata",
                "handler": this.updateLogs,
            },
            {
                "endpoint": "upfiles",
                "handler": this.updateUpfiles,
            },
            {
                "endpoint": "downfiles",
                "handler": this.updateDownfiles,
            },
            {
                "endpoint": "stats",
                "handler": this.updateStats,
            },
        ];
        let polling_keys = this.polling_info.map((item) => { return item.endpoint; });
        _settings.setupPollingSettings(polling_keys);
    }

    startup() {
        let channel_dict = _loader.endpoints["channel-dict"].data;
        // Setup channels object in preparation for updates
        let channels = {};
        for (let key in channel_dict) {
            channels[key] = {id: key, template: channel_dict[key], val: null, time: null};
        }
        this.channels = channels; // Forces new channel map into Vue
        this.commands = _loader.endpoints["command-dict"].data;
        // Clear the commands dictionary for setup
        for (let command in this.commands) {
            command = this.commands[command];
            for (let i = 0; i < command.args.length; i++) {
                command.args[i].error = "";
                if (command.args[i].type === "Enum") {
                    command.args[i].value = command.args[i].possible[0];
                }
            }
        }
        this.polling_info.forEach((item) => {
            this.reregisterPoller(item.endpoint);
        });
    }

    reregisterPoller(endpoint) {
        let ep_data = this.polling_info.filter((item) => item.endpoint === endpoint)[0] || null;
        if (ep_data !== null) {
            let processor = _validator.wrapResponseHandler(ep_data.endpoint, ep_data.handler.bind(this));
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

    registerActiveHandler(item) {
        this.actives.push(item);
        return [false, false];
    }


    updateCommandHistory(data) {
        this.command_history.push(...data["history"]);
        if (_settings.miscellaneous.command_buffer_size >= 0) {
            this.command_history.splice(_settings.miscellaneous.command_buffer_size, this.command_history.length - _settings.miscellaneous.command_buffer_size);
        }
    }

    updateChannels(data) {
        let new_channels = data["history"];
        // Loop over all dictionaries, and merge to the last reading
        for (let i = 0; i < new_channels.length; i++) {
            let channel = new_channels[i];
            let id = channel.id;
            this.channels[id] = channel;
        }
        this.channel_consumers.forEach((consumer) =>
        {
            try {
                consumer.sendChannels(new_channels);
            } catch (e) {
                _validator.updateErrors(e);
            }
        });
        this.updateActivity(new_channels, 0);
    }

    updateEvents(data) {
        let new_events = data["history"];
        this.events.push(...new_events);
        // Fix events to a known size
        if (_settings.miscellaneous.event_buffer_size >= 0) {
            this.events.splice(0, this.events.length - _settings.miscellaneous.event_buffer_size);
        }
        this.updateActivity(new_events, 1);
    }

    updateStats(statistics) {
        _performance.updateStats(statistics);
    }

    updateLogs(log_data) {
        this.logs.splice(0, this.logs.length, ...log_data.logs);
    }

    updateUpfiles(data) {
        let files = data["files"];
        this.upfiles.splice(0, this.upfiles.length, ...files);
        this.uploading.running = data["running"];
    }

    updateDownfiles(data) {
        let files = data["files"];
        this.downfiles.splice(0, this.downfiles.length, ...files);
    }

    updateActivity(new_items, index) {
        let timeout = config.dataTimeout * 1000;
        // Set active items, and register a timeout to turn it off again
        if (new_items.length > 0) {
            let _self = this;
            this.active.splice(index, 1, true);
            clearTimeout(this.active_timeout);
            this.active_timeout = setTimeout(() => _self.active.splice(index, 1, false), timeout);
        }
    }

    /**
     * Register a new channel consumer. Henceforth new channels will be provided directly as a list to the consumer.
     * @param consumer: channel consumer to register
     */
    registerChannelConsumer(consumer) {
        this.channel_consumers.push(consumer);
    }

    /**
     * Deregister the channel consumer passed in. Thus the consumer would henceforth not be provided with new channel
     * information.
     * @param consumer: consumer to deregister
     */
    deregisterChannelConsumer(consumer) {
        let index = this.channel_consumers.indexOf(consumer);
        if (index !== -1) {
            this.channel_consumers.splice(index, 1);
        }
    }
}


// Exports the datastore
export let _datastore = new DataStore();
