import { EvalLog, EvalSample } from "../../@types/log";
import {
  openRemoteLogFile,
  RemoteLogFile,
  SampleNotFoundError,
} from "../remote/remoteLogFile";
import { FileSizeLimitError } from "../remote/remoteZipFile";
import { encodePathParts } from "./api-shared";
import {
  ClientAPI,
  EvalSummary,
  LogContents,
  LogFiles,
  LogViewAPI,
  PendingSampleResponse,
  SampleDataResponse,
} from "./types";

const isEvalFile = (file: string) => {
  return file.endsWith(".eval");
};

/**
 * Represents an error thrown when a file exceeds the maximum allowed size.
 */
export class SampleSizeLimitedExceededError extends Error {
  readonly id: string | number;
  readonly epoch: number;
  readonly maxBytes: number;
  readonly displayStack: boolean;

  constructor(id: string | number, epoch: number, maxBytes: number) {
    super(
      `Sample ${id} in epoch ${epoch} exceeds the maximum supported size (${maxBytes / 1024 / 1024}MB) and cannot be loaded.`,
    );

    this.name = "SampleSizeLimitedExceededError";
    this.id = id;
    this.epoch = epoch;
    this.maxBytes = maxBytes;
    this.displayStack = false;

    Object.setPrototypeOf(this, SampleSizeLimitedExceededError.prototype);
  }
}
interface LoadedLogFile {
  file?: string;
  remoteLog?: RemoteLogFile;
}

/**
 * This provides an API implementation that will serve a single
 * file using an http parameter, designed to be deployed
 * to a webserver without inspect or the ability to enumerate log
 * files
 */
export const clientApi = (api: LogViewAPI, log_file?: string): ClientAPI => {
  let current_log: LogContents | undefined = undefined;
  let current_path: string | undefined = undefined;

  const loadedEvalFile: LoadedLogFile = {
    file: undefined,
    remoteLog: undefined,
  };

  const remoteEvalFile = async (log_file: string, cached: boolean = false) => {
    if (!cached || loadedEvalFile.file !== log_file) {
      const remoteLog = await openRemoteLogFile(
        api,
        encodePathParts(log_file),
        5,
      );
      loadedEvalFile.file = log_file;
      loadedEvalFile.remoteLog = remoteLog;
    }
    return loadedEvalFile.remoteLog;
  };

  /**
   * Gets a log
   */
  const get_log = async (
    log_file: string,
    cached = false,
  ): Promise<LogContents> => {
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
  let pending_log_promise: Promise<LogContents> | null = null;

  /**
   * Gets a log summary
   */
  const get_log_summary = async (log_file: string): Promise<EvalSummary> => {
    if (isEvalFile(log_file)) {
      const remoteLogFile = await remoteEvalFile(log_file);
      if (remoteLogFile) {
        return await remoteLogFile.readLogSummary();
      } else {
        throw new Error("Unable to read remote eval file");
      }
    } else {
      const logContents = await get_log(log_file);
      /**
       * @type {import("./Types.js").SampleSummary[]}
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
              error: sample.error?.message,
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
   */
  const get_log_sample = async (
    log_file: string,
    id: string | number,
    epoch: number,
  ): Promise<EvalSample | undefined> => {
    if (isEvalFile(log_file)) {
      async function fetchSample(useCache: boolean) {
        const remoteLogFile = await remoteEvalFile(log_file, useCache);
        if (!remoteLogFile) {
          throw new Error(`Unable to read remote eval file ${log_file}`);
        }
        return await remoteLogFile.readSample(String(id), epoch);
      }

      function handleError(error: unknown) {
        if (error instanceof FileSizeLimitError) {
          throw new SampleSizeLimitedExceededError(id, epoch, error.maxBytes);
        }
        throw error;
      }

      try {
        // First attempt with cache
        return await fetchSample(true);
      } catch (error) {
        if (error instanceof SampleNotFoundError) {
          try {
            // Retry without cache
            return await fetchSample(false);
          } catch (retryError) {
            handleError(retryError);
          }
        } else {
          handleError(error);
        }
      }
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

  const get_eval_log_header = async (log_file: string) => {
    // Don't re-use the eval log file since we know these are all different log files
    const remoteLogFile = await openRemoteLogFile(
      api,
      encodePathParts(log_file),
      5,
    );
    return remoteLogFile.readHeader();
  };

  /**
   * Gets log headers
   */
  const get_log_headers = async (log_files: string[]): Promise<EvalLog[]> => {
    const eval_files: Record<string, number> = {};
    const json_files: Record<string, number> = {};
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

  const get_log_paths = async (): Promise<LogFiles> => {
    const logFiles = await api.eval_logs();
    if (logFiles) {
      return logFiles!;
    } else if (log_file) {
      // Is there an explicitly passed log file?
      const summary = await get_log_summary(log_file);
      if (summary) {
        return {
          files: [
            {
              name: log_file,
              task: summary.eval.task,
              task_id: summary.eval.task_id,
            },
          ],
        };
      }
    }
    throw new Error("Unable to determine log paths.");
  };

  const get_log_pending_samples = (
    log_file: string,
    etag?: string,
  ): Promise<PendingSampleResponse> => {
    if (!api.eval_pending_samples) {
      throw new Error("API doesn't support streamed samples");
    }
    return api.eval_pending_samples(log_file, etag);
  };

  const get_log_sample_data = (
    log_file: string,
    id: string | number,
    epoch: number,
    last_event?: number,
    last_attachment?: number,
  ): Promise<SampleDataResponse | undefined> => {
    if (!api.eval_log_sample_data) {
      throw new Error("API doesn't supported streamed sample data");
    }
    return api.eval_log_sample_data(
      log_file,
      id,
      epoch,
      last_event,
      last_attachment,
    );
  };

  return {
    client_events: () => {
      return api.client_events();
    },
    get_log_paths: () => {
      return get_log_paths();
    },
    get_log_headers: (log_files) => {
      return get_log_headers(log_files);
    },
    get_log_summary,
    get_log_sample,
    open_log_file: (log_file, log_dir) => {
      return api.open_log_file(log_file, log_dir);
    },
    download_file: (
      download_file: string,
      file_contents: string | Blob | ArrayBuffer | ArrayBufferView,
    ) => {
      return api.download_file(download_file, file_contents);
    },
    log_message: (log_file: string, message: string) => {
      return api.log_message(log_file, message);
    },
    get_log_pending_samples: api.eval_pending_samples
      ? get_log_pending_samples
      : undefined,
    get_log_sample_data: api.eval_log_sample_data
      ? get_log_sample_data
      : undefined,
  };
};
