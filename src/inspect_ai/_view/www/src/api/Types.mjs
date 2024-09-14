//@ts-check

/**
 * @typedef {Object} LogViewAPI
 * @property { () => Promise<any[]> } client_events - A function which can be polled to check for client events.
 * @property { () => Promise<LogFiles>} eval_logs - The parsed content of the file as an object.
 * @property { () => Promise<LogContents> } eval_log - The parsed content of the file as an object.
 * @property { () => Promise<import("../types/log").EvalLog[]>} eval_log_headers - The parsed content of the file as an object.
 * @property { (logFile: string) => Promise<void> } download_file - The parsed content of the file as an object.
 * @property { (logFile: string, log_dir: string) => Promise<void> } open_log_file - The parsed content of the file as an object.
 */

/**
 * @typedef {Object} FetchResponse
 * @property {string} raw - The raw string content of the fetched file.
 * @property {Object} parsed - The parsed content of the file as an object.
 */

/**
 * @typedef {Object} EvalHeader
 * @property {import("../types/log").Version | undefined} version - The raw string content of the fetched file.
 * @property {import("../types/log").Status | undefined} status - The raw string content of the fetched file.
 * @property {import("../types/log").EvalSpec } eval - The raw string content of the fetched file.
 * @property {import("../types/log").EvalPlan | undefined } plan - The raw string content of the fetched file.
 * @property {import("../types/log").EvalResults | undefined | null } results - The raw string content of the fetched file.
 * @property {import("../types/log").EvalStats | undefined } stats - The raw string content of the fetched file.
 * @property {import("../types/log").EvalError | undefined | null } error - The raw string content of the fetched file.
 */

/**
 * @typedef {Object} LogFiles
 * @property {LogFile[]} files - The log files
 */

/**
 * @typedef {Object} LogFile
 * @property {string} name - The path to this log file
 * @property {string} task - The name of the task
 * @property {string} task_id - The the id of the task
 */

/**
 * @typedef {Object} LogContents
 * @property {string} raw - The raw string content of the fetched file.
 * @property {import("../types/log").EvalLog} parsed - The parsed content of the file as an object.
 */

/**
 * @typedef {Object} LogFilesFetchResponse
 * @property {string} raw - The raw string content of the fetched file.
 * @property {Record<string, EvalHeader>} parsed - The parsed content of the file as an object.
 */
