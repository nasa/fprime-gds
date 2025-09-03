/**
 * config.js:
 *
 * Configuration for the F´ GDS. This allows projects to quickly set properties that change how the GDS is displayed in
 * the browser to customise some parts of the look and feel. It also provides the some basic functionality
 * configuration.
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

    // Dashboards are a security vulnerability in that users are uploading artifacts that trigger
    // arbitrary rendering and code execution. This is explained in more detail here:
    //     https://v2.vuejs.org/v2/guide/security#Rule-No-1-Never-Use-Non-trusted-Templates
    //
    // Thus dashboards are disabled by default and projects must opt-in thus taking the responsibility
    // to validate and review the safety of the dashboards they use.
    enableDashboards: false
};
