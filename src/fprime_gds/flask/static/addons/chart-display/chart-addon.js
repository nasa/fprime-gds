/**
 * addons/chart-display.js:
 *
 * Visualize selected telemetry channels using time series charts
 * 
 * @author saba-ja
 */

import { _datastore } from '../../js/datastore.js';
import '../../third-party/js/chart.js';
import '../../third-party/js/chartjs-adapter-luxon.min.js';
import '../../third-party/js/hammer.min.js';
import '../../third-party/js/chartjs-plugin-zoom.min.js';
import '../../third-party/js/chartjs-plugin-streaming.min.js';

/**
 * Wrapper component to allow user add multiple charts to the same page
 */
Vue.component("chart-wrapper", {
    data: function () {
        return {
            counter: 0, // Auto incrementing id of each chart box
            chartInstances: [], // list of chart objects
        };
    },
    template: `
    <div class="fp-flex-repeater">

        <div class="row mt-2">
            <div class="col-md-12">
                <button class="btn btn-sm btn-secondary" v-on:click="addChart('chart-display')">
                <span class="fp-chart-btn-icon">&plus;</span>
                <span class="fp-chart-btn-text">Add Chart</span></button>
            </div>
        </div>

        <component
            v-for="(chartInst, index) in chartInstances"
            v-bind:is="chartInst.type"
            :key="chartInst.id"
            :id="chartInst.id"
            v-on:delete-chart="deleteChart">
        </component>

    </div>
    `,

    methods: {
        /**
         * Add new chart
         */
        addChart: function (type) {
            this.chartInstances.push({'id': this.counter, 'type': type})
            this.counter += 1;
        },
        /**
         * Remove chart with the given id
         */
        deleteChart: function (id) {
            const index = this.chartInstances.findIndex(f => f.id === id);
            this.chartInstances.splice(index,1);
        },
    }
});

/**
 * Main chart component
 */
