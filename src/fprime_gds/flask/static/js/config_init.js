/*
 * config_init.js
 *
 * Configuration for the F´ GDS. This initializes the configuration object that the GDS front-end will read to inform
 * how the GDS is displayed in the browser. This file advertises the properties and also sets default values which
 * projects can modify to customise some parts of the look and feel and also provides some basic functionality
 * configuration.
 *
 * To modify these properties for a project deployment, create a JavaScript function and inform GDS of the file:
 *   1. Create a JavaScript file exporting a function setConfig(c) that assigns values to any number of the properties
 *      below. The GDS will pass the below config object to the first argument of the function. Any properties
 *      unmodified by this function will retain their default value.
 *   2. Instruct the GDS to use the file from #1:
 *       a. Create a Python script that assigns to variable JS_CONFIGURATION_FILE a string pointing to the filename from
 *          #1 (see fprime_gds/flask/default_settings.py for an example).
 *       b. Set the environment variable FP_FLASK_SETTINGS to the path of this Python script, and then run the GDS.
 *
 * By default, without the above steps, the GDS will use the setConfig() function defined here in fprime-gds at
 * ./config.js. See that file for a starting point for #1.
 *
 * After performing the steps above, the GDS will instead use the setConfig() function defined in the custom filename
 * referenced by JS_CONFIGURATION_FILE and pass the global config object to that function.
 */

export let config = {
    // Allows projects to brand the UI
    projectName: "Infrastructure",
    // Logo of the project. Will be grey when timed-out, otherwise will be full-color
    logo: "/img/logo.svg",
    // Time in seconds to wait before reporting data flow error
    dataTimeout: 5,
    // Set the icon for the condition when there is data flowing
    dataSuccessIcon: "/img/success.svg",
    // Set the icon for the condition when there is a data-flow error
    dataErrorIcon: "/img/error.svg",
    // Data polling interval in milliseconds
    dataPollIntervalsMs: {
        channels: 500,
        default: 1000
    },
    // Summary counter fields containing object of field: bootstrap class
    summaryFields: {"WARNING_HI": "warning", "FATAL": "danger", "GDS_Errors": "danger"},
    // Function to use for formatting timestamps in the tables. null provides default formatting
    timeToStringFn: null,

    // Dashboards are a security vulnerability in that users are uploading artifacts that trigger
    // arbitrary rendering and code execution. This is explained in more detail here:
    //     https://v2.vuejs.org/v2/guide/security#Rule-No-1-Never-Use-Non-trusted-Templates
    //
    // Thus dashboards are disabled by default and projects must opt-in thus taking the responsibility
    // to validate and review the safety of the dashboards they use.
    enableDashboards: false
};

