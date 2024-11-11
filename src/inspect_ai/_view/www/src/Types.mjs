/**
 * @typedef {Object} Capabilities
 * @property {boolean} downloadFiles
 * @property {boolean} webWorkers
 */

/**
 * @typedef {Object} CurrentLog
 * @property {string} name
 * @property {import("./api/Types.mjs").EvalSummary} contents
 * @property {string} raw
 */

/**
 * @typedef {Object} Logs
 * @property {string} log_dir
 * @property {string[]} files
 */

/**
 * @typedef {Object} ScoreLabel
 * @property {string} name
 * @property {string} scorer
 */

/**
 * @typedef {Object} ScoreFilter
 * @property {string} [value]
 * @property {string} [type]
 */

/**
 * @typedef {Object} RenderContext
 * @property {(el: import("preact").JSX.Element) => void} afterBody:
 */

/**
 * @typedef {"none" | "single" | "many"} SampleMode
 */