Vue.component("chart-display", {
    template: `
    <div class="mt-3">
        <div class="card">

            <div class="card-header">
                <button type="button" class="close ml-2">
                    <span v-on:click="emitDeleteChart(id)">&times;</span>
                </button>
                <button type="button" class="close ml-2" v-on:click="toggleCollapseChart()">
                    <span v-if="!isCollapsed">&minus;</span>
                    <span v-if="isCollapsed">&#9744;</span>
                </button>
                <button type="button" class="close ml-2">
                    <span v-if="showContrlBtns" v-on:click="toggleShowHelp()">&quest;</span>
                </button>
                <span class="card-subtitle text-muted">{{ channelName }} </span>
            </div>
            
            <div class="card-body" v-bind:class="{'collapse': isCollapsed}">
                
                <div class="row">
                    <div class="col-md-4">
                        <v-select 
                        placeholder="Select a Channel"
                        id="channelList" 
                        label="option"
                        style="flex: 1 1 auto;" 
                        :clearable="false"
                        :searchable="true"
                        :filterable="true"
                        :options="channelNames"
                        v-model="selected">
                        </v-select>
                        <div v-model="updateData"></div>
                    </div>
                </div>

                <div class="row  justify-content-between">
                    <div class="col-md-4 mt-2">
                        <button type="button" 
                        class="btn"
                        v-bind:class="{'btn-warning': !pause, 'btn-success': pause}"
                        v-on:click="toggleStreamFlow()"
                        v-if="showContrlBtns">
                        <span v-if="!pause">&#10074;&#10074;</span>
                        <span v-if="pause">&#9654;</span>
                        </button>
                
                        <button type="button" 
                        class="btn btn-warning" 
                        v-on:click="resetZoom()"
                        v-if="showContrlBtns">
                        Reset Zoom
                        </button>

                    </div>
                    <transition name="fade">
                    <div class="col-md-4" v-if="isHelpActive">
                        <div class="alert alert-warning alert-dismissible fade show" role="alert">
                            <p>
                            <strong>Enable zoom </strong> by clicking on a chart<br/>
                            <strong>Zoom in and out</strong> by using mouse wheel<br/>
                            <strong>Drag horizontally</strong> by right click and hold<br/>
                            <strong>Change size</strong> by dragging bottom right of the chart box</p>
                            <button type="button" class="close">
                                <span v-on:click="dismissHelp()">&times;</span>
                            </button>
                        </div>
                    </div>
                    </transition>

                </div>

                <div class="row">
                    <div class="col-md-12 mt-2 fp-resizable-box">
                        <canvas id="ds-line-chart" style="min-width: 50%"></canvas>
                    </div>
                </div>

            </div>
        </div>
    </div>
    `,
    props: ["id"],
    data: function () {
        return {
            channels: _datastore.channels,
            channelNames: [],
            selected: null,
            oldSelected: null,
            channelLoaded: false,
            
            isCollapsed: false,
            isHelpActive: false,
            
            chartObj: null,
            channelId: null,
            channelName: "",
            channelTimestamp: null,
            channelValue: null,
            showContrlBtns: false,
            
            // https://nagix.github.io/chartjs-plugin-streaming/2.0.0/guide/options.html
            duration: 60000, // (1 min) Duration of the chart in milliseconds (how much time of data it will show).
            ttl: 1800000, // (30 min) // Duration of the data to be kept in milliseconds. 
            delay: 2000, // (2 sec) Delay added to the chart in milliseconds so that upcoming values are known before lines are plotted.            
            refresh: 1000, // (1 sec) Refresh interval of data in milliseconds. onRefresh callback function will be called at this interval.
            frameRate: 30,  // Frequency at which the chart is drawn on a display
            pause: false, // If set to true, scrolling stops. Note that onRefresh callback is called even when this is set to true.
            reverse: false, // If true moves from left to right
            animation: true,
            responsive: true,
            maintainAspectRatio: false,
            intersect: false,
            minDelay: 2000, // (2 sec) Min value of the delay option
            maxDelay: 1800000, // (30 min) Max value of the delay option
            minDuration: 2000, // (2 sec) Min value of the duration option
            maxDuration: 1800000, // (30 min) Max value of the duration option

            config: {},
        };
    },

    methods: {

        /**
         * Extract channel name from channel object
         */
        setChannelNames() {
            if (this.channelLoaded || this.channels === undefined) {
                return;
            }
            let ch_keys = Object.keys(this.channels);
            if (ch_keys.length === 0) {
                return;
            }
            this.channelNames = []; // reset channel names to avoid duplicates
            for (let i = 0; i < ch_keys.length; i++) {
                let ch = this.channels[ch_keys[i]];
                this.channelNames.push({
                    option: ch.template.full_name,
                    id: ch.id,
                });
                this.channelLoaded = true;
            }
        },

        /**
         * Function to update the chart with new data
         */
        onRefresh(){
            this.chartObj.data.datasets[0].data.push({
                x: Date.now(),
                y: this.channelValue,
            });
        },

        /**
         * returns current status (enable/disable) of zooming with mouse wheel
         */
        zoomStatus() {
            if (this.chartObj) {
                return 'Zoom: ' + (this.chartObj.options.plugins.zoom.zoom.wheel.enabled  ? 'enabled' : 'disabled');
            } else {
                return 'Zoom: ' + 'disabled';
            }
        },

        /**
         * Allow user to pause the chart stream
         */
        toggleStreamFlow() {
            const realtimeOpts = this.chartObj.options.scales.x.realtime;
            realtimeOpts.pause = !realtimeOpts.pause;
            this.pause = !this.pause;
            this.chartObj.update("none");
        },

        /**
         * Set chart configuration
         */
        setConfig() {
            this.config = {
                type: "line",
                data: {
                    datasets: [
                        {
                            label: this.channelName,
                            backgroundColor: "rgba(54, 162, 235, 0.5)",
                            borderColor: "rgb(54, 162, 235)",
                            cubicInterpolationMode: "monotone",
                            data: [],
                        },
                    ],
                },
                options: {
                    animation: this.animation,
                    responsive: this.responsive,
                    maintainAspectRatio: this.maintainAspectRatio,
                    interaction: {
                        intersect: this.intersect
                    },
                    onClick(e) {
                        const chart = e.chart;
                        chart.options.plugins.zoom.zoom.wheel.enabled = !chart.options.plugins.zoom.zoom.wheel.enabled;
                        chart.options.plugins.zoom.zoom.pinch.enabled = !chart.options.plugins.zoom.zoom.pinch.enabled;
                        chart.update();
                    },
                    scales: {
                        x: {
                            type: "realtime",
                            realtime: {
                                duration: this.duration,
                                ttl: this.ttl,
                                delay: this.delay,
                                refresh: this.refresh,
                                frameRate: this.frameRate,
                                pause: this.pause,
                                onRefresh: this.onRefresh
                            },
                            reverse: this.reverse
                        },
                        y: {
                            title: {
                              display: true,
                              text: "Value"
                            }
                        }
                    },
                    plugins: {
                        zoom: {
                            // Assume x axis has the realtime scale
                            pan: {
                                enabled: true, // Enable panning
                                mode: "x", // Allow panning in the x direction
                            },
                            zoom: {
                                pinch: {
                                    enabled: false, // Enable pinch zooming
                                },
                                wheel: {
                                    enabled: false, // Enable wheel zooming
                                },
                                mode: "x", // Allow zooming in the x direction
                            },
                            limits: {
                                x: {
                                    minDelay: this.minDelay, 
                                    maxDelay: this.maxDelay, 
                                    minDuration: this.minDuration, 
                                    maxDuration: this.maxDuration, 
                                },
                            },
                        },
                        title: {
                            display: true,
                            position: 'bottom',
                            text: this.zoomStatus // keep track of zoom enable status
                        },
                    },
                },
                plugins:[
                    // Highlight chart border when user clicks on the chart area
                    {
                        id: 'chartAreaBorder',
                        beforeDraw(chart, args, options) {
                            const {ctx, chartArea: {left, top, width, height}} = chart;
                            if (chart.options.plugins.zoom.zoom.wheel.enabled) {
                                ctx.save();
                                ctx.strokeStyle = '#f5c6cb';
                                ctx.lineWidth = 2;
                                ctx.strokeRect(left, top, width, height);
                                ctx.restore();
                            }
                        }
                    }
                ],
            }
        },

        /**
         * Register a new chart object
         */
        registerChart() {
            // If there is a chart object destroy it to reset the chart
            if (this.chartObj !== null) {
                this.chartObj.data.datasets.forEach((dataset) => {
                    dataset.data = [];
                });
                this.chartObj.destroy();
                this.showContrlBtns = false;
            }

            // If the selected channel does not have any value do not register the chart
            let id = this.selected.id;
            if (this.isChannelOff(id)) {
                return;
            }
            
            this.channelName = this.getChannelName(id);
            this.setConfig();
            this.showContrlBtns = true;
            try {
                this.chartObj = new Chart(
                    this.$el.querySelector("#ds-line-chart"),
                    this.config
                );
            } catch(err) {
                // FIXME. This currently suppresses the following bug error
                // See ChartJs bug report https://github.com/chartjs/Chart.js/issues/9368
            }
        },

        /**
         * Check whether there is any data in the channel
         */
        isChannelOff(id) {
            return this.channels[id].str === undefined;
        },

        getChannelName(id) {
            return this.channels[id].template.full_name;
        },

        /**
         * Reset chart zoom back to default
         */
        resetZoom() {
            this.chartObj.resetZoom("none");
        },

        /**
        * Allow user to collapse or open chart display box
        */
        toggleCollapseChart() {
            this.isCollapsed = !this.isCollapsed;
        },

        /**
         * Show or remove alert box when user click on the help button
         */
        toggleShowHelp() {
            this.isHelpActive = !this.isHelpActive;
        },

        /**
        * Remove alert box when user click on the close button of help alert
        */
        dismissHelp () {
            this.isHelpActive = false;
        },

        /**
         * sending message up to the parent to remove this chart with this id
         * @param {int} id of current chart instance known to the parent
         */
        emitDeleteChart(id) {
            if (this.chartObj) {
                this.chartObj.destroy();
            }
            this.$emit('delete-chart', id);
        },
    },

    mounted: function () {
        this.setChannelNames();
    },

    computed: {
        updateData: function () {
            this.setChannelNames();
            
            if (this.selected === null) {
                return;
            }
            let id = this.selected.id;
            if (this.isChannelOff(id)) {
                return;
            } else {
                this.channelId = this.channels[id].id;
                this.channelName = this.channels[id].template.full_name;
                this.channelTimestamp = this.channels[id].time.seconds;
                this.channelValue = this.channels[id].val;
            }
        },
    },

    /**
     * Watch for new selection of channel and re-register the chart
     */
    watch: {
        selected: function() {
            if (this.selected !== this.oldSelected) {
                this.oldSelected = this.selected;
                this.registerChart();
            }
        },
    }
});
