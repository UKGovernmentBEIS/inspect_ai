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

  const remoteEvalFile = async (log_file) => {
    if (loadedEvalFile.file !== log_file) {
      loadedEvalFile.file = log_file;
      loadedEvalFile.remoteLog = await openRemoteLogFile(api, log_file, 5);
    }
    return loadedEvalFile.remoteLog;
  };

  /**
   * Gets a log
   *
   * @param { string } log_file - The api to use when loading logs
   * @returns { Promise<import("./Types.mjs").LogContents> } A Log Viewer API
   */
  const get_log = async (log_file) => {
    // If the requested log is different or no cached log exists, start fetching
    if (log_file !== current_path || !current_log) {
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
      const remoteLogFile = await remoteEvalFile(log_file);
      const sample = await remoteLogFile.readSample(id, epoch);
      return sample;
    } else {
      const logContents = await get_log(log_file);
      if (logContents.parsed.samples && logContents.parsed.samples.length > 0) {
        return logContents.parsed.samples.find((sample) => {
          return sample.id === id && sample.epoch === epoch;
        });
      }
    }
    return undefined;
  };

  return {
    client_events: () => {
      return api.client_events();
    },
    get_log_paths: () => {
      return api.eval_logs();
    },
    get_log_headers: (log_files) => {
      return api.eval_log_headers(log_files);
    },
    get_log_summary,
    get_log_sample,
    open_log_file: (log_file, log_dir) => {
      return api.open_log_file(log_file, log_dir);
    },
    download_log_file: (log_file, download_files, web_workers) => {
      return api.download_file(log_file, download_files, web_workers);
    },
  };
};
