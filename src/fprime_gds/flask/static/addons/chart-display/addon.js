/**
 * addons/chart-display.js:
 *
 * Visualize selected telemetry channels using time series charts. This is done in realtime.  Time-shifted signals
 * will need to be panned into focus.
 *
 * @author saba-ja
 */
import { generate_chart_config } from "./config.js";
import {
    chart_wrapper_template,
    chart_display_template,
} from "./addon-templates.js";
import { _datastore, _dictionaries } from "../../js/datastore.js";
import { SiblingSet } from "./sibling.js";
import { timeToDate } from "../../js/vue-support/utils.js";
import {loadTextFileInputData, saveTextFileViaHref} from "../../js/loader.js";
import {_performance} from "../../js/performance.js";

import "./vendor/chart.js";
import "./vendor/chartjs-adapter-luxon.min.js";
import "./vendor/hammer.min.js";
import { flatten } from "./modified-vendor/flat.js";

// Note: these are modified versions of the original plugin files
import "./modified-vendor/chartjs-plugin-zoom.js";
import "./modified-vendor/chartjs-plugin-streaming.js";

/**
 * Wrapper component to allow user add multiple charts to the same page. This component handles the functions for
 * selecting the chart channel before the chart is created.
 */
Vue.component("chart-wrapper", {
    data: function () {
        return {
            counter: 1,
            locked: false,
            isHelpActive: false,
            wrappers: [{ id: 0, "selected": null }], // Starts with a single chart
            siblings: new SiblingSet(),
        };
    },
    template: chart_wrapper_template,
    methods: {
        /**
         * Add new chart handling the Chart+ button.
         */
        addChart(event, selected) {
            selected = selected || null;
            this.wrappers.push({ id: this.counter, selected: selected });
            this.counter += 1;
        },
        /**
         * Remove chart with the given id for handling the X button on a chart wrapper
         */
        deleteChart(id) {
            const index = this.wrappers.findIndex((f) => f.id === id);
            this.wrappers.splice(index, 1);
        },

        selected(data) {
            const index = this.wrappers.findIndex((f) => f.id === data.id);
            this.wrappers[index].selected = data.selected;
        },

        loadCharts(event) {
            loadTextFileInputData(event).then((data) => {
                let splits = data.split(/\s/);
                // Remove trailing blank chart if it exists and we are loading something to replace it
                if (splits.length > 0 && this.wrappers.length > 0 && this.wrappers[this.wrappers.length - 1].selected == null) {
                    this.wrappers.splice(this.wrappers.length - 1, 1);
                }

                for (let i = 0; i < splits.length; i++) {
                    let new_chart_selected = splits[i].trim();
                    this.addChart(null, new_chart_selected);
                }
            }).catch(console.error);
        }
    },
    computed: {
         saveChartsHref() {
            let data = this.wrappers.map((item) => { return item.selected} );
            data = data.filter((item) => {return item || false});
            return saveTextFileViaHref(data.join("\n"));
        }
    }
});

/**
 * Main chart component. This displays the chart JS object and routes data too it.
 */
