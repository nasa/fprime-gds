/**
 * addon-templates.js:
 *
 * Contains the HTML templates for the chart addon.  This includes a chart wrapper and the chart itself.
 *
 * @type {string}
 */

export let chart_wrapper_template = `
    <div class="fp-flex-repeater">

        <div class="row mt-2">
            <div class="col-md-10">
                <button class="btn btn-sm btn-secondary" v-on:click="addChart">
                    <span class="fp-chart-btn-icon">&plus;</span><span class="fp-chart-btn-text">Add Chart</span>
                </button>
                <button class="btn btn-sm" :class="{'btn-secondary': !this.siblings.in_sync, 'btn-success': siblings.in_sync}" v-on:click="siblings.in_sync = !siblings.in_sync">
                    <span class="fp-chart-btn-text">Lock Timescales</span>
                </button>
            </div>
            <div class="col-md-2">
                <button class="btn btn-sm btn-secondary float-right" v-on:click="isHelpActive = !isHelpActive">
                    <span class="fp-chart-btn-text">Help</span>
                </button>
            </div>
        </div>

        <transition name="fade">
            <div v-if="isHelpActive">
                <div class="alert alert-warning alert-dismissible mt-2 fade show" role="alert">
                    <div class="row">
                        <div class="col-6">
                            <strong>Zoom in and out</strong> by holding <strong>ALT</strong> and using mouse wheel to scroll while hovering over an axis <br/>
                            <strong>Zoom in</strong> by holding <strong>ALT</strong> and clicking and dragging a selection on the chart
                        </div>
                        <div class="col-6">
                            <strong>Pan</strong> by holding <strong>SHIFT</strong> and clicking and dragging the chart <br/>
                            <strong>Change size</strong> by clicking and dragging the icon at the bottom right of the chart box
                        </div>
                        <button type="button" class="close">
                            <span v-on:click="isHelpActive = !isHelpActive">&times;</span>
                        </button>
                    </div>
                </div>
            </div>
        </transition>
        <component v-for="(chartInst, index) in wrappers" is="chart-display" :key="chartInst.id"
            :id="chartInst.id" :siblings="siblings" v-on:delete-chart="deleteChart">
        </component>
    </div>
`;

export let chart_display_template = `
    <div class="mt-3">
        <div class="card">

            <div class="card-header">
                <button type="button" class="close ml-2">
                    <span v-on:click="emitDeleteChart(id)">&times;</span>
                </button>
                <button type="button" class="close ml-2" v-on:click="isCollapsed = !isCollapsed">
                    <span v-if="!isCollapsed">&minus;</span>
                    <span v-if="isCollapsed">&#9744;</span>
                </button>
                <span class="card-subtitle text-muted">{{ selected }} </span>
            </div>
            
            <div class="card-body" v-bind:class="{'collapse': isCollapsed}">
                
                <div class="row">
                    <div class="col-md-4">
                        <v-select placeholder="Select a Channel" id="channelList" label="option" style="flex: 1 1 auto;" 
                                  :clearable="false" :searchable="true" :filterable="true" :options="channelNames"
                                  v-model="selected">
                        </v-select>
                    </div>
                </div>

                <div class="row  justify-content-between">
                    <div class="col-md-4 mt-2">
                        <button type="button" class="btn" v-bind:class="{'btn-warning': !pause, 'btn-success': pause}"
                                v-on:click="toggleStreamFlow()" v-if="chart != null">
                            <span v-if="!pause">&#10074;&#10074;</span>
                            <span v-if="pause">&#9654;</span>
                        </button>
                
                        <button type="button" class="btn btn-warning" v-on:click="resetZoom()" v-if="chart != null">
                            Reset Zoom
                        </button>
                    </div>
                </div>

                <div class="row">
                    <div class="col-md-12 mt-2 fp-resize-box">
                        <canvas id="ds-line-chart" style="min-width: 50%"></canvas>
                    </div>
                </div>

            </div>
        </div>
    </div>
`;