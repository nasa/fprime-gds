/**
 * config.js:
 *
 * Configuration settings for the Chart JS plugin. This is such that the configuration options are in an easy to set
 * place in case adjustments need to be made.
 */

/**
 * Basic chart options (high-level).
 * @type {{responsive: boolean, interaction: {intersect: boolean}, parsing: boolean, maintainAspectRatio: boolean, animation: boolean}}
 */
export let chart_options = {
    parsing: true,
    animation: false,
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
        intersect: false
    },
};

/**
 * Data set specific configuration.
 * @type {{spanGaps: boolean, backgroundColor: string, borderColor: string, normalized: boolean, lineTension: number}}
 */
export let dataset_config = {
    normalized: true,
    spanGaps: false,
    backgroundColor: "rgba(54, 162, 235, 0.5)",
    borderColor: "rgb(54, 162, 235)",
    lineTension: 0,
};

/**
 * Ticks configuration.  Set to be minimal such that the chart renders more quickly.
 * @type {{maxRotation: number, sampleSize: number, autoSkip: boolean}}
 */
export let ticks_config = {
    autoSkip: true,
    maxRotation: 0,
    sampleSize: 10
};

/**
 * Realtime configuration options.  Balances update efficiency vs visual efficiency and data set recall size.
 * @type {{duration: number, frameRate: number, delay: number, refresh: number, ttl: number, pause: boolean}}
 */
export let realtime_config = {
    // Initial display width (ms): 1 min
    duration: 60000,
    // Total data history (ms): 60 min
    ttl: 60 * 60 * 1000,
    // Initial chart delay (ms): 0
    delay: 0,
    // Drawing framerate (ms): 30 Hz
    frameRate: 10,
    // Start paused: false
    pause: false,
    // Refresh rate: 10 Hz
    refresh: 100 //In ms
};

/**
 * Zoom settings configuring a zoom enabled graph using SHIFT and ALT to pan/zoom.
 * @type {{zoom: {mode: string, wheel: {modifierKey: string, enabled: boolean}, overScaleMode: string, drag: {modifierKey: string, enabled: boolean}}, pan: {mode: string, modifierKey: string, enabled: boolean}, limits: {x: {minDelay: number, maxDelay: *, minDuration: number, maxDuration: *}}}}
 */
export let zoom_config = {
    // Allows pan using the "shift" modifier key
    pan: {
        enabled: true,
        mode: "xy",
        modifierKey: "shift"
    },
    // Allows zooming holding the "alt" key and scrolling over an axis or clicking and dragging a region
    // Note: due to a bug in the zoom/streaming plugin interaction, clicking/dragging only affects the y axis
    zoom: {
        drag: {
            enabled: true,
            modifierKey: "alt"
        },
        wheel: {
            enabled: true,
            modifierKey: "alt"
        },
        // Allows zooming of both axises but only over the axis in question
        mode: "xy",
        overScaleMode: "xy",
    },
    limits: {
        // Initial limits for the realtime x axis set from maximum data stored
        x: {
            minDelay: 0,
            maxDelay: realtime_config.ttl,
            minDuration: 0,
            maxDuration: realtime_config.ttl,
        },
    },
};

/**
 * Returns a new chart config object for the given labeled data set.
 * @param label
 * @return {{data: {datasets: [*]}, options: *, type: string}}
 */
export function generate_chart_config(label) {
    let final_realtime_config = Object.assign({}, realtime_config);
    let scales = {
        x: {type: "realtime", realtime: final_realtime_config, ticks: ticks_config},
        y: {title: {display: true, text: "Value"}}
    };
    let plugins = {zoom: zoom_config};

    let final_dataset_config = Object.assign({label: label}, dataset_config, {data: []});
    let final_options_config = Object.assign({}, chart_options, {"scales": scales, "plugins": plugins});

    return {
        type: "line",
        data: {datasets: [final_dataset_config]},
        options: final_options_config
    }
}