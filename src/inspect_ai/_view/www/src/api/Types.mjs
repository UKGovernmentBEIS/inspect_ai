//@ts-check


/**
 * @typedef {Object} EvalSummary
 * @property {import("../types/log").Version} [version]
 * @property {import("../types/log").Status} [status]
 * @property {import("../types/log").EvalSpec} eval
 * @property {import("../types/log").EvalPlan} [plan]
 * @property {import("../types/log").EvalResults} [results]
 * @property {import("../types/log").EvalStats} [stats]
 * @property {import("../types/log").EvalError} [error]
 * @property {SampleSummary[]} sampleSummaries
 */

/**
 * @typedef {Object} EvalLogHeader
 * @property {import("../types/log").Version} [version]
 * @property {import("../types/log").Status} [status]
 * @property {import("../types/log").EvalSpec} eval
 * @property {import("../types/log").EvalPlan} [plan]
 * @property {import("../types/log").EvalResults} [results]
 * @property {import("../types/log").EvalStats} [stats]
 * @property {import("../types/log").EvalError} [error]
 */

/**
 * @typedef {Object} SampleSummary
 * @property { number | string } id
 * @property { number } epoch
 * @property { import("../types/log").Input } input
 * @property { import("../types/log").Target } target
 * @property { import("../types/log").Scores1 } scores
 */


/**
* @typedef {Object} Capabilities
* @property {boolean} downloadFiles - Indicates if file downloads are supported.
* @property {boolean} webWorkers - Indicates if web workers are supported.
*


/**
 * @typedef {Object} LogViewAPI
 * @property { () => Promise<any[]> } client_events - A function which can be polled to check for client events.
 * @property { () => Promise<LogFiles>} eval_logs - Read the list of files
 * @property { (log_file: string, headerOnly?: boolean, capabilities?: Capabilities) => Promise<LogContents> } eval_log - Read the log contents
 * @property { (log_file: string) => Promise<number>} eval_log_size - Get log size
 * @property { (log_file: string, start: number, end: number) => Promise<Uint8Array>} eval_log_bytes - Read bytes
 * @property { (log_files: string[]) => Promise<import("../types/log").EvalLog[]>} eval_log_headers - Read the log headers
 * @property { (logFile: string, downloadFiles?: boolean, webWorkers?: boolean) => Promise<void> } download_file - Execute a file download
 * @property { (logFile: string, log_dir: string) => Promise<void> } open_log_file - Execute a file open
 * @property { (logFile: string ) => Promise<SampleSummary[]> } eval_samples - Read the list of eval samples
 * @property { (logFile: string, id: string | number, epoch: number) => Promise<import("../types/log").EvalSample>} eval_sample - Read a sample
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
