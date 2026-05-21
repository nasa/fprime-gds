export let advanced_template = `
<div class="fp-flex-repeater">
    <div class="fp-flex-header">
        <h2>Advanced GDS Settings and Statistics</h2>
        <p>This page provides advanced settings for controlling the GDS and statistics for introspecting performance.
        Most users can use the standard settings and need not change what is seen here. Change with caution.</p>
        <div class="row">
            <div class="col-12">
                <h3>Data Transport</h3>
                <p>
                    Select how the browser receives channels, events, and command history updates.
                    <strong>Stream</strong> opens a WebSocket to <code>/api/stream</code> and receives push updates
                    as the GDS decodes them (recommended; requires the GDS server-side WebSocket route).
                    <strong>Poll</strong> falls back to periodic REST polling of <code>/channels</code>,
                    <code>/events</code>, and <code>/commands</code>. The choice persists across reloads.
                </p>
                <div class="input-group mb-3">
                    <div class="input-group-prepend col-3">
                        <span class="input-group-text col-12">Transport</span>
                    </div>
                    <select class="form-control col-3" v-model="transport.mode">
                        <option value="stream">Stream (WebSocket push)</option>
                        <option value="poll">Poll (REST)</option>
                    </select>
                    <small class="ml-3 align-self-center">
                        <strong>Server status:</strong>
                        <span v-if="stream_status.active === null">probing…</span>
                        <span v-else-if="stream_status.active">stream available
                            ({{ stream_status.clients }} client(s), {{ stream_status.dropped }} dropped)</span>
                        <span v-else>stream unavailable; falling back to polling</span>
                    </small>
                </div>
            </div>
            <div class="col-4" v-for="setting_category in Object.keys(settings)">
                <h3>{{ setting_category.replace("_", " ") }}</h3>
                <div v-html="settings[setting_category].description"></div>
                <div class="input-group mb-3" v-for="setting_key in Object.keys(settings[setting_category].settings)">
                    <small v-if="(settings[setting_category].descriptions || {})[setting_key]">
                        <strong>{{ setting_key }}</strong>
                        {{ settings[setting_category].descriptions[setting_key]}}
                    </small>
                    <div class="input-group-prepend col-6">
                        <span class="input-group-text col-12">{{ setting_key }}</span>
                    </div>
                    <input v-if="typeof(settings[setting_category].settings[setting_key]) === 'boolean'"
                            type="checkbox" v-model="settings[setting_category].settings[setting_key]">
                    <input v-else class="form-control col-6"
                        v-model.number="settings[setting_category].settings[setting_key]" type="number"/>
                </div>
            </div>
        </div>
        <div class="row">
            <div class="col-4" v-for="statistic_category in Object.keys(statistics)">
                <h3>{{ statistic_category.replace("_", " ") }}</h3>
                <table class="table table-bordered">
                    <tr><th>Statistic</th><th>Value</th></tr>
                    <tr v-for="statistic_key in Object.keys(statistics[statistic_category])">
                        <td>{{ statistic_key }}</td><td>{{ statistics[statistic_category][statistic_key] }}</td>
                    </tr>
                </table>
            </div>
            <div class="col-8">
                <h3>GDS Error Log</h3>
                <table class="col-8 table table-bordered">
                    <tr><th><button v-on:click="clearErrors()" class="btn btn-danger">Clear Errors</button></th></tr>
                    <tr v-for="error in errors.slice().reverse()"><td>{{ error }}</td></tr>
                </table>
            </div>
        </div>
</div>
`;
