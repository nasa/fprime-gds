/**
 * datastore.js:
 *
 * Creates a datastore object that handles the storing of the various data items in the system. It then allows for
 * accessing those data items by the components in this system.
 *
 *  @author mstarch
 */
import {config} from "./config.js";
import {_loader} from "./loader.js";

/**
 * Class tracking the responsiveness of the javascript application through set timeout
 */
class ResponsiveChecker {
    constructor(resolution_ms, window_size) {
        this.start = null;
        this.last = [];
        this.resolution = resolution_ms || 10;
        this.checker_fn = this.checker.bind(this);
        this.window_size = window_size || 100;
        setTimeout(this.checker_fn, this.resolution)
    }
    /**
     * Function that runs updating the time since last run minus the expected time
     */
    checker() {
        let now = new Date();
        this.last.push(now - (this.start || now) - this.resolution);

        this.start = new Date();
        setTimeout(this.checker_fn, this.resolution);
        this.last.splice(0, this.last.length - this.window_size);
    }

    /**
     * Responsiveness metric.
     * @returns maximum delay in ms of last (window) samples
     */
    responsiveness() {
        return Math.max(...this.last);
    }

}

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
        this.settings = {
            "event_buffer_size": -1,
            "command_buffer_size": -1
        };

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

        // Error handling and display
        this.errors = [];
        this.times = {}
        this.counts = {"warning_hi": 0, "fatal": 0, "errors": 0};
        this.responsive = new ResponsiveChecker();

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
        this.polling_info.forEach((item) => {
            item.interval = config.dataPollIntervalsMs[item.endpoint] || config.dataPollIntervalsMs.default || 1000;
        });
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
            _loader.registerPoller(endpoint, ep_data.handler.bind(this), this.handleError.bind(this), ep_data.interval);
        }
    }

    registerActiveHandler(item) {
        this.actives.push(item);
        return [false, false];
    }

    updateCommandHistory(data) {
        this.command_history.push(...data["history"]);
        if (this.settings.command_buffer_size >= 0) {
            this.command_history.splice(0, this.command_history.length - this.settings.command_buffer_size);
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
                console.error(e);
            }
        });
        this.updateActivity(new_channels, 0);
    }

    updateEvents(data) {
        let new_events = data["history"];
        this.events.push(...new_events);
        // Fix events to a known size
        if (this.settings.event_buffer_size >= 0) {
            this.events.splice(0, this.events.length - this.settings.event_buffer_size);
        }
        this.updateActivity(new_events, 1);

        // Loop through events and count the types received
        for (let i = 0; i < new_events.length; i++) {
            let count_key = new_events[i].severity.value.replace("EventSeverity.", "").toLowerCase();
            this.counts[count_key] = (this.counts[count_key] || 0) + 1;
        }
    }

    updateRequestTimeWindows() {
        for (let endpoint in _loader.endpoints) {
            let last = _loader.endpoints[endpoint].last || null;
            // Don't update window if bad reading
            if (last != null) {
                this.times[endpoint] = this.times[endpoint] || [];
                let data_window = this.times[endpoint];
                data_window.push(last);
                data_window.splice(0, window.length - 60);
            }
        }
    }

    updateStats(stats) {
        this.updateRequestTimeWindows();
        let new_times = Object.fromEntries(Object.keys(this.times).map((key) => [key, Math.max(...this.times[key])]));
        let mem_data = window.performance.memory || {};
        let formatter = (data) => {return (data / 1048576).toLocaleString(undefined) + " MiB"};
        let performance = {
            "memory used": formatter(mem_data.usedJSHeapSize),
            "memory allocated": formatter(mem_data.totalJSHeapSize),
            "memory limit": formatter(mem_data.jsHeapSizeLimit),
            "response delay": this.responsive.responsiveness() + " ms"
        }

        let local_stats = {
            "Cached Items": {
                "total": this.events.length + this.command_history.length + Object.keys(this.channels).length,
                "events": this.events.length,
                "commands": this.command_history.length,
                "channels": Object.keys(this.channels).length
            },
            "Request Times": new_times,
            "Performance": performance
        };
        Object.assign(this.stats, stats);
        Object.assign(this.stats, local_stats);
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

    registerChannelConsumer(consumer) {
        this.channel_consumers.push(consumer);
    }
    deregisterChannelConsumer(consumer) {
        let index = this.channel_consumers.indexOf(consumer);
        if (index !== -1) {
            this.channel_consumers.splice(index, 1);
        }
    }

    handleError(endpoint, error) {
        //error.timestamp = new Date();
        this.errors.push(error);
        this.errors.splice(0, this.errors.length - 100);
        this.counts.errors += 1;
        _loader.error_handler(endpoint, error);
    }
}


// Exports the datastore
export let _datastore = new DataStore();
