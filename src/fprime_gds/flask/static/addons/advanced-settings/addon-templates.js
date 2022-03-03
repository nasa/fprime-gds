export let advanced_template = `
<div class="fp-flex-repeater">
    <div class="fp-flex-header">
        <h2>Advanced GDS Settings and Statistics</h2>
        <p>This page provides advanced settings for controlling the GDS and statistics for introspecting performance.
        Most users can use the standard settings and need not change what is seen here. Change with caution.</p>
        <div class="row">
            <div class="col">
                <h3>Polling Interval (ms) Settings</h3>
                <table class="table table-bordered">
                    <tr><th>Setting</th><th>Value</th></tr>
                    <tr v-for="polling in polling_info">
                        <td>{{ polling.endpoint }}</td><td><input class="form-control" v-model="polling.interval" v-on:change="reregister"/></td>
                    </tr>
                </table>
            </div>
            <div class="col" v-for="setting_category in Object.keys(settings)">
                <h3>{{ setting_category }}</h3>
                <table class="table table-bordered">
                    <tr><th>Setting</th><th>Value</th></tr>
                    <tr v-for="setting_key in Object.keys(settings[setting_category])">
                        <td>{{ setting_key }}</td><td><input class="form-control" v-model="settings[setting_category][setting_key]" /></td>
                    </tr>
                </table>
            </div>
            <div class="col" v-for="stat_category in Object.keys(stats)">
                <h3>{{ stat_category }}</h3>
                <table class="table table-bordered">
                    <tr><th>Statistic</th><th>Value</th></tr>
                    <tr v-for="stat_key in Object.keys(stats[stat_category])">
                        <td>{{ stat_key }}</td><td>{{ stats[stat_category][stat_key] }}</td>
                    </tr>
                </table>
            </div>
        </div>
</div>
`;
