//@ts-check
import { openRemoteLogFile } from "../log/remoteLogFile.mjs";

const isEvalFile = (file) => {
  return file.endsWith(".eval");
};

/**
 * This provides an API implementation that will serve a single
 * file using an http parameter, designed to be deployed
 * to a webserver without inspect or the ability to enumerate log
 * files
 *
 * @param { import("./Types.mjs").LogViewAPI } api - The api to use when loading logs
 * @returns { import("./Types.mjs").ClientAPI } A Client API for the viewer
 */
export const clientApi = (api) => {
  let current_log = undefined;
  let current_path = undefined;

  const loadedEvalFile = {
    file: undefined,
    remoteLog: undefined,
  };

  const remoteEvalFile = async (log_file, cached = false) => {
    if (!cached || loadedEvalFile.file !== log_file) {
      loadedEvalFile.file = log_file;
      loadedEvalFile.remoteLog = await openRemoteLogFile(api, log_file, 5);
    }
    return loadedEvalFile.remoteLog;
  };

  /**
   * Gets a log
   *
   * @param { string } log_file - The api to use when loading logs
   * @param { boolean } cached - allow this request to use a cached log file
   * @returns { Promise<import("./Types.mjs").LogContents> } A Log Viewer API
   */
  const get_log = async (log_file, cached = false) => {
    // If the requested log is different or no cached log exists, start fetching
    if (!cached || log_file !== current_path || !current_log) {
      // If there's already a pending fetch, return the same promise
      if (pending_log_promise) {
        return pending_log_promise;
      }

      // Otherwise, create a new promise for fetching the log
      pending_log_promise = api
        .eval_log(log_file, 100)
        .then((log) => {
          current_log = log;
          current_path = log_file;
          pending_log_promise = null;
          return log;
        })
        .catch((err) => {
          pending_log_promise = null;
          throw err;
        });

      return pending_log_promise;
    }
    return current_log;
  };
  let pending_log_promise = null;

  /**
   * Gets a log summary
   *
   * @param { string } log_file - The api to use when loading logs
   * @returns { Promise<import("./Types.mjs").EvalSummary> } A Log Viewer API
   */
  const get_log_summary = async (log_file) => {
    if (isEvalFile(log_file)) {
      const remoteLogFile = await remoteEvalFile(log_file);
      return await remoteLogFile.readLogSummary();
    } else {
      const logContents = await get_log(log_file);
      /**
       * @type {import("./Types.mjs").SampleSummary[]}
       */
      const sampleSummaries = logContents.parsed.samples
        ? logContents.parsed.samples?.map((sample) => {
            return {
              id: sample.id,
              epoch: sample.epoch,
              input: sample.input,
              target: sample.target,
              scores: sample.scores,
              metadata: sample.metadata,
            };
          })
        : [];

      const parsed = logContents.parsed;
      return {
        version: parsed.version,
        status: parsed.status,
        eval: parsed.eval,
        plan: parsed.plan,
        results: parsed.results,
        stats: parsed.stats,
        error: parsed.error,
        sampleSummaries,
      };
    }
  };

  /**
   * Gets a sample
   *
   * @param { string } log_file - The api to use when loading logs
   * @param { string | number } id - The api to use when loading logs
   * @param { number } epoch - The api to use when loading logs
   * @returns { Promise<import("../types/log").EvalSample | undefined> }  The sample
   */
  const get_log_sample = async (log_file, id, epoch) => {
    if (isEvalFile(log_file)) {
      const remoteLogFile = await remoteEvalFile(log_file, true);
      const sample = await remoteLogFile.readSample(id, epoch);
      return sample;
    } else {
      const logContents = await get_log(log_file, true);
      if (logContents.parsed.samples && logContents.parsed.samples.length > 0) {
        return logContents.parsed.samples.find((sample) => {
          return sample.id === id && sample.epoch === epoch;
        });
      }
    }
    return undefined;
  };

  const get_eval_log_header = async (log_file) => {
    // Don't re-use the eval log file since we know these are all different log files
    const remoteLogFile = await openRemoteLogFile(api, log_file, 5);
    return remoteLogFile.readHeader();
  };

  /**
   * Gets log headers
   *
   * @param { string[] } log_files - The api to use when loading logs
   * @returns { Promise<import("../types/log").EvalLog[]> }  The sample
   */
  const get_log_headers = async (log_files) => {
    const eval_files = {};
    const json_files = {};
    let index = 0;

    // Separate files into eval_files and json_files
    for (const file of log_files) {
      if (isEvalFile(file)) {
        eval_files[file] = index;
      } else {
        json_files[file] = index;
      }
      index++;
    }

    // Get the promises for eval log headers
    const evalLogHeadersPromises = Object.keys(eval_files).map((file) =>
      get_eval_log_header(file).then((header) => ({
        index: eval_files[file], // Store original index
        header,
      })),
    );

    // Get the promise for json log headers
    const jsonLogHeadersPromise = api
      .eval_log_headers(Object.keys(json_files))
      .then((headers) =>
        headers.map((header, i) => ({
          index: json_files[Object.keys(json_files)[i]], // Store original index
          header,
        })),
      );

    // Wait for all promises to resolve
    const headers = await Promise.all([
      ...evalLogHeadersPromises,
      jsonLogHeadersPromise,
    ]);

    // Flatten the nested array and sort headers by their original index
    const orderedHeaders = headers.flat().sort((a, b) => a.index - b.index);

    // Return only the header values in the correct order
    return orderedHeaders.map(({ header }) => header);
  };

  return {
    client_events: () => {
      return api.client_events();
    },
    get_log_paths: () => {
      return api.eval_logs();
    },
    get_log_headers: (log_files) => {
      return get_log_headers(log_files);
    },
    get_log_summary,
    get_log_sample,
    open_log_file: (log_file, log_dir) => {
      return api.open_log_file(log_file, log_dir);
    },
    download_file: (download_file, file_contents) => {
      return api.download_file(download_file, file_contents);
    },
  };
};
