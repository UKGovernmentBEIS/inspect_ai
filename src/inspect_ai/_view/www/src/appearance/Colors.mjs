// @ts-check
/**
 * Provides centralized repository of colors used for logging.
 * @typedef {Object} LoggingColors
 * @property {string} debug - Color for debug level logging.
 * @property {string} info - Color for info level logging.
 * @property {string} warning - Color for warning level logging.
 * @property {string} error - Color for error level logging.
 * @property {string} critical - Color for critical level logging.
 */

/**
 * Provides centralized repository of colors.
 * @typedef {Object} Colors
 * @property {LoggingColors} logging - Colors used for different logging levels.
 */

/** @type {Colors} */
export const ApplicationColors = {
  logging: {
    debug: "var(--bs-secondary)",
    info: "var(--bs-blue)",
    warning: "var(--bs-warning)",
    error: "var(--bs-danger)",
    critical: "var(--bs-danger)",
  },
};