Vue.component("chart-display", {
    template: chart_display_template,
    props: ["id", "siblings", "selected"],
    data: function () {
        const names_list = Object.values(
            _dictionaries.channels
        ).map((value) => {
            return flatten(value.type_obj, {
                maxDepth: 20,
                prefix: value.full_name,
            });
        });

        const names = names_list.flat();

        return {
            channelNames: names,
            oldSelected: null,

            isCollapsed: false,
            pause: false,

            chart: null,
            timespan: 3600
        };
    },
    mounted() {
        if (this.selected != null) {
            this.registerChart();
        }
    },
    methods: {
        /**
         * Allow user to pause the chart stream
         */
        toggleStreamFlow() {
            const realtimeOpts = this.chart.options.scales.x.realtime;
            realtimeOpts.pause = !realtimeOpts.pause;
            this.pause = realtimeOpts.pause;
            this.siblings.pause(realtimeOpts.pause);
        },
        /**
         * Register a new chart object
         */
        registerChart() {
            // If there is a chart object destroy it to reset the chart
            this.destroy();
            _datastore.registerConsumer("channels", this);
            let config = generate_chart_config(this.selected);
            config.options.plugins.zoom.zoom.onZoom = this.siblings.syncToAll;
            config.options.plugins.zoom.pan.onPan = this.siblings.syncToAll;
            // Category IV magic: do not alter
            config.options.scales.x.realtime.onRefresh = this.siblings.sync;
            this.showControlBtns = true;
            try {
                this.chart = new Chart(
                    this.$el.querySelector("#ds-line-chart"),
                    config
                );
                _performance.addCachingObject("Chart " + this.id, this.chart.data.datasets[0].data);
            } catch (err) {
                // Todo. This currently suppresses the following bug error
                // See ChartJs bug report https://github.com/chartjs/Chart.js/issues/9368
            }
            this.siblings.add(this.chart);
        },
        /**
         * Reset chart zoom back to default. This should affect all siblings when timescales are locked.
         */
        resetZoom() {
            this.chart.resetZoom("none");
            this.siblings.reset();
        },
        /**
         * Destroy a chart object.
         */
        destroy() {
            // Guard against destroying that which is destroyed
            if (this.chart == null) {
                return;
            }
            _performance.removeCachingObject("Chart " + this.id);
            _datastore.deregisterConsumer("channels", this);
            this.chart.data.datasets.forEach((dataset) => {
                dataset.data = [];
            });
            this.chart.destroy();
            this.siblings.remove(this.chart);
            this.chart = null;
        },

        /**
         * sending message up to the parent to remove this chart with this id
         * @param {int} id of current chart instance known to the parent
         */
        emitDeleteChart(id) {
            this.destroy();
            this.$emit("delete-chart", id);
        },
        /**
         * Callback to handle new channels being pushed at this object.
         * @param channels: new set of channels (unfiltered)
         */
        send(channels) {
            if (this.selected == null || this.chart == null) {
                return;
            }
            // Get channel name assuming the string is in either of these format:
            // - component.channel format for XML dictionaries
            // - deployment.component.channel for JSON dictionaries
            // Can't just slice by last '.' because channel name can include complex types
            // which are in the form of 'component.channel.fieldName'
            let SLICE_INDEX = _dictionaries.metadata.dictionary_type == "xml" ? 2 : 3;
            let channel_full_name = this.selected
                .split(".")
                .slice(0, SLICE_INDEX)
                .join(".");
            let serial_path = this.selected.split(".").slice(SLICE_INDEX).join(".");

            // Filter channels down to the graphed channel
            let new_channels = channels.filter((channel) => {
                return _dictionaries["channels"][channel.id].full_name === channel_full_name;
            });

            // Get channel value
            function getValue(ch_obj, path_str) {
                // If serializable path exist parse and return its value
                if (path_str) {
                    let keys = "val." + serial_path;
                    return keys
                        .split(".")
                        .reduce((o, k) => (o || {})[k], ch_obj);
                } else {
                    // otherwise assume simple object
                    return ch_obj.val;
                }
            }

            // Convert to chart JS format
            new_channels = new_channels.map((channel) => {
                return {
                    x: channel.datetime || timeToDate(channel.time),
                    y: getValue(channel, serial_path),
                };
            });

            // Graph and update
            let data_array = this.chart.data.datasets[0].data;
            data_array.push(...new_channels);

            this.chart.options.scales.x.realtime.ttl = this.timespan * 1000;
            this.chart.update("quiet");

            // Calculate the window span by max samples
            let first = data_array[0] || {x: NaN};
            let last = data_array[data_array.length - 1] || {x: NaN};

            let millis = (last.x - first.x) * this.samples / (data_array.length - 1);
            this.samples_duration = Math.floor(millis / 1000);
        },
        updateSelected(new_selected) {
            if (new_selected !== this.oldSelected) {
                this.$emit('input', new_selected);
                this.oldSelected = new_selected;
                this.$nextTick().then(() => {this.registerChart()});
            }
        }
    }
});
