/**
 * @typedef {Object} Capabilities
 * @property {boolean} downloadFiles
 * @property {boolean} webWorkers
 */

/**
 * @typedef {Object} CurrentLog
 * @property {string} name
 * @property {import("./api/Types.ts").EvalSummary} contents
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
 */

/**
 * @typedef {"none" | "single" | "many"} SampleMode
 */

/**
 * @typedef {Object} ContentTool
 * @property {"tool"} type
 * @property {(import("./types/log").ContentImage | import("./types/log").ContentText)[]} content
 */
