/**
 * addon-templates.js:
 *
 * Contains the HTML templates for the chart addon.  This includes a chart wrapper and the chart itself.
 *
 * @type {string}
 */

export let chart_wrapper_template = `
    <div class="fp-flex-repeater">
        <h2>Charts</h2>
        <div class="row mt-2">
            <div class="col-md-3">
                <div class="form-row">
                    <div class="col-md-6 mb-1">
                        <button class="btn btn-secondary btn-block" v-on:click="addChart">
                            <i class="fas fa-plus"></i> 
                            <span class="d-md-none d-lg-inline">Add Chart</span>
                        </button>
                    </div>
                    <div class="col-md-6 mb-1">
                        <button class="btn btn-block" :class="{'btn-secondary': !this.siblings.in_sync, 'btn-success': siblings.in_sync}" v-on:click="siblings.in_sync = !siblings.in_sync">
                            <i class="fas fa-thumbtack"></i>
                            <span class="d-md-none d-lg-inline">Lock Scale</span>
                        </button>
                    </div>
                </div>
            </div>
            <div class="col-md-6"></div>
            <div class="col-md-1">
                <a :href="saveChartsHref" download="current-charts.txt" class="btn btn-secondary btn-block">
                    <i class="fa fa-save"></i><span class="d-md-none d-lg-inline">Save</span>
                </a>
            </div>
            <div class="col-md-1">
                <label class="btn btn-secondary btn-file btn-block">
                    <i class="fa fa-folder-open"></i>
                    <span class="d-md-none d-lg-inline">Load</span>
                    <input type="file" v-on:input="loadCharts" style="display: none;">
                </label>
            </div>
            <div class="col-md-1">
                <button class="btn btn-secondary btn-block float-right" v-on:click="isHelpActive = !isHelpActive">
                    <i class="fas fa-question-circle"></i>
                    <span class="d-md-none d-lg-inline">Help</span>
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
                        <button type="button" class="close" v-on:click="isHelpActive = !isHelpActive">
                            <li class="fas fa-times" style="font-size: 0.75em"></i>
                        </button>
                    </div>
                </div>
            </div>
        </transition>
        <component v-for="(chartInst, index) in wrappers" is="chart-display" :key="chartInst.id"
            :id="chartInst.id" :siblings="siblings" v-on:delete-chart="deleteChart" v-bind:selected="chartInst.selected"
            v-on:input="chartInst.selected = $event" >
        </component>
    </div>
`;

export let chart_display_template = `
    <div class="mt-3">
        <div class="card">

            <div class="card-header">
                <button type="button" class="close ml-2">
                    <i v-on:click="emitDeleteChart(id)" class="fas fa-times" style="font-size: 0.75em"></i>
                </button>
                <button type="button" class="close ml-2" v-on:click="isCollapsed = !isCollapsed">
                    <i v-if="!isCollapsed" class="fas fa-minus" style="font-size: 0.75em"></i>
                    <i v-if="isCollapsed" class="far fa-square" style="font-size: 0.75em"></i>
                </button>
                <span class="card-subtitle text-muted">{{ selected }} </span>
            </div>
            <div class="card-body" v-bind:class="{'collapse': isCollapsed}">
                
                <div class="row">
                    <div class="col-md-4">
                        <v-select placeholder="Select a Channel" id="channelList" label="option" style="flex: 1 1 auto;" 
                                  :clearable="false" :searchable="true" :filterable="true" :options="channelNames"
                                  v-bind:value="selected" v-on:input="updateSelected($event)">
                        </v-select>
                    </div>
                    <div class="col-md-4 input-group">
                        <div class="input-group-prepend">
                            <span class="input-group-text">Data Window:</span>
                        </div>
                        <input name="timespan" type="number" v-model="timespan" class="form-control" />
                        <span class="input-group-text">(S)</span>
                    </div>
                </div>

                <div class="row  justify-content-between">
                    <div class="col-md-4 mt-2">
                        <button type="button" class="btn" v-bind:class="{'btn-warning': !pause, 'btn-success': pause}" v-on:click="toggleStreamFlow()" v-if="chart != null">
                            <i v-if="!pause" class="fas fa-pause"></i>
                            <i v-if="pause" class="fas fa-play"></i>
                        </button>
                
                        <button type="button" class="btn btn-warning" v-on:click="resetZoom()" v-if="chart != null">
                            <i class="fas fa-undo"></i>
                            <span class="d-none d-lg-inline">Reset Zoom</span>
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