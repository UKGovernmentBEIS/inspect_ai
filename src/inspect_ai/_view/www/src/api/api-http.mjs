//@ts-check
import { asyncJsonParse } from "../utils/Json.mjs";
import { download_file } from "./api-shared.mjs";
import { fetchRange, fetchSize } from "../utils/remoteZipFile.mjs";

/**
 * This provides an API implementation that will serve a single
 * file using an http parameter, designed to be deployed
 * to a webserver without inspect or the ability to enumerate log
 * files
 *
 * @param { string } log_dir - The log directory for this API.
 * @param { string } [log_file] - The log file for this API.
 * @returns { import("./Types.mjs").LogViewAPI } A Log Viewer API
 */
export default function simpleHttpApi(log_dir, log_file) {
  const resolved_log_dir = log_dir.replace(" ", "+");
  const resolved_log_path = log_file ? log_file.replace(" ", "+") : undefined;
  return simpleHttpAPI({
    log_file: resolved_log_path,
    log_dir: resolved_log_dir,
  });
}

/**
 * Fetches a file from the specified URL and parses its content.
 *
 * @param {{ log_file?: string, log_dir: string }} logInfo - The logInfo for this API.
 * @returns { import("./Types.mjs").LogViewAPI } An object containing the parsed data and the raw text of the file.
 */
function simpleHttpAPI(logInfo) {
  const log_file = logInfo.log_file;
  const log_dir = logInfo.log_dir;

  // Use a cache for the single file case
  // since we just use the log file that we already read
  const cache = log_file_cache(log_file);

  async function open_log_file() {
    // No op
  }
  return {
    client_events: async () => {
      return Promise.resolve([]);
    },
    eval_logs: async () => {
      const headers = await fetchLogHeaders(log_dir);
      if (headers) {
        const logRecord = headers.parsed;
        const logs = Object.keys(logRecord).map((key) => {
          return {
            name: joinURI(log_dir, key),
            task: logRecord[key].eval.task,
            task_id: logRecord[key].eval.task_id,
          };
        });
        return Promise.resolve({
          files: logs,
        });
      } else if (log_file) {
        // Check the cache
        let evalLog = cache.get();
        if (!evalLog) {
          const response = await fetchLogFile(log_file);
          cache.set(response.parsed);
          evalLog = response.parsed;
        }

        // Since no log directory manifest was found, just use
        // the log file to generate a single file manifest
        const result = {
          name: log_file,
          task: evalLog.eval.task,
          task_id: evalLog.eval.task_id,
        };

        return {
          files: [result],
        };
      } else {
        // No log.json could be found, and there isn't a log file,
        throw new Error(
          `Failed to load a manifest files using the directory: ${log_dir}. Please be sure you have deployed a manifest file (logs.json).`,
        );
      }
    },
    eval_log: async (file) => {
      const response = await fetchLogFile(file);
      cache.set(response.parsed);
      return response;
    },
    eval_log_size: async (log_file) => {
      return await fetchSize(log_file);
    },
    eval_log_bytes: async (log_file, start, end) => {
      return await fetchRange(log_file, start, end);
    },
    eval_log_headers: async (files) => {
      const headers = await fetchLogHeaders(log_dir);
      if (headers) {
        const keys = Object.keys(headers.parsed);
        const result = [];
        files.forEach((file) => {
          const fileKey = keys.find((key) => {
            return file.endsWith(key);
          });
          if (fileKey) {
            result.push(headers.parsed[fileKey]);
          }
        });
        return result;
      } else if (log_file) {
        // Check the cache
        let evalLog = cache.get();
        if (!evalLog) {
          const response = await fetchLogFile(log_file);
          cache.set(response.parsed);
          evalLog = response.parsed;
        }
        return [evalLog];
      } else {
        // No log.json could be found, and there isn't a log file,
        throw new Error(
          `Failed to load a manifest files using the directory: ${log_dir}. Please be sure you have deployed a manifest file (logs.json).`,
        );
      }
    },
    download_file,
    open_log_file,
  };
}

/**
 * Fetches a file from the specified URL and parses its content.
 *
 * @param {string} url - The URL to fetch the file from.
 * @param {(text: string) => Promise<Object>} parse - A function that takes the raw file text and returns a parsed object.
 * @param {(response: Response) => boolean } [handleError] - A function that may process the error and determine whether to throw
 * @returns {Promise<import("./Types.mjs").FetchResponse | undefined> } An object containing the parsed data and the raw text of the file.
 * @throws {Error} Will throw an error if the HTTP request fails or the response is not OK (status code not 200).
 */
