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
    // Base URL for the application (will be set dynamically)
    baseUrl: "",
    // Data polling interval in milliseconds
    dataPollIntervalsMs: {
        channels: 500,
        default: 1000
    },
    // Summary counter fields containing object of field: bootstrap class
    summaryFields: {"WARNING_HI": "warning", "FATAL": "danger", "GDS_Errors": "danger"}
};

/**
 * Updates the config with the base URL and adjusts resource paths accordingly
 * @param baseUrl: the base URL to use for the application
 */
export function updateConfigWithBaseUrl(baseUrl) {
    config.baseUrl = baseUrl;
    // Update image paths to include base URL
    config.logo = baseUrl + "/img/logo.svg";
    config.dataSuccessIcon = baseUrl + "/img/success.svg";
    config.dataErrorIcon = baseUrl + "/img/error.svg";
}