async function fetchFile(url, parse, handleError) {
  const safe_url = encodePathParts(url);
  const response = await fetch(`${safe_url}`, { method: "GET" });
  if (response.ok) {
    const text = await response.text();
    return {
      parsed: await parse(text),
      raw: text,
    };
  } else if (response.status !== 200) {
    if (handleError && handleError(response)) {
      return undefined;
    }
    const message = (await response.text()) || response.statusText;
    const error = new Error(`${response.status}: ${message})`);
    throw error;
  } else {
    throw new Error(`${response.status} - ${response.statusText} `);
  }
}

/**
 * Fetches a log file and parses its content, updating the log structure if necessary.
 *
 * @param {string} file - The path or URL of the log file to fetch.
 * @returns {Promise<import("./Types.mjs").LogContents | undefined>} The parsed log file, potentially updated to version 2 format.
 * @throws {Error} Will throw an error if the fetching or parsing fails.
 */
const fetchLogFile = async (file) => {
  return fetchFile(file, async (text) => {
    const log = await asyncJsonParse(text);
    if (log.version === 1) {
      // Update log structure to v2 format
      if (log.results) {
        log.results.scores = [];
        log.results.scorer.scorer = log.results.scorer.name;
        log.results.scores.push(log.results.scorer);
        delete log.results.scorer;
        log.results.scores[0].metrics = log.results.metrics;
        delete log.results.metrics;

        // migrate samples
        const scorerName = log.results.scores[0].name;
        log.samples.forEach((sample) => {
          sample.scores = { [scorerName]: sample.score };
          delete sample.score;
        });
      }
    }
    return log;
  });
};

/**
 * Fetches a log file and parses its content, updating the log structure if necessary.
 *
 * @param {string} log_dir - The path to the log directory
 * @returns {Promise<import("./Types.mjs").LogFilesFetchResponse | undefined>} The parsed log file, potentially updated to version 2 format.
 * @throws {Error} Will throw an error if the fetching or parsing fails.
 */
const fetchLogHeaders = async (log_dir) => {
  const logs = await fetchFile(
    log_dir + "/logs.json",
    async (text) => {
      return await asyncJsonParse(text);
    },
    (response) => {
      if (response.status === 404) {
        // Couldn't find a header file
        return true;
      }
    },
  );
  return logs;
};

/**
 * Joins multiple URI segments into a single URI string.
 *
 * This function removes any leading or trailing slashes from each segment
 * and then joins them with a single slash (`/`).
 *
 * @param {...string} segments - The URI segments to join.
 * @returns {string} The joined URI string.
 */
function joinURI(...segments) {
  return segments
    .map((segment) => segment.replace(/(^\/+|\/+$)/g, "")) // Remove leading/trailing slashes from each segment
    .join("/");
}

/**
 * Creates a cache mechanism for a log file. If no log file is provided,
 * a no-op cache is returned. Otherwise, it allows caching of a single log file.
 *
 * @param {string | undefined} log_file - The log file to be cached. If null or undefined, a no-op cache is used.
 * @returns {{ set: function(import("../types/log").EvalLog): void, get: function(): (import("../types/log").EvalLog|undefined) }}
 *          An object with `set` and `get` methods for caching the log file.
 */
const log_file_cache = (log_file) => {
  // Use a no-op cache for non-single file
  // cases
  if (!log_file) {
    return {
      set: () => {},
      get: () => {
        return undefined;
      },
    };
  }

  // For a single file request, cache the log file request
  let cache_file;
  return {
    set: (log_file) => {
      cache_file = log_file;
    },
    get: () => {
      return cache_file;
    },
  };
};

/**
 * Encodes the path segments of a URL or relative path to ensure special characters
 * (like `+`, spaces, etc.) are properly encoded without affecting legal characters like `/`.
 *
 * This function will encode file names and path portions of both absolute URLs and
 * relative paths. It ensures that components of a full URL, such as the protocol and
 * query parameters, remain intact, while only encoding the path.
 *
 * @param {string} url - The URL or relative path to encode.
 * @returns {string} - The URL or path with the path segments properly encoded.
 */
function encodePathParts(url) {
  if (!url) return url; // Handle empty strings

  try {
    // Parse a full Uri
    const fullUrl = new URL(url);
    fullUrl.pathname = fullUrl.pathname
      .split("/")
      .map((segment) =>
        segment ? encodeURIComponent(decodeURIComponent(segment)) : "",
      )
      .join("/");
    return fullUrl.toString();
  } catch {
    // This is a relative path that isn't parseable as Uri
    return url
      .split("/")
      .map((segment) =>
        segment ? encodeURIComponent(decodeURIComponent(segment)) : "",
      )
      .join("/");
  }
}
